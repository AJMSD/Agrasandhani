# Final Submission Freeze

- Generated at: `2026-04-10T03:48:46.966357+00:00`
- Freeze status: `passed`

## Frozen Submission Package

### Core Pipeline Files

- `simulator/preprocess_common.py`
- `simulator/preprocess_intel_lab.py`
- `simulator/preprocess_aot.py`
- `simulator/replay_publisher.py`
- `simulator/replay_timing.py`
- `gateway/app.py`
- `gateway/forwarder.py`
- `gateway/mqtt_ingest.py`
- `gateway/schemas.py`
- `ui/index.html`
- `ui/demo_compare.html`
- `experiments/analyze_run.py`
- `experiments/impairment_proxy.py`
- `experiments/run_sweep.py`
- `experiments/run_demo.py`
- `experiments/run_final_deliverables.py`
- `experiments/build_report_assets.py`
- `experiments/build_run_registry.py`
- `experiments/package_paper_assets.py`
- `experiments/sweep_aggregation.py`
- `experiments/run_replicated_phase6.py`
- `experiments/run_batch_window_sweep.py`
- `experiments/run_v1_v2_isolation_sweep.py`
- `experiments/run_adaptive_impairment_sweep.py`
- `experiments/run_v3_adaptive_parameter_sweep.py`
- `experiments/reproduce_all.sh`
- `experiments/freeze_final_submission.py`

### Documentation and Registries

- `README_reproducibility.md`
- `report/final_report.md`
- `report/reproducibility.md`
- `report/experiment_pipeline_audit.md`
- `report/metric_definitions.md`
- `report/deliverable_gate.md`
- `experiments/logs/run_registry.json`

### Report Assets and Provenance Files

- `report/assets/evidence_manifest.json`
- `report/assets/old_evidence_inventory.json`
- `report/assets/CLAIM_TO_EVIDENCE_MAP.md`
- `report/assets/final_submission_manifest.json`
- `report/assets/figures/intel_clean_qos0_latency_cdf.png`
- `report/assets/figures/intel_delay_qos0_inter_frame_gap_cdf.png`
- `report/assets/figures/intel_outage_qos1_bandwidth_over_time.png`
- `report/assets/figures/intel_outage_qos1_message_rate_over_time.png`
- `report/assets/figures/intel_outage_qos0_v0_vs_v4_age_over_time.png`
- `report/assets/figures/main_outage_frame_rate.png`
- `report/assets/figures/intel_qos_comparison.png`
- `report/assets/figures/final_demo_compare.png`
- `report/assets/figures/final_demo_baseline_dashboard.png`
- `report/assets/figures/final_demo_smart_dashboard.png`
- `report/assets/figures/intel_v2_batch_window_tradeoff.png`
- `report/assets/figures/intel_v1_vs_v2_isolation.png`
- `report/assets/figures/intel_v2_vs_v3_adaptive_impairment.png`
- `report/assets/tables/intel_primary_run_summary.csv`
- `report/assets/tables/intel_primary_run_summary.md`
- `report/assets/tables/intel_bandwidth_vs_v0.csv`
- `report/assets/tables/intel_bandwidth_vs_v0.md`
- `report/assets/tables/intel_qos_comparison.csv`
- `report/assets/tables/intel_qos_comparison.md`
- `report/assets/tables/intel_condensed_summary.csv`
- `report/assets/tables/intel_condensed_summary.md`
- `report/assets/tables/intel_main_summary_table.csv`
- `report/assets/tables/intel_main_summary_table.md`
- `report/assets/tables/intel_outage_qos0_v0_vs_v4_freshness.csv`
- `report/assets/tables/intel_outage_qos0_v0_vs_v4_freshness.md`
- `report/assets/tables/intel_jitter_summary.csv`
- `report/assets/tables/intel_jitter_summary.md`
- `report/assets/tables/aot_validation_summary.csv`
- `report/assets/tables/intel_key_claims.md`
- `report/assets/tables/intel_claim_guardrail_review.md`
- `report/assets/tables/intel_v2_batch_window_tradeoff.csv`
- `report/assets/tables/intel_v2_batch_window_tradeoff.md`
- `report/assets/tables/intel_v1_vs_v2_isolation.csv`
- `report/assets/tables/intel_v1_vs_v2_isolation.md`
- `report/assets/tables/intel_v2_vs_v3_adaptive_impairment.csv`
- `report/assets/tables/intel_v2_vs_v3_adaptive_impairment.md`
- `report/assets/tables/intel_v3_adaptive_parameter_sweep.csv`
- `report/assets/tables/intel_v3_adaptive_parameter_sweep.md`

### Paper Source Files

