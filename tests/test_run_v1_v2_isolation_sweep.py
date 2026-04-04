from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments import run_v1_v2_isolation_sweep


class RunV1V2IsolationSweepTests(unittest.TestCase):
    def test_parse_args_uses_expected_defaults(self) -> None:
        config = run_v1_v2_isolation_sweep.parse_args(["--data-file", "intel.csv"])

        self.assertEqual(config.data_file, Path("intel.csv"))
        self.assertEqual(config.scenarios, ["clean", "bandwidth_200kbps", "outage_5s"])
        self.assertEqual(config.batch_windows, [50, 100, 250, 500, 1000])
        self.assertEqual(config.duration_s, 30)
        self.assertEqual(config.replay_speed, 5.0)
        self.assertEqual(config.sensor_limit, 200)
        self.assertTrue(config.run_browser)

    def test_build_run_label_suffix_formats_batch_window(self) -> None:
        self.assertEqual(run_v1_v2_isolation_sweep.build_run_label_suffix(500), "bw500ms")

    def test_run_v1_v2_isolation_sweep_writes_manifest_and_summary_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            tmp_dir = Path(tmp_dir_name)
            data_file = tmp_dir / "intel.csv"
            data_file.write_text("sensor_id,msg_id,ts_sent,metric_type,value\n", encoding="utf-8")

            config = run_v1_v2_isolation_sweep.V1V2IsolationSweepConfig(
                sweep_id="intel-v1-v2-isolation-test",
                data_file=data_file,
                scenarios=["clean", "outage_5s"],
                batch_windows=[50, 250],
                duration_s=30,
                replay_speed=5.0,
                sensor_limit=200,
                gateway_host="127.0.0.1",
                gateway_port=8000,
                proxy_host="127.0.0.1",
                proxy_port=9000,
                mqtt_host="127.0.0.1",
                mqtt_port=1883,
                run_browser=False,
            )

            def fake_run_once(sweep_config, *, variant: str, mqtt_qos: int, scenario_name: str, run_label_suffix: str | None = None):
                run_dir = tmp_dir / config.sweep_id / f"{variant}-qos0-{scenario_name}-{run_label_suffix}"
                run_dir.mkdir(parents=True, exist_ok=True)
                return run_dir

            with (
                patch.object(run_v1_v2_isolation_sweep, "LOGS_ROOT", tmp_dir),
                patch("experiments.run_v1_v2_isolation_sweep._port_open", return_value=True),
                patch("experiments.run_v1_v2_isolation_sweep.run_once", side_effect=fake_run_once) as run_once_mock,
            ):
                sweep_dir = run_v1_v2_isolation_sweep.run_v1_v2_isolation_sweep(config)

            self.assertEqual(run_once_mock.call_count, 8)
            self.assertEqual(sweep_dir, tmp_dir / config.sweep_id)

            manifest = json.loads((sweep_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["variants"], ["v1", "v2"])
            self.assertEqual(manifest["scenarios"], ["clean", "outage_5s"])
            self.assertEqual(manifest["batch_windows_ms"], [50, 250])
            self.assertEqual(
                [entry["run_id"] for entry in manifest["runs"][:4]],
                [
                    "v1-qos0-clean-bw50ms",
                    "v2-qos0-clean-bw50ms",
                    "v1-qos0-clean-bw250ms",
                    "v2-qos0-clean-bw250ms",
                ],
            )

            with (sweep_dir / "summary.csv").open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 8)
            self.assertEqual(rows[0]["scenario"], "clean")
            self.assertEqual(rows[0]["variant"], "v1")
            self.assertEqual(rows[0]["batch_window_ms"], "50")


if __name__ == "__main__":
    unittest.main()
