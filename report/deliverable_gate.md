# Deliverable Completion Gate

## M1-M3 System Path

- Replay simulator and preprocessors: [simulator/replay_mqtt.py](../simulator/replay_mqtt.py), [simulator/preprocess_intel_lab.py](../simulator/preprocess_intel_lab.py), [simulator/preprocess_aot.py](../simulator/preprocess_aot.py)
- Gateway and dashboard path: [gateway/server.py](../gateway/server.py), [ui/dashboard.html](../ui/dashboard.html)
- Impairment and experiment harnesses: [experiments/impairment_proxy.py](../experiments/impairment_proxy.py), [experiments/run_sweep.py](../experiments/run_sweep.py), [experiments/run_demo.py](../experiments/run_demo.py)

## M4 Evidence Path

- Intel primary sweep run id: `final-intel-primary-20260403` at `experiments\logs\final-intel-primary-20260403`
- AoT validation run id: `final-aot-validation-20260403` at `experiments\logs\final-aot-validation-20260403`
- Demo capture run id: `final-demo-20260403` at `experiments\logs\final-demo-20260403\demo`
- Intel V2 batch-window sweep run id: `intel-v2-batch-window-20260403` at `experiments\logs\intel-v2-batch-window-20260403`
- Final evidence manifest: [report/assets/evidence_manifest.json](assets/evidence_manifest.json)
- Final summary tables: [report/assets/tables/intel_primary_run_summary.csv](assets/tables/intel_primary_run_summary.csv), [report/assets/tables/intel_bandwidth_vs_v0.csv](assets/tables/intel_bandwidth_vs_v0.csv), [report/assets/tables/intel_bandwidth_vs_v0.md](assets/tables/intel_bandwidth_vs_v0.md), [report/assets/tables/intel_v2_batch_window_tradeoff.csv](assets/tables/intel_v2_batch_window_tradeoff.csv), [report/assets/tables/intel_v2_batch_window_tradeoff.md](assets/tables/intel_v2_batch_window_tradeoff.md), [report/assets/figures/intel_v2_batch_window_tradeoff.png](assets/figures/intel_v2_batch_window_tradeoff.png), [report/assets/tables/aot_validation_summary.csv](assets/tables/aot_validation_summary.csv), [report/assets/tables/intel_key_claims.md](assets/tables/intel_key_claims.md)
- Final figures: [report/assets/figures](assets/figures)

## M5 Deliverables

- Final runner: [experiments/run_final_deliverables.py](../experiments/run_final_deliverables.py)
- Report asset builder: [experiments/build_report_assets.py](../experiments/build_report_assets.py)
- Reproducibility instructions: [report/reproducibility.md](reproducibility.md)
- Related-work notes: [report/related_work_notes.md](related_work_notes.md)
- Final report draft: [report/final_report.md](final_report.md)
- Bibliography: [report/references.bib](references.bib)

## Test Coverage

- Core analysis coverage: [tests/test_analysis.py](../tests/test_analysis.py)
- Demo harness and capture coverage: [tests/test_run_demo.py](../tests/test_run_demo.py), [tests/test_playwright_capture.py](../tests/test_playwright_capture.py)
- Final deliverables coverage: [tests/test_build_report_assets.py](../tests/test_build_report_assets.py), [tests/test_run_final_deliverables.py](../tests/test_run_final_deliverables.py)

## Generated From

- Report assets directory: `report\assets`
- Local full-run manifests remain under `experiments/logs/final-deliverables-*/manifest.json`
- `PRD.md` and `PROJECT_CHECKLIST.md` remain local-only planning artifacts and are not part of the pushed deliverable set.
