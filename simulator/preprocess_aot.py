from __future__ import annotations

import argparse
import csv
import gzip
import logging
import tarfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from io import TextIOWrapper
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from simulator.preprocess_common import Measurement, parse_numeric, write_normalized_csv
except ModuleNotFoundError:  # pragma: no cover - script entrypoint fallback
    from preprocess_common import Measurement, parse_numeric, write_normalized_csv

LOGGER = logging.getLogger(__name__)
TARGET_METRICS = {"temperature", "humidity"}
try:
    AOT_DEFAULT_TIMEZONE = ZoneInfo("America/Chicago")
except ZoneInfoNotFoundError:  # pragma: no cover - depends on host tzdata availability
    AOT_DEFAULT_TIMEZONE = timezone(timedelta(hours=-6), name="America/Chicago")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize AoT data into Agrasandhani replay CSV format")
    parser.add_argument("--input", required=True, help="Path to AoT archive directory, .tar, data.csv, or data.csv.gz")
    parser.add_argument("--output", required=True, help="Output CSV path in unified replay format")
    parser.add_argument("--sensor-limit", type=int, default=0, help="Limit output to the first N sensors encountered")
    parser.add_argument(
        "--rows-per-sensor",
        type=int,
        default=0,
        help="Limit output rows per sensor after normalization",
    )
    return parser.parse_args()


def canonicalize_metric_name(raw_value: str) -> str | None:
    normalized = "".join(character for character in raw_value.strip().lower() if character.isalnum())
    if normalized in {"temperature", "temp"}:
        return "temperature"
    if normalized in {"humidity", "relativehumidity", "relativehumid"}:
        return "humidity"
    return None


def normalize_column_name(name: str) -> str:
    return "".join(character for character in name.strip().lower() if character.isalnum())


def find_column(fieldnames: list[str] | None, candidates: tuple[str, ...], *, required: bool = True) -> str | None:
    if not fieldnames:
        if required:
            raise ValueError("CSV file is missing a header row")
        return None

    normalized_to_original = {normalize_column_name(name): name for name in fieldnames}
    for candidate in candidates:
        match = normalized_to_original.get(normalize_column_name(candidate))
        if match is not None:
            return match

    if required:
        raise ValueError(f"Missing required CSV column. Expected one of: {', '.join(candidates)}")

    return None


def normalize_token(value: object) -> str:
    return normalize_column_name("" if value is None else str(value))


def parse_aot_timestamp(timestamp_text: str) -> int:
    stripped = timestamp_text.strip()
    if not stripped:
        raise ValueError("AoT row is missing a timestamp")

    iso_candidate = stripped.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso_candidate)
    except ValueError:
        parsed = None

    if parsed is None:
        for fmt in (
            "%Y/%m/%d %H:%M:%S.%f",
            "%Y/%m/%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
        ):
            try:
                parsed = datetime.strptime(stripped, fmt)
                break
            except ValueError:
                continue

    if parsed is None:
        raise ValueError(f"Unsupported AoT timestamp format: {timestamp_text}")

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=AOT_DEFAULT_TIMEZONE)

    return int(parsed.timestamp() * 1_000)


def load_metric_rules(sensor_stream) -> tuple[dict[tuple[str, str, str], str], dict[tuple[str, str], str], dict[str, str]]:
    reader = csv.DictReader(sensor_stream)
    subsystem_col = find_column(reader.fieldnames, ("subsystem",), required=False)
    sensor_col = find_column(reader.fieldnames, ("sensor", "sensor_path"), required=False)
    parameter_col = find_column(reader.fieldnames, ("parameter", "parameter_name"), required=False)

    if parameter_col is None:
        return {}, {}, {}

    exact_rules: dict[tuple[str, str, str], str] = {}
    sensor_parameter_rules: dict[tuple[str, str], str] = {}
    parameter_rules: dict[str, str] = {}

    for row in reader:
        parameter_raw = str(row.get(parameter_col, ""))
        metric_type = canonicalize_metric_name(parameter_raw)
        if metric_type not in TARGET_METRICS:
            continue

        parameter_key = normalize_token(parameter_raw)
        subsystem_key = normalize_token(row.get(subsystem_col, "")) if subsystem_col else ""
        sensor_key = normalize_token(row.get(sensor_col, "")) if sensor_col else ""
        exact_rules[(subsystem_key, sensor_key, parameter_key)] = metric_type
        if sensor_key:
            sensor_parameter_rules[(sensor_key, parameter_key)] = metric_type
        parameter_rules[parameter_key] = metric_type

    return exact_rules, sensor_parameter_rules, parameter_rules


