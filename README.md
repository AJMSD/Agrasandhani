# Agrasandhani

Agrasandhani is a local MQTT-to-WebSocket sensor gateway for replaying datasets into a minimal dashboard. It now supports the baseline forward-every-message path plus M4 tooling for batching, exact duplicate suppression, latest-per-sensor compaction, adaptive publish cadence, runtime-tunable freshness TTLs, reconnect-safe last-known-good snapshots, and deterministic impairment experiments.

## Stack

- Python 3.11+
- Mosquitto broker
- `paho-mqtt`
- FastAPI + uvicorn
- Static HTML + browser WebSocket client
- Node.js + Playwright for experiment capture

## Repo Layout

- `simulator/replay_publisher.py`: reads CSV rows and publishes MQTT messages to `sensors/raw/<metric_type>`
- `simulator/sample_data.csv`: checked-in synthetic sample dataset
- `simulator/generate_sample_data.py`: regenerates the sample CSV
- `simulator/preprocess_aot.py`: normalizes local AoT archives into replay-ready CSV
- `simulator/preprocess_intel_lab.py`: normalizes local Intel Lab readings into replay-ready CSV
- `simulator/datasets/aot_sample.csv`: checked-in normalized AoT example output
- `simulator/datasets/intel_lab_sample.csv`: checked-in normalized Intel Lab example output
- `gateway/app.py`: FastAPI app with `/health`, `/metrics`, `/config`, `/ws`, and static UI serving
- `gateway/mqtt_ingest.py`: MQTT subscriber that pushes broker messages into an internal queue
- `gateway/forwarder.py`: gateway forwarding modes, aggregate-frame batching, metrics, and CSV run logger
- `gateway/schemas.py`: shared payload validation
- `ui/index.html`: dashboard with live measurement counters and display-event CSV export
- `ui/demo_compare.html`: side-by-side baseline-versus-smart demo page
- `experiments/run_one.ps1`: standard 60s run harness
- `experiments/run_one.sh`: standard 60s run harness for macOS/Linux
- `experiments/impairment_proxy.py`: app-layer impairment proxy that serves the dashboard and proxies `/ws` plus `/config`
- `experiments/scenarios/*.json`: deterministic impairment phase definitions
- `experiments/run_sweep.py`: comparison runner for `v0`, `v2`, and `v4` scenario sweeps
- `experiments/run_demo.py`: live demo runner for simultaneous `v0` versus `v4` comparison
- `experiments/run_demo.ps1`: PowerShell wrapper for the M5 demo harness
- `experiments/run_demo.sh`: Bash wrapper for the M5 demo harness
- `experiments/analyze_run.py`: derives latency, bandwidth, loss, lateness, and freshness metrics
- `experiments/plot_sweep.py`: generates sweep plots from per-run summaries

## Message Schema

Every MQTT payload uses this exact JSON shape:

```json
{
  "sensor_id": 101,
  "msg_id": 1,
  "ts_sent": 1712050000000,
  "metric_type": "temperature",
  "value": 20.5
}
```

The simulator preserves pacing from the CSV timestamps, but rewrites outgoing `ts_sent` to the real publish time so latency instrumentation is based on actual sends.

WebSocket outputs depend on `GATEWAY_MODE`:

- `v0`: emits the raw `SensorMessage` payload above for each accepted MQTT message
- `v1` and `v2`: emit a fixed-window aggregate frame envelope
- `v3`: emits aggregate frames with adaptive window control based on queue depth and downstream send cost
- `v4`: emits the same adaptive aggregate frames as `v3` and also sends a snapshot frame containing the current last-known-good state to newly connected dashboards

```json
{
  "kind": "aggregate_frame",
  "frame_id": 3,
  "mode": "v4",
  "flush_reason": "time",
  "window_started_ms": 1712050000000,
  "window_closed_ms": 1712050000250,
  "update_count": 2,
  "updates": [
    {
      "sensor_id": 101,
      "msg_id": 9,
      "ts_sent": 1712050000200,
      "metric_type": "temperature",
      "value": 20.9
    }
  ]
}
```

`flush_reason` is `time`, `threshold`, or `snapshot`. Snapshot frames are sent only to a newly connected client and repopulate the UI with the current LKG view.

## Real Dataset Preprocessing

