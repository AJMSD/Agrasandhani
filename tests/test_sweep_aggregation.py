from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from experiments.sweep_aggregation import (
    CONDITION_AGGREGATES_FILENAME,
    aggregate_summary_rows,
    load_summary_rows,
    write_condition_aggregates,
)


class SweepAggregationTests(unittest.TestCase):
    def test_load_summary_rows_supports_legacy_and_trial_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            sweep_dir = Path(tmp_dir_name) / "final-intel-primary-replicated-20260407"
            self._write_run(
                sweep_dir / "v0-qos0-clean",
                run_id="v0-qos0-clean",
                condition_id="v0-qos0-clean",
                trial_id=None,
                trial_index=None,
                impairment_seed=537,
                latency_p95_ms=10.0,
            )
            self._write_run(
                sweep_dir / "v2-qos0-clean" / "trial-01-seed-53701",
                run_id="v2-qos0-clean-trial-01-seed-53701",
                condition_id="v2-qos0-clean",
                trial_id="trial-01-seed-53701",
                trial_index=1,
                impairment_seed=53701,
                latency_p95_ms=200.0,
            )

            rows = load_summary_rows(sweep_dir)

            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["condition_id"], "v0-qos0-clean")
            self.assertIsNone(rows[0]["trial_id"])
            self.assertEqual(rows[1]["condition_id"], "v2-qos0-clean")
            self.assertEqual(rows[1]["trial_id"], "trial-01-seed-53701")
            self.assertEqual(rows[1]["trial_index"], 1)
            self.assertEqual(rows[1]["impairment_seed"], 53701)
            self.assertEqual(rows[1]["adaptive_step_up_ms"], 100)
            self.assertEqual(rows[1]["adaptive_send_slow_ms"], 40)

    def test_aggregate_summary_rows_groups_multi_trial_and_special_condition_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            sweep_dir = Path(tmp_dir_name) / "final-intel-primary-replicated-20260407"
            self._write_run(
                sweep_dir / "v2-qos0-clean" / "trial-01-seed-53701",
                run_id="v2-qos0-clean-trial-01-seed-53701",
                condition_id="v2-qos0-clean",
                trial_id="trial-01-seed-53701",
                trial_index=1,
                impairment_seed=53701,
                latency_p95_ms=200.0,
                bytes_out=12000.0,
            )
            self._write_run(
                sweep_dir / "v2-qos0-clean" / "trial-02-seed-53702",
                run_id="v2-qos0-clean-trial-02-seed-53702",
                condition_id="v2-qos0-clean",
                trial_id="trial-02-seed-53702",
                trial_index=2,
                impairment_seed=53702,
                latency_p95_ms=220.0,
                bytes_out=14000.0,
            )
            self._write_run(
                sweep_dir / "v2-qos0-clean-bw500ms",
                run_id="v2-qos0-clean-bw500ms",
                condition_id="v2-qos0-clean-bw500ms",
                trial_id=None,
                trial_index=None,
                impairment_seed=537,
                latency_p95_ms=260.0,
                bytes_out=16000.0,
            )
            self._write_run(
                sweep_dir / "v3-qos0-loss_2pct-cfgabc12345" / "trial-01-seed-53701",
                run_id="v3-qos0-loss_2pct-cfgabc12345-trial-01-seed-53701",
                condition_id="v3-qos0-loss_2pct-cfgabc12345",
                trial_id="trial-01-seed-53701",
                trial_index=1,
                impairment_seed=53701,
                latency_p95_ms=240.0,
                bytes_out=15000.0,
            )

            aggregated = aggregate_summary_rows(load_summary_rows(sweep_dir))

            self.assertEqual([row["condition_id"] for row in aggregated], [
                "v2-qos0-clean",
                "v2-qos0-clean-bw500ms",
                "v3-qos0-loss_2pct-cfgabc12345",
            ])
            clean_row = aggregated[0]
            self.assertEqual(clean_row["n"], 2)
            self.assertEqual(clean_row["trial_ids"], ["trial-01-seed-53701", "trial-02-seed-53702"])
            self.assertEqual(clean_row["impairment_seeds"], [53701, 53702])
            self.assertEqual(clean_row["latency_p95_ms"], 210.0)
            self.assertEqual(clean_row["latency_p95_ms_stddev"], 10.0)
            self.assertEqual(clean_row["proxy_downstream_bytes_out_min"], 12000.0)
            self.assertEqual(clean_row["proxy_downstream_bytes_out_max"], 14000.0)
            self.assertEqual(clean_row["adaptive_window_increase_events"], 1.5)
            self.assertEqual(clean_row["adaptive_window_increase_events_stddev"], 0.5)

            batch_row = aggregated[1]
            self.assertEqual(batch_row["n"], 1)
            self.assertEqual(batch_row["condition_id"], "v2-qos0-clean-bw500ms")

            adaptive_row = aggregated[2]
            self.assertEqual(adaptive_row["condition_id"], "v3-qos0-loss_2pct-cfgabc12345")

    def test_write_condition_aggregates_writes_root_level_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            sweep_dir = Path(tmp_dir_name) / "intel-v2-batch-window-replicated-20260407"
            self._write_run(
                sweep_dir / "v2-qos0-clean-bw250ms" / "trial-01-seed-53701",
                run_id="v2-qos0-clean-bw250ms-trial-01-seed-53701",
                condition_id="v2-qos0-clean-bw250ms",
                trial_id="trial-01-seed-53701",
                trial_index=1,
                impairment_seed=53701,
                latency_p95_ms=240.0,
            )
            self._write_run(
                sweep_dir / "v2-qos0-clean-bw250ms" / "trial-02-seed-53702",
                run_id="v2-qos0-clean-bw250ms-trial-02-seed-53702",
                condition_id="v2-qos0-clean-bw250ms",
                trial_id="trial-02-seed-53702",
                trial_index=2,
                impairment_seed=53702,
                latency_p95_ms=260.0,
            )

            output_path = write_condition_aggregates(sweep_dir)

            self.assertEqual(output_path, sweep_dir / CONDITION_AGGREGATES_FILENAME)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["trial_summary_count"], 2)
            self.assertEqual(payload["condition_count"], 1)
            self.assertEqual(payload["conditions"][0]["condition_id"], "v2-qos0-clean-bw250ms")
            self.assertEqual(payload["conditions"][0]["latency_p95_ms"], 250.0)

    def _write_run(
        self,
        run_dir: Path,
        *,
        run_id: str,
        condition_id: str,
        trial_id: str | None,
        trial_index: int | None,
        impairment_seed: int,
        latency_p95_ms: float,
        bytes_out: float = 10000.0,
    ) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "run_id": run_id,
            "condition_id": condition_id,
            "trial_id": trial_id,
            "trial_index": trial_index,
            "impairment_seed": impairment_seed,
            "variant": condition_id.split("-")[0],
            "scenario": "clean" if "clean" in condition_id else "loss_2pct",
            "mqtt_qos": 0,
            "latency_mean_ms": latency_p95_ms - 20,
            "latency_p50_ms": latency_p95_ms - 30,
            "latency_p95_ms": latency_p95_ms,
            "latency_p99_ms": latency_p95_ms + 20,
            "proxy_downstream_frames_out": 24,
            "proxy_downstream_bytes_out": bytes_out,
            "stale_fraction": 0.01,
            "freshness_stddev_ms": 5.0,
            "max_bandwidth_bytes_per_s": bytes_out / 10,
            "max_frame_rate_per_s": 4,
            "max_update_rate_per_s": 40,
            "effective_batch_window_ms": 250.0,
            "adaptive_window_increase_events": float(trial_index or 1),
            "adaptive_window_decrease_events": 0.0,
            "proxy_inter_frame_gap_mean_ms": 250.0,
            "proxy_inter_frame_gap_p50_ms": 240.0,
            "proxy_inter_frame_gap_p95_ms": 300.0,
            "proxy_inter_frame_gap_p99_ms": 320.0,
            "proxy_inter_frame_gap_stddev_ms": 15.0,
            "proxy_frame_rate_stddev_per_s": 1.5,
        }
        (run_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        (run_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "run_id": run_id,
                    "condition_id": condition_id,
                    "trial_id": trial_id,
                    "trial_index": trial_index,
                    "impairment_seed": impairment_seed,
                    "effective_gateway_env": {
                        "ADAPTIVE_STEP_UP_MS": "100",
                        "ADAPTIVE_SEND_SLOW_MS": "40",
                    },
                }
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
