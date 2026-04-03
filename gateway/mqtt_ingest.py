from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from paho.mqtt import client as mqtt_client

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class MqttEnvelope:
    topic: str
    payload: bytes
    received_at_ms: int


class MQTTIngestor:
    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue[MqttEnvelope],
        host: str,
        port: int,
        qos: int,
        client_id: str,
    ) -> None:
        self._loop = loop
        self._queue = queue
        self._host = host
        self._port = port
        self._qos = qos
        self._client = mqtt_client.Client(
            mqtt_client.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.enable_logger(LOGGER)
        self._is_connected = False

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def start(self) -> None:
        LOGGER.info("Connecting to MQTT broker at %s:%s", self._host, self._port)
        self._client.connect_async(self._host, self._port)
        self._client.loop_start()

    def stop(self) -> None:
        try:
            self._client.disconnect()
        except Exception:  # pragma: no cover - defensive shutdown path
            LOGGER.exception("Failed to disconnect MQTT client cleanly")
        finally:
            self._client.loop_stop()

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        self._is_connected = self._is_success(reason_code)
        if self._is_connected:
            LOGGER.info("Subscribed to sensors/raw/# with QoS %s", self._qos)
            client.subscribe("sensors/raw/#", qos=self._qos)
            return

        LOGGER.error("MQTT connection failed with reason code %s", reason_code)

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties) -> None:
        self._is_connected = False
        if self._is_success(reason_code):
            LOGGER.info("MQTT client disconnected with reason code %s", reason_code)
            return

        LOGGER.warning("MQTT client disconnected with reason code %s", reason_code)

    def _on_message(self, client, userdata, message) -> None:
        envelope = MqttEnvelope(
            topic=message.topic,
            payload=bytes(message.payload),
            received_at_ms=time.time_ns() // 1_000_000,
        )
        self._loop.call_soon_threadsafe(self._queue.put_nowait, envelope)

    @staticmethod
    def _is_success(reason_code) -> bool:
        try:
            return int(reason_code) == 0
        except (TypeError, ValueError):
            return str(reason_code).lower() == "success"
