from __future__ import annotations

import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from experiments import run_demo


def _pick_bound_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class FakeProcess:
    def __init__(self, *, name: str, complete_on_wait: bool, exit_code: int = 0) -> None:
        self.name = name
        self.complete_on_wait = complete_on_wait
        self.exit_code = exit_code
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def wait(self, timeout: int | None = None) -> int:
        if self.returncode is None:
            self.returncode = self.exit_code
        return self.returncode

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        if self.returncode is None:
            self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        if self.returncode is None:
            self.returncode = -9


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
        self.assertFalse(config.auto_ports)
        self.assertFalse(config.capture_artifacts)
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

    def test_validate_environment_rejects_busy_service_port_without_auto_ports(self) -> None:
        busy_port = _pick_bound_port()
        config = run_demo.parse_args(["--baseline-gateway-port", str(busy_port)])
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", busy_port))
        self.addCleanup(sock.close)

        with patch("experiments.run_demo._tcp_port_open", return_value=True):
            with self.assertRaisesRegex(SystemExit, "baseline_gateway=127.0.0.1"):
                run_demo.validate_environment(config)

    def test_validate_environment_auto_ports_reassigns_busy_ports(self) -> None:
        config = run_demo.parse_args(["--auto-ports"])

        def fake_port_available(host: str, port: int) -> bool:
            return port not in {9000, 9001}

        with (
            patch("experiments.run_demo._tcp_port_open", return_value=True),
            patch("experiments.run_demo._port_available", side_effect=fake_port_available),
            patch("experiments.run_demo._pick_free_port", side_effect=[9100, 9101]),
        ):
            run_demo.validate_environment(config)

        self.assertEqual(config.baseline_proxy_port, 9100)
        self.assertEqual(config.smart_proxy_port, 9101)
        compare_url = run_demo.build_compare_url(config)
        self.assertIn("127.0.0.1:9100", compare_url)
        self.assertIn("127.0.0.1%3A9101", compare_url)

    def test_validate_environment_rejects_missing_scenario(self) -> None:
        config = run_demo.parse_args(["--scenario-file", str(Path("missing-demo-scenario.json"))])

        with self.assertRaisesRegex(SystemExit, "Demo scenario file was not found"):
            run_demo.validate_environment(config)

    def test_run_demo_writes_manifest_without_capture_processes(self) -> None:
        config = run_demo.parse_args(["--run-id", "demo-default", "--no-open-browser"])

        with tempfile.TemporaryDirectory() as tmp_dir_name:
            logs_root = Path(tmp_dir_name)
            spawned: list[tuple[list[str], FakeProcess]] = []

            def fake_spawn(command: list[str], *, env: dict[str, str], stdout_path: Path, stderr_path: Path) -> FakeProcess:
                joined = " ".join(command)
                if "replay_publisher.py" in joined:
                    process = FakeProcess(name="simulator", complete_on_wait=True)
                elif command[0] == "node":
                    process = FakeProcess(name="capture", complete_on_wait=True)
                else:
                    process = FakeProcess(name="service", complete_on_wait=False)
                spawned.append((command, process))
                return process

            with (
                patch.object(run_demo, "LOGS_ROOT", logs_root),
                patch("experiments.run_demo._find_python", return_value="python"),
                patch("experiments.run_demo._wait_for_http"),
                patch("experiments.run_demo._fetch_json", return_value={"ok": True}),
                patch("experiments.run_demo._copy_if_exists"),
                patch("experiments.run_demo._spawn", side_effect=fake_spawn),
                patch("experiments.run_demo.time.sleep"),
                patch("experiments.run_demo.ensure_browser_capture_prerequisites") as capture_preflight,
                patch("experiments.run_demo.webbrowser.open") as browser_open,
                patch("builtins.print") as mocked_print,
            ):
                run_dir = run_demo.run_demo(config)

            manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["capture_artifacts"])
            self.assertFalse(manifest["auto_ports"])
            self.assertEqual(len(spawned), 5)
            self.assertFalse(any(command[0] == "node" for command, _ in spawned))
            capture_preflight.assert_not_called()
            browser_open.assert_not_called()
            mocked_print.assert_not_called()

            service_processes = [process for _, process in spawned if process.name == "service"]
            self.assertTrue(service_processes)
            self.assertTrue(all(process.terminated for process in service_processes))

    def test_run_demo_capture_artifacts_starts_dashboard_and_compare_capture(self) -> None:
        config = run_demo.parse_args(["--run-id", "demo-capture", "--no-open-browser", "--capture-artifacts"])

        with tempfile.TemporaryDirectory() as tmp_dir_name:
            logs_root = Path(tmp_dir_name)
            spawned: list[tuple[list[str], FakeProcess]] = []

            def fake_spawn(command: list[str], *, env: dict[str, str], stdout_path: Path, stderr_path: Path) -> FakeProcess:
                joined = " ".join(command)
                if "replay_publisher.py" in joined:
                    process = FakeProcess(name="simulator", complete_on_wait=True)
                elif command[0] == "node":
                    process = FakeProcess(name="capture", complete_on_wait=True)
                else:
                    process = FakeProcess(name="service", complete_on_wait=False)
                spawned.append((command, process))
                return process

            with (
                patch.object(run_demo, "LOGS_ROOT", logs_root),
                patch("experiments.run_demo._find_python", return_value="python"),
                patch("experiments.run_demo._wait_for_http"),
                patch("experiments.run_demo._fetch_json", return_value={"ok": True}),
                patch("experiments.run_demo._copy_if_exists"),
                patch("experiments.run_demo._spawn", side_effect=fake_spawn),
                patch("experiments.run_demo.time.sleep"),
                patch("experiments.run_demo.ensure_browser_capture_prerequisites") as capture_preflight,
                patch("experiments.run_demo.webbrowser.open"),
            ):
                run_dir = run_demo.run_demo(config)

            manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            capture_preflight.assert_called_once()
            self.assertTrue(manifest["capture_artifacts"])
            self.assertEqual(manifest["artifact_paths"]["compare_screenshot"], str(run_dir / "demo_compare.png"))
            self.assertTrue((run_dir / "baseline_dashboard").exists())
            self.assertTrue((run_dir / "smart_dashboard").exists())

            capture_commands = [command for command, process in spawned if process.name == "capture"]
            self.assertEqual(len(capture_commands), 3)
            self.assertTrue(any("--output-dir" in command and "baseline_dashboard" in " ".join(command) for command in capture_commands))
            self.assertTrue(any("--output-dir" in command and "smart_dashboard" in " ".join(command) for command in capture_commands))
            self.assertTrue(any("--screenshot-only" in command and "demo_compare.png" in " ".join(command) for command in capture_commands))

    def test_run_demo_cleans_up_when_capture_process_fails(self) -> None:
        config = run_demo.parse_args(["--run-id", "demo-failure", "--no-open-browser", "--capture-artifacts"])

        with tempfile.TemporaryDirectory() as tmp_dir_name:
            logs_root = Path(tmp_dir_name)
            spawned: list[tuple[list[str], FakeProcess]] = []
            capture_index = 0

            def fake_spawn(command: list[str], *, env: dict[str, str], stdout_path: Path, stderr_path: Path) -> FakeProcess:
                nonlocal capture_index
                joined = " ".join(command)
                if "replay_publisher.py" in joined:
                    process = FakeProcess(name="simulator", complete_on_wait=True)
                elif command[0] == "node":
                    capture_index += 1
                    exit_code = 1 if capture_index == 1 else 0
                    process = FakeProcess(name="capture", complete_on_wait=True, exit_code=exit_code)
                else:
                    process = FakeProcess(name="service", complete_on_wait=False)
                spawned.append((command, process))
                return process

            with (
                patch.object(run_demo, "LOGS_ROOT", logs_root),
                patch("experiments.run_demo._find_python", return_value="python"),
                patch("experiments.run_demo._wait_for_http"),
                patch("experiments.run_demo._fetch_json", return_value={"ok": True}),
                patch("experiments.run_demo._copy_if_exists"),
                patch("experiments.run_demo._spawn", side_effect=fake_spawn),
                patch("experiments.run_demo.time.sleep"),
                patch("experiments.run_demo.ensure_browser_capture_prerequisites"),
                patch("experiments.run_demo.webbrowser.open"),
            ):
                with self.assertRaisesRegex(RuntimeError, "baseline dashboard capture failed"):
                    run_demo.run_demo(config)

            service_processes = [process for _, process in spawned if process.name == "service"]
            self.assertTrue(service_processes)
            self.assertTrue(all(process.terminated for process in service_processes))

    def test_main_prints_compare_url_after_helper_returns(self) -> None:
        config = run_demo.parse_args(["--run-id", "demo-main", "--no-open-browser"])
        run_dir = Path("demo-run")

        with (
            patch("experiments.run_demo.parse_args", return_value=config),
            patch("experiments.run_demo.validate_environment") as validate_environment,
            patch("experiments.run_demo.run_demo", return_value=run_dir) as run_demo_call,
            patch("builtins.print") as mocked_print,
        ):
            run_demo.main()

        validate_environment.assert_called_once_with(config)
        run_demo_call.assert_called_once_with(config)
        mocked_print.assert_any_call(f"Demo compare page: {run_demo.build_compare_url(config)}")


if __name__ == "__main__":
    unittest.main()
