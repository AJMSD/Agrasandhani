from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments import run_adaptive_impairment_sweep as adaptive_sweep
from experiments.run_sweep import (
    DEFAULT_IMPAIRMENT_SEED,
    LOGS_ROOT,
    _port_open,
    ensure_browser_capture_prerequisites,
    parse_seed_list,
    run_once,
)
from experiments.run_v1_v2_isolation_sweep import parse_csv_list
from experiments.sweep_aggregation import write_condition_aggregates, write_summary_csv

DEFAULT_SCENARIOS = ["bandwidth_200kbps", "loss_2pct", "delay_50ms_jitter20ms"]
DEFAULT_ADAPTIVE_SEND_SLOW_VALUES = [25, 50, 100]
DEFAULT_ADAPTIVE_STEP_UP_VALUES = [50, 100]
DEFAULT_ADAPTIVE_MAX_BATCH_WINDOW_VALUES = [500, 1000]


@dataclass(slots=True)
class V3AdaptiveParameterSweepConfig:
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
    adaptive_send_slow_values: list[int] = field(default_factory=lambda: list(DEFAULT_ADAPTIVE_SEND_SLOW_VALUES))
    adaptive_step_up_values: list[int] = field(default_factory=lambda: list(DEFAULT_ADAPTIVE_STEP_UP_VALUES))
    adaptive_max_batch_window_values: list[int] = field(default_factory=lambda: list(DEFAULT_ADAPTIVE_MAX_BATCH_WINDOW_VALUES))
    trial_seeds: list[int] | None = None
    default_impairment_seed: int = DEFAULT_IMPAIRMENT_SEED


SUMMARY_CSV_FIELDS = [
    "scenario",
    "variant",
    "batch_window_ms",
    "adaptive_send_slow_ms",
    "adaptive_step_up_ms",
    "adaptive_max_batch_window_ms",
    "condition_id",
    "trial_id",
    "trial_index",
    "impairment_seed",
    "run_id",
    "run_dir",
]


def _iter_parameter_grid(config: V3AdaptiveParameterSweepConfig) -> list[dict[str, int]]:
    rows: list[dict[str, int]] = []
    for adaptive_send_slow_ms in config.adaptive_send_slow_values:
        for adaptive_step_up_ms in config.adaptive_step_up_values:
            for adaptive_max_batch_window_ms in config.adaptive_max_batch_window_values:
                rows.append(
                    {
                        "adaptive_send_slow_ms": adaptive_send_slow_ms,
                        "adaptive_step_up_ms": adaptive_step_up_ms,
                        "adaptive_max_batch_window_ms": adaptive_max_batch_window_ms,
                    }
                )
    return rows


def _build_adaptive_config(
    config: V3AdaptiveParameterSweepConfig,
    *,
    scenario: str,
    adaptive_send_slow_ms: int,
    adaptive_step_up_ms: int,
    adaptive_max_batch_window_ms: int,
) -> adaptive_sweep.AdaptiveImpairmentSweepConfig:
    return adaptive_sweep.AdaptiveImpairmentSweepConfig(
        sweep_id=config.sweep_id,
        data_file=config.data_file,
        scenarios=[scenario],
        duration_s=config.duration_s,
        replay_speed=config.replay_speed,
        sensor_limit=config.sensor_limit,
        batch_window_ms=config.batch_window_ms,
        gateway_host=config.gateway_host,
        gateway_port=config.gateway_port,
        proxy_host=config.proxy_host,
        proxy_port=config.proxy_port,
        mqtt_host=config.mqtt_host,
        mqtt_port=config.mqtt_port,
        run_browser=config.run_browser,
        adaptive_step_up_ms=adaptive_step_up_ms,
        adaptive_max_batch_window_ms=adaptive_max_batch_window_ms,
        adaptive_send_slow_ms=adaptive_send_slow_ms,
        trial_seeds=config.trial_seeds,
        default_impairment_seed=config.default_impairment_seed,
    )


