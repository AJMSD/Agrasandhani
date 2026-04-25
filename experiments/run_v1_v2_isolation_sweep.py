from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments.run_batch_window_sweep import build_run_label_suffix, parse_batch_windows
from experiments.run_sweep import (
    DEFAULT_IMPAIRMENT_SEED,
    LOGS_ROOT,
    SweepConfig,
    _port_open,
    ensure_browser_capture_prerequisites,
    parse_seed_list,
    run_once,
)
from experiments.sweep_aggregation import write_condition_aggregates, write_summary_csv

DEFAULT_VARIANTS = ["v1", "v2"]
DEFAULT_SCENARIOS = ["clean", "bandwidth_200kbps", "outage_5s"]
DEFAULT_BATCH_WINDOWS = [50, 100, 250, 500, 1000]


@dataclass(slots=True)
class V1V2IsolationSweepConfig:
    sweep_id: str
    data_file: Path
    scenarios: list[str]
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
    trial_seeds: list[int] | None = None
    default_impairment_seed: int = DEFAULT_IMPAIRMENT_SEED


def parse_csv_list(raw_value: str) -> list[str]:
    values = [item.strip() for item in raw_value.split(",") if item.strip()]
    if not values:
        raise argparse.ArgumentTypeError("value list must not be empty")
    return values


def build_sweep_config(
    config: V1V2IsolationSweepConfig,
    *,
    variant: str,
    scenario: str,
    batch_window_ms: int,
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
        batch_window_ms=batch_window_ms,
    )


SUMMARY_CSV_FIELDS = [
    "scenario",
    "variant",
    "batch_window_ms",
    "condition_id",
    "trial_id",
    "trial_index",
    "impairment_seed",
    "run_id",
    "run_dir",
]


def run_v1_v2_isolation_sweep(config: V1V2IsolationSweepConfig) -> Path:
    if not _port_open(config.mqtt_host, config.mqtt_port):
        raise SystemExit(
            f"MQTT broker is not reachable at {config.mqtt_host}:{config.mqtt_port}. "
            "Start Mosquitto before running experiments/run_v1_v2_isolation_sweep.py."
        )
    if config.run_browser:
        ensure_browser_capture_prerequisites()
    if not config.data_file.exists():
        raise SystemExit(f"Intel replay CSV was not found: {config.data_file}")

    sweep_dir = LOGS_ROOT / config.sweep_id
    if sweep_dir.exists():
        raise SystemExit(f"Sweep output root already exists and will not be overwritten: {sweep_dir}")
    sweep_dir.mkdir(parents=True, exist_ok=True)

    completed_runs: list[dict[str, object]] = []
    trial_seeds = config.trial_seeds or [config.default_impairment_seed]
    use_trial_layout = len(trial_seeds) > 1
    for scenario in config.scenarios:
        for batch_window_ms in config.batch_windows:
            for variant in DEFAULT_VARIANTS:
                for trial_index, impairment_seed in enumerate(trial_seeds, start=1):
                    run_config = build_sweep_config(
                        config,
                        variant=variant,
                        scenario=scenario,
                        batch_window_ms=batch_window_ms,
                    )
                    run_once_kwargs: dict[str, object] = {}
                    if use_trial_layout:
                        run_once_kwargs["trial_index"] = trial_index
                        run_once_kwargs["impairment_seed"] = impairment_seed
                    run_dir = run_once(
                        run_config,
                        variant=variant,
                        mqtt_qos=0,
                        scenario_name=scenario,
                        run_label_suffix=build_run_label_suffix(batch_window_ms),
                        **run_once_kwargs,
                    )
                    completed_runs.append(
                        {
                            "scenario": scenario,
                            "variant": variant,
                            "batch_window_ms": batch_window_ms,
                            "run_dir": str(run_dir),
                            "run_id": f"{run_dir.parent.name}-{run_dir.name}" if use_trial_layout else run_dir.name,
                            "condition_id": run_dir.parent.name if use_trial_layout else run_dir.name,
                            "trial_id": run_dir.name if use_trial_layout else None,
                            "trial_index": trial_index if use_trial_layout else None,
                            "impairment_seed": impairment_seed,
                        }
                    )

    manifest = {
        "schema_version": 2,
        "sweep_id": config.sweep_id,
        "data_file": str(config.data_file),
        "variants": DEFAULT_VARIANTS,
        "scenarios": config.scenarios,
        "mqtt_qos": 0,
        "batch_windows_ms": config.batch_windows,
        "duration_s": config.duration_s,
        "replay_speed": config.replay_speed,
        "sensor_limit": config.sensor_limit,
        "burst_enabled": True,
        "trial_seeds": trial_seeds,
        "runs": completed_runs,
    }
    (sweep_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_summary_csv(sweep_dir / "summary.csv", fieldnames=SUMMARY_CSV_FIELDS, rows=completed_runs)
    write_condition_aggregates(sweep_dir)
    return sweep_dir


def parse_args(argv: list[str] | None = None) -> V1V2IsolationSweepConfig:
    parser = argparse.ArgumentParser(description="Run the Intel V1 versus V2 isolation sweep for M6.")
    parser.add_argument("--sweep-id", default="intel-v1-v2-isolation-20260403")
    parser.add_argument("--data-file", type=Path, required=True)
    parser.add_argument("--scenarios", type=parse_csv_list, default=DEFAULT_SCENARIOS)
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
    parser.add_argument("--impairment-seed", type=int, default=DEFAULT_IMPAIRMENT_SEED)
    parser.add_argument("--trial-seeds", type=parse_seed_list)
    parser.add_argument("--skip-browser", action="store_true")
    args = parser.parse_args(argv)
    return V1V2IsolationSweepConfig(
        sweep_id=args.sweep_id,
        data_file=args.data_file,
        scenarios=args.scenarios,
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
        trial_seeds=args.trial_seeds,
        default_impairment_seed=args.impairment_seed,
    )


def main() -> None:
    config = parse_args()
    sweep_dir = run_v1_v2_isolation_sweep(config)
    print(json.dumps({"sweep_id": config.sweep_id, "sweep_dir": str(sweep_dir)}, indent=2))


if __name__ == "__main__":
    main()
