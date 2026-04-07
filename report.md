# MP6 Task 1 Session Report

## Task Goal

Implement the first MP6 paper-readiness task as a reporting and evidence update, not a gateway behavior change. The goal was to quantify the Intel QoS0 bandwidth outcome versus `v0` for `clean`, `bandwidth_200kbps`, `loss_2pct`, and `outage_5s`, then update the generated report assets so the paper answers the question directly.

## What Was Changed

- Updated `experiments/build_report_assets.py` to generate a paper-ready Intel QoS0 comparison against `v0`.
- Added generated comparison artifacts:
  - `report/assets/tables/intel_bandwidth_vs_v0.csv`
  - `report/assets/tables/intel_bandwidth_vs_v0.md`
- Updated generated outputs to reference the new comparison artifact:
  - `report/final_report.md`
  - `report/deliverable_gate.md`
  - `report/assets/evidence_manifest.json`
  - `report/assets/tables/intel_key_claims.md`
- Updated `tests/test_build_report_assets.py` to lock the new artifact contract and report wording.
- Regenerated the tracked report figures so the committed deliverable set stays in sync with the builder.
- Updated `PROJECT_CHECKLIST.md` locally only so the first M6 item reflects the measured outcome instead of assuming a reduction claim.

## Commands Run

```powershell
python -m pytest tests/test_build_report_assets.py
python experiments/build_report_assets.py --intel-sweep-dir experiments/logs/final-intel-primary-20260403 --aot-sweep-dir experiments/logs/final-aot-validation-20260403 --demo-dir experiments/logs/final-demo-20260403/demo --output-dir report/assets
```

## Verification Results

- `python -m pytest tests/test_build_report_assets.py` passed.
- The builder regenerated the new comparison tables and updated the tracked report artifacts without rerunning the full experiment sweep.
- The generated report now states explicitly that the current Intel QoS0 evidence does not show a downstream payload-byte reduction versus `v0`.

## Measured Bandwidth Deltas Versus V0

| Scenario | V2 bytes delta | V4 bytes delta | V2 peak bytes/s delta | V4 peak bytes/s delta | V2 frame delta | V4 frame delta |
| --- | --- | --- | --- | --- | --- | --- |
| `clean` | `+8.1%` | `+46.2%` | `+28.6%` | `+39.6%` | `-96.2%` | `-95.5%` |
| `bandwidth_200kbps` | `+8.1%` | `+46.2%` | `+5.3%` | `+14.3%` | `-96.2%` | `-95.5%` |
| `loss_2pct` | `+9.8%` | `+48.5%` | `+7.8%` | `+17.0%` | `-96.2%` | `-95.4%` |
| `outage_5s` | `+7.5%` | `+66.3%` | `+5.3%` | `+14.3%` | `-96.6%` | `-94.8%` |

## Analysis

The important result is negative in a useful way: under the current Intel QoS0 evidence, neither `v2` nor `v4` reduces downstream payload bytes compared with naive forwarding. The same is true for the measured peak per-second downstream payload rate. That means the paper should not claim bandwidth reduction if bandwidth is defined as downstream payload bytes or peak downstream payload-byte rate.

The smart variants still produce a strong and consistent frame-cadence result. They reduce downstream frame count by roughly 95%-97% across all four scenarios. That supports a narrower and defensible claim: Agrasandhani stabilizes render cadence and reduces update churn, but it does so by sending fewer, larger aggregate envelopes rather than by shrinking downstream payload-byte volume.

This task closes the MP6 evidence gap by replacing an assumed claim with a measured answer. The paper can now state exactly what happened, under which scenarios, and with what percent deltas.

## Commit And Push Note

`PRD.md` and `PROJECT_CHECKLIST.md` are intentionally local-only for this session and must not be staged or pushed. The push should contain the builder change, the updated test, the regenerated tracked report assets, and this `report.md`.

## MP6 Task 2 Session Report

### Task Goal

Measure the Intel `v2` batch-window tradeoff for the second M6 paper-readiness task, regenerate tracked report assets with the new batch-sweep input, append the analysis here, and keep `PROJECT_CHECKLIST.md` local-only.

### What Was Changed

- Extended `experiments/run_sweep.py` so a run can set `BATCH_WINDOW_MS` through `SweepConfig.batch_window_ms`.
- Added `experiments/run_batch_window_sweep.py` to run the dedicated Intel `v2` qos0 clean burst-enabled batch-window sweep.
- Extended `experiments/build_report_assets.py` with optional `intel_batch_sweep_dir` support and generated:
  - `report/assets/tables/intel_v2_batch_window_tradeoff.csv`
  - `report/assets/tables/intel_v2_batch_window_tradeoff.md`
  - `report/assets/figures/intel_v2_batch_window_tradeoff.png`
- Updated generated outputs to include the batch-window evidence:
  - `report/final_report.md`
  - `report/deliverable_gate.md`
  - `report/assets/evidence_manifest.json`
  - `report/assets/tables/intel_key_claims.md`
  - `report/reproducibility.md`
- Added and updated tests for the new runner and optional asset-builder path.
- Updated the second M6 checklist item locally only.

### Commands Run

```powershell
python -m pytest tests/test_run_sweep.py tests/test_run_batch_window_sweep.py tests/test_build_report_assets.py
python .\experiments\run_batch_window_sweep.py --sweep-id intel-v2-batch-window-20260403 --data-file .\experiments\logs\generated_inputs\intel_lab_final_20260403.csv
python .\experiments\build_report_assets.py --intel-sweep-dir .\experiments\logs\final-intel-primary-20260403 --aot-sweep-dir .\experiments\logs\final-aot-validation-20260403 --demo-dir .\experiments\logs\final-demo-20260403\demo --intel-batch-sweep-dir .\experiments\logs\intel-v2-batch-window-20260403 --output-dir .\report\assets
```

### Verification Results

- `python -m pytest tests/test_run_sweep.py tests/test_run_batch_window_sweep.py tests/test_build_report_assets.py` passed.
- The real Intel V2 batch-window sweep completed successfully and wrote local logs under `experiments/logs/intel-v2-batch-window-20260403/`.
- The tracked report assets regenerated successfully with the new optional batch-sweep input.

### Measured Intel V2 Batch-Window Tradeoff

