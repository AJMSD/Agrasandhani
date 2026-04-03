from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from experiments.analyze_run import analyze_run
from experiments.plot_sweep import plot_sweep


class AnalysisTests(unittest.TestCase):
    def test_analyze_run_derives_latency_loss_and_stale_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            run_dir = Path(tmp_dir_name)
            self._write_csv(
                run_dir / "gateway_forward_log.csv",
                ["sensor_id", "metric_type", "msg_id", "ts_sent"],
                [
                    ["101", "temperature", "1", "1000"],
                    ["101", "temperature", "2", "2000"],
                ],
            )
            self._write_csv(
                run_dir / "proxy_frame_log.csv",
                ["event", "payload_bytes", "downstream_sent_ms"],
                [
                    ["sent", "150", "3000"],
                    ["sent", "180", "3500"],
                ],
            )
            self._write_csv(
                run_dir / "dashboard_measurements.csv",
                [
                    "frame_index",
                    "frame_id",
                    "gateway_mode",
                    "sensor_id",
                    "metric_type",
                    "msg_id",
                    "ts_sent",
                    "ts_displayed",
                    "age_ms_at_display",
                    "stale_at_display",
                ],
                [
                    ["1", "1", "v4", "101", "temperature", "1", "1000", "1600", "600", "false"],
                ],
            )
            (run_dir / "manifest.json").write_text(
                json.dumps({"run_id": "demo", "variant": "v4", "scenario": "clean", "mqtt_qos": 1}),
                encoding="utf-8",
            )
            (run_dir / "gateway_metrics.json").write_text(json.dumps({"mqtt_in_msgs": 3}), encoding="utf-8")
            (run_dir / "proxy_metrics.json").write_text(
                json.dumps({"dropped_frames": 1, "downstream_frames_out": 2, "downstream_bytes_out": 330}),
                encoding="utf-8",
            )

            summary = analyze_run(run_dir, late_threshold_ms=500)

            self.assertEqual(summary["missing_update_count"], 1)
            self.assertEqual(summary["late_count"], 1)
            self.assertEqual(summary["proxy_dropped_frames"], 1)
            self.assertAlmostEqual(summary["stale_fraction"], 0.0)
            self.assertTrue((run_dir / "summary.json").exists())
            self.assertTrue((run_dir / "timeseries.csv").exists())

    def test_plot_sweep_creates_expected_png_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            sweep_dir = Path(tmp_dir_name)
            run_dir = sweep_dir / "run-a"
            run_dir.mkdir(parents=True)
            (run_dir / "summary.json").write_text(
                json.dumps({"variant": "v4", "scenario": "clean", "mqtt_qos": 0}),
                encoding="utf-8",
            )
            self._write_csv(
                run_dir / "summary.csv",
                ["variant", "scenario", "mqtt_qos", "stale_fraction"],
                [["v4", "clean", "0", "0.1"]],
            )
            self._write_csv(
                run_dir / "dashboard_measurements.csv",
                ["age_ms_at_display"],
                [["10"], ["15"], ["30"]],
            )
            self._write_csv(
                run_dir / "timeseries.csv",
                ["epoch_second", "bandwidth_bytes_per_s", "frame_rate_per_s", "update_rate_per_s"],
                [["1", "100", "2", "5"], ["2", "120", "2", "6"]],
            )

            plot_sweep(sweep_dir)

            plots_dir = sweep_dir / "plots"
            self.assertTrue((plots_dir / "latency_cdf.png").exists())
            self.assertTrue((plots_dir / "bandwidth_over_time.png").exists())
            self.assertTrue((plots_dir / "message_rate_over_time.png").exists())
            self.assertTrue((plots_dir / "stale_fraction.png").exists())

    def _write_csv(self, path: Path, header: list[str], rows: list[list[str]]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
