# Research Analysis

## 1. Executive Summary

The repo contains a real, implemented end-to-end system for dataset replay into MQTT, gateway processing, and WebSocket dashboard delivery. The core path is present in `simulator/replay_publisher.py`, `gateway/mqtt_ingest.py`, `gateway/forwarder.py`, `gateway/app.py`, and `ui/index.html`, and the core gateway/app behavior is directly exercised by `tests/test_forwarder.py` and `tests/test_app.py`. Local evidence also exists for a primary Intel sweep, a smaller AoT validation sweep, a captured demo, and several M6 ablation sweeps under `experiments/logs/`.

The project is not yet a fully defensible research deliverable. The biggest gaps are methodological and narrative, not implementation. The current evidence matrix is effectively single-run-per-condition, while `research_paper/Sections/evaluation.tex` still promises multiple trials. The tracked markdown report/assets are materially closer to final than the LaTeX paper package, but the paper package is still largely proposal-state (`research_paper/main.tex`, `research_paper/Sections/introduction.tex`, `research_paper/Sections/evaluation.tex`, `research_paper/Sections/actionplan.tex`). Several repo facts also drift across generated docs, manifests, and naming.

The remaining manual work is mostly human judgment: tighten the claim set to what the logs and tables actually support, rewrite the manuscript into completed-study language, explain weak/null results honestly, choose final figures/tables, and write the limitations/threats-to-validity discussion. An agent could help package assets or clean docs later, but it should not guess the final claims, interpretation, or narrative framing for you.

## 2. Evidence-Based Project Status

### Overall architecture
- Status: Complete
- Evidence: `simulator/replay_publisher.py`, `gateway/mqtt_ingest.py`, `gateway/forwarder.py`, `gateway/app.py`, `ui/index.html`, `ui/demo_compare.html`, `README.md`, `tests/test_forwarder.py`, `tests/test_app.py`
- What is present: The intended path `dataset replay -> MQTT broker -> smart gateway -> WebSocket dashboard` is implemented. `README.md` documents the same architecture, and the tests cover gateway forwarding modes, metrics, and runtime config endpoints.
- What is missing or weak: The architecture is implemented, but the final research narrative around that architecture is split between better-aligned markdown docs and stale proposal-oriented LaTeX sections.
- Confidence level: High

### MQTT ingest path
- Status: Complete
- Evidence: `gateway/mqtt_ingest.py`, `gateway/app.py`, `gateway/schemas.py`, `README.md`, `tests/test_app.py`, `tests/test_forwarder.py`
- What is present: MQTT subscription, internal queueing, schema-aligned message handling, and QoS configuration are present. The repo README and runtime config surface match this path.
- What is missing or weak: I did not find a separate dedicated ingest-only integration test against a live broker in the repo, but the implemented path is well supported by code and higher-level tests.
- Confidence level: High

### Smart gateway behavior
- Status: Partially Complete
- Evidence: `gateway/forwarder.py`, `gateway/app.py`, `tests/test_forwarder.py`, `tests/test_app.py`, `experiments/run_sweep.py`, `experiments/run_batch_window_sweep.py`, `experiments/run_v1_v2_isolation_sweep.py`, `experiments/run_adaptive_impairment_sweep.py`, `report/assets/tables/intel_v2_batch_window_tradeoff.csv`, `report/assets/tables/intel_v1_vs_v2_isolation.csv`, `report/assets/tables/intel_v2_vs_v3_adaptive_impairment.csv`
- What is present: The gateway variants `v0` through `v4` are implemented, with runtime metrics/config visibility and experiment support for batching, exact duplicate suppression, latest-per-sensor compaction, adaptive batching, and last-known-good behavior.
- What is missing or weak: The gateway is implemented, but the research story around which mechanism matters most is still incomplete. `report/assets/tables/intel_v1_vs_v2_isolation.csv` shows mostly small or mixed differences between `v1` and `v2`, and `report/assets/tables/intel_v2_vs_v3_adaptive_impairment.csv` shows little visible benefit from `v3` under the tested defaults. That weakens a strong ablation-attribution claim.
- Confidence level: High

