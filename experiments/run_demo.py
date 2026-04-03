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

BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_ROOT = BASE_DIR / "experiments" / "logs"
DEFAULT_SCENARIO_FILE = BASE_DIR / "experiments" / "scenarios" / "demo_v0_vs_v4.json"
DEFAULT_DATA_FILE = BASE_DIR / "simulator" / "sample_data.csv"


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
        settle_after_run_s=args.settle_after_run_s,
    )


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

    port_checks = [
        ("baseline_gateway", config.baseline_gateway_host, config.baseline_gateway_port),
        ("smart_gateway", config.smart_gateway_host, config.smart_gateway_port),
        ("baseline_proxy", config.baseline_proxy_host, config.baseline_proxy_port),
        ("smart_proxy", config.smart_proxy_host, config.smart_proxy_port),
    ]
    busy_ports = [f"{label}={host}:{port}" for label, host, port in port_checks if not _port_available(host, port)]
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


def run_demo(config: DemoConfig) -> Path:
    python_exe = _find_python()
    run_dir = LOGS_ROOT / config.run_id / "demo"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    baseline_gateway_run_id = f"{config.run_id}-baseline-gateway"
    smart_gateway_run_id = f"{config.run_id}-smart-gateway"
    compare_url = build_compare_url(config)
    scenario_metadata = load_scenario_metadata(config.scenario_file)

    baseline_gateway_env = os.environ.copy() | {
        "RUN_ID": baseline_gateway_run_id,
        "MQTT_HOST": config.mqtt_host,
        "MQTT_PORT": str(config.mqtt_port),
        "MQTT_QOS": str(config.mqtt_qos),
        "WS_HOST": config.baseline_gateway_host,
        "WS_PORT": str(config.baseline_gateway_port),
        "GATEWAY_MODE": "v0",
    }
    smart_gateway_env = os.environ.copy() | {
        "RUN_ID": smart_gateway_run_id,
        "MQTT_HOST": config.mqtt_host,
        "MQTT_PORT": str(config.mqtt_port),
        "MQTT_QOS": str(config.mqtt_qos),
        "WS_HOST": config.smart_gateway_host,
        "WS_PORT": str(config.smart_gateway_port),
        "GATEWAY_MODE": "v4",
        "FRESHNESS_TTL_MS": "1000",
    }
    baseline_proxy_env = os.environ.copy() | {
        "RUN_ID": f"{config.run_id}-baseline-proxy",
        "IMPAIR_HOST": config.baseline_proxy_host,
        "IMPAIR_PORT": str(config.baseline_proxy_port),
        "UPSTREAM_WS_URL": f"ws://{config.baseline_gateway_host}:{config.baseline_gateway_port}/ws",
        "UPSTREAM_HTTP_BASE": f"http://{config.baseline_gateway_host}:{config.baseline_gateway_port}",
        "IMPAIR_SCENARIO_FILE": str(config.scenario_file),
        "IMPAIR_RANDOM_SEED": "537",
        "IMPAIR_FRAME_LOG_PATH": str(run_dir / "baseline_proxy_frame_log.csv"),
    }
    smart_proxy_env = os.environ.copy() | {
        "RUN_ID": f"{config.run_id}-smart-proxy",
        "IMPAIR_HOST": config.smart_proxy_host,
        "IMPAIR_PORT": str(config.smart_proxy_port),
        "UPSTREAM_WS_URL": f"ws://{config.smart_gateway_host}:{config.smart_gateway_port}/ws",
        "UPSTREAM_HTTP_BASE": f"http://{config.smart_gateway_host}:{config.smart_gateway_port}",
        "IMPAIR_SCENARIO_FILE": str(config.scenario_file),
        "IMPAIR_RANDOM_SEED": "537",
        "IMPAIR_FRAME_LOG_PATH": str(run_dir / "smart_proxy_frame_log.csv"),
    }
    simulator_env = os.environ.copy() | {
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

    processes = {
        "baseline_gateway": _spawn(
            [python_exe, "-m", "gateway.app"],
            env=baseline_gateway_env,
            stdout_path=run_dir / "baseline_gateway.stdout.log",
            stderr_path=run_dir / "baseline_gateway.stderr.log",
        ),
        "smart_gateway": _spawn(
            [python_exe, "-m", "gateway.app"],
            env=smart_gateway_env,
            stdout_path=run_dir / "smart_gateway.stdout.log",
            stderr_path=run_dir / "smart_gateway.stderr.log",
        ),
        "baseline_proxy": _spawn(
            [python_exe, "-m", "experiments.impairment_proxy"],
            env=baseline_proxy_env,
            stdout_path=run_dir / "baseline_proxy.stdout.log",
            stderr_path=run_dir / "baseline_proxy.stderr.log",
        ),
        "smart_proxy": _spawn(
            [python_exe, "-m", "experiments.impairment_proxy"],
            env=smart_proxy_env,
            stdout_path=run_dir / "smart_proxy.stdout.log",
            stderr_path=run_dir / "smart_proxy.stderr.log",
        ),
    }

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
        "services": {
            "baseline_gateway": f"http://{config.baseline_gateway_host}:{config.baseline_gateway_port}",
            "smart_gateway": f"http://{config.smart_gateway_host}:{config.smart_gateway_port}",
            "baseline_proxy": f"http://{config.baseline_proxy_host}:{config.baseline_proxy_port}",
            "smart_proxy": f"http://{config.smart_proxy_host}:{config.smart_proxy_port}",
        },
    }

    try:
        _wait_for_http(f"http://{config.baseline_gateway_host}:{config.baseline_gateway_port}/health")
        _wait_for_http(f"http://{config.smart_gateway_host}:{config.smart_gateway_port}/health")
        _wait_for_http(f"http://{config.baseline_proxy_host}:{config.baseline_proxy_port}/health")
        _wait_for_http(f"http://{config.smart_proxy_host}:{config.smart_proxy_port}/health")

        if config.open_browser:
            webbrowser.open(compare_url, new=2)

        print(f"Demo compare page: {compare_url}")

        simulator_process = _spawn(
            [python_exe, str(BASE_DIR / "simulator" / "replay_publisher.py"), "--data-file", str(config.data_file)],
            env=simulator_env,
            stdout_path=run_dir / "simulator.stdout.log",
            stderr_path=run_dir / "simulator.stderr.log",
        )
        simulator_process.wait(timeout=config.duration_s + 20)
        if simulator_process.returncode != 0:
            raise RuntimeError(f"Simulator exited with code {simulator_process.returncode}")

        if config.settle_after_run_s > 0:
            time.sleep(config.settle_after_run_s)

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
        for process in reversed(list(processes.values())):
            _terminate_process(process)

    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return run_dir


def main() -> None:
    config = parse_args()
    validate_environment(config)
    run_dir = run_demo(config)
    print(json.dumps({"run_id": config.run_id, "run_dir": str(run_dir), "compare_url": build_compare_url(config)}, indent=2))


if __name__ == "__main__":
    main()
