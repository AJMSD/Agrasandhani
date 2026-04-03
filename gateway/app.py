from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from gateway.forwarder import BaselineForwarder, CsvRunLogger, ForwarderConfig, GatewayMode
from gateway.mqtt_ingest import MQTTIngestor

BASE_DIR = Path(__file__).resolve().parent.parent
UI_DIR = BASE_DIR / "ui"
LOGS_ROOT = BASE_DIR / "experiments" / "logs"


@dataclass(slots=True)
class Settings:
    mqtt_host: str
    mqtt_port: int
    mqtt_qos: int
    ws_host: str
    ws_port: int
    run_id: str
    gateway_mode: GatewayMode
    batch_window_ms: int
    batch_max_messages: int
    value_dedup_enabled: bool
    freshness_ttl_ms: int
    adaptive_min_batch_window_ms: int
    adaptive_max_batch_window_ms: int
    adaptive_step_up_ms: int
    adaptive_step_down_ms: int
    adaptive_queue_high_watermark: int
    adaptive_queue_low_watermark: int
    adaptive_send_slow_ms: int
    adaptive_recovery_streak: int


@dataclass(slots=True)
class AppServices:
    settings: Settings
    started_at_monotonic: float
    inbound_queue: asyncio.Queue
    run_logger: CsvRunLogger
    forwarder: BaselineForwarder
    mqtt_ingestor: MQTTIngestor
    forwarder_task: asyncio.Task


class RuntimeConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: GatewayMode | None = None
    batch_window_ms: int | None = None
    batch_max_messages: int | None = None
    value_dedup_enabled: bool | None = None
    freshness_ttl_ms: int | None = None
    adaptive_min_batch_window_ms: int | None = None
    adaptive_max_batch_window_ms: int | None = None
    adaptive_step_up_ms: int | None = None
    adaptive_step_down_ms: int | None = None
    adaptive_queue_high_watermark: int | None = None
    adaptive_queue_low_watermark: int | None = None
    adaptive_send_slow_ms: int | None = None
    adaptive_recovery_streak: int | None = None