- `research_paper/main.tex`
- `research_paper/references.bib`
- `research_paper/Sections/actionplan.tex`
- `research_paper/Sections/approach.tex`
- `research_paper/Sections/evaluation.tex`
- `research_paper/Sections/introduction.tex`
- `research_paper/Sections/related-work.tex`
- `research_paper/Sections/TeamInfo.tex`
- `research_paper/Sections/approach-cs537.png`

### Packaged Paper Assets

- `research_paper/tables/paper_assets_manifest.json`
- `research_paper/tables/paper_asset_index.md`
- `research_paper/tables/intel_main_summary_table.tex`
- `research_paper/Sections/approach-cs537.png`
- `research_paper/figures/intel_clean_qos0_latency_cdf.png`
- `research_paper/figures/intel_outage_qos0_v0_vs_v4_age_over_time.png`
- `research_paper/figures/main_outage_frame_rate.png`
- `research_paper/tables/intel_main_summary_table.csv`
- `research_paper/figures/final_demo_compare.png`
- `research_paper/figures/intel_delay_qos0_inter_frame_gap_cdf.png`
- `research_paper/figures/intel_outage_qos1_bandwidth_over_time.png`
- `research_paper/figures/intel_outage_qos1_message_rate_over_time.png`
- `research_paper/figures/intel_qos_comparison.png`
- `research_paper/figures/intel_v1_vs_v2_isolation.png`
- `research_paper/figures/intel_v2_batch_window_tradeoff.png`
- `research_paper/figures/intel_v2_vs_v3_adaptive_impairment.png`
- `research_paper/tables/intel_bandwidth_vs_v0.csv`
- `research_paper/tables/intel_bandwidth_vs_v0.md`
- `research_paper/tables/intel_claim_guardrail_review.md`
- `research_paper/tables/intel_jitter_summary.csv`
- `research_paper/tables/intel_jitter_summary.md`
- `research_paper/tables/intel_outage_qos0_v0_vs_v4_freshness.csv`
- `research_paper/tables/intel_outage_qos0_v0_vs_v4_freshness.md`
- `research_paper/tables/intel_qos_comparison.csv`
- `research_paper/tables/intel_qos_comparison.md`
- `research_paper/tables/intel_v1_vs_v2_isolation.csv`
- `research_paper/tables/intel_v1_vs_v2_isolation.md`
- `research_paper/tables/intel_v2_batch_window_tradeoff.csv`
- `research_paper/tables/intel_v2_batch_window_tradeoff.md`
- `research_paper/tables/intel_v2_vs_v3_adaptive_impairment.csv`
- `research_paper/tables/intel_v2_vs_v3_adaptive_impairment.md`
- `research_paper/tables/intel_v3_adaptive_parameter_sweep.csv`
- `research_paper/tables/intel_v3_adaptive_parameter_sweep.md`

## Canonical Evidence Roots

- `experiments/logs/final-aot-validation-replicated-20260408-135251` (`validation`)
- `experiments/logs/final-demo-20260403` (`demo`)
- `experiments/logs/final-intel-primary-replicated-20260408-135251` (`primary-evidence`)
- `experiments/logs/intel-v1-v2-isolation-replicated-20260408-135251` (`ablation`)
- `experiments/logs/intel-v2-batch-window-replicated-20260408-135251` (`ablation`)
- `experiments/logs/intel-v2-v3-adaptive-replicated-20260408-135251` (`ablation`)
- `experiments/logs/intel-v3-adaptive-parameter-sweep-20260408-190517` (`ablation`)

## Validation Summary

- `unittest_suite`: `passed` (Ran 96 tests in 43.776s; OK)
- `dashboard_capture_preflight`: `passed` (Playwright and Chromium are available.)
- `tex_reference_paths`: `passed`
- `citation_keys`: `passed`
- `report_asset_inventory`: `passed`
- `paper_asset_inventory`: `passed`
- `document_provenance_anchors`: `passed`
- `latex_toolchain`: `warning`

## Environment Limitations

- LaTeX toolchain unavailable; source tree frozen as build-ready only.

## Explicit Exclusions

- `PRD.md`: Planning artifact; not part of the frozen submission package.
- `PROJECT_CHECKLIST.md`: Execution checklist; retained in the repo but excluded from the frozen submission package.
- `q&a.md`: Scratch planning notes; not part of the frozen submission package.
- `research-analysis.md`: Working analysis notes; not part of the frozen submission package.

## Draft Manual Sign-off

- Freeze validation passed; manual research-significance confirmation is still required before the project is declared fully frozen.
- Broad downstream-byte reduction remains unsupported; keep the fallback wording from report/assets/tables/intel_key_claims.md.
- Adaptive control remains a null-result/supporting claim, not a headline result.
- Keep the current main-paper asset slate recorded in research_paper/tables/paper_asset_index.md.
- No extra reruns are recommended before freeze because the bounded Section 7 hard stop is already locked.
