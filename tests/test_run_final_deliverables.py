from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments import run_final_deliverables


class RunFinalDeliverablesTests(unittest.TestCase):
    def test_parse_args_uses_expected_defaults(self) -> None:
        args = run_final_deliverables.parse_args(
            [
                "--intel-input",
                "intel.txt.gz",
                "--aot-input",
                "aot.tar",
            ]
        )

        self.assertEqual(args.intel_input, Path("intel.txt.gz"))
        self.assertEqual(args.aot_input, Path("aot.tar"))
        self.assertEqual(args.report_dir, run_final_deliverables.DEFAULT_REPORT_DIR)
        self.assertEqual(args.mqtt_host, "127.0.0.1")
        self.assertEqual(args.mqtt_port, 1883)

    def test_build_configs_match_final_matrix(self) -> None:
        intel = run_final_deliverables.build_intel_primary_config(
            stamp="20260403",
            data_file=Path("intel.csv"),
            mqtt_host="127.0.0.1",
            mqtt_port=1883,
        )
        aot = run_final_deliverables.build_aot_validation_config(
            stamp="20260403",
            data_file=Path("aot.csv"),
            mqtt_host="127.0.0.1",
            mqtt_port=1883,
        )

        self.assertEqual(intel.sweep_id, "final-intel-primary-20260403")
        self.assertEqual(intel.variants, ["v0", "v2", "v4"])
        self.assertEqual(intel.qos_values, [0, 1])
        self.assertEqual(intel.scenarios, run_final_deliverables.INTEL_PRIMARY_SCENARIOS)
        self.assertEqual(intel.duration_s, 30)
        self.assertEqual(intel.replay_speed, 5.0)
        self.assertEqual(aot.sweep_id, "final-aot-validation-20260403")
        self.assertEqual(aot.variants, ["v0", "v4"])
        self.assertEqual(aot.qos_values, [0])
        self.assertEqual(aot.scenarios, run_final_deliverables.AOT_VALIDATION_SCENARIOS)

    def test_run_final_deliverables_writes_manifest_and_calls_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            tmp_dir = Path(tmp_dir_name)
            intel_input = tmp_dir / "intel.txt.gz"
            aot_input = tmp_dir / "aot.tar"
            intel_input.write_text("intel", encoding="utf-8")
            aot_input.write_text("aot", encoding="utf-8")
            report_dir = tmp_dir / "report"
            intel_sweep_dir = tmp_dir / "logs" / "final-intel-primary-20260403"
            aot_sweep_dir = tmp_dir / "logs" / "final-aot-validation-20260403"
            demo_dir = tmp_dir / "logs" / "final-demo-20260403" / "demo"

            args = run_final_deliverables.parse_args(
                [
                    "--intel-input",
                    str(intel_input),
                    "--aot-input",
                    str(aot_input),
                    "--stamp",
                    "20260403",
                    "--report-dir",
                    str(report_dir),
                ]
            )

            with (
                patch.object(run_final_deliverables, "LOGS_ROOT", tmp_dir / "logs"),
                patch.object(run_final_deliverables, "GENERATED_INPUTS_DIR", tmp_dir / "logs" / "generated_inputs"),
                patch("experiments.run_final_deliverables.ensure_browser_capture_prerequisites") as browser_preflight,
                patch("experiments.run_final_deliverables._port_open", return_value=True),
                patch("experiments.run_final_deliverables._slice_intel_source", return_value=(1296, 54)),
                patch(
                    "experiments.run_final_deliverables._slice_aot_source",
                    return_value=(tmp_dir / "logs" / "generated_source_slices" / "aot_slice_20260403" / "data.csv", tmp_dir / "logs" / "generated_source_slices" / "aot_slice_20260403" / "sensors.csv", 640, 16),
                ),
                patch("experiments.run_final_deliverables.normalize_intel_lab", return_value=(1234, 54)) as normalize_intel,
                patch("experiments.run_final_deliverables.normalize_aot", return_value=(456, 12)) as normalize_aot,
                patch("experiments.run_final_deliverables._run_sweep", side_effect=[intel_sweep_dir, aot_sweep_dir]) as run_sweep,
                patch("experiments.run_final_deliverables.validate_demo_environment") as validate_demo,
                patch("experiments.run_final_deliverables.run_demo", return_value=demo_dir) as run_demo,
                patch(
                    "experiments.run_final_deliverables.build_report_assets",
                    return_value={"intel_sweep_dir": str(intel_sweep_dir)},
                ) as build_assets,
            ):
                manifest = run_final_deliverables.run_final_deliverables(args)

            browser_preflight.assert_called_once()
            normalize_intel.assert_called_once()
            normalize_aot.assert_called_once()
            self.assertEqual(run_sweep.call_count, 2)
            validate_demo.assert_called_once()
            run_demo.assert_called_once()
            build_assets.assert_called_once()
            self.assertEqual(manifest["intel_sweep_id"], "final-intel-primary-20260403")
            self.assertEqual(manifest["aot_sweep_id"], "final-aot-validation-20260403")
            self.assertEqual(manifest["demo_run_id"], "final-demo-20260403")

            manifest_path = tmp_dir / "logs" / "final-deliverables-20260403" / "manifest.json"
            self.assertTrue(manifest_path.exists())
            saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(saved_manifest["intel_rows_written"], 1234)
            self.assertEqual(saved_manifest["aot_rows_written"], 456)


if __name__ == "__main__":
    unittest.main()