### WebSocket/dashboard delivery path
- Status: Complete
- Evidence: `gateway/app.py`, `ui/index.html`, `ui/demo_compare.html`, `experiments/impairment_proxy.py`, `experiments/capture_dashboard.mjs`, `experiments/logs/final-demo-20260403/demo/`, `report/assets/figures/final_demo_compare.png`
- What is present: WebSocket delivery, dashboard rendering, measurement capture, and demo comparison support are implemented. The demo artifacts show end-to-end dashboard outputs were captured.
- What is missing or weak: The dashboard path is implemented, but the final writeup needs a clearer explanation of which dashboard-visible metrics are directly measured versus inferred.
- Confidence level: High

### Dataset/replay realism
- Status: Partially Complete
- Evidence: `simulator/preprocess_intel_lab.py`, `simulator/preprocess_aot.py`, `simulator/replay_publisher.py`, `simulator/replay_timing.py`, `README.md`, `experiments/logs/final-deliverables-20260403/manifest.json`, `experiments/logs/generated_inputs/`
- What is present: Real dataset preprocessors exist for Intel Lab and AoT. The final-deliverables manifest shows bounded real-data slices were actually generated and normalized (`intel_rows_written: 4320`, `intel_sensors_written: 54`, `aot_rows_written: 520`, `aot_sensors_written: 36`).
- What is missing or weak: The realism is bounded and intentionally small. The AoT validation matrix is only four runs (`v0`/`v4`, QoS `0`, `clean`/`outage_5s`), so it is validation support rather than a strong second dataset study. I did not find evidence of a broader workload sweep beyond the bounded local slices.
- Confidence level: Medium

### Impairment/emulation setup
- Status: Partially Complete
- Evidence: `experiments/impairment_proxy.py`, `experiments/impairment.py`, `experiments/scenarios/*.json`, `experiments/netem/README.md`, `README_reproducibility.md`, `report/reproducibility.md`, `context.md`
- What is present: Deterministic application-layer impairment injection is implemented and is the clear basis of the reported downstream measurements. The docs consistently say the reported evidence is primarily last-hop proxy based.
- What is missing or weak: `tc netem` is documented only as optional support. I did not find tracked evidence that final reported figures/tables depend on netem-based runs. If the final paper wants to claim Linux-level impairment evidence, that is currently unverified.
- Confidence level: Medium

### Logging/instrumentation
- Status: Partially Complete
- Evidence: `gateway/forwarder.py`, `experiments/analyze_run.py`, `experiments/logs/final-intel-primary-20260403/*/gateway_forward_log.csv`, `proxy_frame_log.csv`, `dashboard_measurements.csv`, `summary.json`, `timeseries.csv`, `report/assets/tables/intel_primary_run_summary.csv`
- What is present: The project logs gateway events, proxy frame events, dashboard measurements, run summaries, and timeseries outputs. `experiments/analyze_run.py` computes latency, stale fraction, freshness spread, missing updates, frame counts, byte counts, and rate summaries.
- What is missing or weak: There is no explicit implemented dashboard jitter metric in `experiments/analyze_run.py`, despite jitter appearing in `context.md`, `PRD.md`, and `research_paper/Sections/evaluation.tex`. Missing-update cause attribution is also weak: in `report/assets/tables/intel_primary_run_summary.csv`, `proxy_frame_alignment_mode` is `frame_order_exact` for only 2 runs and `unavailable` for 28.
- Confidence level: High

### Experiment automation
- Status: Partially Complete
- Evidence: `experiments/run_sweep.py`, `experiments/run_final_deliverables.py`, `experiments/run_demo.py`, `experiments/run_batch_window_sweep.py`, `experiments/run_v1_v2_isolation_sweep.py`, `experiments/run_adaptive_impairment_sweep.py`, `experiments/reproduce_all.sh`, `README_reproducibility.md`, `report/reproducibility.md`
- What is present: The repo has automation for the primary matrix, demo capture, M6 sweeps, and asset regeneration. The reproducibility docs name the expected entrypoints and outputs.
- What is missing or weak: The automation is not methodologically complete for a paper-quality experimental claim set. `experiments/run_sweep.py` executes one run per condition, and I did not find a multi-trial loop or trial aggregation path. That directly conflicts with the multiple-trials wording still present in `research_paper/Sections/evaluation.tex`.
- Confidence level: High

