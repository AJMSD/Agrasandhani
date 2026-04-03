# Agrasandhani

Agrasandhani is a local MQTT-to-WebSocket baseline for replaying sensor datasets into a minimal dashboard. This branch implements the MVP foundation only: CSV replay publisher -> Mosquitto -> Python gateway -> WebSocket -> static UI, with real counters and per-message CSV logging for later experiments.

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
- `gateway/app.py`: FastAPI app with `/health`, `/metrics`, `/ws`, and static UI serving
- `gateway/mqtt_ingest.py`: MQTT subscriber that pushes broker messages into an internal queue
- `gateway/forwarder.py`: baseline forward-every-message path, latest snapshot map, and CSV run logger
- `gateway/schemas.py`: shared payload validation
- `ui/index.html`: minimal dashboard
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
- `experiments/logs/<RUN_ID>/gateway_forward_log.csv` contains one row per forwarded message

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
.\experiments\run_one.ps1
```

```bash
export RUN_ID=session-001
export DURATION_S=60
export REPLAY_SPEED=1.0
export SENSOR_LIMIT=0
export MQTT_QOS=0
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

## Tests

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
```

```bash
python -m unittest discover -s tests -v
```
