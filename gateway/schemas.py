from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, ConfigDict, Field

SensorId = Union[str, int]


class SensorMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sensor_id: SensorId
    msg_id: int = Field(ge=0)
    ts_sent: int = Field(ge=0, description="Unix epoch timestamp in milliseconds")
    metric_type: str = Field(min_length=1)
    value: float

    def ui_key(self) -> tuple[str, str]:
        return (str(self.sensor_id), self.metric_type)

    def duplicate_key(self) -> tuple[str, int]:
        return (str(self.sensor_id), self.msg_id)


class AggregatedFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["aggregate_frame"] = "aggregate_frame"
    frame_id: int = Field(ge=1)
    mode: Literal["v1", "v2"]
    flush_reason: Literal["time", "threshold"]
    window_started_ms: int = Field(ge=0)
    window_closed_ms: int = Field(ge=0)
    update_count: int = Field(ge=0)
    updates: list[SensorMessage]
