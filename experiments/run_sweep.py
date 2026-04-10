from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from shutil import which

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments.analyze_run import analyze_run
from experiments.sweep_aggregation import write_condition_aggregates

BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_ROOT = BASE_DIR / "experiments" / "logs"
DEFAULT_IMPAIRMENT_SEED = 537
GATEWAY_ENV_DEFAULTS = {
    "BATCH_MAX_MESSAGES": "50",
    "DUPLICATE_TTL_MS": "30000",
    "VALUE_DEDUP_ENABLED": "0",
    "FRESHNESS_TTL_MS": "1000",
    "ADAPTIVE_MIN_BATCH_WINDOW_MS": "10",
    "ADAPTIVE_MAX_BATCH_WINDOW_MS": "1000",
    "ADAPTIVE_STEP_UP_MS": "100",
    "ADAPTIVE_STEP_DOWN_MS": "50",
    "ADAPTIVE_QUEUE_HIGH_WATERMARK": "25",
    "ADAPTIVE_QUEUE_LOW_WATERMARK": "5",
    "ADAPTIVE_SEND_SLOW_MS": "40",
    "ADAPTIVE_RECOVERY_STREAK": "3",
}

SHORT_SMOKE_PROFILE = {
    "variants": ["v0", "v2", "v4"],
    "qos_values": [0, 1],
    "scenarios": ["clean", "loss_5pct", "outage_5s"],
    "data_file": BASE_DIR / "simulator" / "sample_data.csv",
    "duration_s": 16,
    "replay_speed": 2.0,
    "sensor_limit": 20,
    "burst_enabled": True,
    "burst_start_s": 1,
    "burst_duration_s": 2,
    "burst_speed_multiplier": 5.0,
}


@dataclass(slots=True)
class SweepConfig:
    sweep_id: str
    variants: list[str]
    qos_values: list[int]
    scenarios: list[str]
    data_file: Path
    duration_s: int
    replay_speed: float
    sensor_limit: int
    burst_enabled: bool
    burst_start_s: int
    burst_duration_s: int
    burst_speed_multiplier: float
    gateway_host: str
    gateway_port: int
    proxy_host: str
    proxy_port: int
    mqtt_host: str
    mqtt_port: int
    run_browser: bool
    batch_window_ms: int | None = None
    gateway_env_overrides: dict[str, str] | None = None
    trial_seeds: list[int] | None = None
    default_impairment_seed: int = DEFAULT_IMPAIRMENT_SEED


def parse_seed_list(raw_value: str) -> list[int]:
    seeds = [int(item.strip()) for item in raw_value.split(",") if item.strip()]
    if not seeds:
        raise argparse.ArgumentTypeError("trial seeds must not be empty")
    return seeds


