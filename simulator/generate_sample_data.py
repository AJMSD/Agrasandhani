from __future__ import annotations

import csv
from pathlib import Path

OUTPUT_PATH = Path(__file__).resolve().parent / "sample_data.csv"
SENSOR_IDS = [101, 102, 103]
METRICS = ("temperature", "humidity")
SECONDS = 60
START_TS_MS = 1_700_000_000_000


def metric_value(sensor_id: int, metric_type: str, second: int) -> float:
    sensor_index = SENSOR_IDS.index(sensor_id)
    if metric_type == "temperature":
        return round(20.0 + sensor_index * 0.7 + (second % 8) * 0.18, 2)
    return round(44.0 + sensor_index * 1.5 + (second % 6) * 0.35, 2)


def main() -> None:
    rows: list[dict[str, object]] = []
    msg_ids = {sensor_id: 1 for sensor_id in SENSOR_IDS}

    for second in range(SECONDS):
        base_ts_ms = START_TS_MS + second * 1_000
        for sensor_offset, sensor_id in enumerate(SENSOR_IDS):
            for metric_index, metric_type in enumerate(METRICS):
                rows.append(
                    {
                        "sensor_id": sensor_id,
                        "msg_id": msg_ids[sensor_id],
                        "ts_sent": base_ts_ms + sensor_offset * 50 + metric_index * 100,
                        "metric_type": metric_type,
                        "value": metric_value(sensor_id, metric_type, second),
                    }
                )
                msg_ids[sensor_id] += 1

    with OUTPUT_PATH.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(
            output_file,
            fieldnames=["sensor_id", "msg_id", "ts_sent", "metric_type", "value"],
        )
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
