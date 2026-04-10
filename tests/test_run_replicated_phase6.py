from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments import run_replicated_phase6


class RunReplicatedPhase6Tests(unittest.TestCase):
    def test_parse_args_defaults_to_plan_only_and_local_raw_sources(self) -> None:
        args = run_replicated_phase6.parse_args([])

        self.assertFalse(args.execute)
        self.assertEqual(args.intel_input, run_replicated_phase6.DEFAULT_INTEL_INPUT)
        self.assertEqual(args.aot_input, run_replicated_phase6.DEFAULT_AOT_INPUT)
        self.assertEqual(args.mqtt_host, "127.0.0.1")
        self.assertEqual(args.mqtt_port, 1883)

    def test_run_phase6_writes_plan_only_manifest_with_exact_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            tmp_dir = Path(tmp_dir_name)
            args = run_replicated_phase6.parse_args(
                [
                    "--stamp",
                    "20260407-010203",
                    "--intel-input",
                    str(tmp_dir / "intel_data.txt.gz"),
                    "--aot-input",
                    str(tmp_dir / "aot_weekly.tar"),
                ]
            )

            with (
                patch.object(run_replicated_phase6, "LOGS_ROOT", tmp_dir),
                patch.object(run_replicated_phase6, "GENERATED_INPUTS_DIR", tmp_dir / "generated_inputs"),
                patch.object(run_replicated_phase6, "SOURCE_SLICE_DIR", tmp_dir / "generated_source_slices"),
                patch(
                    "experiments.run_replicated_phase6.collect_preflight_status",
                    return_value={
                        "mqtt_broker_reachable": True,
                        "browser_capture_ready": True,
                        "browser_capture_detail": None,
                    },
                ),
                patch("experiments.run_replicated_phase6.execute_phase6") as execute_phase6,
            ):
                manifest_path, manifest = run_replicated_phase6.run_phase6(args)

            self.assertEqual(manifest_path, tmp_dir / "phase6-matrix-plan-20260407-010203.json")
            self.assertTrue(manifest_path.exists())
            self.assertEqual(manifest["mode"], "plan-only")
            self.assertEqual(
                manifest["execution_order"],
                [
                    "intel_primary",
                    "intel_v2_batch_window",
                    "intel_v1_v2_isolation",
                    "intel_v2_vs_v3_adaptive",
                    "aot_validation",
                ],
            )
            self.assertEqual(manifest["total_expected_runs"], 180)
            execute_phase6.assert_not_called()

            sweeps = {entry["name"]: entry for entry in manifest["sweeps"]}
            self.assertEqual(sweeps["intel_primary"]["sweep_id"], "final-intel-primary-replicated-20260407-010203")
            self.assertEqual(sweeps["intel_primary"]["trial_seeds"], [53701, 53702, 53703])
            self.assertEqual(sweeps["intel_primary"]["expected_run_count"], 90)
            self.assertEqual(sweeps["intel_v2_batch_window"]["sweep_id"], "intel-v2-batch-window-replicated-20260407-010203")
            self.assertEqual(sweeps["intel_v2_batch_window"]["batch_windows_ms"], [50, 100, 250, 500, 1000])
            self.assertEqual(sweeps["intel_v2_batch_window"]["trial_seeds"], [53701, 53702])
            self.assertEqual(sweeps["intel_v2_batch_window"]["expected_run_count"], 10)
            self.assertEqual(sweeps["intel_v1_v2_isolation"]["expected_run_count"], 60)
            self.assertEqual(
                sweeps["intel_v2_vs_v3_adaptive"]["scenarios"],
                ["bandwidth_200kbps", "loss_2pct", "delay_50ms_jitter20ms"],
            )
            self.assertEqual(sweeps["intel_v2_vs_v3_adaptive"]["expected_run_count"], 12)
            self.assertEqual(sweeps["aot_validation"]["expected_run_count"], 8)
            self.assertEqual(
                sweeps["aot_validation"]["aggregate_output_path"],
                run_replicated_phase6._repo_path(
                    tmp_dir / "final-aot-validation-replicated-20260407-010203" / "condition_aggregates.json"
                ),
            )
            self.assertEqual(
                manifest["planned_inputs"]["intel_replay_csv"],
                run_replicated_phase6._repo_path(tmp_dir / "generated_inputs" / "intel_lab_final_20260407-010203.csv"),
            )
            self.assertEqual(
                manifest["planned_inputs"]["aot_source_slice_dir"],
                run_replicated_phase6._repo_path(tmp_dir / "generated_source_slices" / "aot_slice_20260407-010203"),
            )

    def test_run_phase6_only_executes_when_flag_is_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            tmp_dir = Path(tmp_dir_name)
            args = run_replicated_phase6.parse_args(
                [
                    "--stamp",
                    "20260407-020304",
                    "--execute",
                    "--intel-input",
                    str(tmp_dir / "intel_data.txt.gz"),
                    "--aot-input",
                    str(tmp_dir / "aot_weekly.tar"),
                ]
            )
            fake_execution = {
                "prepared_inputs": {"intel_replay_csv": "generated_inputs/intel_lab_final_20260407-020304.csv"},
                "executed_sweeps": [{"name": "intel_primary", "sweep_dir": "experiments/logs/final-intel-primary-replicated-20260407-020304"}],
            }

            with (
                patch.object(run_replicated_phase6, "LOGS_ROOT", tmp_dir),
                patch.object(run_replicated_phase6, "GENERATED_INPUTS_DIR", tmp_dir / "generated_inputs"),
                patch.object(run_replicated_phase6, "SOURCE_SLICE_DIR", tmp_dir / "generated_source_slices"),
                patch(
                    "experiments.run_replicated_phase6.collect_preflight_status",
                    return_value={
                        "mqtt_broker_reachable": True,
                        "browser_capture_ready": True,
                        "browser_capture_detail": None,
                    },
                ),
                patch("experiments.run_replicated_phase6.execute_phase6", return_value=fake_execution) as execute_phase6,
            ):
                manifest_path, manifest = run_replicated_phase6.run_phase6(args)

            self.assertTrue(manifest_path.exists())
            execute_phase6.assert_called_once()
            self.assertEqual(manifest["mode"], "execute")
            self.assertEqual(manifest["prepared_inputs"], fake_execution["prepared_inputs"])
            self.assertEqual(manifest["executed_sweeps"], fake_execution["executed_sweeps"])


if __name__ == "__main__":
    unittest.main()
