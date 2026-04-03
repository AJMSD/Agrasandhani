from __future__ import annotations

import csv
import tarfile
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from simulator.preprocess_aot import AOT_DEFAULT_TIMEZONE, normalize_aot

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "aot_archive"


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as input_file:
        return list(csv.DictReader(input_file))


class AotPreprocessTests(unittest.TestCase):
    def test_normalize_aot_from_tar_filters_and_orders_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            archive_path = Path(tmp_dir) / "aot-fixture.tar"
            with tarfile.open(archive_path, "w") as archive:
                archive.add(FIXTURE_DIR / "data.csv", arcname="AoT_Chicago.complete.2024-01-01/data.csv")
                archive.add(FIXTURE_DIR / "sensors.csv", arcname="AoT_Chicago.complete.2024-01-01/sensors.csv")

            output_path = Path(tmp_dir) / "normalized.csv"
            rows_written, sensors_written = normalize_aot(input_path=archive_path, output_path=output_path)

            rows = read_rows(output_path)
            self.assertEqual(rows_written, 5)
            self.assertEqual(sensors_written, 2)
            self.assertEqual(
                [(row["sensor_id"], row["msg_id"], row["metric_type"]) for row in rows],
                [
                    ("node-a", "1", "temperature"),
                    ("node-a", "2", "humidity"),
                    ("node-a", "3", "temperature"),
                    ("node-b", "1", "temperature"),
                    ("node-b", "2", "humidity"),
                ],
            )

            expected_ts = int(datetime(2024, 1, 1, 0, 0, 0, tzinfo=AOT_DEFAULT_TIMEZONE).timestamp() * 1_000)
            self.assertEqual(int(rows[0]["ts_sent"]), expected_ts)
            self.assertEqual(float(rows[-1]["value"]), 47.0)

    def test_normalize_aot_applies_sensor_and_row_limits_after_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "limited.csv"
            rows_written, sensors_written = normalize_aot(
                input_path=FIXTURE_DIR,
                output_path=output_path,
                sensor_limit=1,
                rows_per_sensor=2,
            )

            rows = read_rows(output_path)
            self.assertEqual(rows_written, 2)
            self.assertEqual(sensors_written, 1)
            self.assertEqual([row["sensor_id"] for row in rows], ["node-a", "node-a"])
            self.assertEqual([row["msg_id"] for row in rows], ["1", "2"])


if __name__ == "__main__":
    unittest.main()
