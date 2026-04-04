from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments.build_report_assets import build_report_assets


class BuildReportAssetsTests(unittest.TestCase):
    def test_build_report_assets_writes_expected_tables_figures_and_report_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            base_dir = Path(tmp_dir_name)
            intel_sweep = base_dir / "final-intel-primary-20260403"
            aot_sweep = base_dir / "final-aot-validation-20260403"
            demo_dir = base_dir / "final-demo-20260403" / "demo"
            output_dir = base_dir / "report-assets"

            self._create_intel_run(intel_sweep, "v0", "clean", 0, latency_p95=5, frames=120, bytes_out=10000)
            self._create_intel_run(intel_sweep, "v2", "clean", 0, latency_p95=205, frames=24, bytes_out=14000)
            self._create_intel_run(intel_sweep, "v4", "clean", 0, latency_p95=255, frames=20, bytes_out=15000)
            self._create_intel_run(intel_sweep, "v0", "outage_5s", 1, latency_p95=7, frames=132, bytes_out=12279)
            self._create_intel_run(intel_sweep, "v2", "outage_5s", 1, latency_p95=240, frames=28, bytes_out=15000)
            self._create_intel_run(intel_sweep, "v4", "outage_5s", 1, latency_p95=276, frames=23, bytes_out=16777)
            for scenario in ("bandwidth_200kbps", "loss_2pct", "delay_50ms_jitter20ms"):
                for variant, latency, frames, bytes_out in (("v0", 10, 100, 9000), ("v2", 220, 24, 13000), ("v4", 245, 20, 14000)):
                    for qos in (0, 1):
                        self._create_intel_run(
                            intel_sweep,
                            variant,
                            scenario,
                            qos,
                            latency_p95=latency,
                            frames=frames,
                            bytes_out=bytes_out,
                        )
            for qos in (0, 1):
                for variant, latency, frames, bytes_out in (("v0", 8, 118, 9800), ("v2", 200, 23, 13800), ("v4", 248, 19, 14900)):
                    self._create_intel_run(intel_sweep, variant, "clean", qos, latency_p95=latency + qos, frames=frames, bytes_out=bytes_out)
                    self._create_intel_run(
                        intel_sweep,
                        variant,
                        "outage_5s",
                        qos,
                        latency_p95=latency + 5 + qos,
                        frames=frames - 5,
                        bytes_out=bytes_out - 300,
                    )

            self._create_aot_run(aot_sweep, "v0", "clean", 0, latency_p95=12, frames=80, bytes_out=6200)
            self._create_aot_run(aot_sweep, "v4", "clean", 0, latency_p95=230, frames=18, bytes_out=7100)
            self._create_aot_run(aot_sweep, "v0", "outage_5s", 0, latency_p95=15, frames=40, bytes_out=4000)
            self._create_aot_run(aot_sweep, "v4", "outage_5s", 0, latency_p95=240, frames=10, bytes_out=5000)

            self._create_demo_artifacts(demo_dir)

            report_dir = base_dir / "report"
            with patch("experiments.build_report_assets.REPORT_DIR", report_dir):
                manifest = build_report_assets(
                    intel_sweep_dir=intel_sweep,
                    aot_sweep_dir=aot_sweep,
                    demo_dir=demo_dir,
                    output_dir=output_dir,
                )

            self.assertEqual(manifest["intel_sweep_dir"], str(intel_sweep))
            self.assertTrue((output_dir / "evidence_manifest.json").exists())
            self.assertTrue((output_dir / "tables" / "intel_primary_run_summary.csv").exists())
            self.assertTrue((output_dir / "tables" / "intel_bandwidth_vs_v0.csv").exists())
            self.assertTrue((output_dir / "tables" / "intel_bandwidth_vs_v0.md").exists())
            self.assertTrue((output_dir / "tables" / "aot_validation_summary.csv").exists())
            self.assertTrue((output_dir / "tables" / "intel_key_claims.md").exists())
            self.assertTrue((output_dir / "figures" / "intel_clean_qos0_latency_cdf.png").exists())
            self.assertTrue((output_dir / "figures" / "intel_outage_qos1_bandwidth_over_time.png").exists())
            self.assertTrue((output_dir / "figures" / "intel_outage_qos1_message_rate_over_time.png").exists())
            self.assertTrue((output_dir / "figures" / "final_demo_compare.png").exists())
            self.assertTrue((report_dir / "final_report.md").exists())
            self.assertTrue((report_dir / "deliverable_gate.md").exists())
            key_claims = (output_dir / "tables" / "intel_key_claims.md").read_text(encoding="utf-8")
            self.assertIn("did not drop below V0", key_claims)
            self.assertIn("retained 6 latest rows versus 6", key_claims)
            bandwidth_table = (output_dir / "tables" / "intel_bandwidth_vs_v0.md").read_text(encoding="utf-8")
            self.assertIn("| clean | v2 | 9800 | 13800 | 40.8% |", bandwidth_table)
            final_report = (report_dir / "final_report.md").read_text(encoding="utf-8")
            self.assertIn("did not show a downstream payload-byte reduction versus V0", final_report)
            self.assertIn("The explicit Intel qos0 bandwidth comparison answers the first paper question directly.", final_report)
            self.assertIn("AoT provides a smaller portability check", final_report)
            deliverable_gate = (report_dir / "deliverable_gate.md").read_text(encoding="utf-8")
            self.assertIn("intel_bandwidth_vs_v0.csv", deliverable_gate)
            self.assertIn("M1-M3 System Path", deliverable_gate)
            self.assertIn("tests/test_run_final_deliverables.py", deliverable_gate)

    def test_build_report_assets_writes_batch_window_tradeoff_outputs_when_batch_sweep_is_provided(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            base_dir = Path(tmp_dir_name)
            intel_sweep = base_dir / "final-intel-primary-20260403"
            aot_sweep = base_dir / "final-aot-validation-20260403"
            demo_dir = base_dir / "final-demo-20260403" / "demo"
            batch_sweep = base_dir / "intel-v2-batch-window-20260403"
            output_dir = base_dir / "report-assets"

            for variant, latency, frames, bytes_out in (("v0", 8, 118, 9800), ("v2", 200, 23, 13800), ("v4", 248, 19, 14900)):
                self._create_intel_run(intel_sweep, variant, "clean", 0, latency_p95=latency, frames=frames, bytes_out=bytes_out)
                self._create_intel_run(intel_sweep, variant, "outage_5s", 0, latency_p95=latency + 4, frames=frames - 5, bytes_out=bytes_out - 300)
                self._create_intel_run(intel_sweep, variant, "outage_5s", 1, latency_p95=latency + 5, frames=frames - 5, bytes_out=bytes_out - 300)
            for scenario in ("bandwidth_200kbps", "loss_2pct", "delay_50ms_jitter20ms"):
                for variant, latency, frames, bytes_out in (("v0", 10, 100, 9000), ("v2", 220, 24, 13000), ("v4", 245, 20, 14000)):
                    for qos in (0, 1):
                        self._create_intel_run(
                            intel_sweep,
                            variant,
                            scenario,
                            qos,
                            latency_p95=latency,
                            frames=frames,
                            bytes_out=bytes_out,
                        )

            self._create_aot_run(aot_sweep, "v0", "clean", 0, latency_p95=12, frames=80, bytes_out=6200)
            self._create_aot_run(aot_sweep, "v4", "clean", 0, latency_p95=230, frames=18, bytes_out=7100)
            self._create_aot_run(aot_sweep, "v0", "outage_5s", 0, latency_p95=15, frames=40, bytes_out=4000)
            self._create_aot_run(aot_sweep, "v4", "outage_5s", 0, latency_p95=240, frames=10, bytes_out=5000)

            for batch_window_ms, latency_p95, latency_mean, frame_rate, frames, bytes_out in [
                (50, 120, 90, 12, 40, 13100),
                (100, 170, 110, 8, 28, 13020),
                (250, 260, 170, 4, 15, 12980),
                (500, 410, 260, 2, 9, 12910),
                (1000, 780, 410, 1, 5, 12890),
            ]:
                self._create_batch_window_run(
                    batch_sweep,
                    batch_window_ms=batch_window_ms,
                    latency_p95=latency_p95,
                    latency_mean=latency_mean,
                    max_frame_rate_per_s=frame_rate,
                    frames=frames,
                    bytes_out=bytes_out,
                )

            self._create_demo_artifacts(demo_dir)

            report_dir = base_dir / "report"
            with patch("experiments.build_report_assets.REPORT_DIR", report_dir):
                manifest = build_report_assets(
                    intel_sweep_dir=intel_sweep,
                    aot_sweep_dir=aot_sweep,
                    demo_dir=demo_dir,
                    output_dir=output_dir,
                    intel_batch_sweep_dir=batch_sweep,
                )

            self.assertEqual(manifest["intel_batch_sweep_dir"], str(batch_sweep))
            self.assertTrue((output_dir / "tables" / "intel_v2_batch_window_tradeoff.csv").exists())
            self.assertTrue((output_dir / "tables" / "intel_v2_batch_window_tradeoff.md").exists())
            self.assertTrue((output_dir / "figures" / "intel_v2_batch_window_tradeoff.png").exists())
            tradeoff_table = (output_dir / "tables" / "intel_v2_batch_window_tradeoff.md").read_text(encoding="utf-8")
            self.assertIn("| 50 | 120.0 | 90.0 | 12 | 40 | 13100 | 1310 | 0.0 |", tradeoff_table)
            key_claims = (output_dir / "tables" / "intel_key_claims.md").read_text(encoding="utf-8")
            self.assertIn("Intel V2 batch-window sweep moved latency p95", key_claims)
            final_report = (report_dir / "final_report.md").read_text(encoding="utf-8")
            self.assertIn("The Intel V2 batch-window sweep answers the second paper question directly.", final_report)
            self.assertIn("intel_v2_batch_window_tradeoff.png", final_report)
            deliverable_gate = (report_dir / "deliverable_gate.md").read_text(encoding="utf-8")
            self.assertIn("intel_v2_batch_window_tradeoff.csv", deliverable_gate)
            self.assertIn("intel-v2-batch-window-20260403", deliverable_gate)

    def test_build_report_assets_writes_v1_v2_isolation_outputs_when_sweep_is_provided(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            base_dir = Path(tmp_dir_name)
            intel_sweep = base_dir / "final-intel-primary-20260403"
            aot_sweep = base_dir / "final-aot-validation-20260403"
            demo_dir = base_dir / "final-demo-20260403" / "demo"
            isolation_sweep = base_dir / "intel-v1-v2-isolation-20260403"
            output_dir = base_dir / "report-assets"

            for variant, latency, frames, bytes_out in (("v0", 8, 118, 9800), ("v2", 200, 23, 13800), ("v4", 248, 19, 14900)):
                self._create_intel_run(intel_sweep, variant, "clean", 0, latency_p95=latency, frames=frames, bytes_out=bytes_out)
                self._create_intel_run(intel_sweep, variant, "outage_5s", 0, latency_p95=latency + 4, frames=frames - 5, bytes_out=bytes_out - 300)
                self._create_intel_run(intel_sweep, variant, "outage_5s", 1, latency_p95=latency + 5, frames=frames - 5, bytes_out=bytes_out - 300)
            for scenario in ("bandwidth_200kbps", "loss_2pct", "delay_50ms_jitter20ms"):
                for variant, latency, frames, bytes_out in (("v0", 10, 100, 9000), ("v2", 220, 24, 13000), ("v4", 245, 20, 14000)):
                    for qos in (0, 1):
                        self._create_intel_run(
                            intel_sweep,
                            variant,
                            scenario,
                            qos,
                            latency_p95=latency,
                            frames=frames,
                            bytes_out=bytes_out,
                        )

            self._create_aot_run(aot_sweep, "v0", "clean", 0, latency_p95=12, frames=80, bytes_out=6200)
            self._create_aot_run(aot_sweep, "v4", "clean", 0, latency_p95=230, frames=18, bytes_out=7100)
            self._create_aot_run(aot_sweep, "v0", "outage_5s", 0, latency_p95=15, frames=40, bytes_out=4000)
            self._create_aot_run(aot_sweep, "v4", "outage_5s", 0, latency_p95=240, frames=10, bytes_out=5000)

            for scenario, scenario_offset in [("clean", 0), ("bandwidth_200kbps", 15), ("outage_5s", 30)]:
                for batch_window_ms, v1_latency, v2_latency, v1_frames, v2_frames, v1_bytes, v2_bytes, v1_stale, v2_stale in [
                    (50, 90, 80, 18, 10, 15100, 14000, 0.0, 0.0),
                    (100, 140, 120, 14, 8, 14500, 13600, 0.0, 0.0),
                    (250, 240, 210, 8, 5, 13600, 13000, 0.0, 0.0),
                    (500, 430, 390, 6, 4, 13450, 12950, 0.0, 0.0),
                    (1000, 910, 960, 5, 4, 13200, 13550, 0.05, 0.08),
                ]:
                    self._create_v1_v2_isolation_run(
                        isolation_sweep,
                        variant="v1",
                        scenario=scenario,
                        batch_window_ms=batch_window_ms,
                        latency_p95=v1_latency + scenario_offset,
                        frames=v1_frames,
                        bytes_out=v1_bytes + scenario_offset * 10,
                        stale_fraction=v1_stale,
                    )
                    self._create_v1_v2_isolation_run(
                        isolation_sweep,
                        variant="v2",
                        scenario=scenario,
                        batch_window_ms=batch_window_ms,
                        latency_p95=v2_latency + scenario_offset,
                        frames=v2_frames,
                        bytes_out=v2_bytes + scenario_offset * 10,
                        stale_fraction=v2_stale,
                    )

            self._create_demo_artifacts(demo_dir)

            report_dir = base_dir / "report"
            with patch("experiments.build_report_assets.REPORT_DIR", report_dir):
                manifest = build_report_assets(
                    intel_sweep_dir=intel_sweep,
                    aot_sweep_dir=aot_sweep,
                    demo_dir=demo_dir,
                    output_dir=output_dir,
                    intel_v1_v2_sweep_dir=isolation_sweep,
                )

            self.assertEqual(manifest["intel_v1_v2_sweep_dir"], str(isolation_sweep))
            self.assertTrue((output_dir / "tables" / "intel_v1_vs_v2_isolation.csv").exists())
            self.assertTrue((output_dir / "tables" / "intel_v1_vs_v2_isolation.md").exists())
            self.assertTrue((output_dir / "figures" / "intel_v1_vs_v2_isolation.png").exists())
            isolation_table = (output_dir / "tables" / "intel_v1_vs_v2_isolation.md").read_text(encoding="utf-8")
            self.assertIn("| clean | 50 | 90.0 | 80.0 | -10.0 | 18 | 10 | -44.4% | 15100 | 14000 | -7.3% |", isolation_table)
            key_claims = (output_dir / "tables" / "intel_key_claims.md").read_text(encoding="utf-8")
            self.assertIn("Intel V1 versus V2 isolation sweep shows what compaction changes beyond batching alone", key_claims)
            final_report = (report_dir / "final_report.md").read_text(encoding="utf-8")
            self.assertIn("The Intel V1 versus V2 isolation sweep answers the third paper question directly.", final_report)
            self.assertIn("intel_v1_vs_v2_isolation.png", final_report)
            deliverable_gate = (report_dir / "deliverable_gate.md").read_text(encoding="utf-8")
            self.assertIn("intel_v1_vs_v2_isolation.csv", deliverable_gate)
            self.assertIn("intel-v1-v2-isolation-20260403", deliverable_gate)

    def _create_intel_run(
        self,
        sweep_dir: Path,
        variant: str,
        scenario: str,
        mqtt_qos: int,
        *,
        latency_p95: int,
        frames: int,
        bytes_out: int,
    ) -> None:
        run_dir = sweep_dir / f"{variant}-qos{mqtt_qos}-{scenario}"
        run_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "run_id": run_dir.name,
            "variant": variant,
            "scenario": scenario,
            "mqtt_qos": mqtt_qos,
            "latency_p95_ms": latency_p95,
            "latency_p99_ms": latency_p95 + 20,
            "proxy_downstream_frames_out": frames,
            "proxy_downstream_bytes_out": bytes_out,
            "max_bandwidth_bytes_per_s": bytes_out // 10,
            "gateway_mqtt_in_msgs": 200,
            "duplicates_dropped": 0,
            "compacted_dropped": 6 if variant != "v0" else 0,
            "value_dedup_dropped": 0,
            "effective_batch_window_ms": 250 if variant != "v0" else 0,
            "dashboard_stale_count": 6 if "outage" in scenario else 0,
            "dashboard_message_count": 150,
            "dashboard_frame_count": frames,
        }
        (run_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        self._write_dashboard_measurements(run_dir / "dashboard_measurements.csv", [latency_p95 - 10, latency_p95, latency_p95 + 10])
        self._write_timeseries(run_dir / "timeseries.csv")

    def _create_aot_run(
        self,
        sweep_dir: Path,
        variant: str,
        scenario: str,
        mqtt_qos: int,
        *,
        latency_p95: int,
        frames: int,
        bytes_out: int,
    ) -> None:
        run_dir = sweep_dir / f"{variant}-qos{mqtt_qos}-{scenario}"
        run_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "run_id": run_dir.name,
            "variant": variant,
            "scenario": scenario,
            "mqtt_qos": mqtt_qos,
            "latency_p95_ms": latency_p95,
            "latency_p99_ms": latency_p95 + 15,
            "proxy_downstream_frames_out": frames,
            "proxy_downstream_bytes_out": bytes_out,
            "max_bandwidth_bytes_per_s": bytes_out // 10,
            "gateway_mqtt_in_msgs": 120,
            "duplicates_dropped": 0,
            "compacted_dropped": 4 if variant == "v4" else 0,
            "value_dedup_dropped": 0,
            "effective_batch_window_ms": 250 if variant == "v4" else 0,
            "dashboard_stale_count": 6 if "outage" in scenario else 0,
            "dashboard_message_count": 60,
            "dashboard_frame_count": frames,
        }
        (run_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        self._write_dashboard_measurements(run_dir / "dashboard_measurements.csv", [latency_p95 - 5, latency_p95, latency_p95 + 5])
        self._write_timeseries(run_dir / "timeseries.csv")

    def _create_demo_artifacts(self, demo_dir: Path) -> None:
        (demo_dir / "baseline_dashboard").mkdir(parents=True, exist_ok=True)
        (demo_dir / "smart_dashboard").mkdir(parents=True, exist_ok=True)
        (demo_dir / "demo_compare.png").write_bytes(b"compare")
        (demo_dir / "baseline_dashboard" / "dashboard.png").write_bytes(b"baseline")
        (demo_dir / "smart_dashboard" / "dashboard.png").write_bytes(b"smart")
        (demo_dir / "baseline_dashboard" / "dashboard_summary.json").write_text(
            json.dumps({"summary": {"latestRowCount": 6, "messageCount": 209, "frameCount": 209, "staleCount": 6}}),
            encoding="utf-8",
        )
        (demo_dir / "smart_dashboard" / "dashboard_summary.json").write_text(
            json.dumps({"summary": {"latestRowCount": 6, "messageCount": 198, "frameCount": 33, "staleCount": 6}}),
            encoding="utf-8",
        )

    def _create_batch_window_run(
        self,
        sweep_dir: Path,
        *,
        batch_window_ms: int,
        latency_p95: int,
        latency_mean: int,
        max_frame_rate_per_s: int,
        frames: int,
        bytes_out: int,
    ) -> None:
        run_dir = sweep_dir / f"v2-qos0-clean-bw{batch_window_ms}ms"
        run_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "run_id": run_dir.name,
            "variant": "v2",
            "scenario": "clean",
            "mqtt_qos": 0,
            "latency_mean_ms": latency_mean,
            "latency_p95_ms": latency_p95,
            "latency_p99_ms": latency_p95 + 20,
            "proxy_downstream_frames_out": frames,
            "proxy_downstream_bytes_out": bytes_out,
            "max_bandwidth_bytes_per_s": bytes_out // 10,
            "max_frame_rate_per_s": max_frame_rate_per_s,
            "stale_fraction": 0.0,
            "effective_batch_window_ms": batch_window_ms,
        }
        (run_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    def _create_v1_v2_isolation_run(
        self,
        sweep_dir: Path,
        *,
        variant: str,
        scenario: str,
        batch_window_ms: int,
        latency_p95: int,
        frames: int,
        bytes_out: int,
        stale_fraction: float,
    ) -> None:
        run_dir = sweep_dir / f"{variant}-qos0-{scenario}-bw{batch_window_ms}ms"
        run_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "run_id": run_dir.name,
            "variant": variant,
            "scenario": scenario,
            "mqtt_qos": 0,
            "latency_mean_ms": latency_p95 - 20,
            "latency_p95_ms": latency_p95,
            "latency_p99_ms": latency_p95 + 20,
            "proxy_downstream_frames_out": frames,
            "proxy_downstream_bytes_out": bytes_out,
            "max_bandwidth_bytes_per_s": bytes_out // 10,
            "max_frame_rate_per_s": max(1, frames // 2),
            "stale_fraction": stale_fraction,
            "effective_batch_window_ms": batch_window_ms,
        }
        (run_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    def _write_dashboard_measurements(self, path: Path, latencies: list[int]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["age_ms_at_display"])
            for latency in latencies:
                writer.writerow([latency])

    def _write_timeseries(self, path: Path) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["epoch_second", "bandwidth_bytes_per_s", "frame_rate_per_s", "update_rate_per_s"])
            writer.writerow(["1", "1000", "5", "20"])
            writer.writerow(["2", "1400", "4", "15"])


if __name__ == "__main__":
    unittest.main()
