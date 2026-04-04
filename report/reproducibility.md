# Reproducibility

## Prerequisites

- Python 3.11+
- Node.js with `npm install` already run in the repo
- Playwright Chromium installed via `npx playwright install chromium`
- Mosquitto running locally on `127.0.0.1:1883`
- Local raw dataset inputs:
  - Intel Berkeley Lab readings file (`data.txt` or `data.txt.gz`)
  - AoT archive or extracted data (`.tar`, `data.csv`, `data.csv.gz`, or extracted directory with `sensors.csv`)

## Final Deliverables Runner

PowerShell:

```powershell
$env:INTEL_LAB_INPUT = "C:\path\to\data.txt.gz"
$env:AOT_INPUT = "C:\path\to\chicago-complete.weekly.2019-09-30-to-2019-10-06.tar"
.\experiments\run_final_deliverables.ps1
```

Bash:

```bash
export INTEL_LAB_INPUT=/path/to/data.txt.gz
export AOT_INPUT=/path/to/chicago-complete.weekly.2019-09-30-to-2019-10-06.tar
./experiments/run_final_deliverables.sh
```

Direct Python:

```powershell
python .\experiments\run_final_deliverables.py `
  --intel-input C:\path\to\data.txt.gz `
  --aot-input C:\path\to\chicago-complete.weekly.2019-09-30-to-2019-10-06.tar `
  --stamp 20260403
```

```bash
python ./experiments/run_final_deliverables.py \
  --intel-input /path/to/data.txt.gz \
  --aot-input /path/to/chicago-complete.weekly.2019-09-30-to-2019-10-06.tar \
  --stamp 20260403
```

## What The Runner Does

1. Normalizes the Intel and AoT raw inputs into ignored replay CSVs under `experiments/logs/generated_inputs/`.
   Before normalization, the runner creates bounded real-data source slices under `experiments/logs/generated_source_slices/` so the final matrix stays reproducible and fast enough to rerun locally.
2. Runs the Intel primary matrix:
   - variants `v0,v2,v4`
   - MQTT QoS `0,1`
   - scenarios `clean,bandwidth_200kbps,loss_2pct,delay_50ms_jitter20ms,outage_5s`
3. Runs the AoT validation matrix:
   - variants `v0,v4`
   - MQTT QoS `0`
   - scenarios `clean,outage_5s`
4. Runs the captured M5 demo against the Intel replay CSV.
5. Regenerates tracked report assets under `report/assets/`, `report/final_report.md`, and `report/deliverable_gate.md`.

## M6 Batch-Window Sweep

If the normalized Intel replay CSV already exists locally, run the dedicated V2 batch-window sweep:

```powershell
python .\experiments\run_batch_window_sweep.py `
  --sweep-id intel-v2-batch-window-20260403 `
  --data-file .\experiments\logs\generated_inputs\intel_lab_final_20260403.csv
```

This produces local-only logs under `experiments/logs/intel-v2-batch-window-20260403/` for the canonical `50,100,250,500,1000 ms` windows.

## M6 V1 vs V2 Isolation Sweep

If the normalized Intel replay CSV already exists locally, run the dedicated V1-versus-V2 isolation sweep:

```powershell
python .\experiments\run_v1_v2_isolation_sweep.py `
  --sweep-id intel-v1-v2-isolation-20260403 `
  --data-file .\experiments\logs\generated_inputs\intel_lab_final_20260403.csv
```

This produces local-only logs under `experiments/logs/intel-v1-v2-isolation-20260403/` for `v1` and `v2` across `clean`, `bandwidth_200kbps`, and `outage_5s` at the canonical `50,100,250,500,1000 ms` windows.

## Local-Only Outputs

- `experiments/logs/final-deliverables-<STAMP>/manifest.json`
- `experiments/logs/generated_inputs/intel_lab_final_<STAMP>.csv`
- `experiments/logs/generated_inputs/aot_final_<STAMP>.csv`
- `experiments/logs/generated_source_slices/intel_lab_slice_<STAMP>.txt`
- `experiments/logs/generated_source_slices/aot_slice_<STAMP>/`
- `experiments/logs/final-intel-primary-<STAMP>/`
- `experiments/logs/final-aot-validation-<STAMP>/`
- `experiments/logs/final-demo-<STAMP>/demo/`
- `experiments/logs/intel-v2-batch-window-<STAMP>/`
- `experiments/logs/intel-v1-v2-isolation-<STAMP>/`

These remain ignored and should not be committed.

## Tracked Outputs

- `report/assets/evidence_manifest.json`
- `report/assets/tables/*.csv`
- `report/assets/tables/*.md`
- `report/assets/figures/*.png`
- `report/final_report.md`
- `report/deliverable_gate.md`

## Regenerating Only The Report Assets

If the final sweeps and demo already exist locally, rerun only the tracked asset builder:

```powershell
python .\experiments\build_report_assets.py `
  --intel-sweep-dir .\experiments\logs\final-intel-primary-20260403 `
  --aot-sweep-dir .\experiments\logs\final-aot-validation-20260403 `
  --demo-dir .\experiments\logs\final-demo-20260403\demo `
  --intel-batch-sweep-dir .\experiments\logs\intel-v2-batch-window-20260403 `
  --intel-v1-v2-sweep-dir .\experiments\logs\intel-v1-v2-isolation-20260403 `
  --output-dir .\report\assets
```

## Verification

- `python -m unittest discover -s tests -v`
- `node .\experiments\capture_dashboard.mjs --check-only`
- inspect `report/assets/evidence_manifest.json` after the final run
- confirm `report/final_report.md` references the expected sweep and demo ids
