from __future__ import annotations

import argparse
import csv
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments.run_v1_v2_isolation_sweep import parse_csv_list
from experiments.run_sweep import LOGS_ROOT, SweepConfig, _port_open, ensure_browser_capture_prerequisites, run_once

DEFAULT_VARIANTS = ["v2", "v3"]
DEFAULT_SCENARIOS = ["bandwidth_200kbps", "loss_2pct"]


@dataclass(slots=True)
class AdaptiveImpairmentSweepConfig:
    sweep_id: str
    data_file: Path
    scenarios: list[str]
    duration_s: int
    replay_speed: float
    sensor_limit: int
    batch_window_ms: int
    gateway_host: str
    gateway_port: int
    proxy_host: str
    proxy_port: int
    mqtt_host: str
    mqtt_port: int
    run_browser: bool
    adaptive_min_batch_window_ms: int | None = None
    adaptive_max_batch_window_ms: int | None = None
    adaptive_step_up_ms: int | None = None
    adaptive_step_down_ms: int | None = None
    adaptive_queue_high_watermark: int | None = None
    adaptive_queue_low_watermark: int | None = None
    adaptive_send_slow_ms: int | None = None
    adaptive_recovery_streak: int | None = None


def _adaptive_gateway_overrides(config: AdaptiveImpairmentSweepConfig) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for env_name, value in [
        ("ADAPTIVE_MIN_BATCH_WINDOW_MS", config.adaptive_min_batch_window_ms),
        ("ADAPTIVE_MAX_BATCH_WINDOW_MS", config.adaptive_max_batch_window_ms),
        ("ADAPTIVE_STEP_UP_MS", config.adaptive_step_up_ms),
        ("ADAPTIVE_STEP_DOWN_MS", config.adaptive_step_down_ms),
        ("ADAPTIVE_QUEUE_HIGH_WATERMARK", config.adaptive_queue_high_watermark),
        ("ADAPTIVE_QUEUE_LOW_WATERMARK", config.adaptive_queue_low_watermark),
        ("ADAPTIVE_SEND_SLOW_MS", config.adaptive_send_slow_ms),
        ("ADAPTIVE_RECOVERY_STREAK", config.adaptive_recovery_streak),
    ]:
        if value is not None:
            overrides[env_name] = str(value)
    return overrides


def build_sweep_config(
    config: AdaptiveImpairmentSweepConfig,
    *,
    variant: str,
    scenario: str,
) -> SweepConfig:
    return SweepConfig(
        sweep_id=config.sweep_id,
        variants=[variant],
        qos_values=[0],
        scenarios=[scenario],
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
        batch_window_ms=config.batch_window_ms,
        gateway_env_overrides=_adaptive_gateway_overrides(config),
    )


def _write_summary_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["scenario", "variant", "batch_window_ms", "run_id", "run_dir"],
        )
        writer.writeheader()
        writer.writerows(rows)


def run_adaptive_impairment_sweep(config: AdaptiveImpairmentSweepConfig) -> Path:
    if not _port_open(config.mqtt_host, config.mqtt_port):
        raise SystemExit(
            f"MQTT broker is not reachable at {config.mqtt_host}:{config.mqtt_port}. "
            "Start Mosquitto before running experiments/run_adaptive_impairment_sweep.py."
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
    for scenario in config.scenarios:
        for variant in DEFAULT_VARIANTS:
            run_config = build_sweep_config(config, variant=variant, scenario=scenario)
            run_dir = run_once(
                run_config,
                variant=variant,
                mqtt_qos=0,
                scenario_name=scenario,
            )
            completed_runs.append(
                {
                    "scenario": scenario,
                    "variant": variant,
                    "batch_window_ms": config.batch_window_ms,
                    "run_dir": str(run_dir),
                    "run_id": run_dir.name,
                }
            )

    manifest = {
        "sweep_id": config.sweep_id,
        "data_file": str(config.data_file),
        "variants": DEFAULT_VARIANTS,
        "scenarios": config.scenarios,
        "mqtt_qos": 0,
        "batch_window_ms": config.batch_window_ms,
        "duration_s": config.duration_s,
        "replay_speed": config.replay_speed,
        "sensor_limit": config.sensor_limit,
        "burst_enabled": True,
        "adaptive_overrides": _adaptive_gateway_overrides(config),
        "runs": completed_runs,
    }
    (sweep_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _write_summary_csv(sweep_dir / "summary.csv", completed_runs)
    return sweep_dir


def parse_args(argv: list[str] | None = None) -> AdaptiveImpairmentSweepConfig:
    parser = argparse.ArgumentParser(description="Run the Intel V2 versus V3 adaptive impairment sweep for M6.")
    parser.add_argument("--sweep-id", default="intel-v2-v3-adaptive-20260404")
    parser.add_argument("--data-file", type=Path, required=True)
    parser.add_argument("--scenarios", type=parse_csv_list, default=DEFAULT_SCENARIOS)
    parser.add_argument("--duration-s", type=int, default=30)
    parser.add_argument("--replay-speed", type=float, default=5.0)
    parser.add_argument("--sensor-limit", type=int, default=200)
    parser.add_argument("--batch-window-ms", type=int, default=250)
    parser.add_argument("--gateway-host", default="127.0.0.1")
    parser.add_argument("--gateway-port", type=int, default=8000)
    parser.add_argument("--proxy-host", default="127.0.0.1")
    parser.add_argument("--proxy-port", type=int, default=9000)
    parser.add_argument("--mqtt-host", default="127.0.0.1")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--adaptive-min-batch-window-ms", type=int)
    parser.add_argument("--adaptive-max-batch-window-ms", type=int)
    parser.add_argument("--adaptive-step-up-ms", type=int)
    parser.add_argument("--adaptive-step-down-ms", type=int)
    parser.add_argument("--adaptive-queue-high-watermark", type=int)
    parser.add_argument("--adaptive-queue-low-watermark", type=int)
    parser.add_argument("--adaptive-send-slow-ms", type=int)
    parser.add_argument("--adaptive-recovery-streak", type=int)
    parser.add_argument("--skip-browser", action="store_true")
    args = parser.parse_args(argv)
    return AdaptiveImpairmentSweepConfig(
        sweep_id=args.sweep_id,
        data_file=args.data_file,
        scenarios=args.scenarios,
        duration_s=args.duration_s,
        replay_speed=args.replay_speed,
        sensor_limit=args.sensor_limit,
        batch_window_ms=args.batch_window_ms,
        gateway_host=args.gateway_host,
        gateway_port=args.gateway_port,
        proxy_host=args.proxy_host,
        proxy_port=args.proxy_port,
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        run_browser=not args.skip_browser,
        adaptive_min_batch_window_ms=args.adaptive_min_batch_window_ms,
        adaptive_max_batch_window_ms=args.adaptive_max_batch_window_ms,
        adaptive_step_up_ms=args.adaptive_step_up_ms,
        adaptive_step_down_ms=args.adaptive_step_down_ms,
        adaptive_queue_high_watermark=args.adaptive_queue_high_watermark,
        adaptive_queue_low_watermark=args.adaptive_queue_low_watermark,
        adaptive_send_slow_ms=args.adaptive_send_slow_ms,
        adaptive_recovery_streak=args.adaptive_recovery_streak,
    )


def main() -> None:
    config = parse_args()
    sweep_dir = run_adaptive_impairment_sweep(config)
    print(json.dumps({"sweep_id": config.sweep_id, "sweep_dir": str(sweep_dir)}, indent=2))


if __name__ == "__main__":
    main()
