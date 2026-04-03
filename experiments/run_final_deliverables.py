from __future__ import annotations

import argparse
import csv
import gzip
import json
import shutil
import socket
import tarfile
import time
from io import TextIOWrapper
from pathlib import Path

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments.build_report_assets import build_report_assets
from experiments.plot_sweep import plot_sweep
from experiments.run_demo import DemoConfig, run_demo, validate_environment as validate_demo_environment
from experiments.run_sweep import SweepConfig, ensure_browser_capture_prerequisites, run_once
from simulator.preprocess_aot import normalize_aot
from simulator.preprocess_intel_lab import normalize_intel_lab

BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_ROOT = BASE_DIR / "experiments" / "logs"
GENERATED_INPUTS_DIR = LOGS_ROOT / "generated_inputs"
DEFAULT_REPORT_DIR = BASE_DIR / "report"
SOURCE_SLICE_DIR = LOGS_ROOT / "generated_source_slices"

INTEL_PRIMARY_SCENARIOS = ["clean", "bandwidth_200kbps", "loss_2pct", "delay_50ms_jitter20ms", "outage_5s"]
AOT_VALIDATION_SCENARIOS = ["clean", "outage_5s"]


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        try:
            sock.connect((host, port))
            return True
        except OSError:
            return False


def _run_sweep(config: SweepConfig) -> Path:
    if not _port_open(config.mqtt_host, config.mqtt_port):
        raise SystemExit(
            f"MQTT broker is not reachable at {config.mqtt_host}:{config.mqtt_port}. "
            "Start Mosquitto before running experiments/run_final_deliverables.py."
        )
    if config.run_browser:
        ensure_browser_capture_prerequisites()

    sweep_dir = LOGS_ROOT / config.sweep_id
    if sweep_dir.exists():
        shutil.rmtree(sweep_dir)
    sweep_dir.mkdir(parents=True, exist_ok=True)

    for variant in config.variants:
        for qos in config.qos_values:
            for scenario in config.scenarios:
                run_once(config, variant=variant, mqtt_qos=qos, scenario_name=scenario)

    plot_sweep(sweep_dir)
    return sweep_dir


def _open_text_input(path: Path):
    return gzip.open(path, "rt", encoding="utf-8") if path.suffix.lower() == ".gz" else path.open("r", encoding="utf-8")


def _slice_intel_source(*, input_path: Path, output_path: Path, sensor_limit: int, raw_rows_per_sensor: int) -> tuple[int, int]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    selected_sensors: set[str] = set()
    rows_by_sensor: dict[str, int] = {}
    lines_written = 0

    with _open_text_input(input_path) as source, output_path.open("w", encoding="utf-8", newline="") as destination:
        for line in source:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split()
            if len(parts) != 8:
                continue

            sensor_id = parts[3].strip()
            if sensor_limit > 0 and sensor_id not in selected_sensors:
                if len(selected_sensors) >= sensor_limit:
                    continue
                selected_sensors.add(sensor_id)

            current_count = rows_by_sensor.get(sensor_id, 0)
            if current_count >= raw_rows_per_sensor:
                if sensor_limit > 0 and len(selected_sensors) >= sensor_limit and all(
                    count >= raw_rows_per_sensor for count in rows_by_sensor.values()
                ):
                    break
                continue

            destination.write(stripped + "\n")
            rows_by_sensor[sensor_id] = current_count + 1
            lines_written += 1

            if sensor_limit > 0 and len(selected_sensors) >= sensor_limit and all(
                count >= raw_rows_per_sensor for count in rows_by_sensor.values()
            ):
                break

    return lines_written, len(rows_by_sensor)