| Batch window | Latency mean | Latency p95 | Max frame rate/s | Downstream frames | Downstream bytes | Max bytes/s | Stale fraction |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `50 ms` | `46.189 ms` | `64.0 ms` | `4` | `15` | `14751` | `4736` | `0.0` |
| `100 ms` | `72.326 ms` | `110.45 ms` | `3` | `11` | `14071` | `4567` | `0.0` |
| `250 ms` | `174.606 ms` | `276.0 ms` | `1` | `5` | `13051` | `4228` | `0.0` |
| `500 ms` | `419.121 ms` | `525.45 ms` | `1` | `5` | `13051` | `4228` | `0.0` |
| `1000 ms` | `902.222 ms` | `1015.0 ms` | `1` | `6` | `17637` | `4586` | `0.155556` |

### Analysis

The tradeoff is explicit in the measured run. As the fixed batch window increased from `50 ms` to `1000 ms`, latency p95 rose from `64.0 ms` to `1015.0 ms`, while the maximum downstream frame rate fell from `4/s` to `1/s`. That is the paper-ready curve this task needed: larger windows stabilize render cadence, but they do so by adding increasingly visible end-to-end latency.

The payload-byte result is secondary but still worth recording. Downstream bytes changed from `14751` at `50 ms` to `17637` at `1000 ms`, a `+19.6%` shift. That means the observed tradeoff here is not a clean “more batching equals fewer bytes” story. It is better framed as a latency-versus-cadence tradeoff, with payload volume changing as supporting context rather than serving as the headline benefit.

The `1000 ms` point also introduced a non-zero stale fraction (`0.155556`), which suggests that pushing the fixed window this high starts to degrade freshness enough to be visible in the dashboard. For the paper, that makes the middle windows more defensible than the extreme high-window setting.

### Commit And Push Note

`PRD.md` and `PROJECT_CHECKLIST.md` remain local-only for this session and must not be staged or pushed. The push should contain the runner change, the new tests, the regenerated tracked report assets, and this appended `report.md`.

## MP6 Task 3 Session Report

### Task Goal

Isolate what `v2` adds beyond batching alone by running a controlled Intel `v1` versus `v2` comparison across `clean`, `bandwidth_200kbps`, and `outage_5s` at the same five fixed batch windows, then regenerate tracked report assets so the paper can answer the question directly.

### What Was Changed

- Added `experiments/run_v1_v2_isolation_sweep.py` to run the dedicated Intel `v1` versus `v2` isolation sweep.
- Extended `experiments/build_report_assets.py` with optional `intel_v1_v2_sweep_dir` support and generated:
  - `report/assets/tables/intel_v1_vs_v2_isolation.csv`
  - `report/assets/tables/intel_v1_vs_v2_isolation.md`
  - `report/assets/figures/intel_v1_vs_v2_isolation.png`
- Updated generated outputs to include the new isolation evidence:
  - `report/final_report.md`
  - `report/deliverable_gate.md`
  - `report/assets/evidence_manifest.json`
  - `report/assets/tables/intel_key_claims.md`
- Updated `report/reproducibility.md` with the local-only `v1` versus `v2` sweep command and the matching report-asset regeneration command.
- Added and updated tests for the new runner and optional asset-builder path.
- Updated the third M6 checklist item locally only.

### Commands Run

```powershell
python -m pytest tests/test_run_v1_v2_isolation_sweep.py tests/test_build_report_assets.py tests/test_run_sweep.py tests/test_run_batch_window_sweep.py
python .\experiments\run_v1_v2_isolation_sweep.py --sweep-id intel-v1-v2-isolation-20260403 --data-file .\experiments\logs\generated_inputs\intel_lab_final_20260403.csv
python .\experiments\build_report_assets.py --intel-sweep-dir .\experiments\logs\final-intel-primary-20260403 --aot-sweep-dir .\experiments\logs\final-aot-validation-20260403 --demo-dir .\experiments\logs\final-demo-20260403\demo --intel-batch-sweep-dir .\experiments\logs\intel-v2-batch-window-20260403 --intel-v1-v2-sweep-dir .\experiments\logs\intel-v1-v2-isolation-20260403 --output-dir .\report\assets
python -m pytest tests/test_run_sweep.py tests/test_run_batch_window_sweep.py tests/test_run_v1_v2_isolation_sweep.py tests/test_build_report_assets.py
```

### Verification Results

- The unit-test suite for the sweep plumbing and report builder passed before and after regenerating the tracked assets.
- The real Intel isolation sweep completed successfully and wrote local logs under `experiments/logs/intel-v1-v2-isolation-20260403/`.
- The tracked report package regenerated successfully with the new optional sweep input and now references the isolation table and figure.

### Measured Intel V1 Versus V2 Outcome

| Scenario | Bytes delta range (`v2` vs `v1`) | Frames delta range (`v2` vs `v1`) | Latency p95 delta range | Stale-fraction delta range |
| --- | --- | --- | --- | --- |
| `clean` | `-1.1%` to `0.0%` | `-6.2%` to `0.0%` | `-7.45 ms` to `+2.0 ms` | `-0.027778` to `0.0` |
| `bandwidth_200kbps` | `0.0%` to `+6.9%` | `0.0%` to `+20.0%` | `-9.9 ms` to `+6.1 ms` | `0.0` to `+0.027778` |
| `outage_5s` | `0.0%` | `0.0%` | `-10.0 ms` to `+14.0 ms` | `0.0` to `+0.025` |

Additional raw-sweep observation: `duplicates_dropped`, `compacted_dropped`, and `value_dedup_dropped` were all `0` in every one of the `30` isolation runs.

### Analysis

This task produced a useful negative answer. On the current Intel qos0 slice, `v2` does not show a consistent benefit over `v1` once both are already using the same fixed batch window. Most scenario-window pairs were identical on downstream bytes and frame count, and the counters that would show actual duplicate or compaction drops remained zero across the entire sweep.

The only measurable differences were small and mixed. Under `clean` at `50 ms`, `v2` reduced downstream frames from `16` to `15` and bytes from `14921` to `14751` (`-1.1%`). Under `bandwidth_200kbps` at `250 ms`, `v2` moved in the opposite direction, increasing frames from `5` to `6` and bytes from `13051` to `13958` (`+6.9%`). The outage runs were effectively identical on bytes and frames across all five windows.

The paper-ready conclusion is therefore narrow and defensible: on this dataset and replay configuration, batching is doing almost all of the visible work, while `v2`'s extra compaction and exact-duplicate suppression do not materially change the outcome beyond batching alone. That is exactly the result the checklist needed, even though it is not a positive win for `v2`.

