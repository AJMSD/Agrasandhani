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
