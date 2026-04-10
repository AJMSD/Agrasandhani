from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments import run_adaptive_impairment_sweep as adaptive_sweep
from experiments import run_batch_window_sweep as batch_window_sweep
from experiments import run_sweep as primary_sweep
from experiments import run_v1_v2_isolation_sweep as isolation_sweep
from experiments.run_final_deliverables import (
    GENERATED_INPUTS_DIR as FINAL_DELIVERABLES_GENERATED_INPUTS_DIR,
    SOURCE_SLICE_DIR as FINAL_DELIVERABLES_SOURCE_SLICE_DIR,
    _slice_aot_source,
    _slice_intel_source,
)
from simulator.preprocess_aot import normalize_aot
from simulator.preprocess_intel_lab import normalize_intel_lab

BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_ROOT = BASE_DIR / "experiments" / "logs"
GENERATED_INPUTS_DIR = FINAL_DELIVERABLES_GENERATED_INPUTS_DIR
SOURCE_SLICE_DIR = FINAL_DELIVERABLES_SOURCE_SLICE_DIR

DEFAULT_INTEL_INPUT = LOGS_ROOT / "final-source-downloads" / "intel_data.txt.gz"
DEFAULT_AOT_INPUT = LOGS_ROOT / "final-source-downloads" / "aot_weekly.tar"
PLAN_MANIFEST_PREFIX = "phase6-matrix-plan"

INTEL_PRIMARY_TRIAL_SEEDS = [53701, 53702, 53703]
TARGETED_TRIAL_SEEDS = [53701, 53702]

INTEL_PRIMARY_SCENARIOS = ["clean", "bandwidth_200kbps", "loss_2pct", "delay_50ms_jitter20ms", "outage_5s"]
AOT_VALIDATION_SCENARIOS = ["clean", "outage_5s"]
ADAPTIVE_DEFAULT_SCENARIOS = ["bandwidth_200kbps", "loss_2pct", "delay_50ms_jitter20ms"]
BATCH_WINDOWS_MS = [50, 100, 250, 500, 1000]

INTEL_SOURCE_SENSOR_LIMIT = 54
INTEL_SOURCE_ROWS_PER_SENSOR = 24
INTEL_NORMALIZED_ROWS_PER_SENSOR = 80
AOT_SOURCE_SENSOR_LIMIT = 50
AOT_SOURCE_ROWS_PER_SENSOR = 40


@dataclass(slots=True)
class Phase6Paths:
    manifest_path: Path
    intel_source_slice_path: Path
    aot_source_slice_dir: Path
    intel_replay_csv: Path
    aot_replay_csv: Path


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_path(path: Path) -> str:
    try:
        return path.relative_to(BASE_DIR).as_posix()
    except ValueError:
        return path.as_posix()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lock or execute the Section 6 replicated experiment matrix.")
    parser.add_argument("--stamp", default=time.strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--intel-input", type=Path, default=DEFAULT_INTEL_INPUT)
    parser.add_argument("--aot-input", type=Path, default=DEFAULT_AOT_INPUT)
    parser.add_argument("--mqtt-host", default="127.0.0.1")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Start the replicated runs. Without this flag, the script only writes the Section 6 plan manifest.",
    )
    return parser.parse_args(argv)


def build_phase6_paths(stamp: str) -> Phase6Paths:
    return Phase6Paths(
        manifest_path=LOGS_ROOT / f"{PLAN_MANIFEST_PREFIX}-{stamp}.json",
        intel_source_slice_path=SOURCE_SLICE_DIR / f"intel_lab_slice_{stamp}.txt",
        aot_source_slice_dir=SOURCE_SLICE_DIR / f"aot_slice_{stamp}",
        intel_replay_csv=GENERATED_INPUTS_DIR / f"intel_lab_final_{stamp}.csv",
        aot_replay_csv=GENERATED_INPUTS_DIR / f"aot_final_{stamp}.csv",
    )