### Results collection
- Status: Partially Complete
- Evidence: `experiments/analyze_run.py`, `report/assets/evidence_manifest.json`, `report/assets/tables/*.csv`, `report/assets/figures/*.png`, `experiments/logs/final-intel-primary-20260403/`, `experiments/logs/final-aot-validation-20260403/`, `experiments/logs/final-demo-20260403/demo/`
- What is present: There is a real evidence package with tracked summary tables and figures plus local raw logs/runs behind them.
- What is missing or weak: The evidence is enough to support a prototype/results section, but not enough to support every framing claim equally well. The current results support strong frame reduction; they do not support a generic downstream byte reduction claim in the Intel primary runs (`report/assets/tables/intel_bandwidth_vs_v0.csv` shows higher downstream bytes for `v2` and `v4` than `v0` in all listed Intel scenarios).
- Confidence level: High

### Figures/plots/tables
- Status: Partially Complete
- Evidence: `report/assets/figures/*.png`, `report/assets/tables/*.csv`, `report/assets/tables/*.md`, `experiments/plot_sweep.py`, `experiments/build_report_assets.py`, `experiments/package_paper_assets.py`
- What is present: The repo already has tracked paper-style figures and tables, including the main outage frame-rate figure, QoS comparison, batch-window tradeoff, freshness table/plot, and demo figure. The paper-asset packaging path also exists in `experiments/package_paper_assets.py`.
- What is missing or weak: Some figures are descriptive but not especially strong for a final paper claim. The `v2` versus `v3` adaptive figure mostly visualizes a null result, which is acceptable if you discuss it honestly, but it is not a strong headline figure. The paper asset package also has provenance risk because `experiments/package_paper_assets.py` is currently untracked and `research_paper/figures/` and `research_paper/tables/` were not tracked in the current git state.
- Confidence level: High

### Research writeup alignment
- Status: Partially Complete
- Evidence: `report/final_report.md`, `context.md`, `report/reproducibility.md`, `research_paper/main.tex`, `research_paper/Sections/introduction.tex`, `research_paper/Sections/evaluation.tex`, `research_paper/Sections/actionplan.tex`
- What is present: `report/final_report.md` is relatively aligned with the completed system and the final sweep IDs. `context.md` also reflects the actual last-hop impairment framing more accurately than the older paper draft.
- What is missing or weak: The LaTeX paper is not in final-paper state. `research_paper/main.tex` is still titled as a proposal, `research_paper/Sections/introduction.tex` and `research_paper/Sections/evaluation.tex` still use future-tense proposal wording, and `research_paper/Sections/actionplan.tex` is still an action plan rather than a final paper section.
- Confidence level: High

### Related work support
- Status: Partially Complete
- Evidence: `report/related_work_notes.md`, `research_paper/Sections/related-work.tex`, `research_paper/references.bib`, `context.md`
- What is present: The repo includes concrete related-work positioning around MQTT QoS semantics, pub/sub system framing, Senselet-style inspiration, and dataset provenance.
- What is missing or weak: The related-work material exists, but it is still more note-like than fully integrated into a final research argument. The final paper still needs a human-written positioning section that ties those sources directly to the gateway problem and the chosen evaluation claims.
- Confidence level: Medium

### Reproducibility/readability of repo
- Status: Partially Complete
- Evidence: `README.md`, `README_reproducibility.md`, `report/reproducibility.md`, `report/assets/evidence_manifest.json`, `experiments/logs/final-deliverables-20260403/manifest.json`, `report/deliverable_gate.md`, `experiments/build_report_assets.py`, git status observed on 2026-04-07
- What is present: The root README is strong, the reproducibility docs are concrete, the evidence manifest is tracked, and the local run structure is understandable. On 2026-04-07, `python -m unittest discover -s tests -v` passed all 78 tests, and `node .\experiments\capture_dashboard.mjs --check-only` confirmed Playwright/Chromium availability.
- What is missing or weak: There is drift and provenance noise. `report/deliverable_gate.md` references stale/nonexistent files (`simulator/replay_mqtt.py`, `gateway/server.py`, `ui/dashboard.html`), and those stale references are generated by `experiments/build_report_assets.py` rather than being a one-off typo. Naming also drifts between `Agrasandhani` and `Agrasandhini` in `PRD.md` and `q&a.md`. The final-deliverables manifest contains an older, smaller nested `report_assets_manifest` than the current tracked `report/assets/evidence_manifest.json`, so provenance is split across at least two states.
- Confidence level: High

