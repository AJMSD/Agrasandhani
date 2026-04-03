from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments.run_sweep import ensure_browser_capture_prerequisites

BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_ROOT = BASE_DIR / "experiments" / "logs"
CAPTURE_SCRIPT = BASE_DIR / "experiments" / "capture_dashboard.mjs"
DEFAULT_SCENARIO_FILE = BASE_DIR / "experiments" / "scenarios" / "demo_v0_vs_v4.json"
DEFAULT_DATA_FILE = BASE_DIR / "simulator" / "sample_data.csv"
SERVICE_PORT_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("baseline_gateway", "baseline_gateway_host", "baseline_gateway_port"),
    ("smart_gateway", "smart_gateway_host", "smart_gateway_port"),
    ("baseline_proxy", "baseline_proxy_host", "baseline_proxy_port"),
    ("smart_proxy", "smart_proxy_host", "smart_proxy_port"),
)


@dataclass(slots=True)
class DemoConfig:
    run_id: str
    data_file: Path
    scenario_file: Path
    duration_s: int
    replay_speed: float
    sensor_limit: int
    mqtt_host: str
    mqtt_port: int
    mqtt_qos: int
    burst_enabled: bool
    burst_start_s: int
    burst_duration_s: int
    burst_speed_multiplier: float
    baseline_gateway_host: str
    baseline_gateway_port: int
    smart_gateway_host: str
    smart_gateway_port: int
    baseline_proxy_host: str
    baseline_proxy_port: int
    smart_proxy_host: str
    smart_proxy_port: int
    left_label: str
    right_label: str
    open_browser: bool
    auto_ports: bool
    capture_artifacts: bool
    settle_after_run_s: int