The repo includes reproducible preprocessors for the two real replay sources used in the evaluation. Raw source archives stay local; only small normalized outputs are checked in under `simulator/datasets/`.

### Array of Things (AoT)

Official archive source:

- `https://www.mcs.anl.gov/research/projects/waggle/downloads/datasets/AoT_Chicago.complete.latest.tar`

The AoT archive contains `data.csv.gz` and `sensors.csv`. The preprocessor keeps only temperature and humidity measurements and converts them into the unified replay schema.

```powershell
python .\simulator\preprocess_aot.py `
  --input C:\path\to\AoT_Chicago.complete.latest.tar `
  --output .\simulator\datasets\aot_sample.csv `
  --sensor-limit 2 `
  --rows-per-sensor 6
```

```bash
python ./simulator/preprocess_aot.py \
  --input /path/to/AoT_Chicago.complete.latest.tar \
  --output ./simulator/datasets/aot_sample.csv \
  --sensor-limit 2 \
  --rows-per-sensor 6
```

Notes:

- `--input` can be an extracted AoT directory, the `.tar` archive, `data.csv`, or `data.csv.gz`
- when AoT timestamps are naive, the script interprets them as `America/Chicago` and falls back to a fixed UTC-06 offset if the host lacks timezone data
- `rows-per-sensor` applies after normalization, so temperature and humidity rows count separately

### Intel Berkeley Research Lab Sensor Data

Official source page:

- `https://db.csail.mit.edu/labdata/labdata.html`

Download the readings file from that page, then normalize it into the unified replay schema. The preprocessor emits temperature, humidity, light, and voltage rows.

```powershell
python .\simulator\preprocess_intel_lab.py `
  --input C:\path\to\data.txt.gz `
  --output .\simulator\datasets\intel_lab_sample.csv `
  --sensor-limit 2 `
  --rows-per-sensor 8
```

```bash
python ./simulator/preprocess_intel_lab.py \
  --input /path/to/data.txt.gz \
  --output ./simulator/datasets/intel_lab_sample.csv \
  --sensor-limit 2 \
  --rows-per-sensor 8
```

Checked-in normalized examples:

- `simulator/datasets/aot_sample.csv`
- `simulator/datasets/intel_lab_sample.csv`

## Setup

This foundation is intended to run on Windows, macOS, and Linux. The Python services are cross-platform; the experiment harness now has one script per shell environment.

1. Create a virtual environment and install the Python dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

2. Make sure `mosquitto` is installed.
   On Windows, if it is not on `PATH`, the default executable path is usually `C:\Program Files\mosquitto\mosquitto.exe`.

3. Install the browser automation dependency for M4 runs:

```powershell
npm install
npx playwright install chromium
```

You can verify the browser-capture prerequisites without starting a run:

```powershell
node .\experiments\capture_dashboard.mjs --check-only
```

```bash
node ./experiments/capture_dashboard.mjs --check-only
```

```bash
npm install
npx playwright install chromium
```

4. Regenerate the sample dataset if needed:

```powershell
python .\simulator\generate_sample_data.py
```

```bash
python ./simulator/generate_sample_data.py
```

## Run Components Manually

Start the MQTT broker:

```powershell
mosquitto -p 1883 -v
```

If `mosquitto` is not on `PATH` in PowerShell:

```powershell
& "C:\Program Files\mosquitto\mosquitto.exe" -p 1883 -v
```

```bash
mosquitto -p 1883 -v
```

Start the gateway:

```powershell
$env:MQTT_HOST = "127.0.0.1"
$env:MQTT_PORT = "1883"
$env:MQTT_QOS = "0"
$env:WS_HOST = "127.0.0.1"
$env:WS_PORT = "8000"
$env:RUN_ID = "manual-baseline"
$env:GATEWAY_MODE = "v4"
$env:BATCH_WINDOW_MS = "250"
$env:BATCH_MAX_MESSAGES = "50"
$env:DUPLICATE_TTL_MS = "30000"
$env:VALUE_DEDUP_ENABLED = "0"
$env:FRESHNESS_TTL_MS = "1000"
$env:ADAPTIVE_MIN_BATCH_WINDOW_MS = "10"
$env:ADAPTIVE_MAX_BATCH_WINDOW_MS = "1000"
$env:ADAPTIVE_STEP_UP_MS = "100"
$env:ADAPTIVE_STEP_DOWN_MS = "50"
$env:ADAPTIVE_QUEUE_HIGH_WATERMARK = "25"
$env:ADAPTIVE_QUEUE_LOW_WATERMARK = "5"
$env:ADAPTIVE_SEND_SLOW_MS = "40"
$env:ADAPTIVE_RECOVERY_STREAK = "3"
python -m gateway.app
```