def build_intel_primary_config(*, stamp: str, data_file: Path, mqtt_host: str, mqtt_port: int) -> primary_sweep.SweepConfig:
    return primary_sweep.SweepConfig(
        sweep_id=f"final-intel-primary-replicated-{stamp}",
        variants=["v0", "v2", "v4"],
        qos_values=[0, 1],
        scenarios=INTEL_PRIMARY_SCENARIOS,
        data_file=data_file,
        duration_s=30,
        replay_speed=5.0,
        sensor_limit=200,
        burst_enabled=True,
        burst_start_s=5,
        burst_duration_s=10,
        burst_speed_multiplier=8.0,
        gateway_host="127.0.0.1",
        gateway_port=8000,
        proxy_host="127.0.0.1",
        proxy_port=9000,
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port,
        run_browser=True,
        trial_seeds=INTEL_PRIMARY_TRIAL_SEEDS,
    )


def build_aot_validation_config(*, stamp: str, data_file: Path, mqtt_host: str, mqtt_port: int) -> primary_sweep.SweepConfig:
    return primary_sweep.SweepConfig(
        sweep_id=f"final-aot-validation-replicated-{stamp}",
        variants=["v0", "v4"],
        qos_values=[0],
        scenarios=AOT_VALIDATION_SCENARIOS,
        data_file=data_file,
        duration_s=20,
        replay_speed=5.0,
        sensor_limit=50,
        burst_enabled=True,
        burst_start_s=5,
        burst_duration_s=10,
        burst_speed_multiplier=8.0,
        gateway_host="127.0.0.1",
        gateway_port=8000,
        proxy_host="127.0.0.1",
        proxy_port=9000,
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port,
        run_browser=True,
        trial_seeds=TARGETED_TRIAL_SEEDS,
    )


def build_batch_window_config(
    *, stamp: str, data_file: Path, mqtt_host: str, mqtt_port: int
) -> batch_window_sweep.BatchWindowSweepConfig:
    return batch_window_sweep.BatchWindowSweepConfig(
        sweep_id=f"intel-v2-batch-window-replicated-{stamp}",
        data_file=data_file,
        batch_windows=BATCH_WINDOWS_MS,
        duration_s=30,
        replay_speed=5.0,
        sensor_limit=200,
        gateway_host="127.0.0.1",
        gateway_port=8000,
        proxy_host="127.0.0.1",
        proxy_port=9000,
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port,
        run_browser=True,
        trial_seeds=TARGETED_TRIAL_SEEDS,
    )


def build_v1_v2_isolation_config(
    *, stamp: str, data_file: Path, mqtt_host: str, mqtt_port: int
) -> isolation_sweep.V1V2IsolationSweepConfig:
    return isolation_sweep.V1V2IsolationSweepConfig(
        sweep_id=f"intel-v1-v2-isolation-replicated-{stamp}",
        data_file=data_file,
        scenarios=["clean", "bandwidth_200kbps", "outage_5s"],
        batch_windows=BATCH_WINDOWS_MS,
        duration_s=30,
        replay_speed=5.0,
        sensor_limit=200,
        gateway_host="127.0.0.1",
        gateway_port=8000,
        proxy_host="127.0.0.1",
        proxy_port=9000,
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port,
        run_browser=True,
        trial_seeds=TARGETED_TRIAL_SEEDS,
    )


def build_adaptive_default_config(
    *, stamp: str, data_file: Path, mqtt_host: str, mqtt_port: int
) -> adaptive_sweep.AdaptiveImpairmentSweepConfig:
    return adaptive_sweep.AdaptiveImpairmentSweepConfig(
        sweep_id=f"intel-v2-v3-adaptive-replicated-{stamp}",
        data_file=data_file,
        scenarios=ADAPTIVE_DEFAULT_SCENARIOS,
        duration_s=30,
        replay_speed=5.0,
        sensor_limit=200,
        batch_window_ms=250,
        gateway_host="127.0.0.1",
        gateway_port=8000,
        proxy_host="127.0.0.1",
        proxy_port=9000,
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port,
        run_browser=True,
        trial_seeds=TARGETED_TRIAL_SEEDS,
    )


