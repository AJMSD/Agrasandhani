from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments import run_adaptive_impairment_sweep


class RunAdaptiveImpairmentSweepTests(unittest.TestCase):
    def test_parse_args_uses_expected_defaults(self) -> None:
        config = run_adaptive_impairment_sweep.parse_args(["--data-file", "intel.csv"])

        self.assertEqual(config.data_file, Path("intel.csv"))
        self.assertEqual(config.scenarios, ["bandwidth_200kbps", "loss_2pct"])
        self.assertEqual(config.batch_window_ms, 250)
        self.assertEqual(config.duration_s, 30)
        self.assertEqual(config.replay_speed, 5.0)
        self.assertEqual(config.sensor_limit, 200)
        self.assertTrue(config.run_browser)
        self.assertIsNone(config.adaptive_step_up_ms)

    def test_build_sweep_config_exposes_adaptive_overrides(self) -> None:
        config = run_adaptive_impairment_sweep.AdaptiveImpairmentSweepConfig(
            sweep_id="adaptive-test",
            data_file=Path("intel.csv"),
            scenarios=["bandwidth_200kbps"],
            duration_s=30,
            replay_speed=5.0,
            sensor_limit=200,
            batch_window_ms=250,
            gateway_host="127.0.0.1",
            gateway_port=8000,
            proxy_host="127.0.0.1",
            proxy_port=9000,
            mqtt_host="127.0.0.1",
            mqtt_port=1883,
            run_browser=False,
            adaptive_step_up_ms=150,
            adaptive_send_slow_ms=25,
        )

        sweep_config = run_adaptive_impairment_sweep.build_sweep_config(
            config,
            variant="v3",
            scenario="bandwidth_200kbps",
        )

        self.assertEqual(sweep_config.batch_window_ms, 250)
        self.assertEqual(
            sweep_config.gateway_env_overrides,
            {"ADAPTIVE_STEP_UP_MS": "150", "ADAPTIVE_SEND_SLOW_MS": "25"},
        )

    def test_run_adaptive_impairment_sweep_writes_manifest_and_summary_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            tmp_dir = Path(tmp_dir_name)
            data_file = tmp_dir / "intel.csv"
            data_file.write_text("sensor_id,msg_id,ts_sent,metric_type,value\n", encoding="utf-8")

            config = run_adaptive_impairment_sweep.AdaptiveImpairmentSweepConfig(
                sweep_id="intel-v2-v3-adaptive-test",
                data_file=data_file,
                scenarios=["bandwidth_200kbps", "loss_2pct"],
                duration_s=30,
                replay_speed=5.0,
                sensor_limit=200,
                batch_window_ms=250,
                gateway_host="127.0.0.1",
                gateway_port=8000,
                proxy_host="127.0.0.1",
                proxy_port=9000,
                mqtt_host="127.0.0.1",
                mqtt_port=1883,
                run_browser=False,
                adaptive_step_up_ms=125,
            )

            def fake_run_once(sweep_config, *, variant: str, mqtt_qos: int, scenario_name: str, run_label_suffix: str | None = None):
                run_dir = tmp_dir / config.sweep_id / f"{variant}-qos0-{scenario_name}"
                run_dir.mkdir(parents=True, exist_ok=True)
                return run_dir

            with (
                patch.object(run_adaptive_impairment_sweep, "LOGS_ROOT", tmp_dir),
                patch("experiments.run_adaptive_impairment_sweep._port_open", return_value=True),
                patch("experiments.run_adaptive_impairment_sweep.run_once", side_effect=fake_run_once) as run_once_mock,
            ):
                sweep_dir = run_adaptive_impairment_sweep.run_adaptive_impairment_sweep(config)

            self.assertEqual(run_once_mock.call_count, 4)
            self.assertEqual(sweep_dir, tmp_dir / config.sweep_id)

            manifest = json.loads((sweep_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["variants"], ["v2", "v3"])
            self.assertEqual(manifest["scenarios"], ["bandwidth_200kbps", "loss_2pct"])
            self.assertEqual(manifest["batch_window_ms"], 250)
            self.assertEqual(manifest["adaptive_overrides"], {"ADAPTIVE_STEP_UP_MS": "125"})
            self.assertEqual(
                [entry["run_id"] for entry in manifest["runs"]],
                [
                    "v2-qos0-bandwidth_200kbps",
                    "v3-qos0-bandwidth_200kbps",
                    "v2-qos0-loss_2pct",
                    "v3-qos0-loss_2pct",
                ],
            )

            with (sweep_dir / "summary.csv").open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 4)
            self.assertEqual(rows[0]["scenario"], "bandwidth_200kbps")
            self.assertEqual(rows[0]["variant"], "v2")
            self.assertEqual(rows[0]["batch_window_ms"], "250")


if __name__ == "__main__":
    unittest.main()