```bash
export MQTT_HOST=127.0.0.1
export MQTT_PORT=1883
export MQTT_QOS=0
export WS_HOST=127.0.0.1
export WS_PORT=8000
export RUN_ID=manual-baseline
export GATEWAY_MODE=v4
export BATCH_WINDOW_MS=250
export BATCH_MAX_MESSAGES=50
export DUPLICATE_TTL_MS=30000
export VALUE_DEDUP_ENABLED=0
export FRESHNESS_TTL_MS=1000
export ADAPTIVE_MIN_BATCH_WINDOW_MS=10
export ADAPTIVE_MAX_BATCH_WINDOW_MS=1000
export ADAPTIVE_STEP_UP_MS=100
export ADAPTIVE_STEP_DOWN_MS=50
export ADAPTIVE_QUEUE_HIGH_WATERMARK=25
export ADAPTIVE_QUEUE_LOW_WATERMARK=5
export ADAPTIVE_SEND_SLOW_MS=40
export ADAPTIVE_RECOVERY_STREAK=3
python -m gateway.app
```

Open the dashboard:

```powershell
Start-Process http://127.0.0.1:8000/ui/index.html
```

```bash
open http://127.0.0.1:8000/ui/index.html
# Linux alternative:
# xdg-open http://127.0.0.1:8000/ui/index.html
```

Run the simulator:

```powershell
$env:MQTT_HOST = "127.0.0.1"
$env:MQTT_PORT = "1883"
$env:MQTT_QOS = "0"
$env:REPLAY_SPEED = "1.0"
$env:SENSOR_LIMIT = "0"
$env:DURATION_S = "10"
$env:RUN_ID = "manual-baseline"
python .\simulator\replay_publisher.py --data-file .\simulator\sample_data.csv
```

```bash
export MQTT_HOST=127.0.0.1
export MQTT_PORT=1883
export MQTT_QOS=0
export REPLAY_SPEED=1.0
export SENSOR_LIMIT=0
export DURATION_S=10
export RUN_ID=manual-baseline
python ./simulator/replay_publisher.py --data-file ./simulator/sample_data.csv
```

Replay one of the normalized real-dataset samples instead of the synthetic scaffold:

```powershell
python .\simulator\replay_publisher.py --data-file .\simulator\datasets\aot_sample.csv
python .\simulator\replay_publisher.py --data-file .\simulator\datasets\intel_lab_sample.csv
```

```bash
python ./simulator/replay_publisher.py --data-file ./simulator/datasets/aot_sample.csv
python ./simulator/replay_publisher.py --data-file ./simulator/datasets/intel_lab_sample.csv
```

Optional burst injection uses the replay clock, not the raw timestamps. Example burst configuration:

```powershell
$env:BURST_ENABLED = "1"
$env:BURST_START_S = "5"
$env:BURST_DURATION_S = "10"
$env:BURST_SPEED_MULTIPLIER = "8"
python .\simulator\replay_publisher.py --data-file .\simulator\datasets\aot_sample.csv
```

```bash
export BURST_ENABLED=1
export BURST_START_S=5
export BURST_DURATION_S=10
export BURST_SPEED_MULTIPLIER=8
python ./simulator/replay_publisher.py --data-file ./simulator/datasets/aot_sample.csv
```

## Sanity Test

With the broker and gateway running:

```powershell
python .\simulator\replay_publisher.py --data-file .\simulator\sample_data.csv --max-messages 5
```

```bash
python ./simulator/replay_publisher.py --data-file ./simulator/sample_data.csv --max-messages 5
```

Expected result:

- the UI updates with sensor rows
- `/health` returns `status: ok`
- `/metrics` shows non-zero `mqtt_in_msgs`, `latest_sensor_count`, and mode-specific outbound counters
- the dashboard shows non-zero `Update Rate` and `WebSocket FPS` under traffic
- the dashboard records display-side timing events and can export them as CSV
- `experiments/logs/<RUN_ID>/gateway_forward_log.csv` contains one row per emitted sensor update with frame metadata