### Commit And Push Note

`PRD.md` and `PROJECT_CHECKLIST.md` remain local-only for this session and must not be staged or pushed. The push should contain the new isolation runner, test updates, regenerated tracked report assets, the reproducibility update, and this appended `report.md`.

## MP6 Task 4 Session Report

### Task Goal

Evaluate whether adaptive publish rate helps under impairment by running a controlled Intel `v2` versus `v3` comparison under `bandwidth_200kbps` and `loss_2pct`, regenerating tracked report assets, and recording a paper-ready answer tied to stale fraction, rendered cadence, and the actual adaptive-window trace.

### What Was Changed

- Extended `experiments/run_sweep.py` so a sweep can pass gateway-only environment overrides through `SweepConfig.gateway_env_overrides`.
- Added `experiments/run_adaptive_impairment_sweep.py` to run the dedicated Intel `v2` versus `v3` adaptive impairment sweep.
- Extended `experiments/build_report_assets.py` with optional `intel_adaptive_sweep_dir` support and generated:
  - `report/assets/tables/intel_v2_vs_v3_adaptive_impairment.csv`
  - `report/assets/tables/intel_v2_vs_v3_adaptive_impairment.md`
  - `report/assets/figures/intel_v2_vs_v3_adaptive_impairment.png`
- Updated generated outputs to include the adaptive evidence:
  - `report/final_report.md`
  - `report/deliverable_gate.md`
  - `report/assets/evidence_manifest.json`
  - `report/assets/tables/intel_key_claims.md`
- Updated `report/reproducibility.md` with the local-only adaptive sweep command and matching report-asset regeneration command.
- Added and updated tests for the new runner, the gateway override plumbing, and the optional asset-builder path.
- Updated the fourth M6 checklist item locally only and narrowed it to an adaptation-trace-backed claim instead of requiring separate backlog instrumentation.

### Commands Run

```powershell
python -m pytest tests/test_run_sweep.py tests/test_run_adaptive_impairment_sweep.py tests/test_build_report_assets.py
python .\experiments\run_adaptive_impairment_sweep.py --sweep-id intel-v2-v3-adaptive-20260404 --data-file .\experiments\logs\generated_inputs\intel_lab_final_20260403.csv
python .\experiments\build_report_assets.py --intel-sweep-dir .\experiments\logs\final-intel-primary-20260403 --aot-sweep-dir .\experiments\logs\final-aot-validation-20260403 --demo-dir .\experiments\logs\final-demo-20260403\demo --intel-batch-sweep-dir .\experiments\logs\intel-v2-batch-window-20260403 --intel-v1-v2-sweep-dir .\experiments\logs\intel-v1-v2-isolation-20260403 --intel-adaptive-sweep-dir .\experiments\logs\intel-v2-v3-adaptive-20260404 --output-dir .\report\assets
```

### Verification Results

- `python -m pytest tests/test_run_sweep.py tests/test_run_adaptive_impairment_sweep.py tests/test_build_report_assets.py` passed before the real sweep.
- The real Intel adaptive sweep completed successfully and wrote local logs under `experiments/logs/intel-v2-v3-adaptive-20260404/`.
- The tracked report assets regenerated successfully with the new optional adaptive-sweep input and now include the adaptive table and figure.

### Measured Intel V2 Versus V3 Adaptive Outcome

| Scenario | Latency p95 delta (`v3` vs `v2`) | Stale fraction delta | Max update-rate delta | Frames delta | Bytes delta | V3 window range | V3 adaptive events |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `bandwidth_200kbps` | `-8.55 ms` | `0.0` | `0.0%` | `0.0%` | `0.0%` | `250 ms` to `250 ms` | `0` increase, `0` decrease |
| `loss_2pct` | `+7.45 ms` | `0.0` | `0.0%` | `0.0%` | `0.0%` | `250 ms` to `250 ms` | `0` increase, `0` decrease |

Additional raw-trace observation: the last `v3` adaptation reason in both runs was `healthy_streak=1`, and the effective batch window stayed flat at the base `250 ms` for the entire trace.

### Analysis

This task also produced a useful negative result. Under the current adaptive defaults, `v3` did not actually adapt in either required impairment scenario. The effective batch window stayed fixed at `250 ms`, `adaptive_window_increase_events` and `adaptive_window_decrease_events` both remained `0`, and all of the headline paper metrics stayed unchanged versus `v2` except for small mixed latency noise.

That means the defensible paper answer is narrow: in this Intel qos0 setup, the current adaptive policy did not activate under `bandwidth_200kbps` or `loss_2pct`, so it did not improve stale fraction or rendered cadence beyond fixed-window `v2`. The new adaptation-trace figure still closes the checklist gap because it makes that null result explicit instead of leaving the paper to imply that adaptation helped when the measured trace stayed flat.

This also keeps the scope correct for M6. There is no need to add new backlog instrumentation just to complete the item; the paper can now state that under the default thresholds, the adaptive path did not materially change behavior in these two impairment cases.

### Commit And Push Note

`PRD.md` and `PROJECT_CHECKLIST.md` remain local-only for this session and must not be staged or pushed. The push should contain the new adaptive runner, sweep-plumbing update, regenerated tracked report assets, the reproducibility update, and this appended `report.md`.

## MP6 Task 5 Session Report

### Task Goal

Show the LKG plus TTL effect on freshness perception with a paper-ready Intel outage artifact, using the existing `final-intel-primary-20260403` outage runs instead of adding new gateway behavior or a separate sweep.

### What Was Changed

- Extended `experiments/build_report_assets.py` to derive a default outage freshness artifact from the existing Intel primary sweep.
- Added generated freshness outputs:
  - `report/assets/figures/intel_outage_qos0_v0_vs_v4_age_over_time.png`
  - `report/assets/tables/intel_outage_qos0_v0_vs_v4_freshness.csv`
  - `report/assets/tables/intel_outage_qos0_v0_vs_v4_freshness.md`
- Updated generated report outputs to include the new freshness claim and artifact references:
  - `report/final_report.md`
  - `report/deliverable_gate.md`
  - `report/assets/evidence_manifest.json`
  - `report/assets/tables/intel_key_claims.md`
