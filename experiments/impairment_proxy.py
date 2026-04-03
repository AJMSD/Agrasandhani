from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn
import websockets
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from experiments.impairment import ImpairmentSession, ProxyFrameLogger, ProxyMetrics, load_scenario

BASE_DIR = Path(__file__).resolve().parent.parent
UI_DIR = BASE_DIR / "ui"
LOGS_ROOT = BASE_DIR / "experiments" / "logs"
SCENARIOS_DIR = BASE_DIR / "experiments" / "scenarios"


@dataclass(slots=True)
class ProxySettings:
    impair_host: str
    impair_port: int
    upstream_ws_url: str
    upstream_http_base: str
    scenario_file: Path
    random_seed: int
    run_id: str
    frame_log_path: Path


@dataclass(slots=True)
class ProxyServices:
    settings: ProxySettings
    started_at_monotonic: float
    metrics: ProxyMetrics
    frame_logger: ProxyFrameLogger
    scenario_name: str
    scenario: object
    next_session_id: int = 1


def load_settings() -> ProxySettings:
    run_id = os.getenv("RUN_ID", "dev")
    scenario_file = Path(os.getenv("IMPAIR_SCENARIO_FILE", str(SCENARIOS_DIR / "clean.json")))
    return ProxySettings(
        impair_host=os.getenv("IMPAIR_HOST", "127.0.0.1"),
        impair_port=int(os.getenv("IMPAIR_PORT", "9000")),
        upstream_ws_url=os.getenv("UPSTREAM_WS_URL", "ws://127.0.0.1:8000/ws"),
        upstream_http_base=os.getenv("UPSTREAM_HTTP_BASE", "http://127.0.0.1:8000"),
        scenario_file=scenario_file,
        random_seed=int(os.getenv("IMPAIR_RANDOM_SEED", "537")),
        run_id=run_id,
        frame_log_path=Path(
            os.getenv("IMPAIR_FRAME_LOG_PATH", str(LOGS_ROOT / run_id / "proxy_frame_log.csv"))
        ),
    )


