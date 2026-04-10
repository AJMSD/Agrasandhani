# Experiment Pipeline Audit

This document is the canonical Section 3 audit for the current experiment pipeline. It describes the pipeline as it exists today, records the concrete provenance gaps in the current runners and manifests, and lists the current provenance-drift issues without fixing later-phase metrics, replication, or paper-writing work.

## Scope

- Audit target: current local repo state as of the Section 3 pass
- Research object: `dataset replay -> MQTT broker -> smart gateway -> WebSocket dashboard`
- Pipeline focus: raw Intel/AoT inputs, replay CSV generation, sweep/demo execution, per-run analysis, tracked report assets, and paper-packaged assets
- Out of scope for this phase: implementing provenance fixes, trial support, metric changes, reruns, or manuscript rewrites

## Canonical Pipeline Map

### Pipeline shape

```text
raw Intel/AoT inputs
-> bounded source slices under experiments/logs/generated_source_slices/
-> normalized replay CSVs under experiments/logs/generated_inputs/
-> sweep/demo run directories under experiments/logs/<sweep-id>/
-> per-run summary.json, summary.csv, timeseries.csv
-> tracked report assets under report/assets/ plus report/final_report.md and report/deliverable_gate.md
-> copied paper assets under research_paper/figures/ and research_paper/tables/
```

### Artifact classes used in this audit

- Raw inputs: local Intel and AoT source data outside the tracked deliverable set
- Local ignored evidence: generated replay CSVs, source slices, sweep roots, demo captures, and final-deliverables manifests under `experiments/logs/`
- Tracked report assets: `report/assets/`, `report/final_report.md`, and `report/deliverable_gate.md`
- Paper-packaged assets: `research_paper/figures/`, `research_paper/tables/`, and `research_paper/tables/paper_assets_manifest.json`

## Script-by-Script I/O

### `experiments/run_final_deliverables.py`

- Artifact tier: raw inputs -> local ignored evidence -> tracked report assets
- Entry conditions and required inputs:
  - local MQTT broker reachable at the configured host/port
  - Node.js and Playwright browser capture prerequisites available
  - `--intel-input` path exists
  - `--aot-input` path exists
  - optional `--stamp`, `--report-dir`, `--mqtt-host`, `--mqtt-port`
- Reads:
  - raw Intel input file from `--intel-input`
  - raw AoT archive/directory/file from `--aot-input`
  - scenario definitions via downstream sweep/demo helpers
  - local environment for MQTT host/port and browser capture checks
- Writes:
  - bounded source slices under `experiments/logs/generated_source_slices/`
  - normalized replay CSVs under `experiments/logs/generated_inputs/`
  - Intel sweep root `experiments/logs/final-intel-primary-<STAMP>/`
  - AoT sweep root `experiments/logs/final-aot-validation-<STAMP>/`
  - demo root `experiments/logs/final-demo-<STAMP>/demo/`
  - deliverables manifest `experiments/logs/final-deliverables-<STAMP>/manifest.json`
  - tracked report assets by calling `experiments/build_report_assets.py`
- Later-stage consumers:
  - `experiments/reproduce_all.sh --mode from-raw`
  - `report/assets/evidence_manifest.json`
  - `report/final_report.md`
  - `report/deliverable_gate.md`
- Notes:
  - This is the top-level raw-to-assets orchestrator for the current final-evidence flow.
  - It does not package paper assets directly.

### `experiments/run_sweep.py`

- Artifact tier: local ignored evidence
- Entry conditions and required inputs:
  - local MQTT broker reachable at the configured host/port
  - optional browser capture prerequisites when `run_browser=True`
  - replay CSV supplied via `SweepConfig.data_file`
  - scenario names resolvable to `experiments/scenarios/<scenario>.json`
- Reads:
  - replay CSV specified by `data_file`
  - scenario JSON under `experiments/scenarios/`
  - gateway runtime environment and optional gateway overrides
  - browser capture script `experiments/capture_dashboard.mjs`
- Writes:
  - sweep root `experiments/logs/<sweep_id>/`
  - per-run directories such as `experiments/logs/<sweep_id>/<variant>-qos<qos>-<scenario>/`
  - per-run process logs, `proxy_frame_log.csv`, copied `gateway_forward_log.csv`, `gateway_metrics.json`, `proxy_metrics.json`, `dashboard_measurements.csv`, `dashboard_summary.json`, `manifest.json`
  - derived `summary.json`, `summary.csv`, and `timeseries.csv` via `experiments/analyze_run.py`
  - sweep-level plots via `experiments/plot_sweep.py`
- Later-stage consumers:
  - `experiments/run_final_deliverables.py`
  - targeted sweep runners
  - `experiments/build_report_assets.py`
