from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments import run_v3_adaptive_parameter_sweep


class RunV3AdaptiveParameterSweepTests(unittest.TestCase):
    def test_parse_args_uses_expected_defaults(self) -> None:
        config = run_v3_adaptive_parameter_sweep.parse_args(
            ["--sweep-id", "section7-test", "--data-file", "intel.csv"]
        )

        self.assertEqual(config.sweep_id, "section7-test")
        self.assertEqual(config.data_file, Path("intel.csv"))
        self.assertEqual(config.scenarios, ["bandwidth_200kbps", "loss_2pct", "delay_50ms_jitter20ms"])
        self.assertEqual(config.batch_window_ms, 250)
        self.assertEqual(config.adaptive_send_slow_values, [25, 50, 100])
        self.assertEqual(config.adaptive_step_up_values, [50, 100])
        self.assertEqual(config.adaptive_max_batch_window_values, [500, 1000])
        self.assertTrue(config.run_browser)

    def test_run_v3_adaptive_parameter_sweep_writes_manifest_summary_and_aggregates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            tmp_dir = Path(tmp_dir_name)
            data_file = tmp_dir / "intel.csv"
            data_file.write_text("sensor_id,msg_id,ts_sent,metric_type,value\n", encoding="utf-8")

            config = run_v3_adaptive_parameter_sweep.V3AdaptiveParameterSweepConfig(
                sweep_id="intel-v3-adaptive-parameter-sweep-20260408-200000",
                data_file=data_file,
                scenarios=["bandwidth_200kbps", "loss_2pct", "delay_50ms_jitter20ms"],
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
                trial_seeds=[53701, 53702],
            )

            def fake_run_once(
                sweep_config,
                *,
                variant: str,
                mqtt_qos: int,
                scenario_name: str,
                run_label_suffix: str | None = None,
                trial_index: int | None = None,
                impairment_seed: int | None = None,
            ):
                condition_id = f"{variant}-qos{mqtt_qos}-{scenario_name}-{run_label_suffix}"
                run_dir = tmp_dir / config.sweep_id / condition_id / f"trial-{trial_index:02d}-seed-{impairment_seed}"
                run_dir.mkdir(parents=True, exist_ok=True)
                summary = {
                    "run_id": f"{condition_id}-trial-{trial_index:02d}-seed-{impairment_seed}",
                    "condition_id": condition_id,
                    "trial_id": f"trial-{trial_index:02d}-seed-{impairment_seed}",
                    "trial_index": trial_index,
                    "impairment_seed": impairment_seed,
                    "variant": variant,
                    "scenario": scenario_name,
                    "mqtt_qos": mqtt_qos,
                    "latency_mean_ms": 150.0,
                    "latency_p50_ms": 145.0,
                    "latency_p95_ms": 200.0,
                    "latency_p99_ms": 210.0,
                    "proxy_downstream_bytes_out": 13000.0,
                    "proxy_downstream_frames_out": 5.0,
                    "max_bandwidth_bytes_per_s": 4000.0,
                    "max_frame_rate_per_s": 1.0,
                    "max_update_rate_per_s": 40.0,
                    "stale_fraction": 0.0,
                    "freshness_stddev_ms": 10.0,
                    "effective_batch_window_ms": 250.0,
                    "adaptive_window_increase_events": 1.0,
                    "adaptive_window_decrease_events": 0.0,
                    "proxy_inter_frame_gap_mean_ms": 6000.0,
                    "proxy_inter_frame_gap_p50_ms": 6000.0,
                    "proxy_inter_frame_gap_p95_ms": 6050.0,
                    "proxy_inter_frame_gap_p99_ms": 6075.0,
                    "proxy_inter_frame_gap_stddev_ms": 30.0,
                    "proxy_frame_rate_stddev_per_s": 0.0,
                }
                manifest = {
                    "schema_version": 2,
                    "run_id": summary["run_id"],
                    "condition_id": condition_id,
                    "trial_id": summary["trial_id"],
                    "trial_index": trial_index,
                    "impairment_seed": impairment_seed,
                    "effective_gateway_env": sweep_config.gateway_env_overrides,
                    "batch_window_ms": 250,
                }
                (run_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
                (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
                return run_dir

            with (
                patch.object(run_v3_adaptive_parameter_sweep, "LOGS_ROOT", tmp_dir),
                patch("experiments.run_v3_adaptive_parameter_sweep._port_open", return_value=True),
                patch("experiments.run_v3_adaptive_parameter_sweep.run_once", side_effect=fake_run_once) as run_once_mock,
            ):
                sweep_dir = run_v3_adaptive_parameter_sweep.run_v3_adaptive_parameter_sweep(config)

            self.assertEqual(run_once_mock.call_count, 72)
            self.assertEqual(sweep_dir, tmp_dir / config.sweep_id)

            manifest = json.loads((sweep_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["variants"], ["v3"])
            self.assertEqual(len(manifest["parameter_grid"]), 12)
            self.assertEqual(manifest["trial_seeds"], [53701, 53702])
            self.assertEqual(len(manifest["runs"]), 72)

            with (sweep_dir / "summary.csv").open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 72)
            self.assertEqual(rows[0]["variant"], "v3")
            self.assertEqual(rows[0]["batch_window_ms"], "250")
            self.assertTrue(rows[0]["condition_id"].startswith("v3-qos0-bandwidth_200kbps-cfg"))

            aggregates = json.loads((sweep_dir / "condition_aggregates.json").read_text(encoding="utf-8"))
            self.assertEqual(aggregates["trial_summary_count"], 72)
            self.assertEqual(aggregates["condition_count"], 36)
            self.assertEqual(aggregates["conditions"][0]["n"], 2)
            self.assertIn("adaptive_send_slow_ms", aggregates["conditions"][0])


if __name__ == "__main__":
    unittest.main()
