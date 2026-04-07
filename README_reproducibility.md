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

## 3) Regenerate all paper plots/tables (single script)

Preferred command:

```powershell
bash ./experiments/reproduce_all.sh --mode from-existing --stamp 20260403
```

If bash is unavailable on Windows, run the equivalent Python steps:

```powershell
python .\experiments\build_report_assets.py `
  --intel-sweep-dir .\experiments\logs\final-intel-primary-20260403 `
  --aot-sweep-dir .\experiments\logs\final-aot-validation-20260403 `
  --demo-dir .\experiments\logs\final-demo-20260403\demo `
  --intel-batch-sweep-dir .\experiments\logs\intel-v2-batch-window-20260403 `
  --intel-v1-v2-sweep-dir .\experiments\logs\intel-v1-v2-isolation-20260403 `
  --intel-adaptive-sweep-dir .\experiments\logs\intel-v2-v3-adaptive-20260404 `
  --output-dir .\report\assets

python .\experiments\package_paper_assets.py `
  --report-assets-dir .\report\assets `
  --paper-dir .\research_paper `
  --claim-map-path .\report\assets\CLAIM_TO_EVIDENCE_MAP.md
```

## 4) Pipeline shape

The reproducibility flow is:

```text
raw logs/data -> processed CSV -> analysis summaries -> report/assets/tables + report/assets/figures -> research_paper/tables + research_paper/figures
```

Main entrypoints:
- `experiments/run_final_deliverables.py`
- `experiments/build_report_assets.py`
- `experiments/package_paper_assets.py`
- `experiments/reproduce_all.sh`

Impairment placement for the reported evidence:
- Impairments are injected primarily on the gateway-to-dashboard last hop via `experiments/impairment_proxy.py`.
- Optional host-level `tc netem` shaping is used in that same last-hop context when enabled.
- Reported downstream traffic metrics are proxy-level outputs (`proxy_downstream_bytes_out`, `proxy_downstream_frames_out`).

## 5) Metric definitions (code-aligned)

- End-to-end latency: `ts_displayed - ts_sent` at dashboard capture time.
  - Recorded as `age_ms_at_display` in `dashboard_measurements.csv`.
  - Aggregated in `experiments/analyze_run.py`.

- Downstream bytes: WebSocket payload bytes sent downstream by the proxy/gateway path.
  - Aggregated as `proxy_downstream_bytes_out` from sent frame payload bytes.

- Frames: Aggregated frames sent to dashboard.
  - Aggregated as `proxy_downstream_frames_out`.
  - Time trace metric: `frame_rate_per_s` in each run `timeseries.csv`.

- Stale by TTL threshold:
  - A row is stale when message age exceeds runtime `freshness_ttl_ms`.
  - Captured as `stale_at_display`, summarized as `stale_fraction` and dashboard `staleCount`.

## 6) Paper-facing artifacts

Generated and copied artifacts include:
- Main figure: `research_paper/figures/main_outage_frame_rate.png`
- Required evaluation figures under `research_paper/figures/`
- Required tables under `research_paper/tables/`
- Main summary table: `research_paper/tables/intel_main_summary_table.csv` and `.tex`
- Claim traceability map: `report/assets/CLAIM_TO_EVIDENCE_MAP.md`

## 7) Notes

- This process does not modify experiment logic or aggregation algorithms.
- If optional M6 sweep directories are missing, generate them first with:
  - `experiments/run_batch_window_sweep.py`
  - `experiments/run_v1_v2_isolation_sweep.py`
  - `experiments/run_adaptive_impairment_sweep.py`