def _http_json_request(
    *,
    base_url: str,
    path: str,
    method: str,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    encoded = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url=f"{base_url.rstrip('/')}{path}",
        data=encoded,
        method=method,
        headers={"Content-Type": "application/json"} if encoded is not None else {},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


def create_app(settings: ProxySettings | None = None) -> FastAPI:
    resolved_settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        scenario = load_scenario(resolved_settings.scenario_file)
        frame_logger = ProxyFrameLogger(resolved_settings.frame_log_path)
        app.state.services = ProxyServices(
            settings=resolved_settings,
            started_at_monotonic=time.monotonic(),
            metrics=ProxyMetrics(),
            frame_logger=frame_logger,
            scenario_name=scenario.name,
            scenario=scenario,
        )
        try:
            yield
        finally:
            frame_logger.close()

    app = FastAPI(title="Agrasandhani Impairment Proxy", lifespan=lifespan)
    app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")

    @app.get("/")
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/ui/index.html")

    @app.get("/health")
    async def health() -> dict[str, object]:
        services: ProxyServices = app.state.services
        return {
            "status": "ok",
            "scenario_name": services.scenario_name,
            "scenario_file": str(services.settings.scenario_file),
            "active_clients": services.metrics.active_clients,
            "current_phase": services.metrics.current_phase,
            "outage_active": services.metrics.outage_active,
        }

    @app.get("/metrics")
    async def metrics() -> dict[str, object]:
        services: ProxyServices = app.state.services
        return services.metrics.snapshot(
            started_at_monotonic=services.started_at_monotonic,
            scenario_name=services.scenario_name,
        )

    @app.get("/config")
    async def get_config() -> dict[str, object]:
        services: ProxyServices = app.state.services
        services.metrics.config_proxy_requests += 1
        try:
            return await asyncio.to_thread(
                _http_json_request,
                base_url=services.settings.upstream_http_base,
                path="/config",
                method="GET",
            )
        except urllib.error.HTTPError as exc:
            raise HTTPException(status_code=exc.code, detail=exc.read().decode("utf-8")) from exc
        except urllib.error.URLError as exc:
            raise HTTPException(status_code=502, detail=str(exc.reason)) from exc

    @app.patch("/config")
    async def patch_config(request: Request) -> dict[str, object]:
        services: ProxyServices = app.state.services
        services.metrics.config_proxy_requests += 1
        payload = await request.json()
        try:
            return await asyncio.to_thread(
                _http_json_request,
                base_url=services.settings.upstream_http_base,
                path="/config",
                method="PATCH",
                payload=payload,
            )
        except urllib.error.HTTPError as exc:
            raise HTTPException(status_code=exc.code, detail=exc.read().decode("utf-8")) from exc
        except urllib.error.URLError as exc:
            raise HTTPException(status_code=502, detail=str(exc.reason)) from exc

    @app.websocket("/ws")
    async def websocket_proxy(websocket: WebSocket) -> None:
        services: ProxyServices = app.state.services
        session_id = services.next_session_id
        services.next_session_id += 1
        session = ImpairmentSession(services.scenario, seed=services.settings.random_seed + session_id)

        await websocket.accept()
        services.metrics.active_clients += 1

        try:
            async with websockets.connect(services.settings.upstream_ws_url, max_size=None) as upstream:
                upstream_task = asyncio.create_task(
                    _pump_upstream_to_client(
                        upstream=upstream,
                        downstream=websocket,
                        session=session,
                        session_id=session_id,
                        services=services,
                    )
                )
                downstream_task = asyncio.create_task(_watch_downstream_disconnect(websocket))
                done, pending = await asyncio.wait(
                    {upstream_task, downstream_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                for task in pending:
                    with suppress(asyncio.CancelledError):
                        await task
                for task in done:
                    task.result()
        except (WebSocketDisconnect, websockets.ConnectionClosed):
            pass
        finally:
            services.metrics.active_clients = max(0, services.metrics.active_clients - 1)
            with suppress(RuntimeError):
                await websocket.close()

    return app


async def _pump_upstream_to_client(
    *,
    upstream: websockets.ClientConnection,
    downstream: WebSocket,
    session: ImpairmentSession,
    session_id: int,
    services: ProxyServices,
) -> None:
    async for payload_text in upstream:
        payload_bytes = len(payload_text.encode("utf-8"))
        upstream_received_ms = time.time_ns() // 1_000_000
        services.metrics.upstream_frames_in += 1
        services.metrics.upstream_bytes_in += payload_bytes

        action = session.plan(payload_bytes=payload_bytes, now_s=time.monotonic())
        services.metrics.current_phase = action.phase_name
        services.metrics.outage_active = action.is_outage

        if action.should_drop:
            services.metrics.dropped_frames += 1
            services.metrics.dropped_bytes += payload_bytes
            services.frame_logger.log(
                session_id=session_id,
                action=action,
                event="dropped",
                payload_bytes=payload_bytes,
                upstream_received_ms=upstream_received_ms,
                downstream_sent_ms=None,
            )
            continue

        if action.total_wait_ms > 0:
            services.metrics.delayed_frames += 1
            services.metrics.total_scheduled_delay_ms += action.scheduled_delay_ms
            services.metrics.total_bandwidth_wait_ms += action.bandwidth_wait_ms
            await asyncio.sleep(action.total_wait_ms / 1000)

        downstream_sent_ms = time.time_ns() // 1_000_000
        await downstream.send_text(payload_text)
        services.metrics.downstream_frames_out += 1
        services.metrics.downstream_bytes_out += payload_bytes
        services.frame_logger.log(
            session_id=session_id,
            action=action,
            event="sent",
            payload_bytes=payload_bytes,
            upstream_received_ms=upstream_received_ms,
            downstream_sent_ms=downstream_sent_ms,
        )


async def _watch_downstream_disconnect(websocket: WebSocket) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect()


app = create_app()


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        "experiments.impairment_proxy:app",
        host=settings.impair_host,
        port=settings.impair_port,
        reload=False,
        ws="websockets-sansio",
    )


if __name__ == "__main__":
    main()
