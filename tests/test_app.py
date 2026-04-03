from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException

from gateway import app as gateway_app
from gateway.forwarder import BaselineForwarder, CsvRunLogger, ForwarderConfig


class AppEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_config_returns_runtime_snapshot(self) -> None:
        forwarder, run_logger = self._build_forwarder(
            ForwarderConfig(mode="v4", batch_window_ms=250, batch_max_messages=50, freshness_ttl_ms=1_000)
        )
        self._install_services(forwarder)
        self.addCleanup(run_logger.close)

        payload = await gateway_app.get_config()

        self.assertEqual(payload["mode"], "v4")
        self.assertEqual(payload["batch_window_ms"], 250)
        self.assertEqual(payload["freshness_ttl_ms"], 1_000)
        self.assertEqual(payload["effective_batch_window_ms"], 250)

    async def test_patch_config_updates_forwarder_state(self) -> None:
        forwarder, run_logger = self._build_forwarder(
            ForwarderConfig(mode="v4", batch_window_ms=250, batch_max_messages=50, freshness_ttl_ms=1_000)
        )
        self._install_services(forwarder)
        self.addCleanup(run_logger.close)

        payload = await gateway_app.patch_config(
            gateway_app.RuntimeConfigUpdate(
                batch_window_ms=300,
                freshness_ttl_ms=1_500,
                adaptive_max_batch_window_ms=1_500,
            )
        )

        self.assertEqual(payload["batch_window_ms"], 300)
        self.assertEqual(payload["freshness_ttl_ms"], 1_500)
        self.assertEqual(payload["adaptive_max_batch_window_ms"], 1_500)
        self.assertEqual(payload["effective_batch_window_ms"], 300)

    async def test_patch_config_rejects_mode_change(self) -> None:
        forwarder, run_logger = self._build_forwarder(ForwarderConfig(mode="v3", batch_window_ms=250, batch_max_messages=50))
        self._install_services(forwarder)
        self.addCleanup(run_logger.close)

        with self.assertRaises(HTTPException) as ctx:
            await gateway_app.patch_config(gateway_app.RuntimeConfigUpdate(mode="v4"))

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("startup-only", str(ctx.exception.detail))

    async def test_metrics_expose_adaptive_and_freshness_fields(self) -> None:
        forwarder, run_logger = self._build_forwarder(
            ForwarderConfig(mode="v4", batch_window_ms=250, batch_max_messages=50, freshness_ttl_ms=1_000)
        )
        self._install_services(forwarder)
        self.addCleanup(run_logger.close)

        payload = await gateway_app.metrics()

        self.assertEqual(payload["gateway_mode"], "v4")
        self.assertIn("effective_batch_window_ms", payload)
        self.assertIn("adaptive_enabled", payload)
        self.assertIn("stale_sensor_count", payload)

    def _build_forwarder(self, config: ForwarderConfig) -> tuple[BaselineForwarder, CsvRunLogger]:
        inbound_queue: asyncio.Queue = asyncio.Queue()
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        log_path = Path(tmp_dir.name) / "gateway_forward_log.csv"
        run_logger = CsvRunLogger(log_path)
        return BaselineForwarder(inbound_queue=inbound_queue, run_logger=run_logger, config=config), run_logger

    def _install_services(self, forwarder: BaselineForwarder) -> None:
        previous = getattr(gateway_app.app.state, "services", None)

        def restore() -> None:
            if previous is None and hasattr(gateway_app.app.state, "services"):
                delattr(gateway_app.app.state, "services")
                return
            gateway_app.app.state.services = previous

        self.addCleanup(restore)
        gateway_app.app.state.services = SimpleNamespace(
            started_at_monotonic=0.0,
            forwarder=forwarder,
            mqtt_ingestor=SimpleNamespace(is_connected=True),
        )


if __name__ == "__main__":
    unittest.main()
