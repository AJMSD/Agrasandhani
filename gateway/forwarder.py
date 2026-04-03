from __future__ import annotations

import asyncio
import csv
import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError
from starlette.websockets import WebSocket

from gateway.mqtt_ingest import MqttEnvelope
from gateway.schemas import AggregatedFrame, SensorMessage

LOGGER = logging.getLogger(__name__)

GatewayMode = Literal["v0", "v1", "v2", "v3", "v4"]
FrameFlushReason = Literal["time", "threshold", "snapshot"]


def summarize_invalid_payload_error(exc: Exception) -> str:
    if isinstance(exc, json.JSONDecodeError):
        return f"invalid_json:{exc.msg}"
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}:{error['msg']}"
            for error in exc.errors()
        )
    return exc.__class__.__name__


def clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(value, upper))


@dataclass(slots=True)
class ForwarderConfig:
    mode: GatewayMode = "v0"
    batch_window_ms: int = 250
    batch_max_messages: int = 50
    duplicate_ttl_ms: int = 30_000
    value_dedup_enabled: bool = False
    freshness_ttl_ms: int = 1_000
    adaptive_min_batch_window_ms: int = 10
    adaptive_max_batch_window_ms: int = 1_000
    adaptive_step_up_ms: int = 100
    adaptive_step_down_ms: int = 50
    adaptive_queue_high_watermark: int = 25
    adaptive_queue_low_watermark: int = 5
    adaptive_send_slow_ms: int = 40
    adaptive_recovery_streak: int = 3

    def __post_init__(self) -> None:
        positive_int_fields = {
            "batch_window_ms": self.batch_window_ms,
            "batch_max_messages": self.batch_max_messages,
            "duplicate_ttl_ms": self.duplicate_ttl_ms,
            "freshness_ttl_ms": self.freshness_ttl_ms,
            "adaptive_min_batch_window_ms": self.adaptive_min_batch_window_ms,
            "adaptive_max_batch_window_ms": self.adaptive_max_batch_window_ms,
            "adaptive_step_up_ms": self.adaptive_step_up_ms,
            "adaptive_step_down_ms": self.adaptive_step_down_ms,
            "adaptive_queue_high_watermark": self.adaptive_queue_high_watermark,
            "adaptive_send_slow_ms": self.adaptive_send_slow_ms,
            "adaptive_recovery_streak": self.adaptive_recovery_streak,
        }
        for field_name, value in positive_int_fields.items():
            if value < 1:
                raise ValueError(f"{field_name} must be >= 1")

        if self.adaptive_queue_low_watermark < 0:
            raise ValueError("adaptive_queue_low_watermark must be >= 0")
        if self.adaptive_queue_low_watermark > self.adaptive_queue_high_watermark:
            raise ValueError("adaptive_queue_low_watermark must be <= adaptive_queue_high_watermark")
        if self.adaptive_min_batch_window_ms > self.adaptive_max_batch_window_ms:
            raise ValueError("adaptive_min_batch_window_ms must be <= adaptive_max_batch_window_ms")
        if not (self.adaptive_min_batch_window_ms <= self.batch_window_ms <= self.adaptive_max_batch_window_ms):
            raise ValueError("batch_window_ms must stay within adaptive min/max bounds")


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
    dedup_cache_evictions: int = 0
    adaptive_window_increase_events: int = 0
    adaptive_window_decrease_events: int = 0


