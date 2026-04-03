from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class _SilentStaticHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


class PlaywrightCaptureTests(unittest.TestCase):
    def test_capture_dashboard_check_only_succeeds_when_playwright_is_ready(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("Node.js is required for Playwright capture tests")

        result = subprocess.run(
            ["node", "experiments/capture_dashboard.mjs", "--check-only"],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            self.skipTest(f"Playwright runtime unavailable: {result.stderr.strip()}")

        self.assertIn("Playwright and Chromium are available.", result.stdout)

    def test_capture_dashboard_check_only_reports_missing_browser_cleanly(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("Node.js is required for Playwright capture tests")

        empty_browser_dir = Path(tempfile.mkdtemp())
        env = dict(**os.environ)
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(empty_browser_dir)
        result = subprocess.run(
            ["node", "experiments/capture_dashboard.mjs", "--check-only"],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            env=env,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Playwright Chromium browser is not installed.", result.stderr)

    def test_capture_dashboard_script_exports_csv_and_summary(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("Node.js is required for Playwright capture tests")

        fixture_dir = Path("tests/fixtures/m4").resolve()
        output_dir = Path(tempfile.mkdtemp())
        server = ThreadingHTTPServer(("127.0.0.1", 0), lambda *args, **kwargs: _SilentStaticHandler(*args, directory=str(fixture_dir), **kwargs))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        url = f"http://127.0.0.1:{server.server_port}/playwright_fixture.html"
        result = subprocess.run(
            [
                "node",
                "experiments/capture_dashboard.mjs",
                "--url",
                url,
                "--output-dir",
                str(output_dir),
                "--capture-ms",
                "10",
            ],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self.skipTest(f"Playwright runtime unavailable: {result.stderr.strip()}")

        self.assertTrue((output_dir / "dashboard_measurements.csv").exists())
        self.assertTrue((output_dir / "dashboard_summary.json").exists())
        self.assertTrue((output_dir / "dashboard.png").exists())
        summary = json.loads((output_dir / "dashboard_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["summary"]["messageCount"], 2)


if __name__ == "__main__":
    unittest.main()
