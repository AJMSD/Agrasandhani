from __future__ import annotations

import subprocess
import unittest
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


if __name__ == "__main__":
    unittest.main()