## 3. What Is Actually Finished

Only items below are clearly supported by code, tests, logs, or tracked artifacts.

- The end-to-end prototype path exists: dataset replay to MQTT to gateway to WebSocket dashboard (`simulator/replay_publisher.py`, `gateway/mqtt_ingest.py`, `gateway/forwarder.py`, `gateway/app.py`, `ui/index.html`).
- Gateway variants `v0` through `v4` are implemented, with runtime config and metrics surfaces (`gateway/forwarder.py`, `gateway/app.py`, `tests/test_forwarder.py`, `tests/test_app.py`).
- Replay/data preprocessing exists for Intel Lab and AoT (`simulator/preprocess_intel_lab.py`, `simulator/preprocess_aot.py`), and the final-deliverables manifest shows bounded real-data slices were actually produced (`experiments/logs/final-deliverables-20260403/manifest.json`).
- Primary experiment runners and analyzers exist and were used to generate real outputs (`experiments/run_sweep.py`, `experiments/run_final_deliverables.py`, `experiments/analyze_run.py`, `experiments/build_report_assets.py`, `experiments/logs/final-intel-primary-20260403/`, `experiments/logs/final-aot-validation-20260403/`, `experiments/logs/final-demo-20260403/demo/`).
- Tracked report evidence assets exist, including tables, figures, and claim mapping (`report/assets/evidence_manifest.json`, `report/assets/tables/*.csv`, `report/assets/figures/*.png`, `report/assets/CLAIM_TO_EVIDENCE_MAP.md`).
- The unit test suite currently passes locally. On 2026-04-07, `python -m unittest discover -s tests -v` completed with 78 passing tests.

## 4. What Is Partially Done

- Cross-dataset validation exists but is narrow. Intel is the primary evidence source, while AoT is a small secondary validation matrix (`experiments/logs/final-aot-validation-20260403/`, `report/assets/tables/aot_validation_summary.csv`).
- Impairment methodology exists and is usable, but the evidence is mainly last-hop proxy based. Optional host-level `tc netem` is documented, not clearly evidenced in final tracked outputs (`experiments/netem/README.md`, `README_reproducibility.md`, `report/reproducibility.md`).
- The ablation story exists, but attribution is weak. The repo supports `v1`/`v2`/`v3` sweeps, yet the resulting tables show small/mixed `v1` vs `v2` differences and mostly null `v2` vs `v3` behavior (`report/assets/tables/intel_v1_vs_v2_isolation.csv`, `report/assets/tables/intel_v2_vs_v3_adaptive_impairment.csv`).
- Jitter/stability framing exists in docs, but explicit jitter measurement does not appear in the analysis code (`context.md`, `PRD.md`, `research_paper/Sections/evaluation.tex` versus `experiments/analyze_run.py`).
- The final paper/manuscript state is incomplete. The markdown report is closer to final, but the LaTeX paper package still reads like a proposal and action plan (`report/final_report.md` versus `research_paper/main.tex`, `research_paper/Sections/actionplan.tex`).
- Reproducibility/provenance is partly documented but not fully clean. There are tracked manifests and docs, but also split manifest states, local-only outputs, untracked paper-packaging support, and stale generated doc references (`report/assets/evidence_manifest.json`, `experiments/logs/final-deliverables-20260403/manifest.json`, `experiments/package_paper_assets.py`, `report/deliverable_gate.md`).

## 5. What Is Missing

- A final manuscript rewritten from proposal/future tense into completed-study language. This is missing from `research_paper/main.tex` and several paper sections.
- Replicated-trial evidence, or a written justification for why single-run-per-condition evidence is acceptable for this submission. The code/docs currently overpromise multiple trials.
- An explicit, claim-bounded treatment of jitter/stability. The framing repeatedly names update jitter, but the implemented analysis does not compute a dedicated jitter metric.
- A final limitations/threats-to-validity section tied to the real evidence, including dataset size limits, single-machine/local-testbed assumptions, and single-trial methodology.
- A frozen final deliverable package with clean provenance. Right now the project has tracked report assets, local-only logs, a paper-packaging path, and split manifests, but not one clearly frozen final package.
- A final built paper/report PDF in the workspace. A PDF search on 2026-04-07 only found `.pdf` files under `.venv\Lib\site-packages\matplotlib\...`; no project PDF was present.