def build_phase6_configs(*, stamp: str, intel_data_file: Path, aot_data_file: Path, mqtt_host: str, mqtt_port: int) -> dict[str, object]:
    return {
        "intel_primary": build_intel_primary_config(
            stamp=stamp,
            data_file=intel_data_file,
            mqtt_host=mqtt_host,
            mqtt_port=mqtt_port,
        ),
        "intel_v2_batch_window": build_batch_window_config(
            stamp=stamp,
            data_file=intel_data_file,
            mqtt_host=mqtt_host,
            mqtt_port=mqtt_port,
        ),
        "intel_v1_v2_isolation": build_v1_v2_isolation_config(
            stamp=stamp,
            data_file=intel_data_file,
            mqtt_host=mqtt_host,
            mqtt_port=mqtt_port,
        ),
        "intel_v2_vs_v3_adaptive": build_adaptive_default_config(
            stamp=stamp,
            data_file=intel_data_file,
            mqtt_host=mqtt_host,
            mqtt_port=mqtt_port,
        ),
        "aot_validation": build_aot_validation_config(
            stamp=stamp,
            data_file=aot_data_file,
            mqtt_host=mqtt_host,
            mqtt_port=mqtt_port,
        ),
    }


def collect_preflight_status(*, mqtt_host: str, mqtt_port: int) -> dict[str, object]:
    browser_capture_ready = True
    browser_capture_detail = None
    try:
        primary_sweep.ensure_browser_capture_prerequisites()
    except SystemExit as exc:
        browser_capture_ready = False
        browser_capture_detail = str(exc)

    return {
        "mqtt_broker_reachable": primary_sweep._port_open(mqtt_host, mqtt_port),
        "browser_capture_ready": browser_capture_ready,
        "browser_capture_detail": browser_capture_detail,
    }


def _expected_run_count(config: object) -> int:
    if isinstance(config, primary_sweep.SweepConfig):
        trial_count = len(config.trial_seeds or [config.default_impairment_seed])
        return len(config.variants) * len(config.qos_values) * len(config.scenarios) * trial_count
    if isinstance(config, batch_window_sweep.BatchWindowSweepConfig):
        trial_count = len(config.trial_seeds or [config.default_impairment_seed])
        return len(config.batch_windows) * trial_count
    if isinstance(config, isolation_sweep.V1V2IsolationSweepConfig):
        trial_count = len(config.trial_seeds or [config.default_impairment_seed])
        return len(isolation_sweep.DEFAULT_VARIANTS) * len(config.scenarios) * len(config.batch_windows) * trial_count
    if isinstance(config, adaptive_sweep.AdaptiveImpairmentSweepConfig):
        trial_count = len(config.trial_seeds or [config.default_impairment_seed])
        return len(adaptive_sweep.DEFAULT_VARIANTS) * len(config.scenarios) * trial_count
    raise TypeError(f"Unsupported sweep config type: {type(config)!r}")


