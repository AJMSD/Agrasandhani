#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MODE="from-existing"
STAMP="20260403"
INTEL_INPUT="${INTEL_INPUT:-}"
AOT_INPUT="${AOT_INPUT:-}"
INTEL_SWEEP_DIR=""
AOT_SWEEP_DIR=""
DEMO_DIR=""
INTEL_BATCH_SWEEP_DIR=""
INTEL_V1_V2_SWEEP_DIR=""
INTEL_ADAPTIVE_SWEEP_DIR=""
INTEL_ADAPTIVE_PARAMETER_SWEEP_DIR=""

usage() {
  cat <<'EOF'
Usage:
  experiments/reproduce_all.sh [--mode from-existing|from-raw] [--stamp YYYYMMDD]

Modes:
  --mode from-existing  Rebuild report/paper assets from existing April sweep logs (default).
  --mode from-raw       Run full deliverables pipeline from raw Intel/AoT inputs, then build assets.

Environment variables for --mode from-raw:
  INTEL_INPUT=/path/to/intel/data.txt.gz
  AOT_INPUT=/path/to/aot/archive-or-data
EOF
}

load_existing_dirs_from_manifest() {
  local manifest_path="$ROOT_DIR/report/assets/evidence_manifest.json"
  if [[ ! -f "$manifest_path" ]]; then
    echo "Missing canonical evidence manifest: $manifest_path" >&2
    exit 1
  fi

  while IFS='=' read -r key value; do
    value="${value//\\//}"
    case "$key" in
      intel_sweep_dir) INTEL_SWEEP_DIR="$ROOT_DIR/$value" ;;
      aot_sweep_dir) AOT_SWEEP_DIR="$ROOT_DIR/$value" ;;
      demo_dir) DEMO_DIR="$ROOT_DIR/$value" ;;
      intel_batch_sweep_dir) INTEL_BATCH_SWEEP_DIR="${value:+$ROOT_DIR/$value}" ;;
      intel_v1_v2_sweep_dir) INTEL_V1_V2_SWEEP_DIR="${value:+$ROOT_DIR/$value}" ;;
      intel_adaptive_sweep_dir) INTEL_ADAPTIVE_SWEEP_DIR="${value:+$ROOT_DIR/$value}" ;;
      intel_adaptive_parameter_sweep_dir) INTEL_ADAPTIVE_PARAMETER_SWEEP_DIR="${value:+$ROOT_DIR/$value}" ;;
    esac
  done < <(
    python - "$manifest_path" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
for key in (
    "intel_sweep_dir",
    "aot_sweep_dir",
    "demo_dir",
    "intel_batch_sweep_dir",
    "intel_v1_v2_sweep_dir",
    "intel_adaptive_sweep_dir",
    "intel_adaptive_parameter_sweep_dir",
):
    print(f"{key}={manifest.get(key) or ''}")
PY
  )
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="$2"
      shift 2
      ;;
    --stamp)
      STAMP="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ "$MODE" == "from-raw" ]]; then
  INTEL_SWEEP_DIR="$ROOT_DIR/experiments/logs/final-intel-primary-${STAMP}"
  AOT_SWEEP_DIR="$ROOT_DIR/experiments/logs/final-aot-validation-${STAMP}"
  DEMO_DIR="$ROOT_DIR/experiments/logs/final-demo-${STAMP}/demo"
  INTEL_BATCH_SWEEP_DIR="$ROOT_DIR/experiments/logs/intel-v2-batch-window-${STAMP}"
  INTEL_V1_V2_SWEEP_DIR="$ROOT_DIR/experiments/logs/intel-v1-v2-isolation-${STAMP}"
  INTEL_ADAPTIVE_SWEEP_DIR="$ROOT_DIR/experiments/logs/intel-v2-v3-adaptive-20260404"
  if [[ -z "$INTEL_INPUT" || -z "$AOT_INPUT" ]]; then
    echo "INTEL_INPUT and AOT_INPUT must be set for --mode from-raw" >&2
    exit 1
  fi

  python "$ROOT_DIR/experiments/run_final_deliverables.py" \
    --intel-input "$INTEL_INPUT" \
    --aot-input "$AOT_INPUT" \
    --stamp "$STAMP"
else
  load_existing_dirs_from_manifest
  if [[ ! -d "$INTEL_SWEEP_DIR" || ! -d "$AOT_SWEEP_DIR" || ! -d "$DEMO_DIR" ]]; then
    echo "Expected existing sweep directories not found for stamp $STAMP." >&2
    echo "Missing one of:" >&2
    echo "  $INTEL_SWEEP_DIR" >&2
    echo "  $AOT_SWEEP_DIR" >&2
    echo "  $DEMO_DIR" >&2
    exit 1
  fi
fi

BUILD_REPORT_ARGS=(
  python "$ROOT_DIR/experiments/build_report_assets.py"
  --intel-sweep-dir "$INTEL_SWEEP_DIR"
  --aot-sweep-dir "$AOT_SWEEP_DIR"
  --demo-dir "$DEMO_DIR"
  --output-dir "$ROOT_DIR/report/assets"
)
if [[ -n "$INTEL_BATCH_SWEEP_DIR" ]]; then
  BUILD_REPORT_ARGS+=(--intel-batch-sweep-dir "$INTEL_BATCH_SWEEP_DIR")
fi
if [[ -n "$INTEL_V1_V2_SWEEP_DIR" ]]; then
  BUILD_REPORT_ARGS+=(--intel-v1-v2-sweep-dir "$INTEL_V1_V2_SWEEP_DIR")
fi
if [[ -n "$INTEL_ADAPTIVE_SWEEP_DIR" ]]; then
  BUILD_REPORT_ARGS+=(--intel-adaptive-sweep-dir "$INTEL_ADAPTIVE_SWEEP_DIR")
fi
if [[ -n "$INTEL_ADAPTIVE_PARAMETER_SWEEP_DIR" ]]; then
  BUILD_REPORT_ARGS+=(--intel-adaptive-parameter-sweep-dir "$INTEL_ADAPTIVE_PARAMETER_SWEEP_DIR")
fi
"${BUILD_REPORT_ARGS[@]}"

python "$ROOT_DIR/experiments/build_run_registry.py" \
  --manifest-path "$ROOT_DIR/report/assets/evidence_manifest.json" \
  --output "$ROOT_DIR/experiments/logs/run_registry.json"

python "$ROOT_DIR/experiments/package_paper_assets.py" \
  --report-assets-dir "$ROOT_DIR/report/assets" \
  --paper-dir "$ROOT_DIR/research_paper"

echo "Reproducibility pipeline complete."
echo "Report assets: $ROOT_DIR/report/assets"
echo "Paper figures: $ROOT_DIR/research_paper/figures"
echo "Paper tables: $ROOT_DIR/research_paper/tables"
echo "Claim map: $ROOT_DIR/report/assets/CLAIM_TO_EVIDENCE_MAP.md"
