#!/usr/bin/env bash
set -euo pipefail

get_setting() {
  local name="$1"
  local default_value="$2"
  local value="${!name-}"
  if [[ -n "$value" ]]; then
    printf '%s' "$value"
  else
    printf '%s' "$default_value"
  fi
}

test_tcp_port() {
  local host="$1"
  local port="$2"
  python - "$host" "$port" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(1.0)
try:
    sock.connect((host, port))
except OSError:
    sys.exit(1)
finally:
    sock.close()
PY
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
  PYTHON_EXE="${REPO_ROOT}/.venv/bin/python"
elif [[ -x "${REPO_ROOT}/.venv/Scripts/python.exe" ]]; then
  PYTHON_EXE="${REPO_ROOT}/.venv/Scripts/python.exe"
else
  PYTHON_EXE="python"
fi

MQTT_HOST="$(get_setting MQTT_HOST 127.0.0.1)"
MQTT_PORT="$(get_setting MQTT_PORT 1883)"
MQTT_QOS="$(get_setting MQTT_QOS 0)"
WS_HOST="$(get_setting WS_HOST 127.0.0.1)"
WS_PORT="$(get_setting WS_PORT 8000)"
RUN_ID="$(get_setting RUN_ID "$(date +%Y%m%d-%H%M%S)")"
GATEWAY_MODE="$(get_setting GATEWAY_MODE v0)"
BATCH_WINDOW_MS="$(get_setting BATCH_WINDOW_MS 250)"
BATCH_MAX_MESSAGES="$(get_setting BATCH_MAX_MESSAGES 50)"
DUPLICATE_TTL_MS="$(get_setting DUPLICATE_TTL_MS 30000)"
VALUE_DEDUP_ENABLED="$(get_setting VALUE_DEDUP_ENABLED 0)"
FRESHNESS_TTL_MS="$(get_setting FRESHNESS_TTL_MS 1000)"
ADAPTIVE_MIN_BATCH_WINDOW_MS="$(get_setting ADAPTIVE_MIN_BATCH_WINDOW_MS 10)"
ADAPTIVE_MAX_BATCH_WINDOW_MS="$(get_setting ADAPTIVE_MAX_BATCH_WINDOW_MS 1000)"
ADAPTIVE_STEP_UP_MS="$(get_setting ADAPTIVE_STEP_UP_MS 100)"
ADAPTIVE_STEP_DOWN_MS="$(get_setting ADAPTIVE_STEP_DOWN_MS 50)"
ADAPTIVE_QUEUE_HIGH_WATERMARK="$(get_setting ADAPTIVE_QUEUE_HIGH_WATERMARK 25)"
ADAPTIVE_QUEUE_LOW_WATERMARK="$(get_setting ADAPTIVE_QUEUE_LOW_WATERMARK 5)"
ADAPTIVE_SEND_SLOW_MS="$(get_setting ADAPTIVE_SEND_SLOW_MS 40)"
ADAPTIVE_RECOVERY_STREAK="$(get_setting ADAPTIVE_RECOVERY_STREAK 3)"
REPLAY_SPEED="$(get_setting REPLAY_SPEED 1.0)"
SENSOR_LIMIT="$(get_setting SENSOR_LIMIT 0)"
DURATION_S="$(get_setting DURATION_S 60)"
BURST_ENABLED="$(get_setting BURST_ENABLED 0)"
BURST_START_S="$(get_setting BURST_START_S 0)"
BURST_DURATION_S="$(get_setting BURST_DURATION_S 0)"
BURST_SPEED_MULTIPLIER="$(get_setting BURST_SPEED_MULTIPLIER 5.0)"

if ! test_tcp_port "$MQTT_HOST" "$MQTT_PORT"; then
  echo "MQTT broker is not reachable at ${MQTT_HOST}:${MQTT_PORT}. Start Mosquitto before running this script." >&2
  exit 1
fi

RUN_DIR="${REPO_ROOT}/experiments/logs/${RUN_ID}"
mkdir -p "$RUN_DIR"

GATEWAY_STDOUT="${RUN_DIR}/gateway.stdout.log"
GATEWAY_STDERR="${RUN_DIR}/gateway.stderr.log"
SIMULATOR_STDOUT="${RUN_DIR}/simulator.stdout.log"
SIMULATOR_STDERR="${RUN_DIR}/simulator.stderr.log"
METRICS_JSON="${RUN_DIR}/metrics.json"

cleanup() {
  if [[ -n "${GATEWAY_PID:-}" ]]; then
    kill "${GATEWAY_PID}" >/dev/null 2>&1 || true
    wait "${GATEWAY_PID}" >/dev/null 2>&1 || true
  fi
}

trap cleanup EXIT

(
  cd "$REPO_ROOT"
  export MQTT_HOST MQTT_PORT MQTT_QOS WS_HOST WS_PORT RUN_ID GATEWAY_MODE BATCH_WINDOW_MS BATCH_MAX_MESSAGES DUPLICATE_TTL_MS VALUE_DEDUP_ENABLED
  export FRESHNESS_TTL_MS ADAPTIVE_MIN_BATCH_WINDOW_MS ADAPTIVE_MAX_BATCH_WINDOW_MS ADAPTIVE_STEP_UP_MS ADAPTIVE_STEP_DOWN_MS
  export ADAPTIVE_QUEUE_HIGH_WATERMARK ADAPTIVE_QUEUE_LOW_WATERMARK ADAPTIVE_SEND_SLOW_MS ADAPTIVE_RECOVERY_STREAK
  "$PYTHON_EXE" -m gateway.app
) >"$GATEWAY_STDOUT" 2>"$GATEWAY_STDERR" &
GATEWAY_PID=$!

sleep 3
if ! test_tcp_port "$WS_HOST" "$WS_PORT"; then
  echo "Gateway did not start on ${WS_HOST}:${WS_PORT}. Check ${GATEWAY_STDERR} for details." >&2
  exit 1
fi

(
  cd "$REPO_ROOT"
  export MQTT_HOST MQTT_PORT MQTT_QOS REPLAY_SPEED SENSOR_LIMIT DURATION_S BURST_ENABLED BURST_START_S BURST_DURATION_S BURST_SPEED_MULTIPLIER RUN_ID
  "$PYTHON_EXE" ./simulator/replay_publisher.py --data-file ./simulator/sample_data.csv
) >"$SIMULATOR_STDOUT" 2>"$SIMULATOR_STDERR"

"$PYTHON_EXE" - "$WS_HOST" "$WS_PORT" "$METRICS_JSON" <<'PY'
import json
import sys
import urllib.request

host, port, output_path = sys.argv[1], sys.argv[2], sys.argv[3]
with urllib.request.urlopen(f"http://{host}:{port}/metrics", timeout=5) as response:
    payload = json.load(response)
with open(output_path, "w", encoding="utf-8") as output_file:
    json.dump(payload, output_file, indent=2)
PY

echo "Run complete. Artifacts saved to ${RUN_DIR}"
