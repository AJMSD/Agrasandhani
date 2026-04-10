from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from experiments.analyze_run import analyze_run, collect_run_summary
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
            (run_dir / "gateway_metrics.json").write_text(
                json.dumps(
                    {
                        "mqtt_in_msgs": 3,
                        "duplicates_dropped": 2,
                        "compacted_dropped": 1,
                        "value_dedup_dropped": 4,
                        "freshness_ttl_ms": 1000,
                        "effective_batch_window_ms": 250,
                        "adaptive_window_increase_events": 2,
                        "adaptive_window_decrease_events": 1,
                        "last_adaptation_reason": "degrade:queue_depth=30",
                        "stale_sensor_count": 5,
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "proxy_metrics.json").write_text(
                json.dumps({"dropped_frames": 1, "downstream_frames_out": 99, "downstream_bytes_out": 9999}),
                encoding="utf-8",
            )
            (run_dir / "dashboard_summary.json").write_text(
                json.dumps(
                    {
                        "summary": {
                            "staleCount": 6,
                            "messageCount": 10,
                            "frameCount": 2,
                        }
                    }
                ),
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
            self.assertEqual(summary["duplicates_dropped"], 2)
            self.assertEqual(summary["compacted_dropped"], 1)
            self.assertEqual(summary["value_dedup_dropped"], 4)
            self.assertEqual(summary["freshness_ttl_ms"], 1000)
            self.assertEqual(summary["effective_batch_window_ms"], 250)
            self.assertEqual(summary["adaptive_window_increase_events"], 2)
            self.assertEqual(summary["adaptive_window_decrease_events"], 1)
            self.assertEqual(summary["last_adaptation_reason"], "degrade:queue_depth=30")
            self.assertEqual(summary["stale_sensor_count"], 5)
            self.assertEqual(summary["dashboard_stale_count"], 6)
            self.assertEqual(summary["dashboard_message_count"], 10)
            self.assertEqual(summary["dashboard_frame_count"], 2)
            self.assertEqual(summary["proxy_sent_frame_count"], 1)
            self.assertEqual(summary["proxy_downstream_frames_out"], 1)
            self.assertEqual(summary["proxy_downstream_bytes_out"], 150)
            self.assertEqual(summary["max_bandwidth_bytes_per_s"], 150)
            self.assertEqual(summary["max_frame_rate_per_s"], 1)
            self.assertEqual(summary["proxy_inter_frame_gap_sample_count"], 0)
            self.assertEqual(summary["proxy_inter_frame_gap_mean_ms"], 0.0)
            self.assertEqual(summary["proxy_frame_rate_stddev_per_s"], 0.0)
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

    def test_analyze_run_derives_proxy_jitter_metrics_from_sent_frames(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            run_dir = Path(tmp_dir_name)
            self._write_csv(
                run_dir / "proxy_frame_log.csv",
                ["event", "payload_bytes", "downstream_sent_ms", "upstream_received_ms", "outage"],
                [
                    ["sent", "100", "1000", "950", "false"],
                    ["sent", "110", "1120", "1080", "false"],
                    ["sent", "120", "1320", "1280", "false"],
                    ["sent", "130", "1600", "1550", "false"],
                    ["sent", "140", "2100", "2050", "false"],
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

            self.assertEqual(summary["proxy_downstream_frames_out"], 5)
            self.assertEqual(summary["proxy_downstream_bytes_out"], 600)
            self.assertEqual(summary["proxy_inter_frame_gap_sample_count"], 4)
            self.assertEqual(summary["proxy_inter_frame_gap_mean_ms"], 275.0)
            self.assertEqual(summary["proxy_inter_frame_gap_p50_ms"], 240.0)
            self.assertEqual(summary["proxy_inter_frame_gap_p95_ms"], 467.0)
            self.assertEqual(summary["proxy_inter_frame_gap_p99_ms"], 493.4)
            self.assertEqual(summary["proxy_inter_frame_gap_stddev_ms"], 141.686)
            self.assertEqual(summary["max_bandwidth_bytes_per_s"], 460)
            self.assertEqual(summary["max_frame_rate_per_s"], 4)
            self.assertEqual(summary["proxy_frame_rate_stddev_per_s"], 1.5)

    def test_collect_run_summary_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            run_dir = Path(tmp_dir_name)
            self._write_csv(
                run_dir / "proxy_frame_log.csv",
                ["event", "payload_bytes", "downstream_sent_ms", "upstream_received_ms", "outage"],
                [
                    ["sent", "100", "1000", "950", "false"],
                    ["sent", "110", "1250", "1210", "false"],
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

            summary = collect_run_summary(run_dir)

            self.assertEqual(summary["proxy_inter_frame_gap_sample_count"], 1)
            self.assertEqual(summary["proxy_inter_frame_gap_mean_ms"], 250.0)
            self.assertFalse((run_dir / "summary.json").exists())
            self.assertFalse((run_dir / "summary.csv").exists())
            self.assertFalse((run_dir / "timeseries.csv").exists())

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

    def test_plot_sweep_script_runs_as_top_level_entrypoint(self) -> None:
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

            result = subprocess.run(
                [sys.executable, str(Path("experiments/plot_sweep.py").resolve()), str(sweep_dir)],
                cwd=Path(__file__).resolve().parent.parent,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
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
