from __future__ import annotations

import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path

from gateway.forwarder import BaselineForwarder, CsvRunLogger, ForwarderConfig
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


def make_envelope(
    *,
    sensor_id: str | int = 101,
    msg_id: int = 1,
    ts_sent: int = 1_700_000_000_123,
    metric_type: str = "temperature",
    value: float = 21.5,
    received_at_ms: int = 1_700_000_000_200,
    raw_payload: bytes | None = None,
) -> MqttEnvelope:
    payload = raw_payload or json.dumps(
        {
            "sensor_id": sensor_id,
            "msg_id": msg_id,
            "ts_sent": ts_sent,
            "metric_type": metric_type,
            "value": value,
        }
    ).encode("utf-8")
    return MqttEnvelope(topic=f"sensors/raw/{metric_type}", payload=payload, received_at_ms=received_at_ms)


class ForwarderTests(unittest.IsolatedAsyncioTestCase):
    async def test_v0_forwarder_tracks_metrics_and_latest_snapshot(self) -> None:
        forwarder, inbound_queue, websocket, log_path, run_logger = await self._build_forwarder()

        task = asyncio.create_task(forwarder.run_forever())
        await inbound_queue.put(make_envelope())
        await asyncio.wait_for(inbound_queue.join(), timeout=1)
        await self._stop_task(task)

        snapshot = forwarder.latest_snapshot
        self.assertIn(("101", "temperature"), snapshot)
        self.assertEqual(len(websocket.messages), 1)
        self.assertEqual(json.loads(websocket.messages[0])["msg_id"], 1)

        metrics = forwarder.metrics_snapshot(started_at_monotonic=0.0)
        self.assertEqual(metrics["gateway_mode"], "v0")
        self.assertEqual(metrics["mqtt_in_msgs"], 1)
        self.assertEqual(metrics["ws_out_msgs"], 1)
        self.assertEqual(metrics["ws_out_frames"], 1)
        self.assertEqual(metrics["latest_sensor_count"], 1)

        log_rows = log_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(log_rows), 2)
        run_logger.close()

    async def test_v1_flushes_batch_on_threshold(self) -> None:
        forwarder, inbound_queue, websocket, _, run_logger = await self._build_forwarder(
            config=ForwarderConfig(mode="v1", batch_window_ms=1_000, batch_max_messages=2)
        )

        task = asyncio.create_task(forwarder.run_forever())
        await inbound_queue.put(make_envelope(msg_id=1, metric_type="temperature", value=21.1))
        await inbound_queue.put(make_envelope(msg_id=2, metric_type="humidity", value=50.0, received_at_ms=1_700_000_000_220))
        await asyncio.wait_for(inbound_queue.join(), timeout=1)
        await self._stop_task(task)

        self.assertEqual(len(websocket.messages), 1)
        frame = json.loads(websocket.messages[0])
        self.assertEqual(frame["kind"], "aggregate_frame")
        self.assertEqual(frame["mode"], "v1")
        self.assertEqual(frame["flush_reason"], "threshold")
        self.assertEqual(frame["update_count"], 2)

        metrics = forwarder.metrics_snapshot(started_at_monotonic=0.0)
        self.assertEqual(metrics["ws_out_msgs"], 2)
        self.assertEqual(metrics["ws_out_frames"], 1)
        self.assertEqual(metrics["batch_flushes"], 1)
        run_logger.close()

    async def test_v1_flushes_batch_on_timer(self) -> None:
        forwarder, inbound_queue, websocket, _, run_logger = await self._build_forwarder(
            config=ForwarderConfig(mode="v1", batch_window_ms=20, batch_max_messages=5)
        )

        task = asyncio.create_task(forwarder.run_forever())
        await inbound_queue.put(make_envelope(msg_id=1))
        await asyncio.wait_for(inbound_queue.join(), timeout=1)
        await asyncio.wait_for(self._wait_for_messages(websocket, expected=1), timeout=1)
        await self._stop_task(task)

        frame = json.loads(websocket.messages[0])
        self.assertEqual(frame["flush_reason"], "time")
        self.assertEqual(frame["update_count"], 1)
        run_logger.close()

    async def test_v2_suppresses_exact_duplicates(self) -> None:
        forwarder, inbound_queue, websocket, _, run_logger = await self._build_forwarder(
            config=ForwarderConfig(mode="v2", batch_window_ms=1_000, batch_max_messages=5, duplicate_ttl_ms=1_000)
        )

        task = asyncio.create_task(forwarder.run_forever())
        await inbound_queue.put(make_envelope(msg_id=8, value=22.0))
        await asyncio.wait_for(inbound_queue.join(), timeout=1)
        await forwarder._flush_pending(flush_reason="threshold")

        await inbound_queue.put(make_envelope(msg_id=8, value=22.0, received_at_ms=1_700_000_000_205))
        await inbound_queue.put(
            make_envelope(
                msg_id=9,
                metric_type="humidity",
                value=55.0,
                received_at_ms=1_700_000_000_210,
            )
        )
        await asyncio.wait_for(inbound_queue.join(), timeout=1)
        await forwarder._flush_pending(flush_reason="threshold")
        await self._stop_task(task)

        self.assertEqual(len(websocket.messages), 2)
        frame = json.loads(websocket.messages[1])
        self.assertEqual(frame["mode"], "v2")
        self.assertEqual(frame["update_count"], 1)
        self.assertEqual([update["msg_id"] for update in frame["updates"]], [9])

        metrics = forwarder.metrics_snapshot(started_at_monotonic=0.0)
        self.assertEqual(metrics["duplicates_dropped"], 1)
        run_logger.close()

    async def test_v2_allows_same_duplicate_key_after_ttl_expiry(self) -> None:
        forwarder, inbound_queue, websocket, _, run_logger = await self._build_forwarder(
            config=ForwarderConfig(mode="v2", batch_window_ms=1_000, batch_max_messages=5, duplicate_ttl_ms=10)
        )

        task = asyncio.create_task(forwarder.run_forever())
        await inbound_queue.put(make_envelope(msg_id=8, value=22.0))
        await asyncio.wait_for(inbound_queue.join(), timeout=1)
        await forwarder._flush_pending(flush_reason="threshold")

        await asyncio.sleep(0.03)

        await inbound_queue.put(make_envelope(msg_id=8, value=22.0, received_at_ms=1_700_000_000_205))
        await asyncio.wait_for(inbound_queue.join(), timeout=1)
        await forwarder._flush_pending(flush_reason="threshold")
        await self._stop_task(task)

        self.assertEqual(len(websocket.messages), 2)
        second_frame = json.loads(websocket.messages[1])
        self.assertEqual(second_frame["update_count"], 1)
        self.assertEqual(second_frame["updates"][0]["msg_id"], 8)

        metrics = forwarder.metrics_snapshot(started_at_monotonic=0.0)
        self.assertEqual(metrics["duplicates_dropped"], 0)
        self.assertEqual(metrics["dedup_cache_size"], 1)
        self.assertGreaterEqual(metrics["dedup_cache_evictions"], 1)
        run_logger.close()

    async def test_v2_compacts_to_latest_per_sensor_metric(self) -> None:
        forwarder, inbound_queue, websocket, _, run_logger = await self._build_forwarder(
            config=ForwarderConfig(mode="v2", batch_window_ms=1_000, batch_max_messages=5)
        )

        task = asyncio.create_task(forwarder.run_forever())
        await inbound_queue.put(make_envelope(msg_id=1, ts_sent=1_700_000_000_100, value=21.0))
        await inbound_queue.put(make_envelope(msg_id=2, ts_sent=1_700_000_000_300, value=23.0, received_at_ms=1_700_000_000_230))
        await inbound_queue.put(make_envelope(msg_id=3, metric_type="humidity", value=49.0, received_at_ms=1_700_000_000_240))
        await asyncio.wait_for(inbound_queue.join(), timeout=1)
        await forwarder._flush_pending(flush_reason="threshold")
        await self._stop_task(task)

        frame = json.loads(websocket.messages[0])
        self.assertEqual(frame["update_count"], 2)
        updates = {(item["metric_type"], item["msg_id"]): item for item in frame["updates"]}
        self.assertIn(("temperature", 2), updates)
        self.assertIn(("humidity", 3), updates)

        metrics = forwarder.metrics_snapshot(started_at_monotonic=0.0)
        self.assertEqual(metrics["compacted_dropped"], 1)
        run_logger.close()

    async def test_v2_value_dedup_suppresses_unchanged_emissions(self) -> None:
        forwarder, inbound_queue, websocket, _, run_logger = await self._build_forwarder(
            config=ForwarderConfig(mode="v2", batch_window_ms=1_000, batch_max_messages=5, value_dedup_enabled=True)
        )

        task = asyncio.create_task(forwarder.run_forever())
        await inbound_queue.put(make_envelope(msg_id=1, value=21.0))
        await asyncio.wait_for(inbound_queue.join(), timeout=1)
        await forwarder._flush_pending(flush_reason="threshold")

        await inbound_queue.put(make_envelope(msg_id=2, value=21.0, received_at_ms=1_700_000_000_240))
        await asyncio.wait_for(inbound_queue.join(), timeout=1)
        await forwarder._flush_pending(flush_reason="threshold")
        await self._stop_task(task)

        self.assertEqual(len(websocket.messages), 1)
        metrics = forwarder.metrics_snapshot(started_at_monotonic=0.0)
        self.assertEqual(metrics["value_dedup_dropped"], 1)
        run_logger.close()

    async def test_v3_adapts_batch_window_up_on_backlog(self) -> None:
        forwarder, inbound_queue, websocket, _, run_logger = await self._build_forwarder(
            config=ForwarderConfig(
                mode="v3",
                batch_window_ms=100,
                batch_max_messages=1,
                adaptive_min_batch_window_ms=100,
                adaptive_max_batch_window_ms=300,
                adaptive_step_up_ms=50,
                adaptive_step_down_ms=50,
                adaptive_queue_high_watermark=1,
                adaptive_queue_low_watermark=0,
                adaptive_send_slow_ms=1_000,
                adaptive_recovery_streak=2,
            )
        )

        task = asyncio.create_task(forwarder.run_forever())
        await inbound_queue.put(make_envelope(msg_id=1, value=21.0))
        await inbound_queue.put(make_envelope(msg_id=2, value=22.0, received_at_ms=1_700_000_000_240))
        await asyncio.wait_for(inbound_queue.join(), timeout=1)
        await self._wait_for_messages(websocket, expected=2)
        await self._stop_task(task)

        metrics = forwarder.metrics_snapshot(started_at_monotonic=0.0)
        self.assertEqual(metrics["gateway_mode"], "v3")
        self.assertEqual(metrics["adaptive_window_increase_events"], 1)
        self.assertEqual(metrics["effective_batch_window_ms"], 150)
        self.assertTrue(str(metrics["last_adaptation_reason"]).startswith("healthy_streak="))
        run_logger.close()

    async def test_v3_recovers_batch_window_after_healthy_flush(self) -> None:
        forwarder, inbound_queue, websocket, _, run_logger = await self._build_forwarder(
            config=ForwarderConfig(
                mode="v3",
                batch_window_ms=100,
                batch_max_messages=1,
                adaptive_min_batch_window_ms=100,
                adaptive_max_batch_window_ms=300,
                adaptive_step_up_ms=50,
                adaptive_step_down_ms=50,
                adaptive_queue_high_watermark=1,
                adaptive_queue_low_watermark=0,
                adaptive_send_slow_ms=1_000,
                adaptive_recovery_streak=1,
            )
        )

        task = asyncio.create_task(forwarder.run_forever())
        await inbound_queue.put(make_envelope(msg_id=1, value=21.0))
        await inbound_queue.put(make_envelope(msg_id=2, value=22.0, received_at_ms=1_700_000_000_240))
        await asyncio.wait_for(inbound_queue.join(), timeout=1)
        await inbound_queue.put(make_envelope(msg_id=3, value=23.0, received_at_ms=1_700_000_000_260))
        await asyncio.wait_for(inbound_queue.join(), timeout=1)
        await self._wait_for_messages(websocket, expected=3)
        await self._stop_task(task)

        metrics = forwarder.metrics_snapshot(started_at_monotonic=0.0)
        self.assertEqual(metrics["adaptive_window_increase_events"], 1)
        self.assertEqual(metrics["adaptive_window_decrease_events"], 1)
        self.assertEqual(metrics["effective_batch_window_ms"], 100)
        run_logger.close()

    async def test_v4_register_client_receives_snapshot_frame(self) -> None:
        forwarder, inbound_queue, websocket, _, run_logger = await self._build_forwarder(
            config=ForwarderConfig(mode="v4", batch_window_ms=100, batch_max_messages=1)
        )

        task = asyncio.create_task(forwarder.run_forever())
        await inbound_queue.put(make_envelope(msg_id=1, value=21.0))
        await asyncio.wait_for(inbound_queue.join(), timeout=1)
        await self._wait_for_messages(websocket, expected=1)

        reconnecting_websocket = DummyWebSocket()
        await forwarder.register_client(reconnecting_websocket)
        await self._stop_task(task)

        self.assertEqual(len(reconnecting_websocket.messages), 1)
        snapshot_frame = json.loads(reconnecting_websocket.messages[0])
        self.assertEqual(snapshot_frame["flush_reason"], "snapshot")
        self.assertEqual(snapshot_frame["mode"], "v4")
        self.assertEqual(snapshot_frame["update_count"], 1)
        self.assertEqual(snapshot_frame["updates"][0]["msg_id"], 1)
        run_logger.close()

    async def test_v4_same_value_update_refreshes_ttl_even_with_value_dedup(self) -> None:
        forwarder, inbound_queue, websocket, _, run_logger = await self._build_forwarder(
            config=ForwarderConfig(mode="v4", batch_window_ms=100, batch_max_messages=1, value_dedup_enabled=True)
        )

        task = asyncio.create_task(forwarder.run_forever())
        await inbound_queue.put(make_envelope(msg_id=1, ts_sent=1_700_000_000_100, value=21.0))
        await asyncio.wait_for(inbound_queue.join(), timeout=1)
        await inbound_queue.put(
            make_envelope(
                msg_id=2,
                ts_sent=1_700_000_000_300,
                value=21.0,
                received_at_ms=1_700_000_000_240,
            )
        )
        await asyncio.wait_for(inbound_queue.join(), timeout=1)
        await self._wait_for_messages(websocket, expected=2)
        await self._stop_task(task)

        second_frame = json.loads(websocket.messages[1])
        self.assertEqual(second_frame["update_count"], 1)
        self.assertEqual(second_frame["updates"][0]["msg_id"], 2)
        self.assertEqual(forwarder.latest_snapshot[("101", "temperature")].ts_sent, 1_700_000_000_300)

        metrics = forwarder.metrics_snapshot(started_at_monotonic=0.0)
        self.assertEqual(metrics["value_dedup_dropped"], 0)
        run_logger.close()

    async def test_invalid_payload_does_not_break_pending_batch(self) -> None:
        forwarder, inbound_queue, websocket, _, run_logger = await self._build_forwarder(
            config=ForwarderConfig(mode="v1", batch_window_ms=1_000, batch_max_messages=5)
        )

        task = asyncio.create_task(forwarder.run_forever())
        with self.assertLogs("gateway.forwarder", level="WARNING") as captured_logs:
            await inbound_queue.put(make_envelope(msg_id=1, value=21.0))
            await inbound_queue.put(make_envelope(raw_payload=b'{"sensor_id":101,"msg_id":2}', metric_type="temperature"))
            await inbound_queue.put(make_envelope(msg_id=3, metric_type="humidity", value=48.0, received_at_ms=1_700_000_000_250))
            await asyncio.wait_for(inbound_queue.join(), timeout=1)
            await forwarder._flush_pending(flush_reason="threshold")
            await self._stop_task(task)

        frame = json.loads(websocket.messages[0])
        self.assertEqual(frame["update_count"], 2)
        metrics = forwarder.metrics_snapshot(started_at_monotonic=0.0)
        self.assertEqual(metrics["invalid_msgs"], 1)
        self.assertEqual(len(captured_logs.output), 1)
        self.assertIn("Dropped invalid MQTT payload", captured_logs.output[0])
        self.assertNotIn("Traceback", captured_logs.output[0])
        run_logger.close()

    async def test_runtime_config_update_applies_safe_fields(self) -> None:
        forwarder, _, _, _, run_logger = await self._build_forwarder(
            config=ForwarderConfig(
                mode="v4",
                batch_window_ms=200,
                batch_max_messages=5,
                duplicate_ttl_ms=30_000,
                freshness_ttl_ms=1_000,
            )
        )

        snapshot = forwarder.update_runtime_config(
            {
                "batch_window_ms": 300,
                "duplicate_ttl_ms": 5_000,
                "freshness_ttl_ms": 1_500,
                "adaptive_max_batch_window_ms": 1_500,
            }
        )

        self.assertEqual(snapshot["mode"], "v4")
        self.assertEqual(snapshot["batch_window_ms"], 300)
        self.assertEqual(snapshot["duplicate_ttl_ms"], 5_000)
        self.assertEqual(snapshot["freshness_ttl_ms"], 1_500)
        self.assertEqual(snapshot["effective_batch_window_ms"], 300)
        self.assertEqual(snapshot["adaptive_max_batch_window_ms"], 1_500)
        run_logger.close()

    async def test_runtime_config_update_rejects_mode_change(self) -> None:
        forwarder, _, _, _, run_logger = await self._build_forwarder(
            config=ForwarderConfig(mode="v3", batch_window_ms=200, batch_max_messages=5)
        )

        with self.assertRaisesRegex(ValueError, "startup-only"):
            forwarder.update_runtime_config({"mode": "v4"})

        run_logger.close()

    async def test_metrics_report_stale_sensor_count_with_ttl(self) -> None:
        forwarder, inbound_queue, websocket, _, run_logger = await self._build_forwarder(
            config=ForwarderConfig(mode="v4", batch_window_ms=100, batch_max_messages=1, freshness_ttl_ms=100)
        )

        task = asyncio.create_task(forwarder.run_forever())
        stale_ts = int(time.time_ns() // 1_000_000) - 5_000
        await inbound_queue.put(make_envelope(msg_id=1, ts_sent=stale_ts, value=21.0))
        await asyncio.wait_for(inbound_queue.join(), timeout=1)
        await self._wait_for_messages(websocket, expected=1)
        await self._stop_task(task)

        metrics = forwarder.metrics_snapshot(started_at_monotonic=0.0)
        self.assertEqual(metrics["stale_sensor_count"], 1)
        self.assertEqual(metrics["freshness_ttl_ms"], 100)
        run_logger.close()

    async def _build_forwarder(
        self,
        *,
        config: ForwarderConfig | None = None,
    ) -> tuple[BaselineForwarder, asyncio.Queue[MqttEnvelope], DummyWebSocket, Path, CsvRunLogger]:
        inbound_queue: asyncio.Queue[MqttEnvelope] = asyncio.Queue()
        tmp_dir = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(asyncio.to_thread, tmp_dir.cleanup)
        log_path = Path(tmp_dir.name) / "gateway_forward_log.csv"
        run_logger = CsvRunLogger(log_path)
        self.addCleanup(run_logger.close)
        forwarder = BaselineForwarder(inbound_queue=inbound_queue, run_logger=run_logger, config=config)
        websocket = DummyWebSocket()
        await forwarder.register_client(websocket)
        return forwarder, inbound_queue, websocket, log_path, run_logger

    async def _wait_for_messages(self, websocket: DummyWebSocket, *, expected: int) -> None:
        while len(websocket.messages) < expected:
            await asyncio.sleep(0.01)

    async def _stop_task(self, task: asyncio.Task[None]) -> None:
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task


if __name__ == "__main__":
    unittest.main()
