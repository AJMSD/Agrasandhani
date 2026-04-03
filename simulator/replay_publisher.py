from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import time
from pathlib import Path

from paho.mqtt import client as mqtt_client

try:
    from simulator.replay_timing import BurstConfig, compute_target_offset_s
except ModuleNotFoundError:  # pragma: no cover - script entrypoint fallback
    from replay_timing import BurstConfig, compute_target_offset_s

LOGGER = logging.getLogger(__name__)


def env_default(name: str, fallback: str) -> str:
    return os.getenv(name, fallback)


def env_default_bool(name: str, fallback: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return fallback

    normalized = raw_value.strip().lower()
    return normalized in {"1", "true", "yes", "on"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay CSV sensor data to MQTT topics")
    parser.add_argument(
        "--data-file",
        default=str(Path(__file__).resolve().parent / "sample_data.csv"),
        help="CSV file with sensor replay rows",
    )
    parser.add_argument("--mqtt-host", default=env_default("MQTT_HOST", "127.0.0.1"))
    parser.add_argument("--mqtt-port", type=int, default=int(env_default("MQTT_PORT", "1883")))
    parser.add_argument("--mqtt-qos", type=int, default=int(env_default("MQTT_QOS", "0")))
    parser.add_argument("--replay-speed", type=float, default=float(env_default("REPLAY_SPEED", "1.0")))
    parser.add_argument("--sensor-limit", type=int, default=int(env_default("SENSOR_LIMIT", "0")))
    parser.add_argument("--duration-s", type=int, default=int(env_default("DURATION_S", "0")))
    parser.add_argument("--run-id", default=env_default("RUN_ID", "dev"))
    parser.add_argument("--max-messages", type=int, default=0, help="Stop after publishing N messages")
    parser.add_argument(
        "--burst-enabled",
        action=argparse.BooleanOptionalAction,
        default=env_default_bool("BURST_ENABLED", False),
        help="Enable a scripted replay-speed burst window",
    )
    parser.add_argument("--burst-start-s", type=float, default=float(env_default("BURST_START_S", "0")))
    parser.add_argument("--burst-duration-s", type=float, default=float(env_default("BURST_DURATION_S", "0")))
    parser.add_argument(
        "--burst-speed-multiplier",
        type=float,
        default=float(env_default("BURST_SPEED_MULTIPLIER", "5.0")),
    )
    return parser.parse_args()


def load_rows(data_file: Path, sensor_limit: int) -> list[dict[str, object]]:
    if not data_file.exists():
        raise FileNotFoundError(f"CSV file not found: {data_file}")

    selected_sensors: list[str] = []
    rows: list[dict[str, object]] = []
    with data_file.open("r", encoding="utf-8", newline="") as input_file:
        reader = csv.DictReader(input_file)
        for row in reader:
            sensor_id = row["sensor_id"]
            if sensor_limit > 0 and sensor_id not in selected_sensors:
                if len(selected_sensors) >= sensor_limit:
                    continue
                selected_sensors.append(sensor_id)

            rows.append(
                {
                    "sensor_id": int(sensor_id) if sensor_id.isdigit() else sensor_id,
                    "msg_id": int(row["msg_id"]),
                    "ts_sent": int(row["ts_sent"]),
                    "metric_type": row["metric_type"],
                    "value": float(row["value"]),
                }
            )

    return rows


def wait_until(target_monotonic: float) -> None:
    while True:
        remaining = target_monotonic - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 0.1))


def publish_rows(
    *,
    client: mqtt_client.Client,
    rows: list[dict[str, object]],
    mqtt_qos: int,
    replay_speed: float,
    duration_s: int,
    max_messages: int,
    burst: BurstConfig,
) -> int:
    if not rows:
        LOGGER.warning("No rows available for replay")
        return 0

    published = 0
    source_start_ms = int(rows[0]["ts_sent"])
    replay_start_monotonic = time.monotonic()
    deadline_monotonic = replay_start_monotonic + duration_s if duration_s > 0 else None

    for row in rows:
        if max_messages > 0 and published >= max_messages:
            break
        if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
            break

        relative_ms = int(row["ts_sent"]) - source_start_ms
        target_offset_s = compute_target_offset_s(
            relative_ms=relative_ms,
            replay_speed=replay_speed,
            burst=burst,
        )
        target_monotonic = replay_start_monotonic + target_offset_s
        if deadline_monotonic is not None and target_monotonic > deadline_monotonic:
            break

        wait_until(target_monotonic)
        payload = {
            "sensor_id": row["sensor_id"],
            "msg_id": row["msg_id"],
            "ts_sent": time.time_ns() // 1_000_000,
            "metric_type": row["metric_type"],
            "value": row["value"],
        }
        payload_text = json.dumps(payload, separators=(",", ":"))
        info = client.publish(f"sensors/raw/{payload['metric_type']}", payload_text, qos=mqtt_qos)
        info.wait_for_publish()
        if info.rc != mqtt_client.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"Failed to publish MQTT message: rc={info.rc}")
        published += 1

    return published


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    args = parse_args()
    rows = load_rows(Path(args.data_file), args.sensor_limit)
    sensor_count = len({str(row["sensor_id"]) for row in rows})
    LOGGER.info(
        "Loaded %s rows from %s for run_id=%s across %s sensors",
        len(rows),
        args.data_file,
        args.run_id,
        sensor_count,
    )
    burst = BurstConfig(
        enabled=args.burst_enabled,
        start_s=max(args.burst_start_s, 0.0),
        duration_s=max(args.burst_duration_s, 0.0),
        speed_multiplier=max(args.burst_speed_multiplier, 1.0),
    )
    LOGGER.info(
        "Replay settings: speed=%sx duration_s=%s burst_enabled=%s burst_start_s=%s burst_duration_s=%s burst_speed_multiplier=%s",
        args.replay_speed,
        args.duration_s,
        burst.enabled,
        burst.start_s,
        burst.duration_s,
        burst.speed_multiplier,
    )

    client = mqtt_client.Client(
        mqtt_client.CallbackAPIVersion.VERSION2,
        client_id=f"agrasandhani-simulator-{args.run_id}",
    )
    client.connect(args.mqtt_host, args.mqtt_port)
    client.loop_start()
    try:
        published = publish_rows(
            client=client,
            rows=rows,
            mqtt_qos=args.mqtt_qos,
            replay_speed=args.replay_speed,
            duration_s=args.duration_s,
            max_messages=args.max_messages,
            burst=burst,
        )
    finally:
        client.disconnect()
        client.loop_stop()

    LOGGER.info("Published %s messages to MQTT", published)


if __name__ == "__main__":
    main()