def _build_sweep_entry(name: str, order: int, config: object) -> dict[str, object]:
    entry = {
        "name": name,
        "execution_order": order,
        "sweep_id": config.sweep_id,
        "output_root": _repo_path(LOGS_ROOT / config.sweep_id),
        "aggregate_output_path": _repo_path(LOGS_ROOT / config.sweep_id / "condition_aggregates.json"),
        "data_file": _repo_path(Path(config.data_file)),
        "expected_run_count": _expected_run_count(config),
        "run_browser": bool(config.run_browser),
    }
    if isinstance(config, primary_sweep.SweepConfig):
        entry.update(
            {
                "variants": list(config.variants),
                "qos_values": list(config.qos_values),
                "scenarios": list(config.scenarios),
                "trial_seeds": list(config.trial_seeds or [config.default_impairment_seed]),
                "duration_s": config.duration_s,
                "replay_speed": config.replay_speed,
                "sensor_limit": config.sensor_limit,
            }
        )
        return entry
    if isinstance(config, batch_window_sweep.BatchWindowSweepConfig):
        entry.update(
            {
                "variants": ["v2"],
                "qos_values": [0],
                "scenarios": ["clean"],
                "batch_windows_ms": list(config.batch_windows),
                "trial_seeds": list(config.trial_seeds or [config.default_impairment_seed]),
                "duration_s": config.duration_s,
                "replay_speed": config.replay_speed,
                "sensor_limit": config.sensor_limit,
            }
        )
        return entry
    if isinstance(config, isolation_sweep.V1V2IsolationSweepConfig):
        entry.update(
            {
                "variants": list(isolation_sweep.DEFAULT_VARIANTS),
                "qos_values": [0],
                "scenarios": list(config.scenarios),
                "batch_windows_ms": list(config.batch_windows),
                "trial_seeds": list(config.trial_seeds or [config.default_impairment_seed]),
                "duration_s": config.duration_s,
                "replay_speed": config.replay_speed,
                "sensor_limit": config.sensor_limit,
            }
        )
        return entry
    if isinstance(config, adaptive_sweep.AdaptiveImpairmentSweepConfig):
        entry.update(
            {
                "variants": list(adaptive_sweep.DEFAULT_VARIANTS),
                "qos_values": [0],
                "scenarios": list(config.scenarios),
                "batch_window_ms": config.batch_window_ms,
                "trial_seeds": list(config.trial_seeds or [config.default_impairment_seed]),
                "duration_s": config.duration_s,
                "replay_speed": config.replay_speed,
                "sensor_limit": config.sensor_limit,
            }
        )
        return entry
    raise TypeError(f"Unsupported sweep config type: {type(config)!r}")


