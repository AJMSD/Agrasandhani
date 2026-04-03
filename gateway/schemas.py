from __future__ import annotations

from typing import Union

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