UI measurement notes:

- `Stale Count` uses the active runtime TTL from `/config`, not a hard-coded client constant
- `window.agrasandhaniMeasurements.summary` exposes the current dashboard counters for inspection
- `window.agrasandhaniMeasurements.events` contains the in-memory per-frame display log
- `window.agrasandhaniMeasurements.exportCsv()` returns the same CSV content used by the export button

Useful checks:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/metrics
Invoke-RestMethod http://127.0.0.1:8000/config
```

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/metrics
curl http://127.0.0.1:8000/config
```

Runtime tuning example:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/config -Method Patch -ContentType "application/json" -Body '{"batch_window_ms":350,"freshness_ttl_ms":1500}'
Invoke-RestMethod http://127.0.0.1:8000/config -Method Patch -ContentType "application/json" -Body '{"duplicate_ttl_ms":5000}'
```

```bash
curl -X PATCH http://127.0.0.1:8000/config \
  -H "Content-Type: application/json" \
  -d '{"batch_window_ms":350,"freshness_ttl_ms":1500}'
curl -X PATCH http://127.0.0.1:8000/config \
  -H "Content-Type: application/json" \
  -d '{"duplicate_ttl_ms":5000}'
```

## Standard 60s Run

After starting Mosquitto, run the repeatable harness:

```powershell
.\experiments\run_one.ps1
```

```bash
chmod +x ./experiments/run_one.sh
./experiments/run_one.sh
```

Optional overrides:

```powershell
$env:RUN_ID = "session-001"
$env:GATEWAY_MODE = "v4"
$env:BATCH_WINDOW_MS = "250"
$env:BATCH_MAX_MESSAGES = "50"
$env:DUPLICATE_TTL_MS = "30000"
$env:VALUE_DEDUP_ENABLED = "0"
$env:FRESHNESS_TTL_MS = "1000"
$env:ADAPTIVE_MIN_BATCH_WINDOW_MS = "10"
$env:ADAPTIVE_MAX_BATCH_WINDOW_MS = "1000"
$env:ADAPTIVE_STEP_UP_MS = "100"
$env:ADAPTIVE_STEP_DOWN_MS = "50"
$env:ADAPTIVE_QUEUE_HIGH_WATERMARK = "25"
$env:ADAPTIVE_QUEUE_LOW_WATERMARK = "5"
$env:ADAPTIVE_SEND_SLOW_MS = "40"
$env:ADAPTIVE_RECOVERY_STREAK = "3"
$env:DURATION_S = "60"
$env:REPLAY_SPEED = "1.0"
$env:SENSOR_LIMIT = "0"
$env:MQTT_QOS = "0"
$env:BURST_ENABLED = "0"
$env:BURST_START_S = "0"
$env:BURST_DURATION_S = "0"
$env:BURST_SPEED_MULTIPLIER = "5"
.\experiments\run_one.ps1
```

```bash
export RUN_ID=session-001
export GATEWAY_MODE=v4
export BATCH_WINDOW_MS=250
export BATCH_MAX_MESSAGES=50
export DUPLICATE_TTL_MS=30000
export VALUE_DEDUP_ENABLED=0
export FRESHNESS_TTL_MS=1000
export ADAPTIVE_MIN_BATCH_WINDOW_MS=10
export ADAPTIVE_MAX_BATCH_WINDOW_MS=1000
export ADAPTIVE_STEP_UP_MS=100
export ADAPTIVE_STEP_DOWN_MS=50
export ADAPTIVE_QUEUE_HIGH_WATERMARK=25
export ADAPTIVE_QUEUE_LOW_WATERMARK=5
export ADAPTIVE_SEND_SLOW_MS=40
export ADAPTIVE_RECOVERY_STREAK=3
export DURATION_S=60
export REPLAY_SPEED=1.0
export SENSOR_LIMIT=0
export MQTT_QOS=0
export BURST_ENABLED=0
export BURST_START_S=0
export BURST_DURATION_S=0
export BURST_SPEED_MULTIPLIER=5
./experiments/run_one.sh
```

Outputs are written to `experiments/logs/<RUN_ID>/`:

- `gateway_forward_log.csv`: per-message timing log with frame window and adaptation decision columns
- `gateway.stdout.log` and `gateway.stderr.log`
- `simulator.stdout.log` and `simulator.stderr.log`
- `metrics.json`: final `/metrics` snapshot

## M4 Impairment Sweeps

The impairment proxy runs in front of the normal gateway and serves the same dashboard UI from its own port. It applies app-layer loss, delay/jitter, bandwidth shaping, and outage phases without changing the existing WebSocket payload contract.

Default scenario files:

- `clean`
- `bandwidth_200kbps`
- `loss_2pct`
- `loss_5pct`
- `delay_50ms_jitter20ms`
- `outage_5s`

Run the default minimal matrix:

```powershell
python .\experiments\run_sweep.py --burst-enabled
```

```bash
python ./experiments/run_sweep.py --burst-enabled
```

Run the reusable short smoke profile for post-change validation:

```powershell
python .\experiments\run_sweep.py --profile short-smoke
```

```bash
python ./experiments/run_sweep.py --profile short-smoke
```

The short smoke profile exercises `v0`, `v2`, and `v4` with QoS `0` and `1` across `clean`, `loss_5pct`, and `outage_5s` using a 16-second replay window and a 20-sensor cap so loss and outage effects surface reliably during validation.

Useful overrides:

```powershell
python .\experiments\run_sweep.py `
  --sweep-id m4-short `
  --variants v0,v2,v4 `
  --qos 0,1 `
  --scenarios clean,loss_2pct,outage_5s `
  --duration-s 20 `
  --data-file .\simulator\datasets\intel_lab_sample.csv
