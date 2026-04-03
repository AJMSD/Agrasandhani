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
- `experiments/run_one.ps1`: standard 60s run harness
- `experiments/run_one.sh`: standard 60s run harness for macOS/Linux
- `experiments/impairment_proxy.py`: app-layer impairment proxy that serves the dashboard and proxies `/ws` plus `/config`
- `experiments/scenarios/*.json`: deterministic impairment phase definitions
- `experiments/run_sweep.py`: comparison runner for `v0`, `v2`, and `v4` scenario sweeps
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

The repo now includes reproducible preprocessors for the two real replay sources in the PRD. Raw source archives stay local; only small normalized outputs are checked in under `simulator/datasets/`.

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

Artifacts are written to `experiments/logs/<RUN_ID>/`:

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

Run the default minimal matrix from the PRD:

```powershell
python .\experiments\run_sweep.py --burst-enabled
```

```bash
python ./experiments/run_sweep.py --burst-enabled
```

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

Sweep-level plots are written to `experiments/logs/<SWEEP_ID>/plots/`.

The Linux-only `tc netem` cross-check helpers live under `experiments/netem/`.

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
