from __future__ import annotations

import asyncio
import csv
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from starlette.websockets import WebSocket

from gateway.mqtt_ingest import MqttEnvelope
from gateway.schemas import SensorMessage

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class Metrics:
    mqtt_in_msgs: int = 0
    mqtt_in_bytes: int = 0
    ws_out_msgs: int = 0
    ws_out_bytes: int = 0


class CsvRunLogger:
    HEADER = [
        "timestamp",
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

    def log(self, *, message: SensorMessage, ts_recv_gateway: int, ts_sent_ws: int, payload_bytes: int) -> None:
        self._writer.writerow(
            [
                datetime.now(timezone.utc).isoformat(),
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


class BaselineForwarder:
    def __init__(self, *, inbound_queue: asyncio.Queue[MqttEnvelope], run_logger: CsvRunLogger) -> None:
        self._queue = inbound_queue
        self._run_logger = run_logger
        self._clients: set[WebSocket] = set()
        self._latest_by_sensor: dict[tuple[str, str], SensorMessage] = {}
        self._metrics = Metrics()

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
            envelope = await self._queue.get()
            try:
                await self._handle_message(envelope)
            finally:
                self._queue.task_done()

    def metrics_snapshot(self, *, started_at_monotonic: float) -> dict[str, int | float]:
        return {
            "mqtt_in_msgs": self._metrics.mqtt_in_msgs,
            "mqtt_in_bytes": self._metrics.mqtt_in_bytes,
            "ws_out_msgs": self._metrics.ws_out_msgs,
            "ws_out_bytes": self._metrics.ws_out_bytes,
            "connected_clients": self.connected_clients,
            "latest_sensor_count": self.latest_sensor_count,
            "process_uptime_s": round(time.monotonic() - started_at_monotonic, 3),
        }

    async def _handle_message(self, envelope: MqttEnvelope) -> None:
        self._metrics.mqtt_in_msgs += 1
        self._metrics.mqtt_in_bytes += len(envelope.payload)

        try:
            payload = json.loads(envelope.payload.decode("utf-8"))
            message = SensorMessage.model_validate(payload)
        except Exception:
            LOGGER.exception("Failed to validate MQTT payload from topic %s", envelope.topic)
            return

        self._latest_by_sensor[message.ui_key()] = message
        ts_sent_ws = time.time_ns() // 1_000_000
        payload_text = message.model_dump_json()
        payload_bytes = len(payload_text.encode("utf-8"))
        await self._broadcast(payload_text, payload_bytes)
        self._run_logger.log(
            message=message,
            ts_recv_gateway=envelope.received_at_ms,
            ts_sent_ws=ts_sent_ws,
            payload_bytes=payload_bytes,
        )

    async def _broadcast(self, payload_text: str, payload_bytes: int) -> None:
        stale_clients: list[WebSocket] = []
        for websocket in list(self._clients):
            try:
                await websocket.send_text(payload_text)
                self._metrics.ws_out_msgs += 1
                self._metrics.ws_out_bytes += payload_bytes
            except Exception:
                LOGGER.exception("Failed to deliver message to WebSocket client")
                stale_clients.append(websocket)

        for websocket in stale_clients:
            await self.unregister_client(websocket)