- Updated `report/reproducibility.md` to note that this task regenerates from the existing Intel primary sweep and does not require a separate local-only sweep.
- Updated `tests/test_build_report_assets.py` to lock the new default artifact contract and report wording.
- Updated `PROJECT_CHECKLIST.md` locally only so the freshness item is marked done and the required-figures item reflects that only the explicit QoS comparison remains missing.

### Commands Run

```powershell
python -m pytest tests/test_build_report_assets.py
python .\experiments\build_report_assets.py --intel-sweep-dir .\experiments\logs\final-intel-primary-20260403 --aot-sweep-dir .\experiments\logs\final-aot-validation-20260403 --demo-dir .\experiments\logs\final-demo-20260403\demo --intel-batch-sweep-dir .\experiments\logs\intel-v2-batch-window-20260403 --intel-v1-v2-sweep-dir .\experiments\logs\intel-v1-v2-isolation-20260403 --intel-adaptive-sweep-dir .\experiments\logs\intel-v2-v3-adaptive-20260404 --output-dir .\report\assets
```

### Verification Results

- `python -m pytest tests/test_build_report_assets.py` passed.
- No new sweep was required; the outage freshness artifact regenerated directly from `v0-qos0-outage_5s` and `v4-qos0-outage_5s` inside `final-intel-primary-20260403`.
- The tracked report package now includes the new age-over-time figure, supporting table, manifest entries, deliverable-gate references, and paper text that explicitly says this task is answered by age-of-information over time rather than a stale-fraction-over-time plot.

### Measured Intel Outage Freshness Result

| Variant | Pre-outage rendered updates | Pre-outage mean age | Pre-outage p95 age | Outage rendered updates | Recovery rendered updates | Recovery mean age | Recovery p95 age | Recovery max age | End-state stale/latest |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `v0` | `64` | `20.781 ms` | `44.0 ms` | `0` | `52` | `66.923 ms` | `119.9 ms` | `129.0 ms` | `80 / 80` |
| `v4` | `112` | `284.196 ms` | `580.0 ms` | `0` | `68` | `190.279 ms` | `269.0 ms` | `269.0 ms` | `100 / 100` |

### Analysis

This task closes the freshness-evidence gap with a narrow but defensible result. The current dashboard export does not support a true stale-fraction-over-time trace because it records measurements only on rendered updates, not during idle periods. The right paper artifact here is therefore age-of-information over time, tied to the outage and recovery phases.

The measured outcome is not a lower-age win for `v4`. In both the pre-outage and recovery phases, `v4` showed substantially older displayed data than `v0` (`580.0 ms` versus `44.0 ms` pre-outage p95, and `269.0 ms` versus `119.9 ms` recovery p95). During the five-second outage, neither side rendered new updates.

What `v4` did provide was a larger retained last-known-good state at the end of the run. The final dashboard summary showed `100` stale/latest rows for `v4` versus `80` for `v0`, which is consistent with the intended LKG plus TTL behavior: preserve more visible state through the outage and recovery window, even though the visible values are older. The paper can now state that tradeoff directly instead of implying a generic freshness improvement.

### Commit And Push Note

`PRD.md` and `PROJECT_CHECKLIST.md` remain local-only for this session and must not be staged or pushed. The push should contain the builder update, regenerated tracked report assets, the reproducibility update, the refreshed report text, the test update, and this appended `report.md`.

## MP6 Task 8 Session Report

### Task Goal

Align the paper-facing latency reporting with the metrics already computed by `experiments/analyze_run.py` by making the report assets explicit about mean, p50, p95, and p99, then regenerate the tracked report package and lock the contract with tests.

### What Was Changed

- Expanded `experiments/build_report_assets.py` so the paper tables now carry the full latency set consistently: mean, p50, p95, and p99.
- Updated the rendered report narrative to include a dedicated latency-metrics subsection in `report/final_report.md` stating that p95 stays the headline metric while the other summaries remain visible in the tables.
- Regenerated the tracked report assets so the main summary and condensed summary tables now show the complete latency set, and the related comparison tables also carry the same metric family.
- Updated `tests/test_build_report_assets.py` so the new table contract is enforced by test, including the expanded latency columns and the report wording.
- Updated `PROJECT_CHECKLIST.md` locally only so G4 is marked complete.

### Commands Run

```powershell
& .\.venv\Scripts\python.exe -m unittest tests.test_build_report_assets
& .\.venv\Scripts\python.exe experiments\build_report_assets.py --intel-sweep-dir experiments\logs\final-intel-primary-20260403 --aot-sweep-dir experiments\logs\final-aot-validation-20260403 --demo-dir experiments\logs\final-demo-20260403\demo --intel-batch-sweep-dir experiments\logs\intel-v2-batch-window-20260403 --intel-v1-v2-sweep-dir experiments\logs\intel-v1-v2-isolation-20260403 --intel-adaptive-sweep-dir experiments\logs\intel-v2-v3-adaptive-20260404 --output-dir report\assets
& .\.venv\Scripts\python.exe -m unittest tests.test_build_report_assets
```

### Verification Results

- `python -m unittest tests.test_build_report_assets` passed before and after regeneration.
- The generated `report/final_report.md` now includes the latency-metrics subsection and explicitly states that the paper standardizes on mean, p50, p95, and p99.
- The tracked summary tables now show the full latency family instead of p95 alone, so the paper no longer has a mismatch between what the analysis computes and what the narrative claims.

### Analysis

The important result here is not a new performance measurement; it is reporting alignment. `analyze_run.py` already computed mean, p50, p95, and p99, but the paper assets mostly surfaced p95 only. That left the report with a narrow claim surface that did not fully reflect the available statistics.

After this update, the paper can make a clean statement: p95 remains the top-line latency comparison in the prose, but the underlying tables now expose the full distribution summary consistently. That reduces ambiguity for readers and makes the report easier to defend because the metric policy is explicit instead of implicit.

The generated assets also remain internally consistent with the measured results. The tables continue to show the same tradeoffs as before, but now the latency summaries are presented in a way that matches the analysis pipeline end-to-end.

### Commit And Push Note

`PRD.md` and `PROJECT_CHECKLIST.md` remain local-only for this session and must not be staged or pushed. The push should contain the builder update, regenerated tracked report assets, the refreshed report text, the test update, and this appended `report.md`.

## MP6 Task 6 Session Report

### Task Goal