```

```bash
python ./experiments/run_sweep.py \
  --sweep-id m4-short \
  --variants v0,v2,v4 \
  --qos 0,1 \
  --scenarios clean,loss_2pct,outage_5s \
  --duration-s 20 \
  --data-file ./simulator/datasets/intel_lab_sample.csv
```

Each run directory under `experiments/logs/<SWEEP_ID>/` includes:

- `manifest.json`
- `gateway_forward_log.csv`
- `proxy_frame_log.csv`
- `gateway_metrics.json`
- `proxy_metrics.json`
- `dashboard_measurements.csv`
- `dashboard_summary.json`
- `dashboard.png`
- `summary.json`, `summary.csv`, and `timeseries.csv`

Analysis notes:

- current runs use exact missing-update matching on `(sensor_id, metric_type, msg_id, ts_sent)`
- older `gateway_forward_log.csv` files without `metric_type` are marked as approximate in `summary.json`
- use `matching_mode` and `missing_update_count_exact` in the summary to distinguish exact vs legacy analysis
- use `proxy_frame_alignment_mode` to tell whether missing-update cause attribution was derived from exact gateway/proxy frame alignment or skipped as unavailable
- `missing_updates_outage_drop_count`, `missing_updates_non_outage_drop_count`, `missing_updates_delivered_frame_count`, and `missing_updates_unclassified_count` break missing updates down by proxy-frame outcome when alignment is available
Sweep-level plots are written to `experiments/logs/<SWEEP_ID>/plots/`.

Optional Linux-only `tc netem` cross-checks are available through `experiments/netem/apply_netem.sh`. They are not required for the default Windows/macOS workflow:

```bash
chmod +x ./experiments/netem/apply_netem.sh
./experiments/netem/apply_netem.sh eth0 clean
./experiments/netem/apply_netem.sh eth0 delay_50ms_jitter20ms
sudo tc qdisc del dev eth0 root
```

## M5 Demo

The M5 demo harness runs the baseline `v0` gateway and the smart `v4` gateway at the same time against the same MQTT replay feed and the same deterministic impairment scenario. It opens a side-by-side compare page so the burst, stale, and recovery differences are visible live.

Default demo behavior:

- scenario: `experiments/scenarios/demo_v0_vs_v4.json` with `6s clean`, `4s outage`, and `10s recovery`
- simulator run: `20s` total with burst enabled at `2s` for `4s` using an `8x` burst multiplier
- ports: baseline gateway `8000`, smart gateway `8001`, baseline proxy `9000`, smart proxy `9001`
- compare page: served from the baseline proxy at `/ui/demo_compare.html`
- default behavior remains fail-fast if those demo ports are already occupied
- browser output capture is off by default and only runs when explicitly requested

One-command launch:

```powershell
.\experiments\run_demo.ps1
```

```bash
chmod +x ./experiments/run_demo.sh
./experiments/run_demo.sh
```

Direct Python entrypoint:

```powershell
python .\experiments\run_demo.py
```

```bash
python ./experiments/run_demo.py
```

Non-interactive smoke run:

```powershell
python .\experiments\run_demo.py --run-id m5-demo-smoke --no-open-browser
```

```bash
python ./experiments/run_demo.py --run-id m5-demo-smoke --no-open-browser
```

Optional additive flags:

- `--auto-ports`: if one of the default demo ports is busy, reassign only the conflicting services to free ports and record the effective ports in `manifest.json`
- `--capture-artifacts`: capture baseline and smart dashboard CSV, summaries, screenshots, plus a final `demo_compare.png` screenshot

Examples:

```powershell
python .\experiments\run_demo.py --run-id m5-demo-auto --no-open-browser --auto-ports
python .\experiments\run_demo.py --run-id m5-demo-capture --no-open-browser --capture-artifacts
```

```bash
python ./experiments/run_demo.py --run-id m5-demo-auto --no-open-browser --auto-ports
python ./experiments/run_demo.py --run-id m5-demo-capture --no-open-browser --capture-artifacts
```

Wrapper toggles:

- `AUTO_PORTS=1` enables `--auto-ports`
- `CAPTURE_ARTIFACTS=1` enables `--capture-artifacts`

Expected live differences:

- `v0` shows higher update-rate churn during the burst window because every incoming message is forwarded directly
- `v4` shifts to aggregate frames, keeps the display steadier, and shows the runtime batch window in the dashboard summary
- during the outage phase both sides stop receiving frames, but `v4` keeps the last-known-good rows visible and marks them stale once the TTL expires
- after recovery the `v4` side should settle back into a cleaner cadence more quickly than the raw baseline feed

Outputs are written to `experiments/logs/<RUN_ID>/demo/`:

- `baseline_gateway.stdout.log`, `baseline_gateway.stderr.log`
- `smart_gateway.stdout.log`, `smart_gateway.stderr.log`
- `baseline_proxy.stdout.log`, `baseline_proxy.stderr.log`
- `smart_proxy.stdout.log`, `smart_proxy.stderr.log`
- `simulator.stdout.log`, `simulator.stderr.log`
- `baseline_gateway_metrics.json`, `smart_gateway_metrics.json`
- `baseline_proxy_metrics.json`, `smart_proxy_metrics.json`
- `baseline_gateway_forward_log.csv`, `smart_gateway_forward_log.csv`
- `baseline_proxy_frame_log.csv`, `smart_proxy_frame_log.csv`
- `manifest.json` with the compare URL and effective demo configuration

When `--capture-artifacts` is enabled, the same demo directory also includes:

- `baseline_dashboard/dashboard_measurements.csv`
- `baseline_dashboard/dashboard_summary.json`
- `baseline_dashboard/dashboard.png`
- `smart_dashboard/dashboard_measurements.csv`
- `smart_dashboard/dashboard_summary.json`
- `smart_dashboard/dashboard.png`
- `demo_compare.png`

## Reproducibility

The main reproducibility paths are kept here so the remote repository has a single documentation entrypoint. Experiment logs remain local under `experiments/logs/`; only compact derived evidence assets and the paper package are intended for version control.

End-to-end runner:

```powershell
$env:INTEL_LAB_INPUT = "C:\path\to\data.txt.gz"
$env:AOT_INPUT = "C:\path\to\chicago-complete.weekly.2019-09-30-to-2019-10-06.tar"
.\experiments\run_final_deliverables.ps1
```

```bash
export INTEL_LAB_INPUT=/path/to/data.txt.gz
export AOT_INPUT=/path/to/chicago-complete.weekly.2019-09-30-to-2019-10-06.tar
./experiments/run_final_deliverables.sh
```

This runner preprocesses the raw datasets into ignored replay CSVs under `experiments/logs/generated_inputs/`, executes the Intel primary sweep plus the AoT validation sweep, captures the final M5 demo, and regenerates the tracked report assets. The large logs remain local-only under `experiments/logs/`; only the derived report package is intended to be committed.

Regenerate plots, tables, run registry, and paper assets from existing frozen evidence:

```powershell
bash ./experiments/reproduce_all.sh --mode from-existing
```

If bash is unavailable on Windows, run the equivalent Python steps:

```powershell
python .\experiments\build_report_assets.py `
  --intel-sweep-dir .\experiments\logs\final-intel-primary-replicated-20260408-135251 `
  --aot-sweep-dir .\experiments\logs\final-aot-validation-replicated-20260408-135251 `
  --demo-dir .\experiments\logs\final-demo-20260403\demo `
  --intel-batch-sweep-dir .\experiments\logs\intel-v2-batch-window-replicated-20260408-135251 `
  --intel-v1-v2-sweep-dir .\experiments\logs\intel-v1-v2-isolation-replicated-20260408-135251 `
  --intel-adaptive-sweep-dir .\experiments\logs\intel-v2-v3-adaptive-replicated-20260408-135251 `
  --intel-adaptive-parameter-sweep-dir .\experiments\logs\intel-v3-adaptive-parameter-sweep-20260408-190517 `
  --output-dir .\report\assets