- Notes:
  - This is the canonical single-condition runner/orchestrator for current sweep roots.
  - Current run manifests are per run, not per trial aggregate.

### `experiments/analyze_run.py`

- Artifact tier: local ignored evidence
- Entry conditions and required inputs:
  - run directory exists
  - expected run artifacts may include `gateway_forward_log.csv`, `proxy_frame_log.csv`, `dashboard_measurements.csv`, `manifest.json`, `dashboard_summary.json`, `gateway_metrics.json`, and `proxy_metrics.json`
- Reads:
  - per-run logs and metrics from one run directory
- Writes:
  - `summary.json`
  - `summary.csv`
  - `timeseries.csv`
- Later-stage consumers:
  - `experiments/build_report_assets.py`
  - sweep-level plots and table generation
- Notes:
  - This is the canonical per-run summarizer for current report-facing metrics.
  - It does not aggregate across multiple trials of one condition.

### `experiments/build_report_assets.py`

- Artifact tier: local ignored evidence -> tracked report assets
- Entry conditions and required inputs:
  - final sweep directories exist for Intel, AoT, and demo
  - optional ablation sweep directories may exist for batch-window, v1-v2 isolation, and adaptive comparisons
  - expected per-run `summary.json`, `timeseries.csv`, and dashboard/proxy artifacts already exist under those sweep roots
- Reads:
  - Intel sweep root from `--intel-sweep-dir`
  - AoT sweep root from `--aot-sweep-dir`
  - demo root from `--demo-dir`
  - optional ablation roots from `--intel-batch-sweep-dir`, `--intel-v1-v2-sweep-dir`, and `--intel-adaptive-sweep-dir`
  - per-run `summary.json`, `timeseries.csv`, `dashboard_measurements.csv`, `dashboard_summary.json`, `proxy_frame_log.csv`, `gateway_forward_log.csv`, and demo screenshots
- Writes:
  - tracked figures under `report/assets/figures/`
  - tracked tables under `report/assets/tables/`
  - `report/assets/evidence_manifest.json`
  - `report/assets/old_evidence_inventory.json`
  - `report/final_report.md`
  - `report/deliverable_gate.md`
- Later-stage consumers:
  - `experiments/package_paper_assets.py`
  - manual paper/report writing
  - claim traceability and final submission packaging
- Notes:
  - This is the canonical local-evidence-to-tracked-assets step.
  - It is also the source of the current stale path references in `report/deliverable_gate.md`.

### `experiments/package_paper_assets.py`

- Artifact tier: tracked report assets -> paper-packaged assets
- Entry conditions and required inputs:
  - `report/assets/` exists and contains the required figures/tables
  - destination paper directory exists or can be created
  - claim map output path is provided
- Reads:
  - `report/assets/figures/`
  - `report/assets/tables/`
  - `report/assets/evidence_manifest.json`
- Writes:
  - copied figures under `research_paper/figures/`
  - copied tables under `research_paper/tables/`
  - generated LaTeX table `research_paper/tables/intel_main_summary_table.tex`
  - claim map at `report/assets/CLAIM_TO_EVIDENCE_MAP.md`
  - paper asset manifest `research_paper/tables/paper_assets_manifest.json`
- Later-stage consumers:
  - `experiments/reproduce_all.sh`
  - manual LaTeX paper assembly
- Notes:
  - This is the only current script that bridges tracked report assets into the paper tree.
  - In the current repo state, the script and resulting paper asset directories are not yet part of one clean, synchronized tracked provenance chain.

### `experiments/reproduce_all.sh`

- Artifact tier: orchestration wrapper across local ignored evidence, tracked report assets, and paper-packaged assets
- Entry conditions and required inputs:
  - bash shell available
  - either existing sweep/demo roots for `--mode from-existing` or raw dataset paths for `--mode from-raw`
  - optional `STAMP`
- Reads:
  - existing sweep roots and demo root when `--mode from-existing`
  - raw Intel/AoT inputs via environment variables when `--mode from-raw`
  - tracked report assets after `experiments/build_report_assets.py`
- Writes:
  - when `--mode from-raw`, the same local ignored evidence and tracked report assets produced by `experiments/run_final_deliverables.py`
  - refreshed `report/assets/`
  - copied `research_paper/figures/` and `research_paper/tables/`
  - refreshed `report/assets/CLAIM_TO_EVIDENCE_MAP.md`
- Later-stage consumers:
  - manual verification and submission packaging
- Notes:
  - This is the highest-level wrapper for rebuilding report and paper assets.
  - It assumes fixed sweep-root names for the current April evidence package.

## Provenance Gap Audit