Complete the next M6 checklist item by adding an explicit Intel QoS `0` versus QoS `1` comparison artifact path that reports duplicate rate, ingress overhead, downstream bandwidth/frame impact, and latency deltas, then regenerate tracked report outputs and capture a bounded interpretation for the paper.

### What Was Changed

- Extended `experiments/build_report_assets.py` with a new paired QoS comparison pipeline:
  - `_build_intel_qos_comparison_rows(...)`
  - `_plot_qos_comparison(...)`
  - `_format_qos_comparison_series(...)`
- Added generated QoS comparison outputs:
  - `report/assets/tables/intel_qos_comparison.csv`
  - `report/assets/tables/intel_qos_comparison.md`
  - `report/assets/figures/intel_qos_comparison.png`
- Integrated the new QoS artifacts into generated documents:
  - `report/final_report.md`
  - `report/deliverable_gate.md`
  - `report/assets/evidence_manifest.json`
  - `report/assets/tables/intel_key_claims.md`
- Updated `tests/test_build_report_assets.py` to lock the new QoS output contract.
- Updated `PROJECT_CHECKLIST.md` locally only to mark:
  - M6 QoS comparison task as done
  - M6 required figures task as done (explicit QoS plot now present)

### Commands Run

```powershell
python -m pytest tests/test_build_report_assets.py
python .\experiments\build_report_assets.py --intel-sweep-dir .\experiments\logs\final-intel-primary-20260403 --aot-sweep-dir .\experiments\logs\final-aot-validation-20260403 --demo-dir .\experiments\logs\final-demo-20260403\demo --intel-batch-sweep-dir .\experiments\logs\intel-v2-batch-window-20260403 --intel-v1-v2-sweep-dir .\experiments\logs\intel-v1-v2-isolation-20260403 --intel-adaptive-sweep-dir .\experiments\logs\intel-v2-v3-adaptive-20260404 --output-dir .\report\assets
```

### Verification Results

- `python -m pytest tests/test_build_report_assets.py` passed (`5 passed`).
- Report assets regenerated cleanly from existing final logs.
- The manifest now includes the QoS comparison table and figure.

### Measured Intel QoS Comparison Result

| Scenario | Variant | Latency p95 delta (`qos1 - qos0`) | Downstream bytes delta | Downstream frames delta | Ingress msgs delta | QoS1 duplicates dropped |
| --- | --- | --- | --- | --- | --- | --- |
| `clean` | `v0` | `-8.8 ms` | `0.0%` | `0.0%` | `0.0%` | `0` |
| `clean` | `v2` | `+3.45 ms` | `0.0%` | `0.0%` | `0.0%` | `0` |
| `clean` | `v4` | `-215.0 ms` | `0.0%` | `0.0%` | `0.0%` | `0` |
| `bandwidth_200kbps` | `v0` | `+22.35 ms` | `0.0%` | `0.0%` | `0.0%` | `0` |
| `bandwidth_200kbps` | `v2` | `+15.1 ms` | `0.0%` | `0.0%` | `0.0%` | `0` |
| `bandwidth_200kbps` | `v4` | `-165.0 ms` | `+1.0%` | `+16.7%` | `0.0%` | `0` |
| `loss_2pct` | `v0` | `+2.1 ms` | `0.0%` | `0.0%` | `0.0%` | `0` |
| `loss_2pct` | `v2` | `-5.55 ms` | `0.0%` | `0.0%` | `0.0%` | `0` |
| `loss_2pct` | `v4` | `-27.0 ms` | `0.0%` | `0.0%` | `0.0%` | `0` |
| `outage_5s` | `v0` | `+4.0 ms` | `0.0%` | `0.0%` | `0.0%` | `0` |
| `outage_5s` | `v2` | `-3.75 ms` | `0.0%` | `0.0%` | `0.0%` | `0` |
| `outage_5s` | `v4` | `-125.95 ms` | `-11.5%` | `-16.7%` | `0.0%` | `0` |

### Analysis

This task closes the QoS evidence gap with a bounded, setup-specific answer. The observed exact duplicate-drop count stayed at `0` across the Intel qos1 comparison matrix, so the report can validly state that no exact duplicates were observed in this environment, without claiming that qos1 duplicates never happen in general.

The measured ingress message overhead was also `0.0%` for all paired runs, and most downstream payload/frame deltas were `0.0%`, with only small scenario-specific movement in `v4` (`+1.0%` bytes and `+16.7%` frames under `bandwidth_200kbps`, `-11.5%` bytes and `-16.7%` frames under `outage_5s`). This indicates that in the current local setup, qos level did not materially change downstream volume behavior.

Latency p95 shifts were mixed in sign and magnitude by scenario/variant (for example `+22.35 ms` for `v0` under `bandwidth_200kbps`, `-125.95 ms` for `v4` under `outage_5s`), so the correct paper framing is comparative and empirical rather than causal. The new table and figure now make that bounded interpretation explicit.

### Commit And Push Note

`PRD.md` and `PROJECT_CHECKLIST.md` remain local-only for this session and must not be staged or pushed. The push should contain the QoS builder/test changes, regenerated tracked report assets, refreshed generated report documents, and this appended `report.md`.

## MP6 Task 7 Session Report

### Task Goal

Complete the next M6 checklist item by adding one condensed Intel summary table that paper readers can scan quickly, then regenerate tracked assets and document the measured interpretation.

### What Was Changed

- Extended `experiments/build_report_assets.py` with `_build_intel_condensed_summary_rows(...)`.
- Added condensed summary outputs:
  - `report/assets/tables/intel_condensed_summary.csv`
  - `report/assets/tables/intel_condensed_summary.md`
- Integrated condensed outputs into generated documents and manifest:
  - `report/final_report.md`
  - `report/deliverable_gate.md`
  - `report/assets/evidence_manifest.json`
- Updated `tests/test_build_report_assets.py` to lock the condensed-table output contract and references.
- Updated `PROJECT_CHECKLIST.md` locally only so the condensed-summary task is now marked done.

### Commands Run

```powershell
python -m pytest tests/test_build_report_assets.py
python .\experiments\build_report_assets.py --intel-sweep-dir .\experiments\logs\final-intel-primary-20260403 --aot-sweep-dir .\experiments\logs\final-aot-validation-20260403 --demo-dir .\experiments\logs\final-demo-20260403\demo --intel-batch-sweep-dir .\experiments\logs\intel-v2-batch-window-20260403 --intel-v1-v2-sweep-dir .\experiments\logs\intel-v1-v2-isolation-20260403 --intel-adaptive-sweep-dir .\experiments\logs\intel-v2-v3-adaptive-20260404 --output-dir .\report\assets
```

