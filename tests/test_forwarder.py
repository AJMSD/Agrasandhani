from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from gateway.forwarder import BaselineForwarder, CsvRunLogger
from gateway.mqtt_ingest import MqttEnvelope


class DummyWebSocket:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def accept(self) -> None:
        return None

    async def send_text(self, payload: str) -> None:
        self.messages.append(payload)

    async def close(self) -> None:
        return None


class BaselineForwarderTests(unittest.IsolatedAsyncioTestCase):
    async def test_forwarder_tracks_metrics_and_latest_snapshot(self) -> None:
        inbound_queue: asyncio.Queue[MqttEnvelope] = asyncio.Queue()
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "gateway_forward_log.csv"
            run_logger = CsvRunLogger(log_path)
            forwarder = BaselineForwarder(inbound_queue=inbound_queue, run_logger=run_logger)
            websocket = DummyWebSocket()
            await forwarder.register_client(websocket)

            task = asyncio.create_task(forwarder.run_forever())
            payload = b'{"sensor_id":101,"msg_id":1,"ts_sent":1700000000123,"metric_type":"temperature","value":21.5}'
            await inbound_queue.put(
                MqttEnvelope(
                    topic="sensors/raw/temperature",
                    payload=payload,
                    received_at_ms=1_700_000_000_200,
                )
            )
            await asyncio.wait_for(inbound_queue.join(), timeout=1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

            snapshot = forwarder.latest_snapshot
            self.assertIn(("101", "temperature"), snapshot)
            self.assertEqual(len(websocket.messages), 1)

            metrics = forwarder.metrics_snapshot(started_at_monotonic=0.0)
            self.assertEqual(metrics["mqtt_in_msgs"], 1)
            self.assertEqual(metrics["ws_out_msgs"], 1)
            self.assertGreater(metrics["ws_out_bytes"], 0)
            self.assertEqual(metrics["latest_sensor_count"], 1)

            log_rows = log_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(log_rows), 2)
            run_logger.close()


if __name__ == "__main__":
    unittest.main()
