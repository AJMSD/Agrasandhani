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

The canonical script-by-script pipeline audit now lives in `report/experiment_pipeline_audit.md`. Use that document as the source of truth for current pipeline inputs, outputs, artifact tiers, provenance gaps, and provenance-drift issues.

The canonical metric catalog now lives in `report/metric_definitions.md`. Use that document as the source of truth for latency, bytes, frames, rates, missing updates, freshness/TTL behavior, and proxy-side jitter definitions.

The canonical replication-enablement helpers now live in:

- `experiments/run_sweep.py`
- `experiments/sweep_aggregation.py`
- `experiments/build_report_assets.py`
- `experiments/run_replicated_phase6.py`

Each new run now writes per-run manifest schema v2 metadata with trial/provenance fields, and each completed sweep root writes a root-level `condition_aggregates.json` artifact that groups trials by condition.

## Evidence Layout Rule

Use `experiments/logs/run_registry.json` as the source of truth for preserved historical artifacts. The current canonical frozen evidence roots are:

- `experiments/logs/final-intel-primary-replicated-20260408-135251/`
- `experiments/logs/final-aot-validation-replicated-20260408-135251/`
- `experiments/logs/final-demo-20260403/`
- `experiments/logs/intel-v2-batch-window-replicated-20260408-135251/`
- `experiments/logs/intel-v1-v2-isolation-replicated-20260408-135251/`
- `experiments/logs/intel-v2-v3-adaptive-replicated-20260408-135251/`
- `experiments/logs/intel-v3-adaptive-parameter-sweep-20260408-190517/`

Older frozen roots from `20260403` and `20260404` remain preserved as legacy evidence:

- `experiments/logs/final-intel-primary-20260403/`
- `experiments/logs/final-aot-validation-20260403/`
- `experiments/logs/final-demo-20260403/`
- `experiments/logs/intel-v2-batch-window-20260403/`
- `experiments/logs/intel-v1-v2-isolation-20260403/`
- `experiments/logs/intel-v2-v3-adaptive-20260404/`

Canonical old-vs-new layout rule:

- Only frozen final-evidence roots may feed report assets, paper assets, and claim language.
- Exploratory or tuning runs must remain separate and must not be merged into frozen final-evidence roots.
- Generated replay CSVs under `experiments/logs/generated_inputs/` and source slices under `experiments/logs/generated_source_slices/` are additive stamped artifacts and must coexist with older outputs.
- All new evidence must use a fresh `STAMP` and must never reuse an existing `sweep_id`.

Canonical future replicated roots:

- `experiments/logs/final-intel-primary-replicated-<STAMP>/`
- `experiments/logs/final-aot-validation-replicated-<STAMP>/`
- `experiments/logs/intel-v2-batch-window-replicated-<STAMP>/`
- `experiments/logs/intel-v1-v2-isolation-replicated-<STAMP>/`
- `experiments/logs/intel-v2-v3-adaptive-replicated-<STAMP>/`

Within each replicated root, each condition must keep explicit trial subdirectories such as:

```text
experiments/logs/final-intel-primary-replicated-<STAMP>/<condition>/trial-01-seed-53701/
```

Current runner behavior:

- Sweep runners refuse to overwrite an existing `sweep_id` root.
- The safe procedure remains issuing a fresh `STAMP` for every new evidence run.
- Replicated trial roots keep the documented `<condition>/trial-<NN>-seed-<SEED>/` layout, while legacy one-run roots remain readable in place.

## Section 6 Matrix-Definition Gate

Before starting any replicated reruns, write the concrete Section 6 matrix manifest in plan-only mode:

```powershell
python .\experiments\run_replicated_phase6.py --stamp 20260407-120000
```

The plan manifest is written to `experiments/logs/phase6-matrix-plan-<STAMP>.json` and locks:

- Intel primary: `final-intel-primary-replicated-<STAMP>/`, `v0/v2/v4`, QoS `0/1`, `clean/bandwidth_200kbps/loss_2pct/delay_50ms_jitter20ms/outage_5s`, seeds `53701,53702,53703`
- V2 batch-window: `intel-v2-batch-window-replicated-<STAMP>/`, windows `50/100/250/500/1000 ms`, seeds `53701,53702`
- V1 vs V2 isolation: `intel-v1-v2-isolation-replicated-<STAMP>/`, `clean/bandwidth_200kbps/outage_5s`, same windows, seeds `53701,53702`
- V2 vs V3 adaptive default comparison: `intel-v2-v3-adaptive-replicated-<STAMP>/`, `bandwidth_200kbps/loss_2pct/delay_50ms_jitter20ms`, base `250 ms`, seeds `53701,53702`
- AoT validation: `final-aot-validation-replicated-<STAMP>/`, `v0/v4`, QoS `0`, `clean/outage_5s`, seeds `53701,53702`

