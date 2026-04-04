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
