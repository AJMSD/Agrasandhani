from __future__ import annotations

import asyncio
import csv
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from starlette.websockets import WebSocket

from gateway.mqtt_ingest import MqttEnvelope
from gateway.schemas import AggregatedFrame, SensorMessage

LOGGER = logging.getLogger(__name__)

GatewayMode = Literal["v0", "v1", "v2"]


@dataclass(slots=True)
class ForwarderConfig:
    mode: GatewayMode = "v0"
    batch_window_ms: int = 250
    batch_max_messages: int = 50
    value_dedup_enabled: bool = False


@dataclass(slots=True)
class Metrics:
    mqtt_in_msgs: int = 0
    mqtt_in_bytes: int = 0
    ws_out_msgs: int = 0
    ws_out_bytes: int = 0
    ws_out_frames: int = 0
    batch_flushes: int = 0
    duplicates_dropped: int = 0
    compacted_dropped: int = 0
    value_dedup_dropped: int = 0
    invalid_msgs: int = 0


class CsvRunLogger:
    HEADER = [
        "timestamp",
        "mode",
        "frame_id",
        "flush_reason",
        "frame_size",
        "frame_payload_bytes",
        "sensor_id",
        "msg_id",
        "ts_sent",
        "ts_recv_gateway",
        "ts_sent_ws",
        "bytes",
    ]

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = path.open("a", encoding="utf-8", newline="")
        self._writer = csv.writer(self._file)
        if self._file.tell() == 0:
            self._writer.writerow(self.HEADER)
            self._file.flush()

    def log_update(
        self,
        *,
        mode: GatewayMode,
        frame_id: int,
        flush_reason: str,
        frame_size: int,
        frame_payload_bytes: int,
        message: SensorMessage,
        ts_recv_gateway: int,
        ts_sent_ws: int,
        payload_bytes: int,
    ) -> None:
        self._writer.writerow(
            [
                datetime.now(timezone.utc).isoformat(),
                mode,
                frame_id,
                flush_reason,
                frame_size,
                frame_payload_bytes,
                message.sensor_id,
                message.msg_id,
                message.ts_sent,
                ts_recv_gateway,
                ts_sent_ws,
                payload_bytes,
            ]
        )
        self._file.flush()

    def close(self) -> None:
        self._file.close()


@dataclass(slots=True)
class BufferedUpdate:
    message: SensorMessage
    envelope: MqttEnvelope