def load_settings() -> Settings:
    gateway_mode = os.getenv("GATEWAY_MODE", "v0")
    if gateway_mode not in {"v0", "v1", "v2", "v3", "v4"}:
        raise ValueError(f"Unsupported GATEWAY_MODE '{gateway_mode}'. Expected one of v0, v1, v2, v3, v4.")

    return Settings(
        mqtt_host=os.getenv("MQTT_HOST", "127.0.0.1"),
        mqtt_port=int(os.getenv("MQTT_PORT", "1883")),
        mqtt_qos=int(os.getenv("MQTT_QOS", "0")),
        ws_host=os.getenv("WS_HOST", "127.0.0.1"),
        ws_port=int(os.getenv("WS_PORT", "8000")),
        run_id=os.getenv("RUN_ID", "dev"),
        gateway_mode=gateway_mode,
        batch_window_ms=int(os.getenv("BATCH_WINDOW_MS", "250")),
        batch_max_messages=int(os.getenv("BATCH_MAX_MESSAGES", "50")),
        value_dedup_enabled=os.getenv("VALUE_DEDUP_ENABLED", "0") == "1",
        freshness_ttl_ms=int(os.getenv("FRESHNESS_TTL_MS", "1000")),
        adaptive_min_batch_window_ms=int(os.getenv("ADAPTIVE_MIN_BATCH_WINDOW_MS", "10")),
        adaptive_max_batch_window_ms=int(os.getenv("ADAPTIVE_MAX_BATCH_WINDOW_MS", "1000")),
        adaptive_step_up_ms=int(os.getenv("ADAPTIVE_STEP_UP_MS", "100")),
        adaptive_step_down_ms=int(os.getenv("ADAPTIVE_STEP_DOWN_MS", "50")),
        adaptive_queue_high_watermark=int(os.getenv("ADAPTIVE_QUEUE_HIGH_WATERMARK", "25")),
        adaptive_queue_low_watermark=int(os.getenv("ADAPTIVE_QUEUE_LOW_WATERMARK", "5")),
        adaptive_send_slow_ms=int(os.getenv("ADAPTIVE_SEND_SLOW_MS", "40")),
        adaptive_recovery_streak=int(os.getenv("ADAPTIVE_RECOVERY_STREAK", "3")),
    )


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = load_settings()
    inbound_queue: asyncio.Queue = asyncio.Queue()
    run_logger = CsvRunLogger(LOGS_ROOT / settings.run_id / "gateway_forward_log.csv")
    forwarder = BaselineForwarder(
        inbound_queue=inbound_queue,
        run_logger=run_logger,
        config=ForwarderConfig(
            mode=settings.gateway_mode,
            batch_window_ms=settings.batch_window_ms,
            batch_max_messages=settings.batch_max_messages,
            value_dedup_enabled=settings.value_dedup_enabled,
            freshness_ttl_ms=settings.freshness_ttl_ms,
            adaptive_min_batch_window_ms=settings.adaptive_min_batch_window_ms,
            adaptive_max_batch_window_ms=settings.adaptive_max_batch_window_ms,
            adaptive_step_up_ms=settings.adaptive_step_up_ms,
            adaptive_step_down_ms=settings.adaptive_step_down_ms,
            adaptive_queue_high_watermark=settings.adaptive_queue_high_watermark,
            adaptive_queue_low_watermark=settings.adaptive_queue_low_watermark,
            adaptive_send_slow_ms=settings.adaptive_send_slow_ms,
            adaptive_recovery_streak=settings.adaptive_recovery_streak,
        ),
    )
    mqtt_ingestor = MQTTIngestor(
        loop=asyncio.get_running_loop(),
        queue=inbound_queue,
        host=settings.mqtt_host,
        port=settings.mqtt_port,
        qos=settings.mqtt_qos,
        client_id=f"agrasandhani-gateway-{settings.run_id}",
    )
    mqtt_ingestor.start()
    forwarder_task = asyncio.create_task(forwarder.run_forever(), name="baseline-forwarder")
    app.state.services = AppServices(
        settings=settings,
        started_at_monotonic=time.monotonic(),
        inbound_queue=inbound_queue,
        run_logger=run_logger,
        forwarder=forwarder,
        mqtt_ingestor=mqtt_ingestor,
        forwarder_task=forwarder_task,
    )
    try:
        yield
    finally:
        mqtt_ingestor.stop()
        forwarder_task.cancel()
        with suppress(asyncio.CancelledError):
            await forwarder_task
        run_logger.close()


app = FastAPI(title="Agrasandhani Gateway", lifespan=lifespan)
app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")


@app.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse(url="/ui/index.html")


@app.get("/health")
async def health() -> dict[str, object]:
    services: AppServices = app.state.services
    return {
        "status": "ok",
        "mqtt_connected": services.mqtt_ingestor.is_connected,
        "run_id": services.settings.run_id,
    }


@app.get("/metrics")
async def metrics() -> dict[str, int | float | str | bool]:
    services: AppServices = app.state.services
    return services.forwarder.metrics_snapshot(started_at_monotonic=services.started_at_monotonic)


@app.get("/config")
async def get_config() -> dict[str, int | str | bool]:
    services: AppServices = app.state.services
    return services.forwarder.runtime_config_snapshot()


@app.patch("/config")
async def patch_config(config_update: RuntimeConfigUpdate) -> dict[str, int | str | bool]:
    services: AppServices = app.state.services
    try:
        return services.forwarder.update_runtime_config(config_update.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.websocket("/ws")
async def websocket_updates(websocket: WebSocket) -> None:
    services: AppServices = app.state.services
    await services.forwarder.register_client(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await services.forwarder.unregister_client(websocket)


def main() -> None:
    settings = load_settings()
    uvicorn.run("gateway.app:app", host=settings.ws_host, port=settings.ws_port, reload=False)


if __name__ == "__main__":
    main()
