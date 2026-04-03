# Agrasandhani

Agrasandhani is a local MQTT-to-WebSocket baseline for replaying sensor datasets into a minimal dashboard. This branch implements the MVP foundation only: CSV replay publisher -> Mosquitto -> Python gateway -> WebSocket -> static UI, with real counters, browser-side display measurements, and per-message CSV logging for later experiments.

## Stack

- Python 3.11+
- Mosquitto broker
- `paho-mqtt`
- FastAPI + uvicorn
- Static HTML + browser WebSocket client

## Repo Layout

- `simulator/replay_publisher.py`: reads CSV rows and publishes MQTT messages to `sensors/raw/<metric_type>`
- `simulator/sample_data.csv`: checked-in synthetic sample dataset
- `simulator/generate_sample_data.py`: regenerates the sample CSV
- `simulator/preprocess_aot.py`: normalizes local AoT archives into replay-ready CSV
- `simulator/preprocess_intel_lab.py`: normalizes local Intel Lab readings into replay-ready CSV
- `simulator/datasets/aot_sample.csv`: checked-in normalized AoT example output
- `simulator/datasets/intel_lab_sample.csv`: checked-in normalized Intel Lab example output
- `gateway/app.py`: FastAPI app with `/health`, `/metrics`, `/ws`, and static UI serving
- `gateway/mqtt_ingest.py`: MQTT subscriber that pushes broker messages into an internal queue
- `gateway/forwarder.py`: baseline forward-every-message path, latest snapshot map, and CSV run logger
- `gateway/schemas.py`: shared payload validation
- `ui/index.html`: dashboard with live measurement counters and display-event CSV export
- `experiments/run_one.ps1`: standard 60s run harness
- `experiments/run_one.sh`: standard 60s run harness for macOS/Linux

## Message Schema

Every MQTT payload and WebSocket update uses this exact JSON shape:

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

2. Make sure `mosquitto` is installed and available on your `PATH`.

3. Regenerate the sample dataset if needed:

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
python -m gateway.app
```

```bash
export MQTT_HOST=127.0.0.1
export MQTT_PORT=1883
export MQTT_QOS=0
export WS_HOST=127.0.0.1
export WS_PORT=8000
export RUN_ID=manual-baseline
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
- `/metrics` shows non-zero `mqtt_in_msgs` and `latest_sensor_count`
- the dashboard shows non-zero `Update Rate` and `WebSocket FPS` under traffic
- the dashboard records display-side timing events and can export them as CSV
- `experiments/logs/<RUN_ID>/gateway_forward_log.csv` contains one row per forwarded message

UI measurement notes:

- `Stale Count` uses a fixed UI threshold of `1000` ms for baseline measurement only
- `window.agrasandhaniMeasurements.summary` exposes the current dashboard counters for inspection
- `window.agrasandhaniMeasurements.events` contains the in-memory per-frame display log
- `window.agrasandhaniMeasurements.exportCsv()` returns the same CSV content used by the export button

Useful checks:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/metrics
```

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/metrics
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

- `gateway_forward_log.csv`: per-message timing log
- `gateway.stdout.log` and `gateway.stderr.log`
- `simulator.stdout.log` and `simulator.stderr.log`
- `metrics.json`: final `/metrics` snapshot

## Environment Variables

- `MQTT_HOST`, `MQTT_PORT`, `MQTT_QOS`
- `WS_HOST`, `WS_PORT`
- `RUN_ID`
- `REPLAY_SPEED`
- `SENSOR_LIMIT`
- `DURATION_S`
- `BURST_ENABLED`
- `BURST_START_S`
- `BURST_DURATION_S`
- `BURST_SPEED_MULTIPLIER`

## Tests

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
```

```bash
python -m unittest discover -s tests -v
```
