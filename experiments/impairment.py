from __future__ import annotations

import csv
import random
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ScenarioPhase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    duration_s: float = Field(gt=0)
    loss_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    delay_ms: int = Field(default=0, ge=0)
    jitter_ms: int = Field(default=0, ge=0)
    bandwidth_bps: int | None = Field(default=None, gt=0)
    outage: bool = False


class ImpairmentScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(default=1)
    name: str = Field(min_length=1)
    phases: list[ScenarioPhase] = Field(min_length=1)

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("Only scenario version 1 is supported")
        return value

    def phase_for_elapsed(self, elapsed_s: float) -> ScenarioPhase:
        cursor = 0.0
        for phase in self.phases:
            cursor += phase.duration_s
            if elapsed_s < cursor:
                return phase
        return self.phases[-1]


def load_scenario(path: Path) -> ImpairmentScenario:
    return ImpairmentScenario.model_validate_json(path.read_text(encoding="utf-8"))


@dataclass(slots=True)
class ImpairmentAction:
    phase_name: str
    should_drop: bool
    is_outage: bool
    scheduled_delay_ms: int
    bandwidth_wait_ms: int
    total_wait_ms: int


class TokenBucket:
    def __init__(self, rate_bps: int | None, now_s: float) -> None:
        self._rate_bps = rate_bps
        self._updated_at_s = now_s
        self._available_bytes = float(rate_bps) if rate_bps else 0.0

    def consume(self, payload_bytes: int, now_s: float) -> int:
        if self._rate_bps is None:
            return 0

        elapsed_s = max(0.0, now_s - self._updated_at_s)
        self._available_bytes = min(
            float(self._rate_bps),
            self._available_bytes + (elapsed_s * self._rate_bps),
        )
        self._updated_at_s = now_s

        if self._available_bytes >= payload_bytes:
            self._available_bytes -= payload_bytes
            return 0

        deficit = payload_bytes - self._available_bytes
        wait_s = deficit / self._rate_bps
        wait_ms = int(round(wait_s * 1000))
        self._available_bytes = 0.0
        self._updated_at_s = now_s + wait_s
        return wait_ms


class ImpairmentSession:
    def __init__(self, scenario: ImpairmentScenario, *, seed: int) -> None:
        self._scenario = scenario
        self._rng = random.Random(seed)
        self._started_at_s: float | None = None
        self._bucket_phase_name: str | None = None
        self._bucket: TokenBucket | None = None

    def plan(self, *, payload_bytes: int, now_s: float) -> ImpairmentAction:
        if self._started_at_s is None:
            self._started_at_s = now_s

        phase = self._scenario.phase_for_elapsed(max(0.0, now_s - self._started_at_s))
        if self._bucket_phase_name != phase.name:
            self._bucket_phase_name = phase.name
            self._bucket = TokenBucket(phase.bandwidth_bps, now_s)

        scheduled_delay_ms = phase.delay_ms
        if phase.jitter_ms:
            scheduled_delay_ms += int(round(self._rng.uniform(-phase.jitter_ms, phase.jitter_ms)))
        scheduled_delay_ms = max(0, scheduled_delay_ms)

        should_drop = phase.outage
        if not should_drop and phase.loss_rate > 0 and self._rng.random() < phase.loss_rate:
            should_drop = True

        bandwidth_wait_ms = self._bucket.consume(payload_bytes, now_s) if self._bucket else 0
        return ImpairmentAction(
            phase_name=phase.name,
            should_drop=should_drop,
            is_outage=phase.outage,
            scheduled_delay_ms=scheduled_delay_ms,
            bandwidth_wait_ms=bandwidth_wait_ms,
            total_wait_ms=scheduled_delay_ms + bandwidth_wait_ms,
        )


@dataclass(slots=True)
class ProxyMetrics:
    upstream_frames_in: int = 0
    upstream_bytes_in: int = 0
    downstream_frames_out: int = 0
    downstream_bytes_out: int = 0
    dropped_frames: int = 0
    dropped_bytes: int = 0
    delayed_frames: int = 0
    total_scheduled_delay_ms: int = 0
    total_bandwidth_wait_ms: int = 0
    active_clients: int = 0
    current_phase: str = "idle"
    outage_active: bool = False
    config_proxy_requests: int = 0

    def snapshot(self, *, started_at_monotonic: float, scenario_name: str) -> dict[str, Any]:
        payload = asdict(self)
        payload["scenario_name"] = scenario_name
        payload["process_uptime_s"] = round(time.monotonic() - started_at_monotonic, 3)
        return payload


class ProxyFrameLogger:
    HEADER = [
        "timestamp",
        "session_id",
        "phase_name",
        "event",
        "payload_bytes",
        "scheduled_delay_ms",
        "bandwidth_wait_ms",
        "total_wait_ms",
        "outage",
        "upstream_received_ms",
        "downstream_sent_ms",
    ]

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = path.open("a", encoding="utf-8", newline="")
        self._writer = csv.writer(self._file)
        if self._file.tell() == 0:
            self._writer.writerow(self.HEADER)
            self._file.flush()

    def log(
        self,
        *,
        session_id: int,
        action: ImpairmentAction,
        event: str,
        payload_bytes: int,
        upstream_received_ms: int,
        downstream_sent_ms: int | None,
    ) -> None:
        self._writer.writerow(
            [
                datetime.now(timezone.utc).isoformat(),
                session_id,
                action.phase_name,
                event,
                payload_bytes,
                action.scheduled_delay_ms,
                action.bandwidth_wait_ms,
                action.total_wait_ms,
                action.is_outage,
                upstream_received_ms,
                downstream_sent_ms if downstream_sent_ms is not None else "",
            ]
        )
        self._file.flush()

    def close(self) -> None:
        self._file.close()