def resolve_metric_type(
    *,
    subsystem: str,
    sensor: str,
    parameter: str,
    exact_rules: dict[tuple[str, str, str], str],
    sensor_parameter_rules: dict[tuple[str, str], str],
    parameter_rules: dict[str, str],
) -> str | None:
    normalized_parameter = normalize_token(parameter)
    if not normalized_parameter:
        return None

    rule = exact_rules.get((normalize_token(subsystem), normalize_token(sensor), normalized_parameter))
    if rule is not None:
        return rule

    sensor_rule = sensor_parameter_rules.get((normalize_token(sensor), normalized_parameter))
    if sensor_rule is not None:
        return sensor_rule

    parameter_rule = parameter_rules.get(normalized_parameter)
    if parameter_rule is not None:
        return parameter_rule

    return canonicalize_metric_name(parameter)


@contextmanager
def open_text_file(path: Path):
    if path.suffix.lower() == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", newline="") as input_file:
            yield input_file
        return

    with path.open("r", encoding="utf-8", newline="") as input_file:
        yield input_file


@contextmanager
def open_tar_text_member(archive: tarfile.TarFile, member: tarfile.TarInfo):
    binary_stream = archive.extractfile(member)
    if binary_stream is None:
        raise FileNotFoundError(f"Could not open archive member {member.name}")

    if member.name.lower().endswith(".gz"):
        gzip_stream = gzip.GzipFile(fileobj=binary_stream)
        text_stream = TextIOWrapper(gzip_stream, encoding="utf-8", newline="")
    else:
        gzip_stream = None
        text_stream = TextIOWrapper(binary_stream, encoding="utf-8", newline="")

    try:
        yield text_stream
    finally:
        text_stream.close()
        if gzip_stream is not None:
            gzip_stream.close()
        binary_stream.close()


def find_first_path(root: Path, names: tuple[str, ...]) -> Path | None:
    lowered_names = {name.lower() for name in names}
    for candidate in root.rglob("*"):
        if candidate.is_file() and candidate.name.lower() in lowered_names:
            return candidate
    return None


def iter_aot_measurements(input_path: Path) -> Iterator[Measurement]:
    if input_path.is_dir():
        data_path = find_first_path(input_path, ("data.csv", "data.csv.gz"))
        if data_path is None:
            raise FileNotFoundError(f"Could not find data.csv or data.csv.gz under {input_path}")
        sensors_path = find_first_path(input_path, ("sensors.csv",))
        yield from iter_aot_measurements_from_paths(data_path=data_path, sensors_path=sensors_path)
        return

    if tarfile.is_tarfile(input_path):
        yield from iter_aot_measurements_from_tar(input_path)
        return

    sensors_path = input_path.parent / "sensors.csv"
    yield from iter_aot_measurements_from_paths(
        data_path=input_path,
        sensors_path=sensors_path if sensors_path.exists() else None,
    )


def iter_aot_measurements_from_tar(archive_path: Path) -> Iterator[Measurement]:
    with tarfile.open(archive_path, "r:*") as archive:
        data_member = None
        sensors_member = None

        for member in archive.getmembers():
            if not member.isfile():
                continue
            member_name = Path(member.name).name.lower()
            if member_name in {"data.csv", "data.csv.gz"} and data_member is None:
                data_member = member
            if member_name == "sensors.csv" and sensors_member is None:
                sensors_member = member

        if data_member is None:
            raise FileNotFoundError(f"Could not find data.csv or data.csv.gz inside {archive_path}")

        exact_rules: dict[tuple[str, str, str], str] = {}
        sensor_parameter_rules: dict[tuple[str, str], str] = {}
        parameter_rules: dict[str, str] = {}
        if sensors_member is not None:
            with open_tar_text_member(archive, sensors_member) as sensors_stream:
                exact_rules, sensor_parameter_rules, parameter_rules = load_metric_rules(sensors_stream)
        else:
            LOGGER.warning("AoT sensors.csv metadata not found in %s; using parameter-name fallback", archive_path)

        with open_tar_text_member(archive, data_member) as data_stream:
            yield from parse_aot_data_stream(
                data_stream,
                exact_rules=exact_rules,
                sensor_parameter_rules=sensor_parameter_rules,
                parameter_rules=parameter_rules,
            )


