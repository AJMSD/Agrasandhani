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
