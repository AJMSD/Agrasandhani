from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments import run_sweep


class RunSweepTests(unittest.TestCase):
    def test_parse_args_short_smoke_profile_sets_expected_defaults(self) -> None:
        with patch("sys.argv", ["run_sweep.py", "--profile", "short-smoke"]):
            config = run_sweep.parse_args()

        self.assertEqual(config.variants, ["v0", "v2", "v4"])
        self.assertEqual(config.qos_values, [0, 1])
        self.assertEqual(config.scenarios, ["clean", "loss_5pct", "outage_5s"])
        self.assertEqual(config.duration_s, 16)
        self.assertEqual(config.sensor_limit, 20)
        self.assertTrue(config.burst_enabled)

    def test_browser_capture_preflight_requires_node(self) -> None:
        with patch("experiments.run_sweep.which", return_value=None):
            with self.assertRaisesRegex(SystemExit, "Node.js is required"):
                run_sweep.ensure_browser_capture_prerequisites()

    def test_browser_capture_preflight_surfaces_capture_script_failure(self) -> None:
        failure = subprocess.CompletedProcess(
            args=["node"],
            returncode=1,
            stdout="",
            stderr="Playwright Chromium browser is not installed.",
        )
        with patch("experiments.run_sweep.which", return_value="node"), patch(
            "experiments.run_sweep.subprocess.run",
            return_value=failure,
        ):
            with self.assertRaisesRegex(SystemExit, "Playwright Chromium browser is not installed"):
                run_sweep.ensure_browser_capture_prerequisites()

    def test_run_once_propagates_batch_window_ms_to_gateway_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            tmp_dir = Path(tmp_dir_name)
            data_file = tmp_dir / "intel.csv"
            data_file.write_text("ts,sensor\n1,a\n", encoding="utf-8")
            gateway_envs: list[dict[str, str]] = []

            class FakeProcess:
                returncode = 0

                def wait(self, timeout: int | None = None) -> int:
                    return 0

                def poll(self) -> int:
                    return 0

                def terminate(self) -> None:
                    return None

                def kill(self) -> None:
                    return None

            def fake_spawn(command: list[str], *, env: dict[str, str], stdout_path: Path, stderr_path: Path) -> FakeProcess:
                if command[-2:] == ["-m", "gateway.app"]:
                    gateway_envs.append(env)
                return FakeProcess()

            class FakeResponse:
                def __init__(self, payload: dict[str, object]) -> None:
                    self._payload = payload

                def __enter__(self) -> "FakeResponse":
                    return self

                def __exit__(self, exc_type, exc, tb) -> None:
                    return None

                def read(self) -> bytes:
                    return json.dumps(self._payload).encode("utf-8")

            config = run_sweep.SweepConfig(
                sweep_id="batch-env-test",
                variants=["v2"],
                qos_values=[0],
                scenarios=["clean"],
                data_file=data_file,
                duration_s=1,
                replay_speed=1.0,
                sensor_limit=1,
                burst_enabled=False,
                burst_start_s=0,
                burst_duration_s=0,
                burst_speed_multiplier=1.0,
                gateway_host="127.0.0.1",
                gateway_port=8000,
                proxy_host="127.0.0.1",
                proxy_port=9000,
                mqtt_host="127.0.0.1",
                mqtt_port=1883,
                run_browser=False,
                batch_window_ms=500,
            )

            with (
                patch.object(run_sweep, "LOGS_ROOT", tmp_dir),
                patch("experiments.run_sweep._git_provenance", return_value={"commit": "abc123", "dirty": True}),
                patch("experiments.run_sweep._find_python", return_value="python"),
                patch("experiments.run_sweep._spawn", side_effect=fake_spawn),
                patch("experiments.run_sweep._wait_for_http"),
                patch("experiments.run_sweep.analyze_run"),
                patch("experiments.run_sweep.urllib.request.urlopen", side_effect=[FakeResponse({}), FakeResponse({})]),
            ):
                run_sweep.run_once(config, variant="v2", mqtt_qos=0, scenario_name="clean")

            self.assertEqual(len(gateway_envs), 1)
            self.assertEqual(gateway_envs[0]["BATCH_WINDOW_MS"], "500")

    def test_run_once_propagates_gateway_env_overrides_to_gateway_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            tmp_dir = Path(tmp_dir_name)
            data_file = tmp_dir / "intel.csv"
            data_file.write_text("ts,sensor\n1,a\n", encoding="utf-8")
            gateway_envs: list[dict[str, str]] = []

            class FakeProcess:
                returncode = 0

                def wait(self, timeout: int | None = None) -> int:
                    return 0

                def poll(self) -> int:
                    return 0

                def terminate(self) -> None:
                    return None

                def kill(self) -> None:
                    return None

            def fake_spawn(command: list[str], *, env: dict[str, str], stdout_path: Path, stderr_path: Path) -> FakeProcess:
                if command[-2:] == ["-m", "gateway.app"]:
                    gateway_envs.append(env)
                return FakeProcess()

            class FakeResponse:
                def __init__(self, payload: dict[str, object]) -> None:
                    self._payload = payload

                def __enter__(self) -> "FakeResponse":
                    return self

                def __exit__(self, exc_type, exc, tb) -> None:
                    return None

                def read(self) -> bytes:
                    return json.dumps(self._payload).encode("utf-8")

            config = run_sweep.SweepConfig(
                sweep_id="gateway-override-test",
                variants=["v3"],
                qos_values=[0],
                scenarios=["loss_2pct"],
                data_file=data_file,
                duration_s=1,
                replay_speed=1.0,
                sensor_limit=1,
                burst_enabled=False,
                burst_start_s=0,
                burst_duration_s=0,
                burst_speed_multiplier=1.0,
                gateway_host="127.0.0.1",
                gateway_port=8000,
                proxy_host="127.0.0.1",
                proxy_port=9000,
                mqtt_host="127.0.0.1",
                mqtt_port=1883,
                run_browser=False,
                batch_window_ms=250,
                gateway_env_overrides={"ADAPTIVE_STEP_UP_MS": "125", "ADAPTIVE_SEND_SLOW_MS": "55"},
            )

            with (
                patch.object(run_sweep, "LOGS_ROOT", tmp_dir),
                patch("experiments.run_sweep._git_provenance", return_value={"commit": "abc123", "dirty": False}),
                patch("experiments.run_sweep._find_python", return_value="python"),
                patch("experiments.run_sweep._spawn", side_effect=fake_spawn),
                patch("experiments.run_sweep._wait_for_http"),
                patch("experiments.run_sweep.analyze_run"),
                patch("experiments.run_sweep.urllib.request.urlopen", side_effect=[FakeResponse({}), FakeResponse({})]),
            ):
                run_sweep.run_once(config, variant="v3", mqtt_qos=0, scenario_name="loss_2pct")

            self.assertEqual(len(gateway_envs), 1)
            self.assertEqual(gateway_envs[0]["ADAPTIVE_STEP_UP_MS"], "125")
            self.assertEqual(gateway_envs[0]["ADAPTIVE_SEND_SLOW_MS"], "55")

    def test_run_once_writes_manifest_v2_for_trial_layout_and_sets_impairment_seed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            tmp_dir = Path(tmp_dir_name)
            data_file = tmp_dir / "intel.csv"
            data_file.write_text("ts,sensor\n1,a\n", encoding="utf-8")
            proxy_envs: list[dict[str, str]] = []

            class FakeProcess:
                returncode = 0

                def wait(self, timeout: int | None = None) -> int:
                    return 0

                def poll(self) -> int:
                    return 0

                def terminate(self) -> None:
                    return None

                def kill(self) -> None:
                    return None

            def fake_spawn(command: list[str], *, env: dict[str, str], stdout_path: Path, stderr_path: Path) -> FakeProcess:
                if command[-2:] == ["-m", "experiments.impairment_proxy"]:
                    proxy_envs.append(env)
                return FakeProcess()

            class FakeResponse:
                def __init__(self, payload: dict[str, object]) -> None:
                    self._payload = payload

                def __enter__(self) -> "FakeResponse":
                    return self

                def __exit__(self, exc_type, exc, tb) -> None:
                    return None

                def read(self) -> bytes:
                    return json.dumps(self._payload).encode("utf-8")

            config = run_sweep.SweepConfig(
                sweep_id="replicated-intel",
                variants=["v2"],
                qos_values=[0],
                scenarios=["clean"],
                data_file=data_file,
                duration_s=1,
                replay_speed=1.0,
                sensor_limit=1,
                burst_enabled=False,
                burst_start_s=0,
                burst_duration_s=0,
                burst_speed_multiplier=1.0,
                gateway_host="127.0.0.1",
                gateway_port=8000,
                proxy_host="127.0.0.1",
                proxy_port=9000,
                mqtt_host="127.0.0.1",
                mqtt_port=1883,
                run_browser=False,
            )

            with (
                patch.object(run_sweep, "LOGS_ROOT", tmp_dir),
                patch("experiments.run_sweep._git_provenance", return_value={"commit": "abc123", "dirty": True}),
                patch("experiments.run_sweep._find_python", return_value="python"),
                patch("experiments.run_sweep._spawn", side_effect=fake_spawn),
                patch("experiments.run_sweep._wait_for_http"),
                patch("experiments.run_sweep.analyze_run"),
                patch("experiments.run_sweep.urllib.request.urlopen", side_effect=[FakeResponse({}), FakeResponse({})]),
            ):
                run_dir = run_sweep.run_once(
                    config,
                    variant="v2",
                    mqtt_qos=0,
                    scenario_name="clean",
                    trial_index=2,
                    impairment_seed=53702,
                )

            self.assertEqual(run_dir, tmp_dir / "replicated-intel" / "v2-qos0-clean" / "trial-02-seed-53702")
            self.assertEqual(proxy_envs[0]["IMPAIR_RANDOM_SEED"], "53702")
            manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(manifest["condition_id"], "v2-qos0-clean")
            self.assertEqual(manifest["trial_id"], "trial-02-seed-53702")
            self.assertEqual(manifest["trial_index"], 2)
            self.assertEqual(manifest["impairment_seed"], 53702)
            self.assertEqual(manifest["git_commit"], "abc123")
            self.assertTrue(manifest["git_dirty"])
            self.assertEqual(manifest["data_file_path"], str(data_file))
            self.assertIsNotNone(manifest["data_file_sha256"])
            self.assertIsNotNone(manifest["scenario_sha256"])
            self.assertEqual(manifest["effective_gateway_env"]["GATEWAY_MODE"], "v2")
            self.assertIn("started_at_utc", manifest)
            self.assertIn("finished_at_utc", manifest)

    def test_run_sweep_returns_sweep_dir_and_completed_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            tmp_dir = Path(tmp_dir_name)
            data_file = tmp_dir / "intel.csv"
            data_file.write_text("ts,sensor\n1,a\n", encoding="utf-8")

            config = run_sweep.SweepConfig(
                sweep_id="replicated-phase6",
                variants=["v0", "v2"],
                qos_values=[0],
                scenarios=["clean", "outage_5s"],
                data_file=data_file,
                duration_s=1,
                replay_speed=1.0,
                sensor_limit=1,
                burst_enabled=False,
                burst_start_s=0,
                burst_duration_s=0,
                burst_speed_multiplier=1.0,
                gateway_host="127.0.0.1",
                gateway_port=8000,
                proxy_host="127.0.0.1",
                proxy_port=9000,
                mqtt_host="127.0.0.1",
                mqtt_port=1883,
                run_browser=False,
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
            ) -> Path:
                run_dir = tmp_dir / config.sweep_id / f"{variant}-qos{mqtt_qos}-{scenario_name}"
                run_dir.mkdir(parents=True, exist_ok=True)
                return run_dir

            with (
                patch.object(run_sweep, "LOGS_ROOT", tmp_dir),
                patch("experiments.run_sweep._port_open", return_value=True),
                patch("experiments.run_sweep.run_once", side_effect=fake_run_once) as run_once_mock,
                patch("experiments.run_sweep.write_condition_aggregates") as write_condition_aggregates,
                patch("experiments.run_sweep.subprocess.run") as subprocess_run,
                patch("experiments.run_sweep._find_python", return_value="python"),
            ):
                sweep_dir, completed_runs = run_sweep.run_sweep(config)

            self.assertEqual(sweep_dir, tmp_dir / config.sweep_id)
            self.assertEqual(run_once_mock.call_count, 4)
            self.assertEqual(len(completed_runs), 4)
            self.assertEqual(
                completed_runs,
                [
                    str(tmp_dir / config.sweep_id / "v0-qos0-clean"),
                    str(tmp_dir / config.sweep_id / "v0-qos0-outage_5s"),
                    str(tmp_dir / config.sweep_id / "v2-qos0-clean"),
                    str(tmp_dir / config.sweep_id / "v2-qos0-outage_5s"),
                ],
            )
            write_condition_aggregates.assert_called_once_with(tmp_dir / config.sweep_id)
            subprocess_run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
