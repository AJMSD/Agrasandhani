from __future__ import annotations

import argparse
import gzip
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

try:
    from simulator.preprocess_common import Measurement, parse_numeric, write_normalized_csv
except ModuleNotFoundError:  # pragma: no cover - script entrypoint fallback
    from preprocess_common import Measurement, parse_numeric, write_normalized_csv

LOGGER = logging.getLogger(__name__)
METRIC_ORDER = ("temperature", "humidity", "light", "voltage")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize Intel Lab data into Agrasandhani replay CSV format")
    parser.add_argument("--input", required=True, help="Path to Intel Lab readings file (.txt or .gz)")
    parser.add_argument("--output", required=True, help="Output CSV path in unified replay format")
    parser.add_argument("--sensor-limit", type=int, default=0, help="Limit output to the first N sensors encountered")
    parser.add_argument(
        "--rows-per-sensor",
        type=int,
        default=0,
        help="Limit output rows per sensor after normalization",
    )
    return parser.parse_args()


def parse_intel_timestamp(date_text: str, time_text: str) -> int:
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(f"{date_text} {time_text}", fmt)
            return int(parsed.replace(tzinfo=timezone.utc).timestamp() * 1_000)
        except ValueError:
            continue

    raise ValueError(f"Unsupported Intel Lab timestamp format: {date_text} {time_text}")


def iter_intel_measurements(input_path: Path) -> Iterator[Measurement]:
    opener = gzip.open if input_path.suffix.lower() == ".gz" else open
    with opener(input_path, "rt", encoding="utf-8") as input_file:
        for line in input_file:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            parts = stripped.split()
            if len(parts) != 8:
                LOGGER.warning("Skipping malformed Intel Lab row: %s", stripped)
                continue

            date_text, time_text, _epoch, mote_id, temperature, humidity, light, voltage = parts
            try:
                ts_sent = parse_intel_timestamp(date_text, time_text)
            except ValueError:
                LOGGER.warning("Skipping Intel Lab row with unsupported timestamp: %s", stripped)
                continue

            sensor_id = mote_id.strip()
            for metric_type, raw_value in zip(
                METRIC_ORDER,
                (temperature, humidity, light, voltage),
                strict=True,
            ):
                numeric_value = parse_numeric(raw_value)
                if numeric_value is None:
                    continue

                yield Measurement(
                    sensor_id=sensor_id,
                    ts_sent=ts_sent,
                    metric_type=metric_type,
                    value=numeric_value,
                )


def normalize_intel_lab(
    *,
    input_path: Path,
    output_path: Path,
    sensor_limit: int = 0,
    rows_per_sensor: int = 0,
) -> tuple[int, int]:
    return write_normalized_csv(
        measurements=iter_intel_measurements(input_path),
        output_path=output_path,
        sensor_limit=sensor_limit,
        rows_per_sensor=rows_per_sensor,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    args = parse_args()
    rows_written, sensors_written = normalize_intel_lab(
        input_path=Path(args.input),
        output_path=Path(args.output),
        sensor_limit=args.sensor_limit,
        rows_per_sensor=args.rows_per_sensor,
    )
    LOGGER.info(
        "Wrote %s normalized Intel Lab rows across %s sensors to %s",
        rows_written,
        sensors_written,
        args.output,
    )


if __name__ == "__main__":
    main()