The script defaults to plan-only and records the matrix without creating fresh replay CSVs or starting runs. When the matrix-definition gate is approved, execute the same bounded plan with:

```powershell
python .\experiments\run_replicated_phase6.py --stamp 20260407-120000 --execute
```

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

## M6 Adaptive Impairment Sweep

If the normalized Intel replay CSV already exists locally, run the dedicated V2-versus-V3 adaptive impairment sweep:

```powershell
python .\experiments\run_adaptive_impairment_sweep.py `
  --sweep-id intel-v2-v3-adaptive-20260404 `
  --data-file .\experiments\logs\generated_inputs\intel_lab_final_20260403.csv
```

This produces local-only logs under `experiments/logs/intel-v2-v3-adaptive-20260404/` for `v2` and `v3` across `bandwidth_200kbps`, `loss_2pct`, and `delay_50ms_jitter20ms` using the default adaptive gateway settings and a base `250 ms` batch window.

## M6 Freshness Trace

No separate local-only sweep is required for the LKG plus TTL freshness task. The `v0` versus `v4` outage age-of-information trace is regenerated directly from the replicated Intel primary sweep runs `v0-qos0-outage_5s` and `v4-qos0-outage_5s` inside `final-intel-primary-replicated-20260408-135251` whenever `experiments/build_report_assets.py` is run.

## Local-Only Outputs

- `experiments/logs/final-deliverables-<STAMP>/manifest.json`
- `experiments/logs/phase6-matrix-plan-<STAMP>.json`
- `experiments/logs/generated_inputs/intel_lab_final_<STAMP>.csv`
- `experiments/logs/generated_inputs/aot_final_<STAMP>.csv`
- `experiments/logs/generated_source_slices/intel_lab_slice_<STAMP>.txt`
- `experiments/logs/generated_source_slices/aot_slice_<STAMP>/`
- `experiments/logs/final-intel-primary-<STAMP>/`
- `experiments/logs/final-aot-validation-<STAMP>/`
- `experiments/logs/final-demo-<STAMP>/demo/`
- `experiments/logs/intel-v2-batch-window-<STAMP>/`
- `experiments/logs/intel-v1-v2-isolation-<STAMP>/`
- `experiments/logs/intel-v2-v3-adaptive-<STAMP>/`
- `experiments/logs/*/condition_aggregates.json`
- `experiments/logs/final-intel-primary-replicated-<STAMP>/<condition>/trial-<NN>-seed-<SEED>/`
- `experiments/logs/final-aot-validation-replicated-<STAMP>/<condition>/trial-<NN>-seed-<SEED>/`
- `experiments/logs/intel-v2-batch-window-replicated-<STAMP>/<condition>/trial-<NN>-seed-<SEED>/`
- `experiments/logs/intel-v1-v2-isolation-replicated-<STAMP>/<condition>/trial-<NN>-seed-<SEED>/`
- `experiments/logs/intel-v2-v3-adaptive-replicated-<STAMP>/<condition>/trial-<NN>-seed-<SEED>/`

These remain ignored and should not be committed.

## Tracked Outputs

- `report/assets/evidence_manifest.json`
- `experiments/logs/run_registry.json`
- `report/assets/tables/*.csv`
- `report/assets/tables/*.md`
- `report/assets/figures/*.png`
- `report/final_report.md`
- `report/deliverable_gate.md`
- `research_paper/tables/paper_assets_manifest.json`

## Regenerating Only The Report Assets

If the final sweeps and demo already exist locally, rerun only the tracked asset builder using frozen final-evidence roots:

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
```

That command also regenerates the outage freshness artifacts `report/assets/figures/intel_outage_qos0_v0_vs_v4_age_over_time.png` and `report/assets/tables/intel_outage_qos0_v0_vs_v4_freshness.{csv,md}` from the Intel primary sweep.

## Verification

- `python -m unittest discover -s tests -v`
- `node .\experiments\capture_dashboard.mjs --check-only`
- inspect `report/assets/evidence_manifest.json` after the final run
- inspect `experiments/logs/run_registry.json` after the final run
- inspect `research_paper/tables/paper_assets_manifest.json` after packaging paper assets
- confirm `report/final_report.md` references the expected sweep and demo ids