def run_v3_adaptive_parameter_sweep(config: V3AdaptiveParameterSweepConfig) -> Path:
    if not _port_open(config.mqtt_host, config.mqtt_port):
        raise SystemExit(
            f"MQTT broker is not reachable at {config.mqtt_host}:{config.mqtt_port}. "
            "Start Mosquitto before running experiments/run_v3_adaptive_parameter_sweep.py."
        )
    if config.run_browser:
        ensure_browser_capture_prerequisites()
    if not config.data_file.exists():
        raise SystemExit(f"Intel replay CSV was not found: {config.data_file}")

    sweep_dir = LOGS_ROOT / config.sweep_id
    if sweep_dir.exists():
        raise SystemExit(f"Sweep output root already exists and will not be overwritten: {sweep_dir}")
    sweep_dir.mkdir(parents=True, exist_ok=True)

    trial_seeds = config.trial_seeds or [config.default_impairment_seed]
    use_trial_layout = len(trial_seeds) > 1
    completed_runs: list[dict[str, object]] = []

    parameter_grid = _iter_parameter_grid(config)
    for parameter_row in parameter_grid:
        for scenario in config.scenarios:
            adaptive_config = _build_adaptive_config(
                config,
                scenario=scenario,
                adaptive_send_slow_ms=parameter_row["adaptive_send_slow_ms"],
                adaptive_step_up_ms=parameter_row["adaptive_step_up_ms"],
                adaptive_max_batch_window_ms=parameter_row["adaptive_max_batch_window_ms"],
            )
            run_config = adaptive_sweep.build_sweep_config(
                adaptive_config,
                variant="v3",
                scenario=scenario,
            )
            condition_suffix = adaptive_sweep._adaptive_condition_suffix(adaptive_config)
            for trial_index, impairment_seed in enumerate(trial_seeds, start=1):
                run_once_kwargs: dict[str, object] = {}
                if use_trial_layout:
                    run_once_kwargs["trial_index"] = trial_index
                    run_once_kwargs["impairment_seed"] = impairment_seed
                run_dir = run_once(
                    run_config,
                    variant="v3",
                    mqtt_qos=0,
                    scenario_name=scenario,
                    run_label_suffix=condition_suffix,
                    **run_once_kwargs,
                )
                completed_runs.append(
                    {
                        "scenario": scenario,
                        "variant": "v3",
                        "batch_window_ms": config.batch_window_ms,
                        "adaptive_send_slow_ms": parameter_row["adaptive_send_slow_ms"],
                        "adaptive_step_up_ms": parameter_row["adaptive_step_up_ms"],
                        "adaptive_max_batch_window_ms": parameter_row["adaptive_max_batch_window_ms"],
                        "run_dir": str(run_dir),
                        "run_id": f"{run_dir.parent.name}-{run_dir.name}" if use_trial_layout else run_dir.name,
                        "condition_id": run_dir.parent.name if use_trial_layout else run_dir.name,
                        "trial_id": run_dir.name if use_trial_layout else None,
                        "trial_index": trial_index if use_trial_layout else None,
                        "impairment_seed": impairment_seed,
                    }
                )

    manifest = {
        "schema_version": 1,
        "sweep_id": config.sweep_id,
        "data_file": str(config.data_file),
        "variants": ["v3"],
        "scenarios": config.scenarios,
        "mqtt_qos": 0,
        "batch_window_ms": config.batch_window_ms,
        "duration_s": config.duration_s,
        "replay_speed": config.replay_speed,
        "sensor_limit": config.sensor_limit,
        "burst_enabled": True,
        "parameter_grid": parameter_grid,
        "trial_seeds": trial_seeds,
        "runs": completed_runs,
    }
    (sweep_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_summary_csv(sweep_dir / "summary.csv", fieldnames=SUMMARY_CSV_FIELDS, rows=completed_runs)
    write_condition_aggregates(sweep_dir)
    return sweep_dir


def parse_args(argv: list[str] | None = None) -> V3AdaptiveParameterSweepConfig:
    parser = argparse.ArgumentParser(description="Run the Section 7 V3-only adaptive parameter sweep.")
    parser.add_argument("--sweep-id", required=True)
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
    parser.add_argument("--adaptive-send-slow-values", type=parse_seed_list, default=DEFAULT_ADAPTIVE_SEND_SLOW_VALUES)
    parser.add_argument("--adaptive-step-up-values", type=parse_seed_list, default=DEFAULT_ADAPTIVE_STEP_UP_VALUES)
    parser.add_argument("--adaptive-max-batch-window-values", type=parse_seed_list, default=DEFAULT_ADAPTIVE_MAX_BATCH_WINDOW_VALUES)
    parser.add_argument("--impairment-seed", type=int, default=DEFAULT_IMPAIRMENT_SEED)
    parser.add_argument("--trial-seeds", type=parse_seed_list)
    parser.add_argument("--skip-browser", action="store_true")
    args = parser.parse_args(argv)
    return V3AdaptiveParameterSweepConfig(
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
        adaptive_send_slow_values=args.adaptive_send_slow_values,
        adaptive_step_up_values=args.adaptive_step_up_values,
        adaptive_max_batch_window_values=args.adaptive_max_batch_window_values,
        trial_seeds=args.trial_seeds,
        default_impairment_seed=args.impairment_seed,
    )


def main() -> None:
    config = parse_args()
    sweep_dir = run_v3_adaptive_parameter_sweep(config)
    print(json.dumps({"sweep_id": config.sweep_id, "sweep_dir": str(sweep_dir)}, indent=2))


if __name__ == "__main__":
    main()
