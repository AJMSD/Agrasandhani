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

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
  PYTHON_EXE="${REPO_ROOT}/.venv/bin/python"
elif [[ -x "${REPO_ROOT}/.venv/Scripts/python.exe" ]]; then
  PYTHON_EXE="${REPO_ROOT}/.venv/Scripts/python.exe"
else
  PYTHON_EXE="python"
fi

RUN_ID="$(get_setting RUN_ID "$(date +%Y%m%d-%H%M%S)")"
MQTT_HOST="$(get_setting MQTT_HOST 127.0.0.1)"
MQTT_PORT="$(get_setting MQTT_PORT 1883)"
MQTT_QOS="$(get_setting MQTT_QOS 0)"
DATA_FILE="$(get_setting DATA_FILE ./simulator/sample_data.csv)"
SCENARIO_FILE="$(get_setting SCENARIO_FILE ./experiments/scenarios/demo_v0_vs_v4.json)"
DURATION_S="$(get_setting DURATION_S 20)"
REPLAY_SPEED="$(get_setting REPLAY_SPEED 2.0)"
SENSOR_LIMIT="$(get_setting SENSOR_LIMIT 0)"
BURST_ENABLED="$(get_setting BURST_ENABLED 1)"
BURST_START_S="$(get_setting BURST_START_S 2)"
BURST_DURATION_S="$(get_setting BURST_DURATION_S 4)"
BURST_SPEED_MULTIPLIER="$(get_setting BURST_SPEED_MULTIPLIER 8.0)"
BASELINE_GATEWAY_PORT="$(get_setting BASELINE_GATEWAY_PORT 8000)"
SMART_GATEWAY_PORT="$(get_setting SMART_GATEWAY_PORT 8001)"
BASELINE_PROXY_PORT="$(get_setting BASELINE_PROXY_PORT 9000)"
SMART_PROXY_PORT="$(get_setting SMART_PROXY_PORT 9001)"
NO_OPEN_BROWSER="$(get_setting NO_OPEN_BROWSER 0)"
AUTO_PORTS="$(get_setting AUTO_PORTS 0)"
CAPTURE_ARTIFACTS="$(get_setting CAPTURE_ARTIFACTS 0)"

ARGS=(
  "./experiments/run_demo.py"
  "--run-id" "m5-demo-${RUN_ID}"
  "--mqtt-host" "${MQTT_HOST}"
  "--mqtt-port" "${MQTT_PORT}"
  "--mqtt-qos" "${MQTT_QOS}"
  "--data-file" "${DATA_FILE}"
  "--scenario-file" "${SCENARIO_FILE}"
  "--duration-s" "${DURATION_S}"
  "--replay-speed" "${REPLAY_SPEED}"
  "--sensor-limit" "${SENSOR_LIMIT}"
  "--baseline-gateway-port" "${BASELINE_GATEWAY_PORT}"
  "--smart-gateway-port" "${SMART_GATEWAY_PORT}"
  "--baseline-proxy-port" "${BASELINE_PROXY_PORT}"
  "--smart-proxy-port" "${SMART_PROXY_PORT}"
  "--burst-start-s" "${BURST_START_S}"
  "--burst-duration-s" "${BURST_DURATION_S}"
  "--burst-speed-multiplier" "${BURST_SPEED_MULTIPLIER}"
)

if [[ "${BURST_ENABLED}" == "0" ]]; then
  ARGS+=("--no-burst-enabled")
fi

if [[ "${NO_OPEN_BROWSER}" == "1" ]]; then
  ARGS+=("--no-open-browser")
fi

if [[ "${AUTO_PORTS}" == "1" ]]; then
  ARGS+=("--auto-ports")
fi

if [[ "${CAPTURE_ARTIFACTS}" == "1" ]]; then
  ARGS+=("--capture-artifacts")
fi

cd "${REPO_ROOT}"
"${PYTHON_EXE}" "${ARGS[@]}"