class CsvRunLogger:
    HEADER = [
        "timestamp",
        "mode",
        "frame_id",
        "flush_reason",
        "batch_window_ms",
        "effective_batch_window_ms",
        "adaptation_reason",
        "frame_size",
        "frame_payload_bytes",
        "sensor_id",
        "metric_type",
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
        batch_window_ms: int,
        effective_batch_window_ms: int,
        adaptation_reason: str,
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
                batch_window_ms,
                effective_batch_window_ms,
                adaptation_reason,
                frame_size,
                frame_payload_bytes,
                message.sensor_id,
                message.metric_type,
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
    RUNTIME_TUNABLE_FIELDS = {
        "batch_window_ms",
        "batch_max_messages",
        "duplicate_ttl_ms",
        "value_dedup_enabled",
        "freshness_ttl_ms",
        "adaptive_min_batch_window_ms",
        "adaptive_max_batch_window_ms",
        "adaptive_step_up_ms",
        "adaptive_step_down_ms",
        "adaptive_queue_high_watermark",
        "adaptive_queue_low_watermark",
        "adaptive_send_slow_ms",
        "adaptive_recovery_streak",
    }

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
        self._seen_message_keys: dict[tuple[str, int], float] = {}
        self._effective_batch_window_ms = self._config.batch_window_ms
        self._healthy_flush_streak = 0
        self._last_adaptation_reason = "steady:startup"

    @property
    def connected_clients(self) -> int:
        return len(self._clients)

    @property
    def latest_sensor_count(self) -> int:
        return len(self._latest_by_sensor)

    @property
    def latest_snapshot(self) -> dict[tuple[str, str], SensorMessage]:
        return dict(self._latest_by_sensor)

    def runtime_config_snapshot(self) -> dict[str, int | str | bool]:
        return {
            "mode": self._config.mode,
            "batch_window_ms": self._config.batch_window_ms,
            "effective_batch_window_ms": self._current_batch_window_ms(),
            "batch_max_messages": self._config.batch_max_messages,
            "duplicate_ttl_ms": self._config.duplicate_ttl_ms,
            "value_dedup_enabled": self._config.value_dedup_enabled,
            "freshness_ttl_ms": self._config.freshness_ttl_ms,
            "adaptive_enabled": self._uses_adaptive_window(),
            "adaptive_min_batch_window_ms": self._config.adaptive_min_batch_window_ms,
            "adaptive_max_batch_window_ms": self._config.adaptive_max_batch_window_ms,
            "adaptive_step_up_ms": self._config.adaptive_step_up_ms,
            "adaptive_step_down_ms": self._config.adaptive_step_down_ms,
            "adaptive_queue_high_watermark": self._config.adaptive_queue_high_watermark,
            "adaptive_queue_low_watermark": self._config.adaptive_queue_low_watermark,
            "adaptive_send_slow_ms": self._config.adaptive_send_slow_ms,
            "adaptive_recovery_streak": self._config.adaptive_recovery_streak,
            "healthy_flush_streak": self._healthy_flush_streak,
            "last_adaptation_reason": self._last_adaptation_reason,
        }

    def update_runtime_config(self, updates: dict[str, Any]) -> dict[str, int | str | bool]:
        invalid_fields = sorted(set(updates) - self.RUNTIME_TUNABLE_FIELDS - {"mode"})
        if invalid_fields:
            raise ValueError(f"Unsupported runtime config fields: {', '.join(invalid_fields)}")

        if "mode" in updates and updates["mode"] != self._config.mode:
            raise ValueError("mode is startup-only and cannot be changed via /config")

        candidate_values = asdict(self._config)
        candidate_values.update({key: value for key, value in updates.items() if key in self.RUNTIME_TUNABLE_FIELDS})
        candidate = ForwarderConfig(**candidate_values)
        self._config = candidate

        if self._uses_adaptive_window():
            self._effective_batch_window_ms = clamp(
                self._effective_batch_window_ms,
                self._config.adaptive_min_batch_window_ms,
                self._config.adaptive_max_batch_window_ms,
            )
            target_window = max(self._config.batch_window_ms, self._config.adaptive_min_batch_window_ms)
            if self._effective_batch_window_ms < target_window:
                self._effective_batch_window_ms = target_window
        else:
            self._effective_batch_window_ms = self._config.batch_window_ms

        return self.runtime_config_snapshot()

    async def register_client(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)
        LOGGER.info("WebSocket client connected. Active clients=%s", self.connected_clients)

        if self._uses_lkg_snapshot() and self._latest_by_sensor:
            if not await self._send_snapshot_frame(websocket):
                await self.unregister_client(websocket)

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

    def metrics_snapshot(self, *, started_at_monotonic: float) -> dict[str, int | float | str | bool]:
        self._prune_seen_message_keys()
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
            "dedup_cache_size": len(self._seen_message_keys),
            "dedup_cache_evictions": self._metrics.dedup_cache_evictions,
            "adaptive_window_increase_events": self._metrics.adaptive_window_increase_events,
            "adaptive_window_decrease_events": self._metrics.adaptive_window_decrease_events,
            "connected_clients": self.connected_clients,
            "latest_sensor_count": self.latest_sensor_count,
            "queue_depth": self._queue.qsize(),
            "stale_sensor_count": self._current_stale_sensor_count(),
            "freshness_ttl_ms": self._config.freshness_ttl_ms,
            "effective_batch_window_ms": self._current_batch_window_ms(),
            "adaptive_enabled": self._uses_adaptive_window(),
            "last_adaptation_reason": self._last_adaptation_reason,
            "process_uptime_s": round(time.monotonic() - started_at_monotonic, 3),
        }

    async def _handle_envelope(self, envelope: MqttEnvelope) -> None:
        self._metrics.mqtt_in_msgs += 1
        self._metrics.mqtt_in_bytes += len(envelope.payload)
        self._prune_seen_message_keys()

        try:
            payload = json.loads(envelope.payload.decode("utf-8"))
            message = SensorMessage.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            self._metrics.invalid_msgs += 1
            LOGGER.warning(
                "Dropped invalid MQTT payload from topic %s: %s",
                envelope.topic,
                summarize_invalid_payload_error(exc),
            )
            return

        if self._config.mode == "v0":
            await self._emit_single(envelope=envelope, message=message)
            return

        if self._uses_compaction() and self._is_recent_duplicate(message):
            self._metrics.duplicates_dropped += 1
            return

        self._buffer_update(BufferedUpdate(message=message, envelope=envelope))
        if self._pending_update_count() >= self._config.batch_max_messages:
            await self._flush_pending(flush_reason="threshold")

    def _uses_compaction(self) -> bool:
        return self._config.mode in {"v2", "v3", "v4"}

    def _uses_adaptive_window(self) -> bool:
        return self._config.mode in {"v3", "v4"}

    def _uses_lkg_snapshot(self) -> bool:
        return self._config.mode == "v4"

    def _current_batch_window_ms(self) -> int:
        if self._uses_adaptive_window():
            return self._effective_batch_window_ms
        return self._config.batch_window_ms

    def _current_stale_sensor_count(self) -> int:
        if not self._latest_by_sensor:
            return 0

        now_ms = time.time_ns() // 1_000_000
        return sum(
            1
            for message in self._latest_by_sensor.values()
            if (now_ms - message.ts_sent) > self._config.freshness_ttl_ms
        )

    def _buffer_update(self, buffered: BufferedUpdate) -> None:
        if self._pending_started_at is None:
            self._pending_started_at = time.monotonic()

        if not self._uses_compaction():
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

    def _is_recent_duplicate(self, message: SensorMessage) -> bool:
        seen_at = self._seen_message_keys.get(message.duplicate_key())
        if seen_at is None:
            return False
        return (time.monotonic() - seen_at) * 1_000 <= self._config.duplicate_ttl_ms

    def _mark_duplicate_key_seen(self, message: SensorMessage) -> None:
        self._seen_message_keys[message.duplicate_key()] = time.monotonic()

    def _prune_seen_message_keys(self) -> None:
        if not self._seen_message_keys:
            return

        now = time.monotonic()
        expired_keys = [
            key
            for key, seen_at in self._seen_message_keys.items()
            if (now - seen_at) * 1_000 > self._config.duplicate_ttl_ms
        ]
        if not expired_keys:
            return

        for key in expired_keys:
            self._seen_message_keys.pop(key, None)
        self._metrics.dedup_cache_evictions += len(expired_keys)

    def _pending_update_count(self) -> int:
        if self._uses_compaction():
            return len(self._pending_latest)
        return len(self._pending_updates)

    def _next_flush_timeout_s(self) -> float | None:
        if self._pending_started_at is None:
            return None

        elapsed_ms = (time.monotonic() - self._pending_started_at) * 1_000
        remaining_ms = max(0.0, self._current_batch_window_ms() - elapsed_ms)
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
            batch_window_ms=self._config.batch_window_ms,
            effective_batch_window_ms=self._current_batch_window_ms(),
            adaptation_reason="fixed:v0",
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

        if self._uses_compaction() and self._config.value_dedup_enabled:
            filtered_updates: list[BufferedUpdate] = []
            for buffered in updates:
                key = buffered.message.ui_key()
                previous = self._last_emitted_by_sensor.get(key)
                if previous is None or previous.value != buffered.message.value:
                    filtered_updates.append(buffered)
                    continue

                if self._uses_lkg_snapshot() and buffered.message.ts_sent > previous.ts_sent:
                    filtered_updates.append(buffered)
                    continue

                self._metrics.value_dedup_dropped += 1
            updates = filtered_updates

        if not updates:
            self._clear_pending()
            return

        frame_id = self._next_frame_id
        self._next_frame_id += 1
        window_used_ms = self._current_batch_window_ms()
        frame = self._build_frame(
            frame_id=frame_id,
            flush_reason=flush_reason,
            updates=updates,
            window_used_ms=window_used_ms,
        )
        payload_text = frame.model_dump_json()
        payload_bytes = len(payload_text.encode("utf-8"))
        ts_sent_ws = time.time_ns() // 1_000_000
        queue_depth_before_flush = self._queue.qsize()
        send_started_at = time.perf_counter()
        await self._broadcast(payload_text=payload_text, payload_bytes=payload_bytes, update_count=len(frame.updates))
        send_duration_ms = max(1, round((time.perf_counter() - send_started_at) * 1_000))
        adaptation_reason = self._update_adaptive_window(
            queue_depth=queue_depth_before_flush,
            send_duration_ms=send_duration_ms,
        )

        for buffered in updates:
            message = buffered.message
            key = message.ui_key()
            self._latest_by_sensor[key] = message
            self._last_emitted_by_sensor[key] = message
            if self._uses_compaction():
                self._mark_duplicate_key_seen(message)
            self._run_logger.log_update(
                mode=self._config.mode,
                frame_id=frame_id,
                flush_reason=flush_reason,
                batch_window_ms=self._config.batch_window_ms,
                effective_batch_window_ms=window_used_ms,
                adaptation_reason=adaptation_reason,
                frame_size=len(frame.updates),
                frame_payload_bytes=payload_bytes,
                message=message,
                ts_recv_gateway=buffered.envelope.received_at_ms,
                ts_sent_ws=ts_sent_ws,
                payload_bytes=payload_bytes,
            )

        self._metrics.batch_flushes += 1
        self._clear_pending()

    def _update_adaptive_window(self, *, queue_depth: int, send_duration_ms: int) -> str:
        if not self._uses_adaptive_window():
            self._last_adaptation_reason = "fixed_window"
            return self._last_adaptation_reason

        degraded_reasons: list[str] = []
        if queue_depth >= self._config.adaptive_queue_high_watermark:
            degraded_reasons.append(f"queue_depth={queue_depth}")
        if send_duration_ms >= self._config.adaptive_send_slow_ms:
            degraded_reasons.append(f"send_duration_ms={send_duration_ms}")

        if degraded_reasons:
            self._healthy_flush_streak = 0
            next_window = clamp(
                self._effective_batch_window_ms + self._config.adaptive_step_up_ms,
                self._config.adaptive_min_batch_window_ms,
                self._config.adaptive_max_batch_window_ms,
            )
            if next_window > self._effective_batch_window_ms:
                self._effective_batch_window_ms = next_window
                self._metrics.adaptive_window_increase_events += 1
            self._last_adaptation_reason = f"degrade:{'|'.join(degraded_reasons)}"
            return self._last_adaptation_reason

        self._healthy_flush_streak += 1
        if self._healthy_flush_streak < self._config.adaptive_recovery_streak:
            self._last_adaptation_reason = f"healthy_streak={self._healthy_flush_streak}"
            return self._last_adaptation_reason

        target_window = max(self._config.batch_window_ms, self._config.adaptive_min_batch_window_ms)
        next_window = clamp(
            self._effective_batch_window_ms - self._config.adaptive_step_down_ms,
            self._config.adaptive_min_batch_window_ms,
            self._config.adaptive_max_batch_window_ms,
        )
        if next_window < target_window:
            next_window = target_window

        if next_window < self._effective_batch_window_ms:
            self._effective_batch_window_ms = next_window
            self._metrics.adaptive_window_decrease_events += 1
            self._last_adaptation_reason = f"recover:healthy(queue_depth={queue_depth},send_duration_ms={send_duration_ms})"
        else:
            self._last_adaptation_reason = "steady:healthy"

        self._healthy_flush_streak = 0
        return self._last_adaptation_reason

    def _build_frame(
        self,
        *,
        frame_id: int,
        flush_reason: FrameFlushReason,
        updates: list[BufferedUpdate],
        window_used_ms: int,
    ) -> AggregatedFrame:
        window_closed_ms = time.time_ns() // 1_000_000
        window_started_ms = max(
            min(buffered.envelope.received_at_ms for buffered in updates),
            window_closed_ms - window_used_ms,
        )
        return AggregatedFrame(
            frame_id=frame_id,
            mode=self._config.mode,
            flush_reason=flush_reason,
            window_started_ms=window_started_ms,
            window_closed_ms=window_closed_ms,
            update_count=len(updates),
            updates=[buffered.message for buffered in updates],
        )

    async def _send_snapshot_frame(self, websocket: WebSocket) -> bool:
        snapshot_messages = self._snapshot_messages()
        if not snapshot_messages:
            return True

        now_ms = time.time_ns() // 1_000_000
        frame = AggregatedFrame(
            frame_id=self._next_frame_id,
            mode=self._config.mode,
            flush_reason="snapshot",
            window_started_ms=min(message.ts_sent for message in snapshot_messages),
            window_closed_ms=now_ms,
            update_count=len(snapshot_messages),
            updates=snapshot_messages,
        )
        self._next_frame_id += 1
        payload_text = frame.model_dump_json()
        payload_bytes = len(payload_text.encode("utf-8"))

        delivered = await self._send_payload(websocket, payload_text=payload_text, payload_bytes=payload_bytes)
        self._metrics.ws_out_frames += 1
        if delivered:
            self._metrics.ws_out_msgs += len(snapshot_messages)
        return delivered

    def _snapshot_messages(self) -> list[SensorMessage]:
        return sorted(
            self._latest_by_sensor.values(),
            key=lambda message: (str(message.sensor_id), message.metric_type, message.ts_sent),
        )

    def _collect_pending_updates(self) -> list[BufferedUpdate]:
        if self._uses_compaction():
            return sorted(
                self._pending_latest.values(),
                key=lambda buffered: (
                    buffered.message.ts_sent,
                    buffered.envelope.received_at_ms,
                    str(buffered.message.sensor_id),
                    buffered.message.metric_type,
                ),
            )

        return list(self._pending_updates)

    def _clear_pending(self) -> None:
        self._pending_updates.clear()
        self._pending_latest.clear()
        self._pending_started_at = None

    async def _broadcast(self, *, payload_text: str, payload_bytes: int, update_count: int) -> None:
        stale_clients: list[WebSocket] = []
        successful_clients = 0
        for websocket in list(self._clients):
            try:
                delivered = await self._send_payload(websocket, payload_text=payload_text, payload_bytes=payload_bytes)
            except Exception:
                LOGGER.exception("Failed to deliver message to WebSocket client")
                stale_clients.append(websocket)
                continue

            if delivered:
                successful_clients += 1

        self._metrics.ws_out_frames += 1
        self._metrics.ws_out_msgs += update_count * successful_clients

        for websocket in stale_clients:
            await self.unregister_client(websocket)

    async def _send_payload(self, websocket: WebSocket, *, payload_text: str, payload_bytes: int) -> bool:
        await websocket.send_text(payload_text)
        self._metrics.ws_out_bytes += payload_bytes
        return True