### Verification Results

- `python -m pytest tests/test_build_report_assets.py` passed (`5 passed`).
- The regeneration command completed successfully and the manifest now includes:
  - `report/assets/tables/intel_condensed_summary.csv`
  - `report/assets/tables/intel_condensed_summary.md`

### Measured Condensed Intel Summary (QoS0)

| Scenario | Variant | Latency p95 | Downstream frames | Downstream bytes | Stale fraction |
| --- | --- | --- | --- | --- | --- |
| `clean` | `v0` | `131.8 ms` | `132` | `12069` | `0.0` |
| `clean` | `v2` | `269.0 ms` | `5` | `13051` | `0.0` |
| `clean` | `v4` | `682.0 ms` | `6` | `17641` | `0.0` |
| `bandwidth_200kbps` | `v0` | `119.35 ms` | `132` | `12069` | `0.0` |
| `bandwidth_200kbps` | `v2` | `263.9 ms` | `5` | `13051` | `0.0` |
| `bandwidth_200kbps` | `v4` | `604.0 ms` | `6` | `17641` | `0.0` |
| `loss_2pct` | `v0` | `120.55 ms` | `130` | `11883` | `0.0` |
| `loss_2pct` | `v2` | `269.0 ms` | `5` | `13051` | `0.0` |
| `loss_2pct` | `v4` | `586.0 ms` | `6` | `17641` | `0.0` |
| `outage_5s` | `v0` | `112.25 ms` | `116` | `10605` | `0.0` |
| `outage_5s` | `v2` | `277.0 ms` | `4` | `11401` | `0.0` |
| `outage_5s` | `v4` | `579.0 ms` | `6` | `17641` | `0.0` |

### Analysis

This task adds the exact compact scan artifact requested by the checklist. It makes the core tradeoff visible in one place: smart variants (`v2`, `v4`) drastically reduce downstream frame count compared with `v0`, but they do not reduce downstream payload bytes and they increase p95 latency, especially for `v4`. The stale fraction remained `0.0` in this condensed qos0 matrix.

That means the paper can now point readers to one table for a quick evidence overview before the deeper per-task tables and figures. This closes the condensed-summary evidence gap without changing gateway behavior.

### Commit And Push Note

`PRD.md` and `PROJECT_CHECKLIST.md` remain local-only for this session and must not be staged or pushed. The push should contain the builder/test changes, regenerated tracked report artifacts, refreshed generated report docs, and this appended `report.md`.

## MP6 Task 8 Session Report

### Task Goal

Complete the final open M6 checklist item by producing an explicit claim guardrail review artifact that blocks unbounded paper claims unless directly measured, then regenerate report outputs and document what the bounded interpretation means for the final paper narrative.

### What Was Changed

- Extended `experiments/build_report_assets.py` with `_build_claim_guardrail_review(...)` to generate:
  - `report/assets/tables/intel_claim_guardrail_review.md`
- Wired the guardrail artifact into generated report outputs:
  - `report/final_report.md`
  - `report/deliverable_gate.md`
  - `report/assets/evidence_manifest.json`
- Updated `tests/test_build_report_assets.py` to lock guardrail output contract and references.
- Updated `PROJECT_CHECKLIST.md` locally only to mark the final M6 task done.

### Commands Run

```powershell
python -m unittest tests.test_build_report_assets
python .\experiments\build_report_assets.py --intel-sweep-dir experiments/logs/final-intel-primary-20260403 --aot-sweep-dir experiments/logs/final-aot-validation-20260403 --demo-dir experiments/logs/final-demo-20260403/demo --intel-batch-sweep-dir experiments/logs/intel-v2-batch-window-20260403 --intel-v1-v2-sweep-dir experiments/logs/intel-v1-v2-isolation-20260403 --intel-adaptive-sweep-dir experiments/logs/intel-v2-v3-adaptive-20260404 --output-dir report/assets
```

### Verification Results

- `python -m unittest tests.test_build_report_assets` passed (`Ran 5 tests ... OK`).
- Report asset regeneration completed successfully and manifest output now includes:
  - `report/assets/tables/intel_claim_guardrail_review.md`
- Generated `report/final_report.md` now references the explicit guardrail review artifact.
- Generated `report/deliverable_gate.md` now lists guardrail review in final summary tables.

### Guardrail Review Summary

| Guardrail | Blocked unbounded claim | Bounded measured interpretation |
| --- | --- | --- |
| Latency | "Agrasandhani lowers latency overall" | In current Intel evidence, V4 has higher p95 latency than V0 on the clean qos0 run, so the valid claim is a latency-for-stability tradeoff. |
| Reliability | "QoS1 improves reliability in general" | The current matrix observed `0` exact duplicate drops for qos1 and mixed latency shifts, which is setup-specific behavior, not a universal reliability conclusion. |
| Network loss | "Agrasandhani reduces network loss" | Experiments use controlled impairment scenarios and application-level metrics; they do not directly measure reduced network-loss rates attributable to the gateway. |
| Safer wording | "Universal improvements across all metrics" | Use bounded claims tied to evidence, such as reduced downstream frame cadence, explicit freshness-visibility tradeoffs, reduced redundant transmissions when measured, and graceful degradation under tested outage scenarios. |

### Analysis

This final task closes the M6 readiness gate by adding an explicit, auditable claim-boundary artifact instead of relying only on conservative prose scattered through the report. The new guardrail table makes it clear which claims are blocked, why they are blocked, and what safer alternatives are justified by measured outputs.

The practical impact is that the paper now has a hard boundary against over-claiming. It can still present strong measured results where evidence is clear (for example frame-cadence reduction and outage visibility behavior), but it does not overstate wins on latency, reliability, or network loss where direct support is missing or definition-dependent. That improves methodological credibility and aligns the final write-up with the checklist's explicit M6 requirements.

### Commit And Push Note

`PRD.md` and `PROJECT_CHECKLIST.md` remain local-only for this session and must not be staged or pushed. The push should contain builder/test changes, regenerated tracked report assets, refreshed generated report docs, and this appended `report.md`.

## Project Checklist G1 Session Report

### Task Goal

