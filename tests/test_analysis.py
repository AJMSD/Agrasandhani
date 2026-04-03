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
                ["frame_id", "sensor_id", "metric_type", "msg_id", "ts_sent"],
                [
                    ["1", "101", "temperature", "1", "1000"],
                    ["2", "101", "temperature", "2", "2000"],
                ],
            )
            self._write_csv(
                run_dir / "proxy_frame_log.csv",
                ["event", "payload_bytes", "downstream_sent_ms", "upstream_received_ms", "outage"],
                [
                    ["sent", "150", "3000", "2500", "false"],
                    ["dropped", "180", "", "3200", "true"],
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
            self.assertEqual(summary["matching_mode"], "exact_sensor_metric_msg_ts")
            self.assertTrue(summary["missing_update_count_exact"])
            self.assertEqual(summary["proxy_frame_alignment_mode"], "frame_order_exact")
            self.assertEqual(summary["missing_updates_outage_drop_count"], 1)
            self.assertEqual(summary["missing_updates_non_outage_drop_count"], 0)
            self.assertEqual(summary["missing_updates_delivered_frame_count"], 0)
            self.assertEqual(summary["missing_updates_unclassified_count"], 0)
            self.assertEqual(summary["late_count"], 1)
            self.assertEqual(summary["proxy_dropped_frames"], 1)
            self.assertAlmostEqual(summary["stale_fraction"], 0.0)
            self.assertTrue((run_dir / "summary.json").exists())
            self.assertTrue((run_dir / "timeseries.csv").exists())

    def test_analyze_run_marks_legacy_gateway_logs_as_approximate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            run_dir = Path(tmp_dir_name)
            self._write_csv(
                run_dir / "gateway_forward_log.csv",
                ["frame_id", "sensor_id", "msg_id", "ts_sent"],
                [["1", "101", "1", "1000"]],
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
                [],
            )

            summary = analyze_run(run_dir)

            self.assertEqual(summary["matching_mode"], "legacy_sensor_msg_ts_approximate")
            self.assertFalse(summary["missing_update_count_exact"])
            self.assertIn("matching_note", summary)
            self.assertEqual(summary["proxy_frame_alignment_mode"], "unavailable")

    def test_analyze_run_classifies_missing_updates_by_proxy_frame_cause(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            run_dir = Path(tmp_dir_name)
            self._write_csv(
                run_dir / "gateway_forward_log.csv",
                ["frame_id", "sensor_id", "metric_type", "msg_id", "ts_sent"],
                [
                    ["1", "101", "temperature", "1", "1000"],
                    ["2", "102", "humidity", "2", "2000"],
                    ["3", "103", "pressure", "3", "3000"],
                ],
            )
            self._write_csv(
                run_dir / "proxy_frame_log.csv",
                ["event", "payload_bytes", "downstream_sent_ms", "upstream_received_ms", "outage"],
                [
                    ["dropped", "150", "", "1000", "true"],
                    ["dropped", "120", "", "2000", "false"],
                    ["sent", "180", "3600", "3000", "false"],
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
                [],
            )

            summary = analyze_run(run_dir)

            self.assertEqual(summary["proxy_frame_alignment_mode"], "frame_order_exact")
            self.assertEqual(summary["missing_update_count"], 3)
            self.assertEqual(summary["missing_updates_outage_drop_count"], 1)
            self.assertEqual(summary["missing_updates_non_outage_drop_count"], 1)
            self.assertEqual(summary["missing_updates_delivered_frame_count"], 1)
            self.assertEqual(summary["missing_updates_unclassified_count"], 0)

    def test_analyze_run_marks_unaligned_proxy_frames_as_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            run_dir = Path(tmp_dir_name)
            self._write_csv(
                run_dir / "gateway_forward_log.csv",
                ["frame_id", "sensor_id", "metric_type", "msg_id", "ts_sent"],
                [
                    ["1", "101", "temperature", "1", "1000"],
                    ["2", "102", "humidity", "2", "2000"],
                ],
            )
            self._write_csv(
                run_dir / "proxy_frame_log.csv",
                ["event", "payload_bytes", "downstream_sent_ms", "upstream_received_ms", "outage"],
                [
                    ["dropped", "150", "", "1000", "true"],
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
                [],
            )

            summary = analyze_run(run_dir)

            self.assertEqual(summary["proxy_frame_alignment_mode"], "unavailable")
            self.assertEqual(summary["missing_updates_outage_drop_count"], 0)
            self.assertEqual(summary["missing_updates_non_outage_drop_count"], 0)
            self.assertEqual(summary["missing_updates_delivered_frame_count"], 0)
            self.assertEqual(summary["missing_updates_unclassified_count"], 2)
            self.assertIn("proxy_frame_alignment_note", summary)

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
