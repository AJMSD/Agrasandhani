from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import uvicorn
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from experiments import impairment_proxy


def _pick_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _ConfigHandler(BaseHTTPRequestHandler):
    config_payload = {"mode": "v4", "freshness_ttl_ms": 1000, "effective_batch_window_ms": 250}

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/config":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(self.config_payload).encode("utf-8"))

    def do_PATCH(self) -> None:  # noqa: N802
        body = self.rfile.read(int(self.headers["Content-Length"]))
        payload = json.loads(body.decode("utf-8"))
        self.config_payload = self.config_payload | payload
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(self.config_payload).encode("utf-8"))

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


class ImpairmentProxyIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_proxy_relays_ws_and_proxies_config(self) -> None:
        loop = asyncio.get_running_loop()
        original_debug = loop.get_debug()
        original_slow_callback_duration = loop.slow_callback_duration
        loop.set_debug(False)
        loop.slow_callback_duration = 60.0
        self.addAsyncCleanup(self._restore_loop_debug_settings, loop, original_debug, original_slow_callback_duration)

        http_port = _pick_free_port()
        ws_port = _pick_free_port()
        proxy_port = _pick_free_port()

        http_server = ThreadingHTTPServer(("127.0.0.1", http_port), _ConfigHandler)
        http_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
        http_thread.start()
        self.addCleanup(http_thread.join, 2)
        self.addCleanup(http_server.server_close)
        self.addCleanup(http_server.shutdown)

        async def upstream_handler(websocket) -> None:
            await websocket.send(json.dumps({"sensor_id": 101, "msg_id": 1, "ts_sent": 1000, "metric_type": "temperature", "value": 21.0}))
            await websocket.send(
                json.dumps(
                    {
                        "kind": "aggregate_frame",
                        "frame_id": 2,
                        "mode": "v4",
                        "flush_reason": "time",
                        "window_started_ms": 1000,
                        "window_closed_ms": 1100,
                        "update_count": 1,
                        "updates": [{"sensor_id": 101, "msg_id": 2, "ts_sent": 1050, "metric_type": "temperature", "value": 22.0}],
                    }
                )
            )
            await asyncio.sleep(0.1)

        with tempfile.TemporaryDirectory() as tmp_dir_name:
            scenario_path = Path(tmp_dir_name) / "clean.json"
            scenario_path.write_text(
                json.dumps({"version": 1, "name": "clean", "phases": [{"name": "clean", "duration_s": 5}]}),
                encoding="utf-8",
            )
            frame_log_path = Path(tmp_dir_name) / "proxy_frame_log.csv"
            settings = impairment_proxy.ProxySettings(
                impair_host="127.0.0.1",
                impair_port=proxy_port,
                upstream_ws_url=f"ws://127.0.0.1:{ws_port}/ws",
                upstream_http_base=f"http://127.0.0.1:{http_port}",
                scenario_file=scenario_path,
                random_seed=10,
                run_id="proxy-test",
                frame_log_path=frame_log_path,
            )
            app = impairment_proxy.create_app(settings)

            async with serve(upstream_handler, "127.0.0.1", ws_port):
                config = uvicorn.Config(app, host="127.0.0.1", port=proxy_port, log_level="warning", ws="websockets-sansio")
                server = uvicorn.Server(config)
                server_task = asyncio.create_task(server.serve())
                try:
                    await self._wait_for_http(f"http://127.0.0.1:{proxy_port}/health")

                    config_payload = await asyncio.to_thread(self._fetch_json, f"http://127.0.0.1:{proxy_port}/config")
                    self.assertEqual(config_payload["mode"], "v4")

                    patched_payload = await asyncio.to_thread(
                        self._patch_json,
                        f"http://127.0.0.1:{proxy_port}/config",
                        {"freshness_ttl_ms": 1200},
                    )
                    self.assertEqual(patched_payload["freshness_ttl_ms"], 1200)

                    html = await asyncio.to_thread(self._fetch_text, f"http://127.0.0.1:{proxy_port}/ui/index.html")
                    self.assertIn("Agrasandhani Dashboard", html)

                    compare_html = await asyncio.to_thread(
                        self._fetch_text,
                        f"http://127.0.0.1:{proxy_port}/ui/demo_compare.html",
                    )
                    self.assertIn("Agrasandhani Demo Compare", compare_html)

                    async with connect(f"ws://127.0.0.1:{proxy_port}/ws", max_size=None) as client:
                        first = json.loads(await asyncio.wait_for(client.recv(), timeout=5))
                        second = json.loads(await asyncio.wait_for(client.recv(), timeout=5))

                    self.assertEqual(first["msg_id"], 1)
                    self.assertEqual(second["kind"], "aggregate_frame")

                    metrics = await asyncio.to_thread(self._fetch_json, f"http://127.0.0.1:{proxy_port}/metrics")
                    self.assertEqual(metrics["upstream_frames_in"], 2)
                    self.assertEqual(metrics["downstream_frames_out"], 2)
                    self.assertTrue(frame_log_path.exists())
                finally:
                    server.should_exit = True
                    await asyncio.wait_for(server_task, timeout=10)

    async def _wait_for_http(self, url: str) -> None:
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                await asyncio.to_thread(self._fetch_text, url)
                return
            except Exception:
                await asyncio.sleep(0.2)
        self.fail(f"Timed out waiting for {url}")

    @staticmethod
    def _fetch_json(url: str) -> dict[str, object]:
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.load(response)

    @staticmethod
    def _fetch_text(url: str) -> str:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.read().decode("utf-8")

    @staticmethod
    def _patch_json(url: str, payload: dict[str, object]) -> dict[str, object]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="PATCH",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.load(response)

    @staticmethod
    async def _restore_loop_debug_settings(
        loop: asyncio.AbstractEventLoop,
        original_debug: bool,
        original_slow_callback_duration: float,
    ) -> None:
        loop.set_debug(original_debug)
        loop.slow_callback_duration = original_slow_callback_duration


if __name__ == "__main__":
    unittest.main()