def _load_existing_plan_manifest(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _planned_inputs(paths: Phase6Paths) -> dict[str, str]:
    return {
        "intel_source_slice_path": _repo_path(paths.intel_source_slice_path),
        "aot_source_slice_dir": _repo_path(paths.aot_source_slice_dir),
        "intel_replay_csv": _repo_path(paths.intel_replay_csv),
        "aot_replay_csv": _repo_path(paths.aot_replay_csv),
    }


def _build_manifest(
    *,
    args: argparse.Namespace,
    paths: Phase6Paths,
    configs: dict[str, object],
    preflight: dict[str, object],
    execution_details: dict[str, object] | None = None,
) -> dict[str, object]:
    sweep_entries = [
        _build_sweep_entry("intel_primary", 1, configs["intel_primary"]),
        _build_sweep_entry("intel_v2_batch_window", 2, configs["intel_v2_batch_window"]),
        _build_sweep_entry("intel_v1_v2_isolation", 3, configs["intel_v1_v2_isolation"]),
        _build_sweep_entry("intel_v2_vs_v3_adaptive", 4, configs["intel_v2_vs_v3_adaptive"]),
        _build_sweep_entry("aot_validation", 5, configs["aot_validation"]),
    ]
    manifest = {
        "schema_version": 1,
        "script": "experiments/run_replicated_phase6.py",
        "generated_at_utc": _utc_now_iso(),
        "mode": "execute" if args.execute else "plan-only",
        "stamp": args.stamp,
        "execute_flag_required": True,
        "matrix_definition_exit_gate_locked": True,
        "manifest_path": _repo_path(paths.manifest_path),
        "raw_inputs": {
            "intel_input": _repo_path(args.intel_input),
            "intel_input_exists": args.intel_input.exists(),
            "aot_input": _repo_path(args.aot_input),
            "aot_input_exists": args.aot_input.exists(),
        },
        "preflight": preflight,
        "planned_inputs": _planned_inputs(paths),
        "execution_order": [entry["name"] for entry in sweep_entries],
        "total_expected_runs": sum(int(entry["expected_run_count"]) for entry in sweep_entries),
        "sweeps": sweep_entries,
        "runtime_note": "At current durations, full Section 6 execution is expected to take roughly 90-120 minutes wall clock.",
    }
    if execution_details:
        manifest.update(execution_details)
    return manifest


def _ensure_execute_prerequisites(
    *,
    args: argparse.Namespace,
    paths: Phase6Paths,
    preflight: dict[str, object],
    configs: dict[str, object],
) -> None:
    if not args.intel_input.exists():
        raise SystemExit(f"Intel input was not found: {args.intel_input}")
    if not args.aot_input.exists():
        raise SystemExit(f"AoT input was not found: {args.aot_input}")
    if not bool(preflight["mqtt_broker_reachable"]):
        raise SystemExit(
            f"MQTT broker is not reachable at {args.mqtt_host}:{args.mqtt_port}. "
            "Start Mosquitto before executing the Section 6 matrix."
        )
    if not bool(preflight["browser_capture_ready"]):
        detail = preflight.get("browser_capture_detail") or "Browser capture prerequisites are not available."
        raise SystemExit(str(detail))

    conflicts = [
        paths.intel_source_slice_path,
        paths.aot_source_slice_dir,
        paths.intel_replay_csv,
        paths.aot_replay_csv,
    ]
    conflicts.extend(LOGS_ROOT / str(config.sweep_id) for config in configs.values())
    existing = [path for path in conflicts if path.exists()]
    if existing:
        conflict_text = ", ".join(_repo_path(path) for path in existing)
        raise SystemExit(f"Section 6 execution would overwrite existing artifacts: {conflict_text}")


def prepare_replay_inputs(*, args: argparse.Namespace, paths: Phase6Paths) -> dict[str, object]:
    GENERATED_INPUTS_DIR.mkdir(parents=True, exist_ok=True)
    SOURCE_SLICE_DIR.mkdir(parents=True, exist_ok=True)

    intel_slice_rows, intel_slice_sensors = _slice_intel_source(
        input_path=args.intel_input,
        output_path=paths.intel_source_slice_path,
        sensor_limit=INTEL_SOURCE_SENSOR_LIMIT,
        raw_rows_per_sensor=INTEL_SOURCE_ROWS_PER_SENSOR,
    )
    aot_slice_data, aot_slice_sensors_path, aot_slice_rows, aot_slice_sensor_count = _slice_aot_source(
        input_path=args.aot_input,
        output_dir=paths.aot_source_slice_dir,
        sensor_limit=AOT_SOURCE_SENSOR_LIMIT,
        rows_per_sensor=AOT_SOURCE_ROWS_PER_SENSOR,
    )

    intel_rows_written, intel_sensors_written = normalize_intel_lab(
        input_path=paths.intel_source_slice_path,
        output_path=paths.intel_replay_csv,
        sensor_limit=0,
        rows_per_sensor=INTEL_NORMALIZED_ROWS_PER_SENSOR,
    )
    aot_rows_written, aot_sensors_written = normalize_aot(
        input_path=aot_slice_data,
        output_path=paths.aot_replay_csv,
        sensor_limit=AOT_SOURCE_SENSOR_LIMIT,
        rows_per_sensor=AOT_SOURCE_ROWS_PER_SENSOR,
    )

    return {
        "prepared_inputs": {
            "intel_source_slice_path": _repo_path(paths.intel_source_slice_path),
            "intel_source_slice_rows": intel_slice_rows,
            "intel_source_slice_sensor_count": intel_slice_sensors,
            "intel_replay_csv": _repo_path(paths.intel_replay_csv),
            "intel_rows_written": intel_rows_written,
            "intel_sensors_written": intel_sensors_written,
            "aot_source_slice_dir": _repo_path(paths.aot_source_slice_dir),
            "aot_slice_data_path": _repo_path(aot_slice_data),
            "aot_slice_sensors_path": _repo_path(aot_slice_sensors_path),
            "aot_source_slice_rows": aot_slice_rows,
            "aot_source_slice_sensor_count": aot_slice_sensor_count,
            "aot_replay_csv": _repo_path(paths.aot_replay_csv),
            "aot_rows_written": aot_rows_written,
            "aot_sensors_written": aot_sensors_written,
        }
    }


def execute_phase6(*, args: argparse.Namespace, paths: Phase6Paths, configs: dict[str, object], preflight: dict[str, object]) -> dict[str, object]:
    _ensure_execute_prerequisites(args=args, paths=paths, preflight=preflight, configs=configs)
    prepared_inputs = prepare_replay_inputs(args=args, paths=paths)

    executed_sweeps: list[dict[str, str]] = []
    primary_sweep_dir, _ = primary_sweep.run_sweep(configs["intel_primary"])
    executed_sweeps.append(
        {
            "name": "intel_primary",
            "sweep_id": configs["intel_primary"].sweep_id,
            "sweep_dir": _repo_path(primary_sweep_dir),
            "aggregate_output_path": _repo_path(primary_sweep_dir / "condition_aggregates.json"),
        }
    )

    batch_sweep_dir = batch_window_sweep.run_batch_window_sweep(configs["intel_v2_batch_window"])
    executed_sweeps.append(
        {
            "name": "intel_v2_batch_window",
            "sweep_id": configs["intel_v2_batch_window"].sweep_id,
            "sweep_dir": _repo_path(batch_sweep_dir),
            "aggregate_output_path": _repo_path(batch_sweep_dir / "condition_aggregates.json"),
        }
    )

    isolation_sweep_dir = isolation_sweep.run_v1_v2_isolation_sweep(configs["intel_v1_v2_isolation"])
    executed_sweeps.append(
        {
            "name": "intel_v1_v2_isolation",
            "sweep_id": configs["intel_v1_v2_isolation"].sweep_id,
            "sweep_dir": _repo_path(isolation_sweep_dir),
            "aggregate_output_path": _repo_path(isolation_sweep_dir / "condition_aggregates.json"),
        }
    )

    adaptive_sweep_dir = adaptive_sweep.run_adaptive_impairment_sweep(configs["intel_v2_vs_v3_adaptive"])
    executed_sweeps.append(
        {
            "name": "intel_v2_vs_v3_adaptive",
            "sweep_id": configs["intel_v2_vs_v3_adaptive"].sweep_id,
            "sweep_dir": _repo_path(adaptive_sweep_dir),
            "aggregate_output_path": _repo_path(adaptive_sweep_dir / "condition_aggregates.json"),
        }
    )

    aot_sweep_dir, _ = primary_sweep.run_sweep(configs["aot_validation"])
    executed_sweeps.append(
        {
            "name": "aot_validation",
            "sweep_id": configs["aot_validation"].sweep_id,
            "sweep_dir": _repo_path(aot_sweep_dir),
            "aggregate_output_path": _repo_path(aot_sweep_dir / "condition_aggregates.json"),
        }
    )

    return prepared_inputs | {"executed_sweeps": executed_sweeps}


def run_phase6(args: argparse.Namespace) -> tuple[Path, dict[str, object]]:
    paths = build_phase6_paths(args.stamp)
    configs = build_phase6_configs(
        stamp=args.stamp,
        intel_data_file=paths.intel_replay_csv,
        aot_data_file=paths.aot_replay_csv,
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
    )
    preflight = collect_preflight_status(mqtt_host=args.mqtt_host, mqtt_port=args.mqtt_port)

    existing_manifest = _load_existing_plan_manifest(paths.manifest_path)
    if existing_manifest is not None and not args.execute:
        raise SystemExit(f"Phase 6 plan manifest already exists and will not be overwritten: {paths.manifest_path}")
    if existing_manifest is not None and args.execute and existing_manifest.get("mode") != "plan-only":
        raise SystemExit(
            f"Phase 6 manifest already exists but is not a reusable plan-only manifest: {paths.manifest_path}"
        )

    execution_details = None
    if args.execute:
        execution_details = execute_phase6(args=args, paths=paths, configs=configs, preflight=preflight)

    manifest = _build_manifest(
        args=args,
        paths=paths,
        configs=configs,
        preflight=preflight,
        execution_details=execution_details,
    )
    paths.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    paths.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return paths.manifest_path, manifest


def main() -> None:
    manifest_path, manifest = run_phase6(parse_args())
    payload = {"manifest_path": _repo_path(manifest_path)} | manifest
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
