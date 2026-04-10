# Reproducibility Guide

This guide documents how to reproduce Agrasandhani paper artifacts from experiments and local logs without changing experiment logic.

## 1) Run one experiment

Run a single scenario/variant with the sweep runner:

```powershell
python .\experiments\run_sweep.py `
  --sweep-id local-one-run `
  --variants v2 `
  --qos 0 `
  --scenarios outage_5s `
  --data-file .\experiments\logs\generated_inputs\intel_lab_final_20260403.csv
```

Outputs are written under `experiments/logs/local-one-run/` including per-run logs, `summary.json`, and `timeseries.csv`.

## 2) Run the full sweep

From raw datasets:

```powershell
python .\experiments\run_final_deliverables.py `
  --intel-input C:\path\to\data.txt.gz `
  --aot-input C:\path\to\aot_archive.tar `
  --stamp 20260403
```

This orchestrates:
- raw source slicing and preprocessing
- Intel primary matrix
- AoT validation matrix
- demo capture
- report asset generation

The canonical script-by-script pipeline audit now lives in `report/experiment_pipeline_audit.md`. Use that document as the source of truth for current pipeline inputs, outputs, artifact tiers, provenance gaps, and provenance-drift issues.

## 3) Regenerate all paper plots/tables (single script)

Preferred command:

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

## 4) Frozen vs new evidence roots

Use `experiments/logs/run_registry.json` as the source of truth for preserved historical artifacts. The current canonical frozen evidence roots are:

- `experiments/logs/final-intel-primary-replicated-20260408-135251/`
- `experiments/logs/final-aot-validation-replicated-20260408-135251/`
- `experiments/logs/final-demo-20260403/`
- `experiments/logs/intel-v2-batch-window-replicated-20260408-135251/`
- `experiments/logs/intel-v1-v2-isolation-replicated-20260408-135251/`
- `experiments/logs/intel-v2-v3-adaptive-replicated-20260408-135251/`
- `experiments/logs/intel-v3-adaptive-parameter-sweep-20260408-190517/`

Older frozen roots from `20260403` and `20260404` remain preserved as legacy evidence and must remain untouched:

- `experiments/logs/final-intel-primary-20260403/`
- `experiments/logs/final-aot-validation-20260403/`
- `experiments/logs/final-demo-20260403/`
- `experiments/logs/intel-v2-batch-window-20260403/`
- `experiments/logs/intel-v1-v2-isolation-20260403/`
- `experiments/logs/intel-v2-v3-adaptive-20260404/`

All future reruns must be additive:

- Always issue a fresh `STAMP` and never reuse an existing `sweep_id`.
- Do not move, rename, merge, overwrite, or delete historical evidence directories.
- Keep exploratory or tuning runs outside frozen final-evidence roots.
- Keep generated inputs and generated source slices additive by creating new stamped artifacts alongside older ones.

Canonical future replicated roots:

- `experiments/logs/final-intel-primary-replicated-<STAMP>/`
- `experiments/logs/final-aot-validation-replicated-<STAMP>/`
- `experiments/logs/intel-v2-batch-window-replicated-<STAMP>/`
- `experiments/logs/intel-v1-v2-isolation-replicated-<STAMP>/`
- `experiments/logs/intel-v2-v3-adaptive-replicated-<STAMP>/`

Within each replicated root, keep each condition additive under explicit trial directories, for example:

```text
experiments/logs/final-intel-primary-replicated-<STAMP>/<condition>/trial-01-seed-53701/
```

Current runner caveat:

- The current sweep runners refuse to overwrite an existing `sweep_id` root.
- The safe procedure remains creating a fresh `STAMP` for every new evidence run.

## 5) Lock the Section 6 matrix

Before starting the replicated reruns, write the bounded Section 6 matrix manifest in safe plan-only mode:

```powershell
python .\experiments\run_replicated_phase6.py --stamp 20260407-120000
```

This writes `experiments/logs/phase6-matrix-plan-<STAMP>.json` and locks:

- Intel primary: `final-intel-primary-replicated-<STAMP>/`, `v0/v2/v4`, QoS `0/1`, `clean/bandwidth_200kbps/loss_2pct/delay_50ms_jitter20ms/outage_5s`, seeds `53701,53702,53703`
- V2 batch-window: `intel-v2-batch-window-replicated-<STAMP>/`, windows `50/100/250/500/1000 ms`, seeds `53701,53702`
- V1 vs V2 isolation: `intel-v1-v2-isolation-replicated-<STAMP>/`, `clean/bandwidth_200kbps/outage_5s`, same windows, seeds `53701,53702`
- V2 vs V3 adaptive default comparison: `intel-v2-v3-adaptive-replicated-<STAMP>/`, `bandwidth_200kbps/loss_2pct/delay_50ms_jitter20ms`, base `250 ms`, seeds `53701,53702`
- AoT validation: `final-aot-validation-replicated-<STAMP>/`, `v0/v4`, QoS `0`, `clean/outage_5s`, seeds `53701,53702`

The script defaults to plan-only. It does not create replay CSVs or start runs unless `--execute` is provided later.

When you are ready to start the actual Section 6 reruns, rerun the same command with `--execute`.

## 6) Pipeline shape

The reproducibility flow is:

```text
raw logs/data -> processed CSV -> analysis summaries -> report/assets/tables + report/assets/figures -> research_paper/tables + research_paper/figures
```

Main entrypoints:
- `experiments/run_final_deliverables.py`
- `experiments/build_report_assets.py`
- `experiments/package_paper_assets.py`
- `experiments/reproduce_all.sh`

For the full script-by-script audit, use `report/experiment_pipeline_audit.md` rather than expanding this guide further.

Impairment placement for the reported evidence:
- Impairments are injected primarily on the gateway-to-dashboard last hop via `experiments/impairment_proxy.py`.
- Optional host-level `tc netem` shaping is used in that same last-hop context when enabled.
- Reported downstream traffic metrics are proxy-level outputs (`proxy_downstream_bytes_out`, `proxy_downstream_frames_out`).

## 7) Metric definitions (code-aligned)

Use `report/metric_definitions.md` as the canonical metric catalog for formulas, source logs, units, and stage labels.

Short version:

- latency is dashboard-side `age_ms_at_display = ts_displayed - ts_sent`
- downstream bytes and frames come from proxy `sent` rows only
- stale behavior is TTL-linked through `freshness_ttl_ms` and `stale_at_display`
- jitter/stability is defined from proxy inter-frame gaps, not from dashboard event cadence

## 8) Paper-facing artifacts

Generated and copied artifacts include:
- Main figure: `research_paper/figures/main_outage_frame_rate.png`
- Required evaluation figures under `research_paper/figures/`
- Required tables under `research_paper/tables/`
- Main summary table: `research_paper/tables/intel_main_summary_table.csv` and `.tex`
- Claim traceability map: `report/assets/CLAIM_TO_EVIDENCE_MAP.md`

## 9) Notes

- This process does not modify experiment logic or aggregation algorithms.
- Only frozen final-evidence roots may feed paper claims, figures, and tables.
- Exploratory or tuning runs must stay separate from frozen final-evidence roots even if they use the same datasets or scenarios.
- If optional M6 sweep directories are missing, generate them first with:
  - `experiments/run_batch_window_sweep.py`
  - `experiments/run_v1_v2_isolation_sweep.py`
  - `experiments/run_adaptive_impairment_sweep.py`
  - `experiments/run_replicated_phase6.py --execute`
