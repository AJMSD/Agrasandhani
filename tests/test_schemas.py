from __future__ import annotations

import unittest

from pydantic import ValidationError

from gateway.schemas import AggregatedFrame, SensorMessage


class SensorMessageTests(unittest.TestCase):
    def test_schema_accepts_valid_payload(self) -> None:
        message = SensorMessage.model_validate(
            {
                "sensor_id": 101,
                "msg_id": 7,
                "ts_sent": 1_700_000_000_123,
                "metric_type": "temperature",
                "value": 23.4,
            }
        )

        self.assertEqual(message.ui_key(), ("101", "temperature"))

    def test_schema_rejects_unknown_fields(self) -> None:
        with self.assertRaises(ValidationError):
            SensorMessage.model_validate(
                {
                    "sensor_id": "sensor-a",
                    "msg_id": 2,
                    "ts_sent": 1_700_000_000_123,
                    "metric_type": "humidity",
                    "value": 53.2,
                    "extra": "nope",
                }
            )

    def test_aggregate_frame_accepts_valid_payload(self) -> None:
        frame = AggregatedFrame.model_validate(
            {
                "kind": "aggregate_frame",
                "frame_id": 1,
                "mode": "v2",
                "flush_reason": "time",
                "window_started_ms": 1_700_000_000_000,
                "window_closed_ms": 1_700_000_000_250,
                "update_count": 1,
                "updates": [
                    {
                        "sensor_id": 101,
                        "msg_id": 7,
                        "ts_sent": 1_700_000_000_123,
                        "metric_type": "temperature",
                        "value": 23.4,
                    }
                ],
            }
        )

        self.assertEqual(frame.mode, "v2")
        self.assertEqual(frame.updates[0].duplicate_key(), ("101", 7))


if __name__ == "__main__":
    unittest.main()
