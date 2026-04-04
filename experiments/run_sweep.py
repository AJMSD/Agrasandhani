from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from shutil import which

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments.analyze_run import analyze_run

BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_ROOT = BASE_DIR / "experiments" / "logs"

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
) -> Path:
    python_exe = _find_python()
    run_label = f"{variant}-qos{mqtt_qos}-{scenario_name}"
    if run_label_suffix:
        run_label = f"{run_label}-{run_label_suffix}"
    gateway_run_id = f"{config.sweep_id}-{run_label}"
    run_dir = LOGS_ROOT / config.sweep_id / run_label
    run_dir.mkdir(parents=True, exist_ok=True)

    gateway_env = os.environ.copy() | {
        "RUN_ID": gateway_run_id,
        "MQTT_HOST": config.mqtt_host,
        "MQTT_PORT": str(config.mqtt_port),
        "MQTT_QOS": str(mqtt_qos),
        "WS_HOST": config.gateway_host,
        "WS_PORT": str(config.gateway_port),
        "GATEWAY_MODE": variant,
    }
    if config.batch_window_ms is not None:
        gateway_env["BATCH_WINDOW_MS"] = str(config.batch_window_ms)
    if config.gateway_env_overrides:
        gateway_env.update(config.gateway_env_overrides)
    proxy_env = os.environ.copy() | {
        "RUN_ID": gateway_run_id,
        "IMPAIR_HOST": config.proxy_host,
        "IMPAIR_PORT": str(config.proxy_port),
        "UPSTREAM_WS_URL": f"ws://{config.gateway_host}:{config.gateway_port}/ws",
        "UPSTREAM_HTTP_BASE": f"http://{config.gateway_host}:{config.gateway_port}",
        "IMPAIR_SCENARIO_FILE": str(BASE_DIR / "experiments" / "scenarios" / f"{scenario_name}.json"),
        "IMPAIR_FRAME_LOG_PATH": str(run_dir / "proxy_frame_log.csv"),
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
            stdout, stderr = browser_process.communicate(timeout=config.duration_s + 30)
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
            "run_id": run_label,
            "gateway_run_id": gateway_run_id,
            "variant": variant,
            "scenario": scenario_name,
            "mqtt_qos": mqtt_qos,
            "batch_window_ms": config.batch_window_ms,
            "duration_s": config.duration_s,
            "replay_speed": config.replay_speed,
            "sensor_limit": config.sensor_limit,
            "burst_enabled": config.burst_enabled,
            "data_file": str(config.data_file),
            "browser_capture": browser_capture,
        }
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    finally:
        if browser_process is not None and browser_process.poll() is None:
            browser_process.kill()
            browser_process.wait(timeout=5)
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
    )


def main() -> None:
    config = parse_args()
    if not _port_open(config.mqtt_host, config.mqtt_port):
        raise SystemExit(
            f"MQTT broker is not reachable at {config.mqtt_host}:{config.mqtt_port}. "
            "Start Mosquitto before running experiments/run_sweep.py."
        )
    if config.run_browser:
        ensure_browser_capture_prerequisites()

    sweep_dir = LOGS_ROOT / config.sweep_id
    if sweep_dir.exists():
        shutil.rmtree(sweep_dir)
    sweep_dir.mkdir(parents=True, exist_ok=True)

    completed_runs: list[str] = []
    for variant in config.variants:
        for qos in config.qos_values:
            for scenario in config.scenarios:
                completed_runs.append(str(run_once(config, variant=variant, mqtt_qos=qos, scenario_name=scenario)))

    subprocess.run([_find_python(), str(BASE_DIR / "experiments" / "plot_sweep.py"), str(sweep_dir)], check=True)
    print(json.dumps({"sweep_id": config.sweep_id, "runs": completed_runs}, indent=2))


if __name__ == "__main__":
    main()