def _find_python() -> str:
    for candidate in [BASE_DIR / ".venv" / "Scripts" / "python.exe", BASE_DIR / ".venv" / "bin" / "python"]:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _tcp_port_open(host: str, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    try:
        sock.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _port_available(host: str, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _pick_free_port(host: str) -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


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


def _spawn(command: list[str], *, env: dict[str, str], stdout_path: Path, stderr_path: Path) -> subprocess.Popen[str]:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_handle = stdout_path.open("w", encoding="utf-8")
    stderr_handle = stderr_path.open("w", encoding="utf-8")
    try:
        return subprocess.Popen(
            command,
            cwd=BASE_DIR,
            env=env,
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
        )
    finally:
        stdout_handle.close()
        stderr_handle.close()


def load_scenario_metadata(path: Path) -> dict[str, int | str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    phases = payload.get("phases", [])
    total_duration_s = sum(int(phase.get("duration_s", 0)) for phase in phases)
    return {
        "scenario_name": str(payload.get("name", path.stem)),
        "total_duration_s": total_duration_s,
    }


def build_compare_url(config: DemoConfig) -> str:
    base_url = f"http://{config.baseline_proxy_host}:{config.baseline_proxy_port}/ui/demo_compare.html"
    query = urllib.parse.urlencode(
        {
            "left": f"http://{config.baseline_proxy_host}:{config.baseline_proxy_port}/ui/index.html",
            "right": f"http://{config.smart_proxy_host}:{config.smart_proxy_port}/ui/index.html",
            "leftLabel": config.left_label,
            "rightLabel": config.right_label,
        }
    )
    return f"{base_url}?{query}"


def parse_args(argv: list[str] | None = None) -> DemoConfig:
    parser = argparse.ArgumentParser(description="Run the M5 live baseline-vs-smart demo harness.")
    parser.add_argument("--run-id", default=time.strftime("m5-demo-%Y%m%d-%H%M%S"))
    parser.add_argument("--data-file", type=Path, default=DEFAULT_DATA_FILE)
    parser.add_argument("--scenario-file", type=Path, default=DEFAULT_SCENARIO_FILE)
    parser.add_argument("--duration-s", type=int, default=20)
    parser.add_argument("--replay-speed", type=float, default=2.0)
    parser.add_argument("--sensor-limit", type=int, default=0)
    parser.add_argument("--mqtt-host", default=os.getenv("MQTT_HOST", "127.0.0.1"))
    parser.add_argument("--mqtt-port", type=int, default=int(os.getenv("MQTT_PORT", "1883")))
    parser.add_argument("--mqtt-qos", type=int, default=0)
    parser.add_argument("--burst-enabled", dest="burst_enabled", action="store_true")
    parser.add_argument("--no-burst-enabled", dest="burst_enabled", action="store_false")
    parser.set_defaults(burst_enabled=True)
    parser.add_argument("--burst-start-s", type=int, default=2)
    parser.add_argument("--burst-duration-s", type=int, default=4)
    parser.add_argument("--burst-speed-multiplier", type=float, default=8.0)
    parser.add_argument("--baseline-gateway-host", default="127.0.0.1")
    parser.add_argument("--baseline-gateway-port", type=int, default=8000)
    parser.add_argument("--smart-gateway-host", default="127.0.0.1")
    parser.add_argument("--smart-gateway-port", type=int, default=8001)
    parser.add_argument("--baseline-proxy-host", default="127.0.0.1")
    parser.add_argument("--baseline-proxy-port", type=int, default=9000)
    parser.add_argument("--smart-proxy-host", default="127.0.0.1")
    parser.add_argument("--smart-proxy-port", type=int, default=9001)
    parser.add_argument("--left-label", default="Baseline v0")
    parser.add_argument("--right-label", default="Smart v4")
    parser.add_argument("--no-open-browser", action="store_true")
    parser.add_argument("--auto-ports", action="store_true")
    parser.add_argument("--capture-artifacts", action="store_true")
    parser.add_argument("--settle-after-run-s", type=int, default=2)
    args = parser.parse_args(argv)

    return DemoConfig(
        run_id=args.run_id,
        data_file=args.data_file,
        scenario_file=args.scenario_file,
        duration_s=args.duration_s,
        replay_speed=args.replay_speed,
        sensor_limit=args.sensor_limit,
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        mqtt_qos=args.mqtt_qos,
        burst_enabled=args.burst_enabled,
        burst_start_s=args.burst_start_s,
        burst_duration_s=args.burst_duration_s,
        burst_speed_multiplier=args.burst_speed_multiplier,
        baseline_gateway_host=args.baseline_gateway_host,
        baseline_gateway_port=args.baseline_gateway_port,
        smart_gateway_host=args.smart_gateway_host,
        smart_gateway_port=args.smart_gateway_port,
        baseline_proxy_host=args.baseline_proxy_host,
        baseline_proxy_port=args.baseline_proxy_port,
        smart_proxy_host=args.smart_proxy_host,
        smart_proxy_port=args.smart_proxy_port,
        left_label=args.left_label,
        right_label=args.right_label,
        open_browser=not args.no_open_browser,
        auto_ports=args.auto_ports,
        capture_artifacts=args.capture_artifacts,
        settle_after_run_s=args.settle_after_run_s,
    )


def effective_port_map(config: DemoConfig) -> dict[str, dict[str, int | str]]:
    return {
        label: {
            "host": str(getattr(config, host_field)),
            "port": int(getattr(config, port_field)),
        }
        for label, host_field, port_field in SERVICE_PORT_FIELDS
    }


def resolve_demo_ports(config: DemoConfig) -> None:
    assigned: set[tuple[str, int]] = set()
    for _, host_field, port_field in SERVICE_PORT_FIELDS:
        host = str(getattr(config, host_field))
        port = int(getattr(config, port_field))
        if _port_available(host, port) and (host, port) not in assigned:
            assigned.add((host, port))
            continue

        while True:
            candidate = _pick_free_port(host)
            if (host, candidate) in assigned:
                continue
            setattr(config, port_field, candidate)
            assigned.add((host, candidate))
            break


def validate_environment(config: DemoConfig) -> None:
    if not config.data_file.exists():
        raise SystemExit(f"Demo data file was not found: {config.data_file}")
    if not config.scenario_file.exists():
        raise SystemExit(f"Demo scenario file was not found: {config.scenario_file}")
    if not _tcp_port_open(config.mqtt_host, config.mqtt_port):
        raise SystemExit(
            f"MQTT broker is not reachable at {config.mqtt_host}:{config.mqtt_port}. "
            "Start Mosquitto before running experiments/run_demo.py."
        )

    if config.auto_ports:
        resolve_demo_ports(config)
        return

    busy_ports = []
    seen: set[tuple[str, int]] = set()
    for label, host_field, port_field in SERVICE_PORT_FIELDS:
        host = str(getattr(config, host_field))
        port = int(getattr(config, port_field))
        if (host, port) in seen or not _port_available(host, port):
            busy_ports.append(f"{label}={host}:{port}")
        seen.add((host, port))
    if busy_ports:
        raise SystemExit(f"Required demo ports are already in use: {', '.join(busy_ports)}")


def _fetch_json(url: str) -> dict[str, object]:
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)


def _copy_if_exists(source: Path, destination: Path) -> None:
    if source.exists():
        shutil.copy2(source, destination)


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _build_gateway_env(config: DemoConfig, *, run_id: str, host: str, port: int, mode: str) -> dict[str, str]:
    env = os.environ.copy() | {
        "RUN_ID": run_id,
        "MQTT_HOST": config.mqtt_host,
        "MQTT_PORT": str(config.mqtt_port),
        "MQTT_QOS": str(config.mqtt_qos),
        "WS_HOST": host,
        "WS_PORT": str(port),
        "GATEWAY_MODE": mode,
    }
    if mode == "v4":
        env["FRESHNESS_TTL_MS"] = "1000"
    return env


def _build_proxy_env(
    config: DemoConfig,
    *,
    run_id: str,
    host: str,
    port: int,
    upstream_host: str,
    upstream_port: int,
    frame_log_path: Path,
) -> dict[str, str]:
    return os.environ.copy() | {
        "RUN_ID": run_id,
        "IMPAIR_HOST": host,
        "IMPAIR_PORT": str(port),
        "UPSTREAM_WS_URL": f"ws://{upstream_host}:{upstream_port}/ws",
        "UPSTREAM_HTTP_BASE": f"http://{upstream_host}:{upstream_port}",
        "IMPAIR_SCENARIO_FILE": str(config.scenario_file),
        "IMPAIR_RANDOM_SEED": "537",
        "IMPAIR_FRAME_LOG_PATH": str(frame_log_path),
    }


def _build_simulator_env(config: DemoConfig) -> dict[str, str]:
    return os.environ.copy() | {
        "RUN_ID": f"{config.run_id}-simulator",
        "MQTT_HOST": config.mqtt_host,
        "MQTT_PORT": str(config.mqtt_port),
        "MQTT_QOS": str(config.mqtt_qos),
        "REPLAY_SPEED": str(config.replay_speed),
        "SENSOR_LIMIT": str(config.sensor_limit),
        "DURATION_S": str(config.duration_s),
        "BURST_ENABLED": "1" if config.burst_enabled else "0",
        "BURST_START_S": str(config.burst_start_s),
        "BURST_DURATION_S": str(config.burst_duration_s),
        "BURST_SPEED_MULTIPLIER": str(config.burst_speed_multiplier),
    }


def _capture_duration_ms(config: DemoConfig) -> int:
    return max(1_000, (config.duration_s + config.settle_after_run_s + 2) * 1_000)


def _capture_wait_timeout_s(config: DemoConfig) -> int:
    return config.duration_s + config.settle_after_run_s + 30


def _start_capture_process(
    *,
    url: str,
    capture_ms: int,
    stdout_path: Path,
    stderr_path: Path,
    output_dir: Path | None = None,
    screenshot_path: Path | None = None,
) -> subprocess.Popen[str]:
    command = [
        "node",
        str(CAPTURE_SCRIPT),
        "--url",
        url,
        "--capture-ms",
        str(capture_ms),
    ]
    if output_dir is not None:
        command.extend(["--output-dir", str(output_dir)])
    if screenshot_path is not None:
        command.extend(["--screenshot-only", "--screenshot-path", str(screenshot_path)])

    return _spawn(
        command,
        env=os.environ.copy(),
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )


def _wait_for_process_exit(
    process: subprocess.Popen[str],
    *,
    timeout_s: int,
    process_name: str,
    stderr_path: Path,
) -> None:
    try:
        process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        _terminate_process(process)
        raise RuntimeError(f"{process_name} timed out. Check {stderr_path}") from exc

    if process.returncode != 0:
        raise RuntimeError(f"{process_name} failed with code {process.returncode}. Check {stderr_path}")


def _capture_artifact_paths(run_dir: Path) -> dict[str, str]:
    return {
        "baseline_dashboard": str(run_dir / "baseline_dashboard"),
        "smart_dashboard": str(run_dir / "smart_dashboard"),
        "compare_screenshot": str(run_dir / "demo_compare.png"),
    }


def run_demo(config: DemoConfig) -> Path:
    if config.capture_artifacts:
        ensure_browser_capture_prerequisites()

    python_exe = _find_python()
    run_dir = LOGS_ROOT / config.run_id / "demo"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    baseline_gateway_run_id = f"{config.run_id}-baseline-gateway"
    smart_gateway_run_id = f"{config.run_id}-smart-gateway"
    compare_url = build_compare_url(config)
    scenario_metadata = load_scenario_metadata(config.scenario_file)

    processes = {
        "baseline_gateway": _spawn(
            [python_exe, "-m", "gateway.app"],
            env=_build_gateway_env(
                config,
                run_id=baseline_gateway_run_id,
                host=config.baseline_gateway_host,
                port=config.baseline_gateway_port,
                mode="v0",
            ),
            stdout_path=run_dir / "baseline_gateway.stdout.log",
            stderr_path=run_dir / "baseline_gateway.stderr.log",
        ),
        "smart_gateway": _spawn(
            [python_exe, "-m", "gateway.app"],
            env=_build_gateway_env(
                config,
                run_id=smart_gateway_run_id,
                host=config.smart_gateway_host,
                port=config.smart_gateway_port,
                mode="v4",
            ),
            stdout_path=run_dir / "smart_gateway.stdout.log",
            stderr_path=run_dir / "smart_gateway.stderr.log",
        ),
        "baseline_proxy": _spawn(
            [python_exe, "-m", "experiments.impairment_proxy"],
            env=_build_proxy_env(
                config,
                run_id=f"{config.run_id}-baseline-proxy",
                host=config.baseline_proxy_host,
                port=config.baseline_proxy_port,
                upstream_host=config.baseline_gateway_host,
                upstream_port=config.baseline_gateway_port,
                frame_log_path=run_dir / "baseline_proxy_frame_log.csv",
            ),
            stdout_path=run_dir / "baseline_proxy.stdout.log",
            stderr_path=run_dir / "baseline_proxy.stderr.log",
        ),
        "smart_proxy": _spawn(
            [python_exe, "-m", "experiments.impairment_proxy"],
            env=_build_proxy_env(
                config,
                run_id=f"{config.run_id}-smart-proxy",
                host=config.smart_proxy_host,
                port=config.smart_proxy_port,
                upstream_host=config.smart_gateway_host,
                upstream_port=config.smart_gateway_port,
                frame_log_path=run_dir / "smart_proxy_frame_log.csv",
            ),
            stdout_path=run_dir / "smart_proxy.stdout.log",
            stderr_path=run_dir / "smart_proxy.stderr.log",
        ),
    }

    capture_processes: list[tuple[str, subprocess.Popen[str], Path]] = []
    simulator_process: subprocess.Popen[str] | None = None
    manifest: dict[str, object] = {
        "run_id": config.run_id,
        "compare_url": compare_url,
        "scenario_file": str(config.scenario_file),
        "scenario_name": scenario_metadata["scenario_name"],
        "scenario_total_duration_s": scenario_metadata["total_duration_s"],
        "data_file": str(config.data_file),
        "duration_s": config.duration_s,
        "replay_speed": config.replay_speed,
        "sensor_limit": config.sensor_limit,
        "mqtt_qos": config.mqtt_qos,
        "burst_enabled": config.burst_enabled,
        "burst_start_s": config.burst_start_s,
        "burst_duration_s": config.burst_duration_s,
        "burst_speed_multiplier": config.burst_speed_multiplier,
        "auto_ports": config.auto_ports,
        "capture_artifacts": config.capture_artifacts,
        "effective_ports": effective_port_map(config),
        "services": {
            "baseline_gateway": f"http://{config.baseline_gateway_host}:{config.baseline_gateway_port}",
            "smart_gateway": f"http://{config.smart_gateway_host}:{config.smart_gateway_port}",
            "baseline_proxy": f"http://{config.baseline_proxy_host}:{config.baseline_proxy_port}",
            "smart_proxy": f"http://{config.smart_proxy_host}:{config.smart_proxy_port}",
        },
    }
    if config.capture_artifacts:
        manifest["artifact_paths"] = _capture_artifact_paths(run_dir)

    try:
        _wait_for_http(f"http://{config.baseline_gateway_host}:{config.baseline_gateway_port}/health")
        _wait_for_http(f"http://{config.smart_gateway_host}:{config.smart_gateway_port}/health")
        _wait_for_http(f"http://{config.baseline_proxy_host}:{config.baseline_proxy_port}/health")
        _wait_for_http(f"http://{config.smart_proxy_host}:{config.smart_proxy_port}/health")

        if config.capture_artifacts:
            capture_ms = _capture_duration_ms(config)
            baseline_dashboard_dir = run_dir / "baseline_dashboard"
            smart_dashboard_dir = run_dir / "smart_dashboard"
            baseline_dashboard_dir.mkdir(parents=True, exist_ok=True)
            smart_dashboard_dir.mkdir(parents=True, exist_ok=True)
            capture_processes = [
                (
                    "baseline dashboard capture",
                    _start_capture_process(
                        url=f"http://{config.baseline_proxy_host}:{config.baseline_proxy_port}/ui/index.html",
                        capture_ms=capture_ms,
                        output_dir=baseline_dashboard_dir,
                        stdout_path=baseline_dashboard_dir / "capture.stdout.log",
                        stderr_path=baseline_dashboard_dir / "capture.stderr.log",
                    ),
                    baseline_dashboard_dir / "capture.stderr.log",
                ),
                (
                    "smart dashboard capture",
                    _start_capture_process(
                        url=f"http://{config.smart_proxy_host}:{config.smart_proxy_port}/ui/index.html",
                        capture_ms=capture_ms,
                        output_dir=smart_dashboard_dir,
                        stdout_path=smart_dashboard_dir / "capture.stdout.log",
                        stderr_path=smart_dashboard_dir / "capture.stderr.log",
                    ),
                    smart_dashboard_dir / "capture.stderr.log",
                ),
                (
                    "compare page capture",
                    _start_capture_process(
                        url=compare_url,
                        capture_ms=capture_ms,
                        screenshot_path=run_dir / "demo_compare.png",
                        stdout_path=run_dir / "demo_compare_capture.stdout.log",
                        stderr_path=run_dir / "demo_compare_capture.stderr.log",
                    ),
                    run_dir / "demo_compare_capture.stderr.log",
                ),
            ]

        if config.open_browser:
            webbrowser.open(compare_url, new=2)

        simulator_process = _spawn(
            [python_exe, str(BASE_DIR / "simulator" / "replay_publisher.py"), "--data-file", str(config.data_file)],
            env=_build_simulator_env(config),
            stdout_path=run_dir / "simulator.stdout.log",
            stderr_path=run_dir / "simulator.stderr.log",
        )
        _wait_for_process_exit(
            simulator_process,
            timeout_s=config.duration_s + 20,
            process_name="simulator",
            stderr_path=run_dir / "simulator.stderr.log",
        )

        if config.settle_after_run_s > 0:
            time.sleep(config.settle_after_run_s)

        for process_name, process, stderr_path in capture_processes:
            _wait_for_process_exit(
                process,
                timeout_s=_capture_wait_timeout_s(config),
                process_name=process_name,
                stderr_path=stderr_path,
            )

        metrics_targets = [
            ("baseline_gateway_metrics.json", f"http://{config.baseline_gateway_host}:{config.baseline_gateway_port}/metrics"),
            ("smart_gateway_metrics.json", f"http://{config.smart_gateway_host}:{config.smart_gateway_port}/metrics"),
            ("baseline_proxy_metrics.json", f"http://{config.baseline_proxy_host}:{config.baseline_proxy_port}/metrics"),
            ("smart_proxy_metrics.json", f"http://{config.smart_proxy_host}:{config.smart_proxy_port}/metrics"),
        ]
        for filename, url in metrics_targets:
            payload = _fetch_json(url)
            (run_dir / filename).write_text(json.dumps(payload, indent=2), encoding="utf-8")

        _copy_if_exists(
            LOGS_ROOT / baseline_gateway_run_id / "gateway_forward_log.csv",
            run_dir / "baseline_gateway_forward_log.csv",
        )
        _copy_if_exists(
            LOGS_ROOT / smart_gateway_run_id / "gateway_forward_log.csv",
            run_dir / "smart_gateway_forward_log.csv",
        )
    finally:
        if simulator_process is not None:
            _terminate_process(simulator_process)
        for _, process, _ in reversed(capture_processes):
            _terminate_process(process)
        for process in reversed(list(processes.values())):
            _terminate_process(process)

    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return run_dir


def main() -> None:
    config = parse_args()
    validate_environment(config)
    run_dir = run_demo(config)
    print(f"Demo compare page: {build_compare_url(config)}")
    print(
        json.dumps(
            {
                "run_id": config.run_id,
                "run_dir": str(run_dir),
                "compare_url": build_compare_url(config),
                "capture_artifacts": config.capture_artifacts,
                "effective_ports": effective_port_map(config),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