The current pipeline is functionally reproducible for single-run evidence, but it does not yet capture enough provenance for replicated evidence. The following Section 3.2 gaps are present as repo facts today.

- No trial dimension in sweep orchestration:
  - `experiments/run_sweep.py` iterates only over `variant`, `mqtt_qos`, and `scenario`.
  - Current run labels and output paths do not include a trial loop or trial directory layer.
- No explicit trial id in per-run manifests:
  - `experiments/run_sweep.py` writes per-run `manifest.json` with `run_id`, `gateway_run_id`, `variant`, `scenario`, `mqtt_qos`, and replay settings.
  - There is no `trial_id`, `trial_index`, or equivalent manifest field.
- No impairment-seed capture in run manifests:
  - Current run manifests record the scenario name but not a deterministic impairment seed or seed source.
  - This blocks exact replicated reruns for any future seeded impairment model.
- No code-version capture:
  - Current manifests do not record git commit, branch, dirty state, or equivalent source snapshot metadata.
  - Reproducing a run against the exact code state therefore depends on external discipline rather than manifested provenance.
- No config hash capture:
  - Current manifests store several explicit settings, but they do not capture a hash of the effective gateway config, scenario file, or normalized input slice.
  - This makes it harder to detect silent config drift across runs with similar names.
- No aggregate-by-trial summary path:
  - `experiments/analyze_run.py` writes one `summary.json`, one `summary.csv`, and one `timeseries.csv` per run directory.
  - `experiments/build_report_assets.py` consumes those per-run summaries directly and does not aggregate multiple trial directories for the same condition.

## Provenance-Drift Remediation List

The following Section 3.3 drift issues are present as repo facts today. They are documented here for later remediation and are not fixed in this phase.

### 1. Stale path references generated into `report/deliverable_gate.md`

- `experiments/build_report_assets.py` currently generates stale system-path references:
  - `simulator/replay_mqtt.py`
  - `gateway/server.py`
  - `ui/dashboard.html`
- Those same stale references appear in the generated `report/deliverable_gate.md`.
- Remediation target for a later phase:
  - update the generator to reference the current entrypoints that actually exist in the repo
  - regenerate `report/deliverable_gate.md` from the corrected source

### 2. Split manifest state between final-deliverables and report assets

- `experiments/logs/final-deliverables-20260403/manifest.json` captures:
  - raw input paths
  - generated input paths
  - sweep ids
  - high-level command settings
  - embedded `report_assets_manifest` snapshot
- `report/assets/evidence_manifest.json` captures:
  - current tracked sweep roots
  - generated report asset paths
  - current old-evidence inventory pointer
- These are overlapping but non-identical manifest states with different scopes and different update paths.
- Remediation target for a later phase:
  - define one canonical provenance chain that explains how the raw-run manifest, tracked asset manifest, and future paper manifest relate to each other

### 3. Paper-asset packaging path is not fully synchronized/tracked together

- `experiments/package_paper_assets.py` is the current bridge from tracked report assets into `research_paper/`.
- In the current local repo state:
  - `experiments/package_paper_assets.py` is untracked
  - `research_paper/figures/` exists locally
  - `research_paper/tables/` exists locally
- This means the packaging path and the generated paper asset tree are present locally, but not yet clearly frozen as one synchronized tracked provenance unit.
- Remediation target for a later phase:
  - decide whether the paper-packaging script and its manifests are part of the final tracked deliverable chain
  - then align tracking, manifest ownership, and regeneration procedure accordingly

### 4. Repo-local generated paper assets are outside one canonical tracked provenance chain

- The current pipeline creates:
  - tracked report assets under `report/assets/`
  - paper-facing copies under `research_paper/figures/` and `research_paper/tables/`
  - a paper manifest under `research_paper/tables/paper_assets_manifest.json`
  - a claim map under `report/assets/CLAIM_TO_EVIDENCE_MAP.md`
- These artifacts are related, but the current repo state does not yet express one canonical, end-to-end tracked provenance chain from raw run ids to paper-packaged assets.
- Remediation target for a later phase:
  - unify the report-asset manifest, claim map, and paper-assets manifest under one explicit ownership model
  - make the packaging status of each paper artifact unambiguous

## Current Section 3 Conclusion

Section 3 is complete when this document is treated as the canonical experiment-pipeline audit for the current repo state.

- `3.1` is satisfied by the canonical pipeline map and script-by-script I/O above.
- `3.2` is satisfied by the explicit provenance-gap audit above.
- `3.3` is satisfied by the explicit provenance-drift remediation list above.

No Section 3 fixes are implemented here. Later phases should use this audit as the source of truth before changing metrics, manifests, replicated-trial support, or paper packaging.