## 6. What Is Unclear or Risky

- Unsupported bandwidth-byte reduction wording: `report/assets/tables/intel_bandwidth_vs_v0.csv` supports strong downstream frame reduction, but not downstream byte reduction in the Intel primary runs. Any generic statement that the gateway reduced downstream bandwidth without qualification is risky.
- V3 adaptive null result: `report/assets/tables/intel_v2_vs_v3_adaptive_impairment.csv` shows only small p95 latency differences (`-8.55 ms` and `+7.45 ms` in the two listed scenarios). If you want to present `v3` as a meaningful improvement, the current evidence is weak.
- Weak missing-update attribution coverage: `report/assets/tables/intel_primary_run_summary.csv` shows `proxy_frame_alignment_mode=frame_order_exact` for only 2 runs and `unavailable` for 28. That means most missing-update counts are not cleanly attributable to dropped versus delivered frames.
- Stale/generated doc drift: `report/deliverable_gate.md` contains stale paths, and the same stale paths are hard-coded inside `experiments/build_report_assets.py`. That means one of the polished deliverable docs is not fully trustworthy as generated.
- Naming/story drift: `PRD.md` and `q&a.md` use `Agrasandhini`, while the repo root and main docs use `Agrasandhani`. That is minor technically but weakens final polish and can confuse the submission story.
- AoT validation is small and secondary: the final-deliverables manifest shows only a small AoT slice and a four-run validation matrix. It helps as a portability check, but it is not strong enough to carry a major multi-dataset claim by itself.
- No direct evidence that `tc netem` contributed to final reported results: the docs mention it as optional support, but the tracked evidence package is clearly centered on the application-layer impairment proxy. If the final writeup mentions netem as part of the demonstrated evaluation, that should be labeled carefully or removed.
- Single-run methodology risk: `research_paper/Sections/evaluation.tex` still says each condition will be executed for multiple trials, but the automation and manifests support a single run per condition. That is one of the biggest submission risks.

## 7. Manual Work I Still Need To Do

This is the part an agent should not guess for you.

- Decide the final claim set and remove or narrow any claim that is stronger than the tracked evidence. In practice, that means treating frame reduction, latency tradeoff, and outage visibility as supported, while treating byte reduction and adaptive-gateway benefits much more carefully.
- Interpret the weak/null results yourself. You need to decide how to present the `v1` vs `v2` and especially `v2` vs `v3` outcomes: as negative results, scope-limited results, or evidence that batching dominates the observed effect.
- Choose the final figures and tables. The repo has enough assets, but you need to decide which ones belong in the main paper versus appendix and how each figure is captioned so it supports the right claim.
- Write the methodology justification. You need to explain why the bounded slices, local testbed, chosen scenarios, and last-hop impairment placement are sufficient for the project scope.
- Write the limitations and threats-to-validity section. This should explicitly cover single-run evidence, bounded datasets, local-only environment, last-hop emphasis, missing direct jitter measurement, and the weak attribution coverage in many runs.
- Rewrite the report/paper narrative into consistent past-tense completed-study language. The markdown report is closer, but the paper package still reads like a proposal.
- Integrate related work into the final story. The notes exist, but you need to decide the final positioning and how much weight to give MQTT QoS, pub/sub system comparisons, Senselet-style framing, and dataset provenance.
- Decide the canonical final deliverable format. You need to choose whether the submitted artifact is primarily the markdown report, the LaTeX paper, or a polished PDF generated from one of those paths.
- Clean up the final naming/story choices. You need to decide the canonical project spelling and ensure the final deliverable uses one name consistently.
- Decide whether you will defend the current single-trial evidence as-is or rerun/extend experiments. That is a research judgment call, not an agent choice.

## 8. Things That Could Be Delegated Later

