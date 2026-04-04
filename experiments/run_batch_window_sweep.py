from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments.run_sweep import LOGS_ROOT, SweepConfig, _port_open, ensure_browser_capture_prerequisites, run_once

DEFAULT_BATCH_WINDOWS = [50, 100, 250, 500, 1000]


@dataclass(slots=True)
class BatchWindowSweepConfig:
    sweep_id: str
    data_file: Path
    batch_windows: list[int]
    duration_s: int
    replay_speed: float
    sensor_limit: int
    gateway_host: str
    gateway_port: int
    proxy_host: str
    proxy_port: int
    mqtt_host: str
    mqtt_port: int
    run_browser: bool


def parse_batch_windows(raw_value: str) -> list[int]:
    windows = [int(item.strip()) for item in raw_value.split(",") if item.strip()]
    if not windows:
        raise argparse.ArgumentTypeError("batch windows must not be empty")
    if any(window < 1 for window in windows):
        raise argparse.ArgumentTypeError("batch windows must be positive integers")
    return windows


def build_sweep_config(config: BatchWindowSweepConfig, *, batch_window_ms: int) -> SweepConfig:
    return SweepConfig(
        sweep_id=config.sweep_id,
        variants=["v2"],
        qos_values=[0],
        scenarios=["clean"],
        data_file=config.data_file,
        duration_s=config.duration_s,
        replay_speed=config.replay_speed,
        sensor_limit=config.sensor_limit,
        burst_enabled=True,
        burst_start_s=5,
        burst_duration_s=10,
        burst_speed_multiplier=8.0,
        gateway_host=config.gateway_host,
        gateway_port=config.gateway_port,
        proxy_host=config.proxy_host,
        proxy_port=config.proxy_port,
        mqtt_host=config.mqtt_host,
        mqtt_port=config.mqtt_port,
        run_browser=config.run_browser,
        batch_window_ms=batch_window_ms,
    )


def build_run_label_suffix(batch_window_ms: int) -> str:
    return f"bw{batch_window_ms}ms"


def run_batch_window_sweep(config: BatchWindowSweepConfig) -> Path:
    if not _port_open(config.mqtt_host, config.mqtt_port):
        raise SystemExit(
            f"MQTT broker is not reachable at {config.mqtt_host}:{config.mqtt_port}. "
            "Start Mosquitto before running experiments/run_batch_window_sweep.py."
        )
    if config.run_browser:
        ensure_browser_capture_prerequisites()
    if not config.data_file.exists():
        raise SystemExit(f"Intel replay CSV was not found: {config.data_file}")

    sweep_dir = LOGS_ROOT / config.sweep_id
    if sweep_dir.exists():
        shutil.rmtree(sweep_dir)
    sweep_dir.mkdir(parents=True, exist_ok=True)

    completed_runs: list[dict[str, object]] = []
    for batch_window_ms in config.batch_windows:
        run_config = build_sweep_config(config, batch_window_ms=batch_window_ms)
        run_dir = run_once(
            run_config,
            variant="v2",
            mqtt_qos=0,
            scenario_name="clean",
            run_label_suffix=build_run_label_suffix(batch_window_ms),
        )
        completed_runs.append(
            {
                "batch_window_ms": batch_window_ms,
                "run_dir": str(run_dir),
                "run_id": run_dir.name,
            }
        )

    manifest = {
        "sweep_id": config.sweep_id,
        "data_file": str(config.data_file),
        "variant": "v2",
        "scenario": "clean",
        "mqtt_qos": 0,
        "batch_windows_ms": config.batch_windows,
        "duration_s": config.duration_s,
        "replay_speed": config.replay_speed,
        "sensor_limit": config.sensor_limit,
        "burst_enabled": True,
        "runs": completed_runs,
    }
    (sweep_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return sweep_dir


def parse_args(argv: list[str] | None = None) -> BatchWindowSweepConfig:
    parser = argparse.ArgumentParser(description="Run the Intel V2 batch-window tradeoff sweep for M6.")
    parser.add_argument("--sweep-id", default="intel-v2-batch-window-20260403")
    parser.add_argument("--data-file", type=Path, required=True)
    parser.add_argument("--batch-windows", type=parse_batch_windows, default=DEFAULT_BATCH_WINDOWS)
    parser.add_argument("--duration-s", type=int, default=30)
    parser.add_argument("--replay-speed", type=float, default=5.0)
    parser.add_argument("--sensor-limit", type=int, default=200)
    parser.add_argument("--gateway-host", default="127.0.0.1")
    parser.add_argument("--gateway-port", type=int, default=8000)
    parser.add_argument("--proxy-host", default="127.0.0.1")
    parser.add_argument("--proxy-port", type=int, default=9000)
    parser.add_argument("--mqtt-host", default="127.0.0.1")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--skip-browser", action="store_true")
    args = parser.parse_args(argv)
    return BatchWindowSweepConfig(
        sweep_id=args.sweep_id,
        data_file=args.data_file,
        batch_windows=args.batch_windows,
        duration_s=args.duration_s,
        replay_speed=args.replay_speed,
        sensor_limit=args.sensor_limit,
        gateway_host=args.gateway_host,
        gateway_port=args.gateway_port,
        proxy_host=args.proxy_host,
        proxy_port=args.proxy_port,
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        run_browser=not args.skip_browser,
    )


def main() -> None:
    config = parse_args()
    sweep_dir = run_batch_window_sweep(config)
    print(json.dumps({"sweep_id": config.sweep_id, "sweep_dir": str(sweep_dir)}, indent=2))


if __name__ == "__main__":
    main()