def iter_aot_measurements_from_paths(*, data_path: Path, sensors_path: Path | None) -> Iterator[Measurement]:
    exact_rules: dict[tuple[str, str, str], str] = {}
    sensor_parameter_rules: dict[tuple[str, str], str] = {}
    parameter_rules: dict[str, str] = {}

    if sensors_path is not None and sensors_path.exists():
        with open_text_file(sensors_path) as sensors_stream:
            exact_rules, sensor_parameter_rules, parameter_rules = load_metric_rules(sensors_stream)
    else:
        LOGGER.warning("AoT sensors.csv metadata not found next to %s; using parameter-name fallback", data_path)

    with open_text_file(data_path) as data_stream:
        yield from parse_aot_data_stream(
            data_stream,
            exact_rules=exact_rules,
            sensor_parameter_rules=sensor_parameter_rules,
            parameter_rules=parameter_rules,
        )


def parse_aot_data_stream(
    data_stream,
    *,
    exact_rules: dict[tuple[str, str, str], str],
    sensor_parameter_rules: dict[tuple[str, str], str],
    parameter_rules: dict[str, str],
) -> Iterator[Measurement]:
    reader = csv.DictReader(data_stream)
    timestamp_col = find_column(reader.fieldnames, ("timestamp", "datetime", "date"))
    node_id_col = find_column(reader.fieldnames, ("node_id", "nodeid", "node"))
    parameter_col = find_column(reader.fieldnames, ("parameter", "parameter_name"))
    subsystem_col = find_column(reader.fieldnames, ("subsystem",), required=False)
    sensor_col = find_column(reader.fieldnames, ("sensor", "sensor_path"), required=False)

    primary_value_column = find_column(reader.fieldnames, ("value_hrf",), required=False)
    if primary_value_column is None:
        primary_value_column = find_column(reader.fieldnames, ("value",), required=False)
    if primary_value_column is None:
        primary_value_column = find_column(reader.fieldnames, ("value_raw",), required=False)

    if primary_value_column is None:
        raise ValueError("AoT data is missing a value column such as value_hrf, value, or value_raw")

    for row in reader:
        sensor_id = str(row.get(node_id_col, "")).strip()
        if not sensor_id:
            continue

        parameter = str(row.get(parameter_col, ""))
        metric_type = resolve_metric_type(
            subsystem=str(row.get(subsystem_col, "")) if subsystem_col else "",
            sensor=str(row.get(sensor_col, "")) if sensor_col else "",
            parameter=parameter,
            exact_rules=exact_rules,
            sensor_parameter_rules=sensor_parameter_rules,
            parameter_rules=parameter_rules,
        )
        if metric_type not in TARGET_METRICS:
            continue

        numeric_value = parse_numeric(row.get(primary_value_column))
        if numeric_value is None:
            continue

        try:
            ts_sent = parse_aot_timestamp(str(row.get(timestamp_col, "")))
        except ValueError:
            LOGGER.warning("Skipping AoT row with unsupported timestamp: %s", row.get(timestamp_col))
            continue

        yield Measurement(
            sensor_id=sensor_id,
            ts_sent=ts_sent,
            metric_type=metric_type,
            value=numeric_value,
        )


def normalize_aot(
    *,
    input_path: Path,
    output_path: Path,
    sensor_limit: int = 0,
    rows_per_sensor: int = 0,
) -> tuple[int, int]:
    return write_normalized_csv(
        measurements=iter_aot_measurements(input_path),
        output_path=output_path,
        sensor_limit=sensor_limit,
        rows_per_sensor=rows_per_sensor,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    args = parse_args()
    rows_written, sensors_written = normalize_aot(
        input_path=Path(args.input),
        output_path=Path(args.output),
        sensor_limit=args.sensor_limit,
        rows_per_sensor=args.rows_per_sensor,
    )
    LOGGER.info("Wrote %s normalized AoT rows across %s sensors to %s", rows_written, sensors_written, args.output)


if __name__ == "__main__":
    main()
