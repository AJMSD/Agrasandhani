from __future__ import annotations

import socket
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from experiments import run_demo


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class RunDemoTests(unittest.TestCase):
    def test_parse_args_defaults_match_demo_profile(self) -> None:
        config = run_demo.parse_args([])

        self.assertEqual(config.data_file, run_demo.DEFAULT_DATA_FILE)
        self.assertEqual(config.scenario_file, run_demo.DEFAULT_SCENARIO_FILE)
        self.assertEqual(config.duration_s, 20)
        self.assertEqual(config.replay_speed, 2.0)
        self.assertEqual(config.mqtt_qos, 0)
        self.assertTrue(config.burst_enabled)
        self.assertEqual(config.burst_start_s, 2)
        self.assertEqual(config.burst_duration_s, 4)
        self.assertEqual(config.burst_speed_multiplier, 8.0)
        self.assertEqual(config.baseline_gateway_port, 8000)
        self.assertEqual(config.smart_gateway_port, 8001)
        self.assertEqual(config.baseline_proxy_port, 9000)
        self.assertEqual(config.smart_proxy_port, 9001)
        self.assertTrue(config.open_browser)

    def test_build_compare_url_uses_query_params_for_urls_and_labels(self) -> None:
        config = run_demo.parse_args(
            [
                "--baseline-proxy-port",
                "9100",
                "--smart-proxy-port",
                "9101",
                "--left-label",
                "Raw Baseline",
                "--right-label",
                "Adaptive Smart",
            ]
        )

        compare_url = run_demo.build_compare_url(config)
        parsed = urlparse(compare_url)
        query = parse_qs(parsed.query)

        self.assertEqual(parsed.netloc, "127.0.0.1:9100")
        self.assertEqual(parsed.path, "/ui/demo_compare.html")
        self.assertEqual(query["left"], ["http://127.0.0.1:9100/ui/index.html"])
        self.assertEqual(query["right"], ["http://127.0.0.1:9101/ui/index.html"])
        self.assertEqual(query["leftLabel"], ["Raw Baseline"])
        self.assertEqual(query["rightLabel"], ["Adaptive Smart"])

    def test_default_demo_scenario_has_expected_phase_timing(self) -> None:
        metadata = run_demo.load_scenario_metadata(run_demo.DEFAULT_SCENARIO_FILE)

        self.assertEqual(metadata["scenario_name"], "demo_v0_vs_v4")
        self.assertEqual(metadata["total_duration_s"], 20)

    def test_validate_environment_rejects_unreachable_mqtt(self) -> None:
        config = run_demo.parse_args([])

        with patch("experiments.run_demo._tcp_port_open", return_value=False):
            with self.assertRaisesRegex(SystemExit, "MQTT broker is not reachable"):
                run_demo.validate_environment(config)

    def test_validate_environment_rejects_busy_service_port(self) -> None:
        busy_port = _pick_free_port()
        config = run_demo.parse_args(["--baseline-gateway-port", str(busy_port)])
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", busy_port))
        self.addCleanup(sock.close)

        with patch("experiments.run_demo._tcp_port_open", return_value=True):
            with self.assertRaisesRegex(SystemExit, "baseline_gateway=127.0.0.1"):
                run_demo.validate_environment(config)

    def test_validate_environment_rejects_missing_scenario(self) -> None:
        config = run_demo.parse_args(["--scenario-file", str(Path("missing-demo-scenario.json"))])

        with self.assertRaisesRegex(SystemExit, "Demo scenario file was not found"):
            run_demo.validate_environment(config)


if __name__ == "__main__":
    unittest.main()