def _find_python() -> str:
    for candidate in [BASE_DIR / ".venv" / "Scripts" / "python.exe", BASE_DIR / ".venv" / "bin" / "python"]:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _wait_for_http(url: str, *, timeout_s: int = 15) -> None:
    deadline = time.time() + timeout_s
    last_error = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except Exception as exc:  # pragma: no cover
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def _port_open(host: str, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    try:
        sock.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _spawn(command: list[str], *, env: dict[str, str], stdout_path: Path, stderr_path: Path) -> subprocess.Popen[str]:
    stdout_handle = stdout_path.open("w", encoding="utf-8")
    stderr_handle = stderr_path.open("w", encoding="utf-8")
    return subprocess.Popen(
        command,
        cwd=BASE_DIR,
        env=env,
        stdout=stdout_handle,
        stderr=stderr_handle,
        text=True,
    )


def _cleanup_headless_shell_processes() -> None:
    try:
        if sys.platform.startswith("win"):
            subprocess.run(
                ["taskkill", "/IM", "chrome-headless-shell.exe", "/F", "/T"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            return
        subprocess.run(
            ["pkill", "-f", "chrome-headless-shell"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_sha256(payload: object) -> str:
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def _git_provenance() -> dict[str, object]:
    commit_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    dirty_result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "commit": commit_result.stdout.strip() or None,
        "dirty": bool(dirty_result.stdout.strip()) if dirty_result.returncode == 0 else None,
    }


def build_condition_id(
    *,
    variant: str,
    mqtt_qos: int,
    scenario_name: str,
    run_label_suffix: str | None = None,
) -> str:
    condition_id = f"{variant}-qos{mqtt_qos}-{scenario_name}"
    if run_label_suffix:
        condition_id = f"{condition_id}-{run_label_suffix}"
    return condition_id


def build_trial_id(*, trial_index: int, impairment_seed: int) -> str:
    return f"trial-{trial_index:02d}-seed-{impairment_seed}"


def _effective_gateway_env(
    *,
    config: SweepConfig,
    variant: str,
    mqtt_qos: int,
    gateway_run_id: str,
) -> dict[str, str]:
    snapshot = {
        "RUN_ID": gateway_run_id,
        "MQTT_HOST": config.mqtt_host,
        "MQTT_PORT": str(config.mqtt_port),
        "MQTT_QOS": str(mqtt_qos),
        "WS_HOST": config.gateway_host,
        "WS_PORT": str(config.gateway_port),
        "GATEWAY_MODE": variant,
    }
    if config.batch_window_ms is not None:
        snapshot["BATCH_WINDOW_MS"] = str(config.batch_window_ms)
    for env_name, default_value in GATEWAY_ENV_DEFAULTS.items():
        snapshot[env_name] = default_value
    if config.gateway_env_overrides:
        snapshot.update(config.gateway_env_overrides)
    return snapshot


def ensure_browser_capture_prerequisites() -> None:
    if which("node") is None:
        raise SystemExit(
            "Node.js is required for browser capture. Install Node.js, then run `npm install` "
            "and `npx playwright install chromium`."
        )

    result = subprocess.run(
        ["node", str(BASE_DIR / "experiments" / "capture_dashboard.mjs"), "--check-only"],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise SystemExit(detail)


def run_once(
    config: SweepConfig,
    *,
    variant: str,
    mqtt_qos: int,
    scenario_name: str,
    run_label_suffix: str | None = None,
    trial_index: int | None = None,
    impairment_seed: int | None = None,
) -> Path:
    python_exe = _find_python()
    condition_id = build_condition_id(
        variant=variant,
        mqtt_qos=mqtt_qos,
        scenario_name=scenario_name,
        run_label_suffix=run_label_suffix,
    )
    resolved_impairment_seed = config.default_impairment_seed if impairment_seed is None else impairment_seed
    trial_id = build_trial_id(trial_index=trial_index, impairment_seed=resolved_impairment_seed) if trial_index is not None else None
    run_id = f"{condition_id}-{trial_id}" if trial_id else condition_id
    gateway_run_id = f"{config.sweep_id}-{run_id}"
    run_dir = LOGS_ROOT / config.sweep_id / condition_id
    if trial_id is not None:
        run_dir = run_dir / trial_id
    run_dir.mkdir(parents=True, exist_ok=True)

    gateway_env = os.environ.copy() | _effective_gateway_env(
        config=config,
        variant=variant,
        mqtt_qos=mqtt_qos,
        gateway_run_id=gateway_run_id,
    )
    scenario_path = BASE_DIR / "experiments" / "scenarios" / f"{scenario_name}.json"
    proxy_env = os.environ.copy() | {
        "RUN_ID": gateway_run_id,
        "IMPAIR_HOST": config.proxy_host,
        "IMPAIR_PORT": str(config.proxy_port),
        "UPSTREAM_WS_URL": f"ws://{config.gateway_host}:{config.gateway_port}/ws",
        "UPSTREAM_HTTP_BASE": f"http://{config.gateway_host}:{config.gateway_port}",
        "IMPAIR_SCENARIO_FILE": str(scenario_path),
        "IMPAIR_FRAME_LOG_PATH": str(run_dir / "proxy_frame_log.csv"),
        "IMPAIR_RANDOM_SEED": str(resolved_impairment_seed),
    }
    simulator_env = os.environ.copy() | {
        "RUN_ID": gateway_run_id,
        "MQTT_HOST": config.mqtt_host,
        "MQTT_PORT": str(config.mqtt_port),
        "MQTT_QOS": str(mqtt_qos),
        "REPLAY_SPEED": str(config.replay_speed),
        "SENSOR_LIMIT": str(config.sensor_limit),
        "DURATION_S": str(config.duration_s),
        "BURST_ENABLED": "1" if config.burst_enabled else "0",
        "BURST_START_S": str(config.burst_start_s),
        "BURST_DURATION_S": str(config.burst_duration_s),
        "BURST_SPEED_MULTIPLIER": str(config.burst_speed_multiplier),
    }
    started_at = _utc_now_iso()
    git_provenance = _git_provenance()

    gateway_process = _spawn(
        [python_exe, "-m", "gateway.app"],
        env=gateway_env,
        stdout_path=run_dir / "gateway.stdout.log",
        stderr_path=run_dir / "gateway.stderr.log",
    )
    proxy_process = _spawn(
        [python_exe, "-m", "experiments.impairment_proxy"],
        env=proxy_env,
        stdout_path=run_dir / "proxy.stdout.log",
        stderr_path=run_dir / "proxy.stderr.log",
    )

    browser_process: subprocess.Popen[str] | None = None
    try:
        _wait_for_http(f"http://{config.gateway_host}:{config.gateway_port}/health")
        _wait_for_http(f"http://{config.proxy_host}:{config.proxy_port}/health")

        if config.run_browser:
            _cleanup_headless_shell_processes()
            browser_process = subprocess.Popen(
                [
                    "node",
                    str(BASE_DIR / "experiments" / "capture_dashboard.mjs"),
                    "--url",
                    f"http://{config.proxy_host}:{config.proxy_port}/ui/index.html",
                    "--output-dir",
                    str(run_dir),
                    "--capture-ms",
                    str((config.duration_s + 5) * 1000),
                ],
                cwd=BASE_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

        simulator_process = _spawn(
            [python_exe, str(BASE_DIR / "simulator" / "replay_publisher.py"), "--data-file", str(config.data_file)],
            env=simulator_env,
            stdout_path=run_dir / "simulator.stdout.log",
            stderr_path=run_dir / "simulator.stderr.log",
        )
        simulator_process.wait(timeout=config.duration_s + 20)
        if simulator_process.returncode != 0:
            raise RuntimeError(f"Simulator exited with code {simulator_process.returncode}")

        browser_capture = None
        if browser_process is not None:
            # Browser capture includes page readiness waits, the full capture window, and
            # the final screenshot/export step, so it needs more headroom than the replay.
            stdout, stderr = browser_process.communicate(timeout=config.duration_s + 90)
            browser_capture = {"stdout": stdout, "stderr": stderr, "returncode": browser_process.returncode}
            if browser_process.returncode != 0:
                raise RuntimeError(f"Browser capture failed: {stderr}")

        for url, filename in [
            (f"http://{config.gateway_host}:{config.gateway_port}/metrics", "gateway_metrics.json"),
            (f"http://{config.proxy_host}:{config.proxy_port}/metrics", "proxy_metrics.json"),
        ]:
            with urllib.request.urlopen(url, timeout=5) as response:
                payload = json.load(response)
            (run_dir / filename).write_text(json.dumps(payload, indent=2), encoding="utf-8")

        gateway_log_source = LOGS_ROOT / gateway_run_id / "gateway_forward_log.csv"
        if gateway_log_source.exists():
            shutil.copy2(gateway_log_source, run_dir / "gateway_forward_log.csv")

        manifest = {
            "schema_version": 2,
            "sweep_id": config.sweep_id,
            "run_id": run_id,
            "gateway_run_id": gateway_run_id,
            "condition_id": condition_id,
            "trial_id": trial_id,
            "trial_index": trial_index,
            "impairment_seed": resolved_impairment_seed,
            "variant": variant,
            "scenario": scenario_name,
            "scenario_path": str(scenario_path),
            "scenario_sha256": _file_sha256(scenario_path),
            "mqtt_qos": mqtt_qos,
            "batch_window_ms": config.batch_window_ms,
            "duration_s": config.duration_s,
            "replay_speed": config.replay_speed,
            "sensor_limit": config.sensor_limit,
            "burst_enabled": config.burst_enabled,
            "data_file": str(config.data_file),
            "data_file_path": str(config.data_file),
            "data_file_sha256": _file_sha256(config.data_file),
            "effective_gateway_env": gateway_env,
            "effective_gateway_env_sha256": _json_sha256(gateway_env),
            "git_commit": git_provenance["commit"],
            "git_dirty": git_provenance["dirty"],
            "started_at_utc": started_at,
            "finished_at_utc": _utc_now_iso(),
            "browser_capture": browser_capture,
        }
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    finally:
        if browser_process is not None and browser_process.poll() is None:
            browser_process.kill()
            browser_process.wait(timeout=5)
        if browser_process is not None:
            _cleanup_headless_shell_processes()
        for process in [proxy_process, gateway_process]:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

    analyze_run(run_dir)
    return run_dir


def parse_args() -> SweepConfig:
    parser = argparse.ArgumentParser(description="Run deterministic M4 comparison sweeps.")
    parser.add_argument("--sweep-id", default=time.strftime("m4-%Y%m%d-%H%M%S"))
    parser.add_argument("--profile", choices=["short-smoke"])
    parser.add_argument("--variants")
    parser.add_argument("--qos")
    parser.add_argument("--scenarios")
    parser.add_argument("--data-file", type=Path)
    parser.add_argument("--duration-s", type=int)
    parser.add_argument("--replay-speed", type=float)
    parser.add_argument("--sensor-limit", type=int)
    parser.add_argument("--burst-enabled", dest="burst_enabled", action="store_true")
    parser.add_argument("--no-burst-enabled", dest="burst_enabled", action="store_false")
    parser.set_defaults(burst_enabled=None)
    parser.add_argument("--burst-start-s", type=int)
    parser.add_argument("--burst-duration-s", type=int)
    parser.add_argument("--burst-speed-multiplier", type=float)
    parser.add_argument("--gateway-host", default="127.0.0.1")
    parser.add_argument("--gateway-port", type=int, default=8000)
    parser.add_argument("--proxy-host", default="127.0.0.1")
    parser.add_argument("--proxy-port", type=int, default=9000)
    parser.add_argument("--mqtt-host", default=os.getenv("MQTT_HOST", "127.0.0.1"))
    parser.add_argument("--mqtt-port", type=int, default=int(os.getenv("MQTT_PORT", "1883")))
    parser.add_argument("--impairment-seed", type=int, default=DEFAULT_IMPAIRMENT_SEED)
    parser.add_argument("--trial-seeds", type=parse_seed_list)
    parser.add_argument("--skip-browser", action="store_true")
    args = parser.parse_args()

    profile_defaults = SHORT_SMOKE_PROFILE if args.profile == "short-smoke" else {}

    variants = args.variants or ",".join(profile_defaults.get("variants", ["v0", "v2", "v4"]))
    qos = args.qos or ",".join(str(item) for item in profile_defaults.get("qos_values", [0, 1]))
    scenarios = args.scenarios or ",".join(
        profile_defaults.get("scenarios", ["clean", "bandwidth_200kbps", "loss_2pct", "delay_50ms_jitter20ms", "outage_5s"])
    )
    return SweepConfig(
        sweep_id=args.sweep_id,
        variants=[item.strip() for item in variants.split(",") if item.strip()],
        qos_values=[int(item.strip()) for item in qos.split(",") if item.strip()],
        scenarios=[item.strip() for item in scenarios.split(",") if item.strip()],
        data_file=args.data_file or profile_defaults.get("data_file", BASE_DIR / "simulator" / "datasets" / "intel_lab_sample.csv"),
        duration_s=args.duration_s if args.duration_s is not None else profile_defaults.get("duration_s", 30),
        replay_speed=args.replay_speed if args.replay_speed is not None else profile_defaults.get("replay_speed", 5.0),
        sensor_limit=args.sensor_limit if args.sensor_limit is not None else profile_defaults.get("sensor_limit", 200),
        burst_enabled=args.burst_enabled if args.burst_enabled is not None else profile_defaults.get("burst_enabled", True),
        burst_start_s=args.burst_start_s if args.burst_start_s is not None else profile_defaults.get("burst_start_s", 5),
        burst_duration_s=args.burst_duration_s if args.burst_duration_s is not None else profile_defaults.get("burst_duration_s", 10),
        burst_speed_multiplier=(
            args.burst_speed_multiplier
            if args.burst_speed_multiplier is not None
            else profile_defaults.get("burst_speed_multiplier", 8.0)
        ),
        gateway_host=args.gateway_host,
        gateway_port=args.gateway_port,
        proxy_host=args.proxy_host,
        proxy_port=args.proxy_port,
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        run_browser=not args.skip_browser,
        batch_window_ms=None,
        gateway_env_overrides=None,
        trial_seeds=args.trial_seeds,
        default_impairment_seed=args.impairment_seed,
    )


def run_sweep(config: SweepConfig) -> tuple[Path, list[str]]:
    if not _port_open(config.mqtt_host, config.mqtt_port):
        raise SystemExit(
            f"MQTT broker is not reachable at {config.mqtt_host}:{config.mqtt_port}. "
            "Start Mosquitto before running experiments/run_sweep.py."
        )
    if config.run_browser:
        ensure_browser_capture_prerequisites()

    sweep_dir = LOGS_ROOT / config.sweep_id
    if sweep_dir.exists():
        raise SystemExit(f"Sweep output root already exists and will not be overwritten: {sweep_dir}")
    sweep_dir.mkdir(parents=True, exist_ok=True)

    completed_runs: list[str] = []
    trial_seeds = config.trial_seeds or [config.default_impairment_seed]
    use_trial_layout = len(trial_seeds) > 1
    for variant in config.variants:
        for qos in config.qos_values:
            for scenario in config.scenarios:
                for trial_index, impairment_seed in enumerate(trial_seeds, start=1):
                    completed_runs.append(
                        str(
                            run_once(
                                config,
                                variant=variant,
                                mqtt_qos=qos,
                                scenario_name=scenario,
                                trial_index=trial_index if use_trial_layout else None,
                                impairment_seed=impairment_seed,
                            )
                        )
                    )

    write_condition_aggregates(sweep_dir)
    subprocess.run([_find_python(), str(BASE_DIR / "experiments" / "plot_sweep.py"), str(sweep_dir)], check=True)
    return sweep_dir, completed_runs


def main() -> None:
    config = parse_args()
    sweep_dir, completed_runs = run_sweep(config)
    print(json.dumps({"sweep_id": config.sweep_id, "sweep_dir": str(sweep_dir), "runs": completed_runs}, indent=2))


if __name__ == "__main__":
    main()
