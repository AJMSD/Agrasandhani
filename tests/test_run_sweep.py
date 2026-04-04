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
                data_file=Path("intel.csv"),
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
                patch("experiments.run_sweep._find_python", return_value="python"),
                patch("experiments.run_sweep._spawn", side_effect=fake_spawn),
                patch("experiments.run_sweep._wait_for_http"),
                patch("experiments.run_sweep.analyze_run"),
                patch("experiments.run_sweep.urllib.request.urlopen", side_effect=[FakeResponse({}), FakeResponse({})]),
            ):
                run_sweep.run_once(config, variant="v2", mqtt_qos=0, scenario_name="clean")

            self.assertEqual(len(gateway_envs), 1)
            self.assertEqual(gateway_envs[0]["BATCH_WINDOW_MS"], "500")


if __name__ == "__main__":
    unittest.main()