- Asset/provenance cleanup, including reconciling `report/assets/evidence_manifest.json` with `experiments/logs/final-deliverables-20260403/manifest.json`.
- Paper-asset packaging, including copying tracked report assets into `research_paper/figures/` and `research_paper/tables/` in a cleaner, committed path.
- Stale-doc cross-checking, especially generated files like `report/deliverable_gate.md`.
- Additional automation for reruns or replicated trials, if you decide that is necessary.
- Explicit jitter metric computation and integration into the analysis pipeline, if you decide jitter needs to be a headline metric.
- Repo readability cleanup, including naming consistency and documentation deduplication.

## 9. Research Deliverable Gap Analysis

| Deliverable Piece | Status | Evidence / Reason |
| --- | --- | --- |
| System description | ready | The implemented system is clear in code and docs: `README.md`, `gateway/app.py`, `gateway/forwarder.py`, `simulator/replay_publisher.py`, `ui/index.html`. |
| Methodology | needs more evidence | The impairment path, datasets, and metrics are described, but the multiple-trials wording is unsupported and the final justification/limitations are not written cleanly (`research_paper/Sections/evaluation.tex`, `report/reproducibility.md`). |
| Experiment matrix | needs more evidence | The matrix exists in logs/manifests, but it is single-run-per-condition and AoT is only a small secondary validation (`experiments/logs/final-deliverables-20260403/manifest.json`, `report/assets/evidence_manifest.json`). |
| Metrics | needs more evidence | Latency, stale fraction, bytes, frames, and missing updates are computed, but explicit jitter is not, and missing-update attribution is often unavailable (`experiments/analyze_run.py`, `report/assets/tables/intel_primary_run_summary.csv`). |
| Results | needs more evidence | There are real tables and plots, but not every intended claim is equally supported. Strongest support is for frame reduction, latency tradeoff, and outage freshness/visibility tradeoff. |
| Discussion | manual writing needed | The repo has evidence, but the interpretation of weak/null results and what they mean for the gateway argument is not done for you. |
| Limitations / threats to validity | manual writing needed | The current docs do not present a final, honest limitations section tied to the exact evidence and methodology risks. |
| Related work integration | manual writing needed | Sources and notes exist, but the final positioning still needs to be written by a human (`report/related_work_notes.md`, `research_paper/Sections/related-work.tex`). |
| Conclusion | manual writing needed | The project has enough material for a conclusion, but it is not yet written in final completed-study form. |

## 10. Priority-Ordered Next Steps

### P0

- Rewrite the final manuscript/report into completed-study language and stop relying on proposal-state LaTeX sections.
- Scope the claims to what the evidence really supports, especially around bandwidth bytes, adaptive behavior, and stability/jitter.
- Write the methodology clarification and the limitations/threats-to-validity section.
- Choose the final main figures/tables and align each one to one claim.
- Resolve the single-trial story: either justify it explicitly in the writeup or decide to rerun with replication before claiming stronger rigor.

### P1

- Clean up provenance so there is one canonical story for where the final evidence comes from.
- Normalize naming and project-story drift across `Agrasandhani` versus `Agrasandhini`.
- Package the paper assets in a clean, committed form if the LaTeX paper is your final deliverable.
- Strengthen the related-work integration so it reads like a final paper section, not notes.

### P2

- Polish repo readability and remove stale generated references.
- If time allows, rerun selected conditions or extend sweeps where the current evidence is weakest.
- Produce a final PDF or otherwise frozen submission artifact once the narrative is stable.

## 11. Final Bottom Line

- What is left? The code and core experiments are mostly there; what remains is turning the existing system and evidence into a defensible research submission. The biggest missing pieces are manuscript rewrite, claim discipline, methodology justification, limitations, and deliverable/provenance cleanup.
- What do I have to do manually? You need to decide the final claim set, interpret the weak and null results, choose figures/tables, write the methodology/limitations/discussion/conclusion, integrate related work, and choose the canonical final submission format.
- What is the minimum remaining path to a defensible final submission? Keep the claim set narrow and evidence-aligned, present the project as a strong local systems prototype with bounded experimental evidence, explicitly acknowledge the single-trial and measurement limitations, use the tracked markdown report/assets as the primary evidence base, and rewrite the paper/report so the narrative matches what the repo actually proves.
