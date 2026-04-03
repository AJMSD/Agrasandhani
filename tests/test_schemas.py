from __future__ import annotations

import unittest

from pydantic import ValidationError

from gateway.schemas import SensorMessage


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


if __name__ == "__main__":
    unittest.main()