Implement the first open task in `PROJECT_CHECKLIST.md` (G1) by resolving the dataset mismatch in `context.md`, then verify consistency with `report/final_report.md` and `report/reproducibility.md` so the project narrative reflects only datasets that have implemented preprocessing, replay runs, and tracked evidence.

### What Was Changed

- Updated `context.md` Section 8 to remove unsupported wording that implied a generic Environmental/Temperature dataset.
- Replaced the second-dataset description with the concrete implemented source: Intel Berkeley Lab deployment data.
- Clarified AoT positioning as portability/validation and Intel as primary final-matrix workload.
- Added an explicit sentence in `context.md` stating no additional temperature-only dataset is used in tracked final evidence.
- Updated `PROJECT_CHECKLIST.md` locally to mark G1 complete.

### Commands Run

```powershell
python -m pytest tests/test_preprocess_aot.py tests/test_preprocess_intel_lab.py tests/test_build_report_assets.py
python -m unittest tests.test_preprocess_aot tests.test_preprocess_intel_lab tests.test_build_report_assets
```

### Verification Results

- `pytest` command failed because `pytest` is not installed in the active venv (`No module named pytest`).
- Equivalent targeted validation succeeded with `unittest`:
  - `Ran 9 tests in 12.511s`
  - `OK`
- Cross-document wording check confirmed two-dataset consistency across:
  - `context.md`
  - `report/final_report.md`
  - `report/reproducibility.md`
- No remaining statement was found that implies a third standalone temperature dataset in the tracked narrative.

### Analysis

This is a documentation-integrity fix, not a gateway behavior change. No experiment code paths, impairment logic, or replay-analysis computations were modified by this task. Therefore, metric outcomes from previously generated evidence remain unchanged.

The impact is methodological: the narrative layer now correctly constrains claims to the two datasets that are actually implemented and evidenced (Intel Berkeley Lab and AoT). That matters for the experiment because dataset scope is part of external validity. Before this correction, readers could infer broader dataset coverage than the repository can substantiate. After this correction, the claim boundary is tighter and auditable against preprocessors, reproducibility steps, and tracked artifacts.

In practical paper terms, this strengthens reproducibility and reduces over-claim risk. Conclusions should now be interpreted as supported by a primary Intel matrix plus AoT portability validation, rather than by an implied third temperature dataset. This improves alignment between what was measured and what is stated.

### Commit And Push Note

`PROJECT_CHECKLIST.md` and `PRD.md` are local-only in this session and must not be staged or pushed.

## Project Checklist G2 Session Report

### Task Goal

Promote the Intel outage frame-rate figure to the main report narrative so the paper treats it as the primary outage result, not as a secondary artifact hidden behind aggregate bandwidth language. The goal was to make the generated report explicitly reference [report/assets/figures/main_outage_frame_rate.png](report/assets/figures/main_outage_frame_rate.png) and explain the outage/recovery behavior in frame-rate continuity terms for V0, V2, and V4.

### What Was Changed

- Updated `experiments/build_report_assets.py` so the generated final-report text now includes an explicit paragraph for `main_outage_frame_rate.png`.
- Framed that paragraph as the paper's primary outage result and described the result in continuity terms rather than byte-volume terms.
- Kept the narrative aligned with `context.md` Section 7, which already defines the outage frame-rate figure as the main figure of the paper.
- Added a regression assertion in `tests/test_build_report_assets.py` so the generated report must keep citing `main_outage_frame_rate.png` and must keep the primary-result wording.
- Regenerated `report/final_report.md` from the builder so the tracked output now contains the updated results narrative.
- Marked the G2 checklist item complete locally in `PROJECT_CHECKLIST.md` without staging it for push.

### Commands Run

```powershell
& ".venv\Scripts\python.exe" .\experiments\build_report_assets.py --intel-sweep-dir .\experiments\logs\final-intel-primary-20260403 --aot-sweep-dir .\experiments\logs\final-aot-validation-20260403 --demo-dir .\experiments\logs\final-demo-20260403\demo --intel-batch-sweep-dir .\experiments\logs\intel-v2-batch-window-20260403 --intel-v1-v2-sweep-dir .\experiments\logs\intel-v1-v2-isolation-20260403 --intel-adaptive-sweep-dir .\experiments\logs\intel-v2-v3-adaptive-20260404 --output-dir .\report\assets
& ".venv\Scripts\python.exe" -m pytest tests\test_build_report_assets.py -v
& ".venv\Scripts\python.exe" -m unittest tests.test_build_report_assets
```

### Verification Results

- The report builder completed successfully and regenerated the tracked report assets.
- The generated [report/final_report.md](report/final_report.md) now contains the explicit paragraph tying the outage story to [report/assets/figures/main_outage_frame_rate.png](report/assets/figures/main_outage_frame_rate.png).
- `pytest` is not installed in the active virtual environment, so the equivalent `unittest` path was used for regression verification.
- `python -m unittest tests.test_build_report_assets` passed with `Ran 5 tests in 19.838s` and `OK`.

### Analysis

This change does not alter the experiment data or the dashboard behavior. It changes how the measured evidence is presented in the final report so the paper's central outage claim matches the repository's own source of truth: frame-rate continuity is the primary outage outcome.

That framing matters because the figure shows a different kind of success than the bandwidth tables. V0 remains the most bursty and least stable trace through the outage window, which makes the dashboard harder to read when continuity matters. V2 and V4 compress the stream into steadier, lower-cadence traces, and that makes the outage and recovery periods easier for an operator to follow. In other words, the smart gateway's value here is not lower payload volume; it is visual continuity under interruption.

The result is also properly bounded. V4 is the most aggressive at stabilizing the display cadence, but that should be read as a readability and continuity win, not as a throughput win. This keeps the paper aligned with the measured evidence: the main outage figure supports the claim that the system preserves a usable live view through interruption by trading frame frequency for steadier continuity.

### Commit And Push Note

`PRD.md` and `PROJECT_CHECKLIST.md` remain local-only in this session and must not be staged or pushed. The push should contain the builder update, the updated test, the regenerated tracked report assets, and this appended `report.md` section.

## Project Checklist G3 Session Report

### Task Goal

Close the next open checklist item by surfacing the Intel outage bandwidth-over-time evidence in the final report text, without overclaiming bandwidth reduction and while staying consistent with the existing Intel bandwidth-vs-V0 table.

### What Was Changed

