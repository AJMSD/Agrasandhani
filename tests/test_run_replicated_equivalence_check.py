from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments import run_replicated_equivalence_check as equivalence


class RunReplicatedEquivalenceCheckTests(unittest.TestCase):
    def test_parse_args_defaults_to_frozen_manifest_and_plan_only(self) -> None:
        args = equivalence.parse_args([])

        self.assertFalse(args.execute)
        self.assertEqual(args.frozen_manifest_path, equivalence.DEFAULT_FROZEN_MANIFEST)
        self.assertEqual(args.intel_input.name, "intel_data.txt.gz")
        self.assertEqual(args.aot_input.name, "aot_weekly.tar")

    def test_build_new_roots_maps_phase6_plus_parameter_and_demo_roots(self) -> None:
        phase6_manifest = {
            "executed_sweeps": [
                {"name": "intel_primary", "sweep_dir": "experiments/logs/final-intel-primary-replicated-x"},
                {"name": "aot_validation", "sweep_dir": "experiments/logs/final-aot-validation-replicated-x"},
                {"name": "intel_v2_batch_window", "sweep_dir": "experiments/logs/intel-v2-batch-window-replicated-x"},
                {"name": "intel_v1_v2_isolation", "sweep_dir": "experiments/logs/intel-v1-v2-isolation-replicated-x"},
                {"name": "intel_v2_vs_v3_adaptive", "sweep_dir": "experiments/logs/intel-v2-v3-adaptive-replicated-x"},
            ]
        }

        with tempfile.TemporaryDirectory() as tmp_dir_name:
            tmp_dir = Path(tmp_dir_name)
            with patch.object(equivalence, "LOGS_ROOT", tmp_dir):
                roots = equivalence.build_new_roots(
                    phase6_manifest=phase6_manifest,
                    stamp="x",
                    demo_dir=tmp_dir / "final-demo-x" / "demo",
                )

        self.assertEqual(roots["intel_primary"], "experiments/logs/final-intel-primary-replicated-x")
        self.assertTrue(roots["intel_v3_adaptive_parameter_sweep"].endswith("intel-v3-adaptive-parameter-sweep-x"))
        self.assertTrue(roots["demo"].endswith("final-demo-x/demo"))

    def test_compare_sweep_accepts_additive_fields_and_runtime_deltas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            tmp_dir = Path(tmp_dir_name)
            baseline = tmp_dir / "baseline"
            new = tmp_dir / "new"
            self._write_sweep(baseline, latency_mean_ms=10.0)
            self._write_sweep(
                new,
                latency_mean_ms=12.0,
                extra_summary_fields={"last_adaptation_reason": "queue_high"},
                extra_aggregate_fields={"adaptive_window_increase_events": 1.0},
            )

            result = equivalence.compare_sweep_roots(
                sweep_name="intel_primary",
                baseline_root=baseline,
                new_root=new,
            )

        self.assertEqual(result.status, "passed_with_notes")
        self.assertEqual(result.blocking_findings, [])
        self.assertIn("last_adaptation_reason", result.additive_fields)
        self.assertIn("adaptive_window_increase_events", result.additive_fields)
        self.assertTrue(result.largest_metric_deltas)

    def test_compare_sweep_blocks_on_missing_baseline_summary_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            tmp_dir = Path(tmp_dir_name)
            baseline = tmp_dir / "baseline"
            new = tmp_dir / "new"
            self._write_sweep(baseline, extra_summary_fields={"paper_metric": 1})
            self._write_sweep(new)

            result = equivalence.compare_sweep_roots(
                sweep_name="intel_primary",
                baseline_root=baseline,
                new_root=new,
            )

        self.assertEqual(result.status, "failed")
        self.assertTrue(any("missing baseline fields" in finding for finding in result.blocking_findings))

    def test_compare_sweep_blocks_on_replication_depth_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            tmp_dir = Path(tmp_dir_name)
            baseline = tmp_dir / "baseline"
            new = tmp_dir / "new"
            self._write_sweep(baseline, trial_count=2)
            self._write_sweep(new, trial_count=1)

            result = equivalence.compare_sweep_roots(
                sweep_name="intel_primary",
                baseline_root=baseline,
                new_root=new,
            )

        self.assertEqual(result.status, "failed")
        self.assertTrue(any("trial_summary_count changed" in finding for finding in result.blocking_findings))
        self.assertTrue(any("field n changed" in finding for finding in result.blocking_findings))

    def test_compare_demo_reports_missing_artifacts_as_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            tmp_dir = Path(tmp_dir_name)
            baseline = tmp_dir / "baseline-demo"
            new = tmp_dir / "new-demo"
            self._write_demo(baseline)
            new.mkdir()

            result = equivalence.compare_demo_roots(baseline_root=baseline, new_root=new)

        self.assertEqual(result.status, "failed")
        self.assertTrue(any("demo new artifact is missing" in finding for finding in result.blocking_findings))

    def _write_sweep(
        self,
        root: Path,
        *,
        trial_count: int = 2,
        latency_mean_ms: float = 10.0,
        extra_summary_fields: dict[str, object] | None = None,
        extra_aggregate_fields: dict[str, object] | None = None,
    ) -> None:
        condition_id = "v0-qos0-clean"
        trial_ids = [f"trial-{index:02d}-seed-{53700 + index}" for index in range(1, trial_count + 1)]
        condition = {
            "condition_id": condition_id,
            "run_id": condition_id,
            "variant": "v0",
            "scenario": "clean",
            "mqtt_qos": 0,
            "n": trial_count,
            "trial_ids": trial_ids,
            "trial_indices": list(range(1, trial_count + 1)),
            "impairment_seeds": [53700 + index for index in range(1, trial_count + 1)],
            "schema_version": 2,
            "latency_mean_ms": latency_mean_ms,
        }
        condition.update(extra_aggregate_fields or {})
        aggregate = {
            "schema_version": 1,
            "sweep_dir": str(root),
            "trial_summary_count": trial_count,
            "condition_count": 1,
            "conditions": [condition],
        }
        root.mkdir(parents=True)
        (root / "condition_aggregates.json").write_text(json.dumps(aggregate, indent=2), encoding="utf-8")

        for index, trial_id in enumerate(trial_ids, start=1):
            run_dir = root / condition_id / trial_id
            run_dir.mkdir(parents=True)
            summary = {
                "run_id": f"{condition_id}-{trial_id}",
                "condition_id": condition_id,
                "trial_id": trial_id,
                "trial_index": index,
                "impairment_seed": 53700 + index,
                "variant": "v0",
                "scenario": "clean",
                "mqtt_qos": 0,
                "schema_version": 2,
                "latency_mean_ms": latency_mean_ms,
            }
            summary.update(extra_summary_fields or {})
            manifest = {
                "schema_version": 2,
                "run_id": summary["run_id"],
                "condition_id": condition_id,
                "trial_id": trial_id,
                "trial_index": index,
                "impairment_seed": 53700 + index,
            }
            (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    def _write_demo(self, root: Path) -> None:
        (root / "baseline_dashboard").mkdir(parents=True)
        (root / "smart_dashboard").mkdir(parents=True)
        manifest = {
            "scenario_name": "demo_v0_vs_v4",
            "scenario_total_duration_s": 20,
            "duration_s": 20,
            "replay_speed": 5.0,
            "sensor_limit": 200,
            "mqtt_qos": 0,
            "burst_enabled": True,
            "burst_start_s": 2,
            "burst_duration_s": 4,
            "burst_speed_multiplier": 8.0,
            "capture_artifacts": True,
        }
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        (root / "demo_compare.png").write_bytes(b"compare")
        for side in ("baseline", "smart"):
            dashboard = root / f"{side}_dashboard"
            (dashboard / "dashboard_measurements.csv").write_text("timestamp,frameCount\n", encoding="utf-8")
            (dashboard / "dashboard_summary.json").write_text(
                json.dumps({"frameCount": 1, "staleCount": 0}, indent=2),
                encoding="utf-8",
            )
            (dashboard / "dashboard.png").write_bytes(b"png")


if __name__ == "__main__":
    unittest.main()