python .\experiments\build_run_registry.py `
  --manifest-path .\report\assets\evidence_manifest.json `
  --output .\experiments\logs\run_registry.json

python .\experiments\package_paper_assets.py `
  --report-assets-dir .\report\assets `
  --paper-dir .\research_paper
```

Current frozen evidence roots:

- `experiments/logs/final-intel-primary-replicated-20260408-135251/`
- `experiments/logs/final-aot-validation-replicated-20260408-135251/`
- `experiments/logs/final-demo-20260403/`
- `experiments/logs/intel-v2-batch-window-replicated-20260408-135251/`
- `experiments/logs/intel-v1-v2-isolation-replicated-20260408-135251/`
- `experiments/logs/intel-v2-v3-adaptive-replicated-20260408-135251/`
- `experiments/logs/intel-v3-adaptive-parameter-sweep-20260408-190517/`

Future reruns should use a fresh stamp and should not overwrite historical evidence roots. The reported impairment path is the gateway-to-dashboard last hop through `experiments/impairment_proxy.py`; reported downstream bytes and frames come from proxy output counters.

Run a full replicated equivalence check against the frozen evidence roots:

```powershell
$stamp = "cleanup-equivalence-replicated-$(Get-Date -Format yyyyMMdd-HHmmss)"
python .\experiments\run_replicated_equivalence_check.py `
  --stamp $stamp `
  --intel-input .\experiments\logs\final-source-downloads\intel_data.txt.gz `
  --aot-input .\experiments\logs\final-source-downloads\aot_weekly.tar `
  --execute