- Updated `experiments/build_report_assets.py` so the generated final report now includes a dedicated paragraph for `report/assets/figures/intel_outage_qos1_bandwidth_over_time.png`.
- Framed that paragraph as an interpretation of the outage/recovery bandwidth trace, not as a payload-byte reduction claim.
- Kept the wording aligned with `report/assets/tables/intel_bandwidth_vs_v0.md`, which already shows V2 and V4 increasing downstream bytes versus V0 in the Intel qos0 scenarios.
- Updated `tests/test_build_report_assets.py` to assert the new figure reference and bounded wording appear in the generated report.
- Marked the G3 checklist item complete locally in `PROJECT_CHECKLIST.md`.

### Commands Run

```powershell
python -m pytest tests/test_build_report_assets.py
python .\experiments\build_report_assets.py --intel-sweep-dir .\experiments\logs\final-intel-primary-20260403 --aot-sweep-dir .\experiments\logs\final-aot-validation-20260403 --demo-dir .\experiments\logs\final-demo-20260403\demo --intel-batch-sweep-dir .\experiments\logs\intel-v2-batch-window-20260403 --intel-v1-v2-sweep-dir .\experiments\logs\intel-v1-v2-isolation-20260403 --intel-adaptive-sweep-dir .\experiments\logs\intel-v2-v3-adaptive-20260404 --output-dir .\report\assets
```

### Verification Results

- `python -m unittest tests.test_build_report_assets` passed with `Ran 5 tests` and `OK`.
- The regenerated `report/final_report.md` now explicitly cites `report/assets/figures/intel_outage_qos1_bandwidth_over_time.png`.
- The new paragraph stays bounded: it treats the trace as outage/recovery shape evidence and does not claim a payload-byte reduction.
- The interpretation remains consistent with `report/assets/tables/intel_bandwidth_vs_v0.md`, which shows V2 and V4 increasing downstream bytes versus V0 in the Intel qos0 scenarios.

### Analysis

The right reading of the figure is operational, not promotional. The bandwidth-over-time trace shows when payload bytes move through the outage window, which helps explain the shape of the stream during interruption and recovery. It does not support a lower-bandwidth claim because the existing Intel bandwidth-vs-V0 table shows the opposite direction on total downstream bytes. That makes the figure useful as support for outage behavior, but not as evidence of byte savings.

This matters for the paper because it keeps the claims bounded to the actual measured behavior. The project can confidently say that the smart gateway changes the cadence and timing of downstream traffic through outage, but it should not imply that those changes reduce total bytes in this evidence set. The updated report text now reflects that distinction directly.

## Project Checklist G6 Session Report

### Task Goal

Resolve the remaining impairment-path inconsistency by aligning wording across `context.md`, `report/final_report.md`, `README_reproducibility.md`, and `research_paper/Sections/evaluation.tex` so all documents describe the same evaluated injection path and match the measured downstream proxy metrics.

### What Was Changed

- Updated `context.md` to explicitly state that evaluated impairments are injected primarily on the gateway-to-dashboard last hop through the impairment proxy, with optional host-level `tc netem` shaping in the same last-hop context.
- Updated `README_reproducibility.md` to add an explicit impairment-placement block and tie reported downstream metrics to proxy-level outputs (`proxy_downstream_bytes_out`, `proxy_downstream_frames_out`).
- Updated `research_paper/Sections/evaluation.tex` in the Evaluation Setting subsection to describe proxy-first last-hop impairment placement, with optional `tc netem` in that same context, and to state that downstream evidence comes from proxy counters.
- Updated `experiments/build_report_assets.py` so generated final-report method text now carries the same canonical impairment-path wording.
- Regenerated `report/final_report.md` from existing April logs so the tracked report artifact reflects the aligned statement.
- Updated `tests/test_build_report_assets.py` with regression assertions that the generated final report retains the new impairment-path wording and proxy metric identifiers.
- Updated `PROJECT_CHECKLIST.md` locally to mark G6 complete and to mark the related completion-gate checks satisfied.

### Commands Run

```powershell
.\.venv\Scripts\python.exe .\experiments\build_report_assets.py --intel-sweep-dir .\experiments\logs\final-intel-primary-20260403 --aot-sweep-dir .\experiments\logs\final-aot-validation-20260403 --demo-dir .\experiments\logs\final-demo-20260403\demo --intel-batch-sweep-dir .\experiments\logs\intel-v2-batch-window-20260403 --intel-v1-v2-sweep-dir .\experiments\logs\intel-v1-v2-isolation-20260403 --intel-adaptive-sweep-dir .\experiments\logs\intel-v2-v3-adaptive-20260404 --output-dir .\report\assets
.\.venv\Scripts\python.exe -m unittest tests.test_build_report_assets
.\.venv\Scripts\python.exe -m unittest tests.test_impairment tests.test_impairment_proxy
```

### Verification Results

- Report regeneration succeeded and wrote refreshed report assets plus updated `report/final_report.md`.
- `tests.test_build_report_assets` passed (`Ran 5 tests ... OK`).
- `tests.test_impairment` and `tests.test_impairment_proxy` passed (`Ran 6 tests ... OK`).
- Cross-file consistency checks confirmed matching wording and metric references in:
  - `context.md`
  - `README_reproducibility.md`
  - `report/final_report.md`
  - `research_paper/Sections/evaluation.tex`

### Analysis

This is a narrative-and-traceability correction, not an algorithm change. No impairment logic, gateway behavior, replay control, or metric-computation code path was modified. Therefore, measured outcomes from the April evidence runs remain unchanged.

What changed is the interpretive boundary of the experiment. After this update, all key documents agree that the reported impairment evidence is primarily last-hop (gateway-to-dashboard) and proxy-instrumented. That alignment matters because the core result tables and figures use proxy downstream counters (`proxy_downstream_bytes_out`, `proxy_downstream_frames_out`). Without this wording alignment, readers could misread those counters as broker-link measurements and draw incorrect conclusions about where degradation and recovery behavior are being observed.

For the experiment narrative, the practical impact is stronger claim validity. The report can now cleanly state that frame-cadence stabilization, outage continuity behavior, and byte/frame tradeoffs are measured at the dashboard-facing hop where the impairment proxy operates. This improves reproducibility, clarifies causal interpretation of the outage figures, and removes a key cross-document ambiguity that previously weakened evidence mapping.

### Commit And Push Note

`PROJECT_CHECKLIST.md` and `PRD.md` are local-only in this session and must not be staged or pushed.
