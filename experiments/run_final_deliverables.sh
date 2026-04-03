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

STAMP="$(get_setting STAMP "$(date +%Y%m%d)")"
MQTT_HOST="$(get_setting MQTT_HOST 127.0.0.1)"
MQTT_PORT="$(get_setting MQTT_PORT 1883)"
INTEL_LAB_INPUT="$(get_setting INTEL_LAB_INPUT "")"
AOT_INPUT="$(get_setting AOT_INPUT "")"
REPORT_DIR="$(get_setting REPORT_DIR ./report)"

if [[ -z "${INTEL_LAB_INPUT}" ]]; then
  echo "INTEL_LAB_INPUT must point to the Intel Lab raw data file." >&2
  exit 1
fi
if [[ -z "${AOT_INPUT}" ]]; then
  echo "AOT_INPUT must point to the AoT raw archive or extracted data file." >&2
  exit 1
fi

ARGS=(
  "./experiments/run_final_deliverables.py"
  "--intel-input" "${INTEL_LAB_INPUT}"
  "--aot-input" "${AOT_INPUT}"
  "--stamp" "${STAMP}"
  "--report-dir" "${REPORT_DIR}"
  "--mqtt-host" "${MQTT_HOST}"
  "--mqtt-port" "${MQTT_PORT}"
)

cd "${REPO_ROOT}"
"${PYTHON_EXE}" "${ARGS[@]}"