class BaselineForwarder:
    def __init__(
        self,
        *,
        inbound_queue: asyncio.Queue[MqttEnvelope],
        run_logger: CsvRunLogger,
        config: ForwarderConfig | None = None,
    ) -> None:
        self._queue = inbound_queue
        self._run_logger = run_logger
        self._config = config or ForwarderConfig()
        self._clients: set[WebSocket] = set()
        self._latest_by_sensor: dict[tuple[str, str], SensorMessage] = {}
        self._last_emitted_by_sensor: dict[tuple[str, str], SensorMessage] = {}
        self._metrics = Metrics()
        self._pending_updates: list[BufferedUpdate] = []
        self._pending_latest: dict[tuple[str, str], BufferedUpdate] = {}
        self._pending_started_at: float | None = None
        self._next_frame_id = 1
        self._seen_message_keys: set[tuple[str, int]] = set()

    @property
    def connected_clients(self) -> int:
        return len(self._clients)

    @property
    def latest_sensor_count(self) -> int:
        return len(self._latest_by_sensor)

    @property
    def latest_snapshot(self) -> dict[tuple[str, str], SensorMessage]:
        return dict(self._latest_by_sensor)

    async def register_client(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)
        LOGGER.info("WebSocket client connected. Active clients=%s", self.connected_clients)

    async def unregister_client(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)
        try:
            await websocket.close()
        except RuntimeError:
            pass
        LOGGER.info("WebSocket client disconnected. Active clients=%s", self.connected_clients)

    async def run_forever(self) -> None:
        while True:
            timeout_s = self._next_flush_timeout_s()
            try:
                if timeout_s is None:
                    envelope = await self._queue.get()
                else:
                    envelope = await asyncio.wait_for(self._queue.get(), timeout=timeout_s)
            except asyncio.TimeoutError:
                await self._flush_pending(flush_reason="time")
                continue

            try:
                await self._handle_envelope(envelope)
            finally:
                self._queue.task_done()

    def metrics_snapshot(self, *, started_at_monotonic: float) -> dict[str, int | float | str]:
        return {
            "gateway_mode": self._config.mode,
            "mqtt_in_msgs": self._metrics.mqtt_in_msgs,
            "mqtt_in_bytes": self._metrics.mqtt_in_bytes,
            "ws_out_msgs": self._metrics.ws_out_msgs,
            "ws_out_bytes": self._metrics.ws_out_bytes,
            "ws_out_frames": self._metrics.ws_out_frames,
            "batch_flushes": self._metrics.batch_flushes,
            "duplicates_dropped": self._metrics.duplicates_dropped,
            "compacted_dropped": self._metrics.compacted_dropped,
            "value_dedup_dropped": self._metrics.value_dedup_dropped,
            "invalid_msgs": self._metrics.invalid_msgs,
            "connected_clients": self.connected_clients,
            "latest_sensor_count": self.latest_sensor_count,
            "process_uptime_s": round(time.monotonic() - started_at_monotonic, 3),
        }

    async def _handle_envelope(self, envelope: MqttEnvelope) -> None:
        self._metrics.mqtt_in_msgs += 1
        self._metrics.mqtt_in_bytes += len(envelope.payload)

        try:
            payload = json.loads(envelope.payload.decode("utf-8"))
            message = SensorMessage.model_validate(payload)
        except Exception:
            self._metrics.invalid_msgs += 1
            LOGGER.exception("Failed to validate MQTT payload from topic %s", envelope.topic)
            return

        if self._config.mode == "v0":
            await self._emit_single(envelope=envelope, message=message)
            return

        if self._config.mode == "v2" and message.duplicate_key() in self._seen_message_keys:
            self._metrics.duplicates_dropped += 1
            return

        self._buffer_update(BufferedUpdate(message=message, envelope=envelope))
        if self._pending_update_count() >= self._config.batch_max_messages:
            await self._flush_pending(flush_reason="threshold")

    def _buffer_update(self, buffered: BufferedUpdate) -> None:
        if self._pending_started_at is None:
            self._pending_started_at = time.monotonic()

        if self._config.mode == "v1":
            self._pending_updates.append(buffered)
            return

        key = buffered.message.ui_key()
        previous = self._pending_latest.get(key)
        if previous is None:
            self._pending_latest[key] = buffered
            return

        if buffered.message.ts_sent >= previous.message.ts_sent:
            self._pending_latest[key] = buffered
            self._metrics.compacted_dropped += 1
            return

        self._metrics.compacted_dropped += 1

    def _pending_update_count(self) -> int:
        if self._config.mode == "v1":
            return len(self._pending_updates)
        return len(self._pending_latest)

    def _next_flush_timeout_s(self) -> float | None:
        if self._pending_started_at is None:
            return None

        elapsed_ms = (time.monotonic() - self._pending_started_at) * 1_000
        remaining_ms = max(0.0, self._config.batch_window_ms - elapsed_ms)
        return remaining_ms / 1_000

    async def _emit_single(self, *, envelope: MqttEnvelope, message: SensorMessage) -> None:
        payload_text = message.model_dump_json()
        payload_bytes = len(payload_text.encode("utf-8"))
        ts_sent_ws = time.time_ns() // 1_000_000
        await self._broadcast(payload_text=payload_text, payload_bytes=payload_bytes, update_count=1)
        self._latest_by_sensor[message.ui_key()] = message
        self._last_emitted_by_sensor[message.ui_key()] = message
        self._run_logger.log_update(
            mode="v0",
            frame_id=self._next_frame_id,
            flush_reason="immediate",
            frame_size=1,
            frame_payload_bytes=payload_bytes,
            message=message,
            ts_recv_gateway=envelope.received_at_ms,
            ts_sent_ws=ts_sent_ws,
            payload_bytes=payload_bytes,
        )
        self._next_frame_id += 1

    async def _flush_pending(self, *, flush_reason: Literal["time", "threshold"]) -> None:
        updates = self._collect_pending_updates()
        if not updates:
            self._clear_pending()
            return

        if self._config.mode == "v2" and self._config.value_dedup_enabled:
            filtered_updates: list[BufferedUpdate] = []
            for buffered in updates:
                key = buffered.message.ui_key()
                previous = self._last_emitted_by_sensor.get(key)
                if previous is not None and previous.value == buffered.message.value:
                    self._metrics.value_dedup_dropped += 1
                    continue
                filtered_updates.append(buffered)
            updates = filtered_updates

        if not updates:
            self._clear_pending()
            return

        frame_id = self._next_frame_id
        self._next_frame_id += 1
        window_closed_ms = time.time_ns() // 1_000_000
        window_started_ms = max(
            min(buffered.envelope.received_at_ms for buffered in updates),
            window_closed_ms - self._config.batch_window_ms,
        )
        messages = [buffered.message for buffered in updates]
        frame = AggregatedFrame(
            frame_id=frame_id,
            mode=self._config.mode,
            flush_reason=flush_reason,
            window_started_ms=window_started_ms,
            window_closed_ms=window_closed_ms,
            update_count=len(messages),
            updates=messages,
        )
        payload_text = frame.model_dump_json()
        payload_bytes = len(payload_text.encode("utf-8"))
        ts_sent_ws = time.time_ns() // 1_000_000
        await self._broadcast(payload_text=payload_text, payload_bytes=payload_bytes, update_count=len(messages))

        for buffered in updates:
            message = buffered.message
            key = message.ui_key()
            self._latest_by_sensor[key] = message
            self._last_emitted_by_sensor[key] = message
            if self._config.mode == "v2":
                self._seen_message_keys.add(message.duplicate_key())
            self._run_logger.log_update(
                mode=self._config.mode,
                frame_id=frame_id,
                flush_reason=flush_reason,
                frame_size=len(messages),
                frame_payload_bytes=payload_bytes,
                message=message,
                ts_recv_gateway=buffered.envelope.received_at_ms,
                ts_sent_ws=ts_sent_ws,
                payload_bytes=payload_bytes,
            )

        self._metrics.batch_flushes += 1
        self._clear_pending()

    def _collect_pending_updates(self) -> list[BufferedUpdate]:
        if self._config.mode == "v1":
            return list(self._pending_updates)

        return sorted(
            self._pending_latest.values(),
            key=lambda buffered: (
                buffered.message.ts_sent,
                buffered.envelope.received_at_ms,
                str(buffered.message.sensor_id),
                buffered.message.metric_type,
            ),
        )

    def _clear_pending(self) -> None:
        self._pending_updates.clear()
        self._pending_latest.clear()
        self._pending_started_at = None

    async def _broadcast(self, *, payload_text: str, payload_bytes: int, update_count: int) -> None:
        stale_clients: list[WebSocket] = []
        successful_clients = 0
        for websocket in list(self._clients):
            try:
                await websocket.send_text(payload_text)
                successful_clients += 1
                self._metrics.ws_out_bytes += payload_bytes
            except Exception:
                LOGGER.exception("Failed to deliver message to WebSocket client")
                stale_clients.append(websocket)

        self._metrics.ws_out_frames += 1
        self._metrics.ws_out_msgs += update_count * successful_clients

        for websocket in stale_clients:
            await self.unregister_client(websocket)