def _copy_aot_sensors_file(input_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if input_path.is_dir():
        candidate = input_path / "sensors.csv"
        if candidate.exists():
            shutil.copy2(candidate, output_path)
            return
        raise FileNotFoundError(f"Could not find sensors.csv under {input_path}")

    if tarfile.is_tarfile(input_path):
        with tarfile.open(input_path, "r:*") as archive:
            for member in archive.getmembers():
                if member.isfile() and Path(member.name).name.lower() == "sensors.csv":
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        break
                    with extracted, output_path.open("wb") as destination:
                        shutil.copyfileobj(extracted, destination)
                    return
        raise FileNotFoundError(f"Could not find sensors.csv inside {input_path}")

    candidate = input_path.parent / "sensors.csv"
    if candidate.exists():
        shutil.copy2(candidate, output_path)
        return
    raise FileNotFoundError(f"Could not find sibling sensors.csv for {input_path}")


def _iter_aot_data_lines(input_path: Path):
    if input_path.is_dir():
        for candidate in (input_path / "data.csv", input_path / "data.csv.gz"):
            if candidate.exists():
                with _open_text_input(candidate) as source:
                    yield from source
                return
        raise FileNotFoundError(f"Could not find AoT data.csv or data.csv.gz under {input_path}")

    if tarfile.is_tarfile(input_path):
        with tarfile.open(input_path, "r:*") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                if Path(member.name).name.lower() not in {"data.csv", "data.csv.gz"}:
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:
                    continue
                if member.name.lower().endswith(".gz"):
                    with extracted, gzip.GzipFile(fileobj=extracted) as gz_stream, TextIOWrapper(gz_stream, encoding="utf-8", newline="") as source:
                        yield from source
                else:
                    with extracted, TextIOWrapper(extracted, encoding="utf-8", newline="") as source:
                        yield from source
                return
        raise FileNotFoundError(f"Could not find AoT data.csv or data.csv.gz inside {input_path}")

    with _open_text_input(input_path) as source:
        yield from source


def _slice_aot_source(*, input_path: Path, output_dir: Path, sensor_limit: int, rows_per_sensor: int) -> tuple[Path, Path, int, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    data_output = output_dir / "data.csv"
    sensors_output = output_dir / "sensors.csv"
    _copy_aot_sensors_file(input_path, sensors_output)

    selected_sensors: set[str] = set()
    rows_by_sensor: dict[str, int] = {}
    rows_written = 0
    writer = None

    with data_output.open("w", encoding="utf-8", newline="") as destination:
        for line in _iter_aot_data_lines(input_path):
            stripped = line.strip()
            if not stripped:
                continue
            if writer is None:
                header = next(csv.reader([stripped]))
                writer = csv.writer(destination)
                writer.writerow(header)
                continue

            row = next(csv.reader([stripped]))
            if len(row) < 2:
                continue
            sensor_id = row[1].strip()
            if sensor_limit > 0 and sensor_id not in selected_sensors:
                if len(selected_sensors) >= sensor_limit:
                    continue
                selected_sensors.add(sensor_id)

            current_count = rows_by_sensor.get(sensor_id, 0)
            if current_count >= rows_per_sensor:
                if sensor_limit > 0 and len(selected_sensors) >= sensor_limit and all(
                    count >= rows_per_sensor for count in rows_by_sensor.values()
                ):
                    break
                continue

            writer.writerow(row)
            rows_by_sensor[sensor_id] = current_count + 1
            rows_written += 1

            if sensor_limit > 0 and len(selected_sensors) >= sensor_limit and all(
                count >= rows_per_sensor for count in rows_by_sensor.values()
            ):
                break

    return data_output, sensors_output, rows_written, len(rows_by_sensor)


def build_intel_primary_config(*, stamp: str, data_file: Path, mqtt_host: str, mqtt_port: int) -> SweepConfig:
    return SweepConfig(
        sweep_id=f"final-intel-primary-{stamp}",
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
    )


def build_aot_validation_config(*, stamp: str, data_file: Path, mqtt_host: str, mqtt_port: int) -> SweepConfig:
    return SweepConfig(
        sweep_id=f"final-aot-validation-{stamp}",
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
    )


def build_demo_config(*, stamp: str, data_file: Path, mqtt_host: str, mqtt_port: int) -> DemoConfig:
    return DemoConfig(
        run_id=f"final-demo-{stamp}",
        data_file=data_file,
        scenario_file=BASE_DIR / "experiments" / "scenarios" / "demo_v0_vs_v4.json",
        duration_s=20,
        replay_speed=5.0,
        sensor_limit=200,
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port,
        mqtt_qos=0,
        burst_enabled=True,
        burst_start_s=2,
        burst_duration_s=4,
        burst_speed_multiplier=8.0,
        baseline_gateway_host="127.0.0.1",
        baseline_gateway_port=8000,
        smart_gateway_host="127.0.0.1",
        smart_gateway_port=8001,
        baseline_proxy_host="127.0.0.1",
        baseline_proxy_port=9000,
        smart_proxy_host="127.0.0.1",
        smart_proxy_port=9001,
        left_label="Baseline v0",
        right_label="Smart v4",
        open_browser=False,
        auto_ports=False,
        capture_artifacts=True,
        settle_after_run_s=2,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run final M5 preprocessing, evidence sweeps, demo capture, and report asset generation.")
    parser.add_argument("--intel-input", type=Path, required=True)
    parser.add_argument("--aot-input", type=Path, required=True)
    parser.add_argument("--stamp", default=time.strftime("%Y%m%d"))
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--mqtt-host", default="127.0.0.1")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    return parser.parse_args(argv)


def run_final_deliverables(args: argparse.Namespace) -> dict[str, object]:
    ensure_browser_capture_prerequisites()
    if not _port_open(args.mqtt_host, args.mqtt_port):
        raise SystemExit(
            f"MQTT broker is not reachable at {args.mqtt_host}:{args.mqtt_port}. "
            "Start Mosquitto before running experiments/run_final_deliverables.py."
        )
    if not args.intel_input.exists():
        raise SystemExit(f"Intel Lab input was not found: {args.intel_input}")
    if not args.aot_input.exists():
        raise SystemExit(f"AoT input was not found: {args.aot_input}")

    GENERATED_INPUTS_DIR.mkdir(parents=True, exist_ok=True)
    SOURCE_SLICE_DIR.mkdir(parents=True, exist_ok=True)
    final_log_dir = LOGS_ROOT / f"final-deliverables-{args.stamp}"
    if final_log_dir.exists():
        shutil.rmtree(final_log_dir)
    final_log_dir.mkdir(parents=True, exist_ok=True)

    intel_output = GENERATED_INPUTS_DIR / f"intel_lab_final_{args.stamp}.csv"
    aot_output = GENERATED_INPUTS_DIR / f"aot_final_{args.stamp}.csv"
    intel_slice = SOURCE_SLICE_DIR / f"intel_lab_slice_{args.stamp}.txt"
    aot_slice_dir = SOURCE_SLICE_DIR / f"aot_slice_{args.stamp}"

    intel_slice_rows, intel_slice_sensors = _slice_intel_source(
        input_path=args.intel_input,
        output_path=intel_slice,
        sensor_limit=54,
        raw_rows_per_sensor=24,
    )
    aot_slice_data, aot_slice_sensors_path, aot_slice_rows, aot_slice_sensor_count = _slice_aot_source(
        input_path=args.aot_input,
        output_dir=aot_slice_dir,
        sensor_limit=50,
        rows_per_sensor=40,
    )

    intel_rows_written, intel_sensors_written = normalize_intel_lab(
        input_path=intel_slice,
        output_path=intel_output,
        sensor_limit=0,
        rows_per_sensor=80,
    )
    aot_rows_written, aot_sensors_written = normalize_aot(
        input_path=aot_slice_data,
        output_path=aot_output,
        sensor_limit=50,
        rows_per_sensor=40,
    )

    intel_config = build_intel_primary_config(
        stamp=args.stamp,
        data_file=intel_output,
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
    )
    aot_config = build_aot_validation_config(
        stamp=args.stamp,
        data_file=aot_output,
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
    )
    demo_config = build_demo_config(
        stamp=args.stamp,
        data_file=intel_output,
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
    )

    intel_sweep_dir = _run_sweep(intel_config)
    aot_sweep_dir = _run_sweep(aot_config)
    validate_demo_environment(demo_config)
    demo_dir = run_demo(demo_config)
    report_assets_dir = args.report_dir / "assets"
    assets_manifest = build_report_assets(
        intel_sweep_dir=intel_sweep_dir,
        aot_sweep_dir=aot_sweep_dir,
        demo_dir=demo_dir,
        output_dir=report_assets_dir,
    )

    manifest = {
        "stamp": args.stamp,
        "intel_input": str(args.intel_input),
        "aot_input": str(args.aot_input),
        "intel_output": str(intel_output),
        "aot_output": str(aot_output),
        "intel_slice": str(intel_slice),
        "aot_slice_data": str(aot_slice_data),
        "aot_slice_sensors": str(aot_slice_sensors_path),
        "intel_slice_rows": intel_slice_rows,
        "intel_slice_sensors": intel_slice_sensors,
        "aot_slice_rows": aot_slice_rows,
        "aot_slice_sensor_count": aot_slice_sensor_count,
        "intel_rows_written": intel_rows_written,
        "intel_sensors_written": intel_sensors_written,
        "aot_rows_written": aot_rows_written,
        "aot_sensors_written": aot_sensors_written,
        "intel_sweep_id": intel_config.sweep_id,
        "aot_sweep_id": aot_config.sweep_id,
        "demo_run_id": demo_config.run_id,
        "intel_sweep_dir": str(intel_sweep_dir),
        "aot_sweep_dir": str(aot_sweep_dir),
        "demo_dir": str(demo_dir),
        "report_assets_dir": str(report_assets_dir),
        "commands": {
            "intel_primary": {
                "variants": intel_config.variants,
                "qos_values": intel_config.qos_values,
                "scenarios": intel_config.scenarios,
                "duration_s": intel_config.duration_s,
                "replay_speed": intel_config.replay_speed,
                "sensor_limit": intel_config.sensor_limit,
            },
            "aot_validation": {
                "variants": aot_config.variants,
                "qos_values": aot_config.qos_values,
                "scenarios": aot_config.scenarios,
                "duration_s": aot_config.duration_s,
                "replay_speed": aot_config.replay_speed,
                "sensor_limit": aot_config.sensor_limit,
            },
            "demo": {
                "run_id": demo_config.run_id,
                "scenario_file": str(demo_config.scenario_file),
                "capture_artifacts": demo_config.capture_artifacts,
            },
        },
        "report_assets_manifest": assets_manifest,
    }
    (final_log_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    args = parse_args()
    manifest = run_final_deliverables(args)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