```

## Environment Variables

- `MQTT_HOST`, `MQTT_PORT`, `MQTT_QOS`
- `WS_HOST`, `WS_PORT`
- `RUN_ID`
- `GATEWAY_MODE` (`v0`, `v1`, `v2`, `v3`, or `v4`)
- `BATCH_WINDOW_MS`
- `BATCH_MAX_MESSAGES`
- `DUPLICATE_TTL_MS`
- `VALUE_DEDUP_ENABLED`
- `FRESHNESS_TTL_MS`
- `ADAPTIVE_MIN_BATCH_WINDOW_MS`
- `ADAPTIVE_MAX_BATCH_WINDOW_MS`
- `ADAPTIVE_STEP_UP_MS`
- `ADAPTIVE_STEP_DOWN_MS`
- `ADAPTIVE_QUEUE_HIGH_WATERMARK`
- `ADAPTIVE_QUEUE_LOW_WATERMARK`
- `ADAPTIVE_SEND_SLOW_MS`
- `ADAPTIVE_RECOVERY_STREAK`
- `REPLAY_SPEED`
- `SENSOR_LIMIT`
- `DURATION_S`
- `BURST_ENABLED`
- `BURST_START_S`
- `BURST_DURATION_S`
- `BURST_SPEED_MULTIPLIER`
- `IMPAIR_HOST`, `IMPAIR_PORT`
- `UPSTREAM_WS_URL`, `UPSTREAM_HTTP_BASE`
- `IMPAIR_SCENARIO_FILE`
- `IMPAIR_RANDOM_SEED`
- `IMPAIR_FRAME_LOG_PATH`

## Tests

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
```

```bash
python -m unittest discover -s tests -v
```
