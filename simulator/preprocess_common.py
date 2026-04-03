from __future__ import annotations

import csv
import math
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

NORMALIZED_HEADER = ["sensor_id", "msg_id", "ts_sent", "metric_type", "value"]


@dataclass(frozen=True, slots=True)
class Measurement:
    sensor_id: str
    ts_sent: int
    metric_type: str
    value: float


def parse_numeric(value: object) -> float | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        numeric_value = float(text)
    except ValueError:
        return None

    if not math.isfinite(numeric_value):
        return None

    return numeric_value


def write_normalized_csv(
    *,
    measurements: Iterable[Measurement],
    output_path: Path,
    sensor_limit: int = 0,
    rows_per_sensor: int = 0,
) -> tuple[int, int]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    db_fd, db_path_text = tempfile.mkstemp(prefix="agrasandhani-normalize-", suffix=".sqlite3")
    os.close(db_fd)
    db_path = Path(db_path_text)
    conn: sqlite3.Connection | None = None

    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE measurements (
                source_index INTEGER PRIMARY KEY,
                sensor_id TEXT NOT NULL,
                ts_sent INTEGER NOT NULL,
                metric_type TEXT NOT NULL,
                value REAL NOT NULL
            )
            """
        )

        batch: list[tuple[int, str, int, str, float]] = []
        source_index = 0
        for measurement in measurements:
            batch.append(
                (
                    source_index,
                    measurement.sensor_id,
                    measurement.ts_sent,
                    measurement.metric_type,
                    measurement.value,
                )
            )
            source_index += 1
            if len(batch) >= 10_000:
                conn.executemany(
                    """
                    INSERT INTO measurements (source_index, sensor_id, ts_sent, metric_type, value)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    batch,
                )
                conn.commit()
                batch.clear()

        if batch:
            conn.executemany(
                """
                INSERT INTO measurements (source_index, sensor_id, ts_sent, metric_type, value)
                VALUES (?, ?, ?, ?, ?)
                """,
                batch,
            )
            conn.commit()

        conn.execute("CREATE INDEX idx_measurements_order ON measurements (ts_sent, source_index)")
        conn.commit()

        selected_sensors: set[str] = set()
        sensor_rows_written: dict[str, int] = {}
        sensor_msg_ids: dict[str, int] = {}
        rows_written = 0

        with output_path.open("w", encoding="utf-8", newline="") as output_file:
            writer = csv.writer(output_file)
            writer.writerow(NORMALIZED_HEADER)

            for sensor_id, ts_sent, metric_type, value in conn.execute(
                """
                SELECT sensor_id, ts_sent, metric_type, value
                FROM measurements
                ORDER BY ts_sent ASC, source_index ASC
                """
            ):
                if sensor_limit > 0 and sensor_id not in selected_sensors:
                    if len(selected_sensors) >= sensor_limit:
                        continue
                    selected_sensors.add(sensor_id)

                current_row_count = sensor_rows_written.get(sensor_id, 0)
                if rows_per_sensor > 0 and current_row_count >= rows_per_sensor:
                    continue

                next_msg_id = sensor_msg_ids.get(sensor_id, 0) + 1
                sensor_msg_ids[sensor_id] = next_msg_id
                sensor_rows_written[sensor_id] = current_row_count + 1
                writer.writerow([sensor_id, next_msg_id, ts_sent, metric_type, value])
                rows_written += 1

        return rows_written, len(sensor_rows_written)
    finally:
        if conn is not None:
            conn.close()
        db_path.unlink(missing_ok=True)
