from __future__ import annotations

import csv
import gzip
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from simulator.preprocess_intel_lab import normalize_intel_lab

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "intel_lab_readings.txt"


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as input_file:
        return list(csv.DictReader(input_file))


class IntelLabPreprocessTests(unittest.TestCase):
    def test_normalize_intel_gzip_emits_all_supported_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            compressed_path = Path(tmp_dir) / "intel.txt.gz"
            with FIXTURE_PATH.open("rb") as source_file, gzip.open(compressed_path, "wb") as output_file:
                output_file.write(source_file.read())

            output_path = Path(tmp_dir) / "normalized.csv"
            rows_written, sensors_written = normalize_intel_lab(input_path=compressed_path, output_path=output_path)

            rows = read_rows(output_path)
            self.assertEqual(rows_written, 11)
            self.assertEqual(sensors_written, 2)
            self.assertEqual(
                [(row["sensor_id"], row["msg_id"], row["metric_type"]) for row in rows[:7]],
                [
                    ("1", "1", "temperature"),
                    ("1", "2", "humidity"),
                    ("1", "3", "light"),
                    ("1", "4", "voltage"),
                    ("2", "1", "temperature"),
                    ("2", "2", "light"),
                    ("2", "3", "voltage"),
                ],
            )

            expected_ts = int(datetime(2004, 2, 28, 0, 0, 30, tzinfo=timezone.utc).timestamp() * 1_000)
            self.assertEqual(int(rows[0]["ts_sent"]), expected_ts)
            self.assertEqual([row["msg_id"] for row in rows if row["sensor_id"] == "1"][-1], "8")

    def test_normalize_intel_respects_sensor_and_row_limits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "limited.csv"
            rows_written, sensors_written = normalize_intel_lab(
                input_path=FIXTURE_PATH,
                output_path=output_path,
                sensor_limit=1,
                rows_per_sensor=5,
            )

            rows = read_rows(output_path)
            self.assertEqual(rows_written, 5)
            self.assertEqual(sensors_written, 1)
            self.assertTrue(all(row["sensor_id"] == "1" for row in rows))
            self.assertEqual([row["msg_id"] for row in rows], ["1", "2", "3", "4", "5"])


if __name__ == "__main__":
    unittest.main()
