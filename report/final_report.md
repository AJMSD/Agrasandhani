# Agrasandhani Final Report

## Abstract

Agrasandhani explores a local MQTT-to-WebSocket sensor pipeline that can either forward every message directly or apply batching, compaction, adaptive flushing, and last-known-good freshness semantics. The final evaluation uses a real Intel Berkeley Lab replay as the primary workload, a smaller AoT validation replay, and a captured live demo. Across the Intel clean qos0 run, the raw baseline reached a latency p95 of 131.8 ms while the adaptive V4 path reached 682.0 ms, reflecting the deliberate latency-for-stability tradeoff introduced by batching. The explicit Intel qos0 bandwidth comparison did not show a downstream payload-byte reduction versus V0; instead, the smart paths traded higher payload-byte totals for much lower frame counts. Under the Intel outage qos1 run, V4 reduced downstream frame count from 116 to 5 while keeping stale rows visible through the outage window, which made the live comparison materially easier to interpret.

## 1. Introduction

The project goal is to make bursty IoT replay traffic easier to visualize without losing the ability to trace timing and freshness behavior. MQTT remains a natural fit for lightweight sensing pipelines, but its QoS modes and duplicate semantics still require careful interpretation in downstream gateways [@mqtt311]. For broader pub/sub context, Kafka emphasizes log-oriented throughput and replay semantics rather than low-overhead device messaging [@kreps2011kafka], while later comparative work highlights how RabbitMQ and Kafka occupy different operating points in the reliability-throughput design space [@dobbelaere2017kafka]. For sensing-pipeline inspiration, SENSELET++ demonstrates the value of pairing sensing infrastructure with a reproducible visualization path [@tian2021senseletpp].

## 2. Workloads and Method

The primary evidence run is `final-intel-primary-20260403`. It uses a bounded slice of the Intel Berkeley Lab deployment data [@intelLabData] preprocessed into Agrasandhani's normalized replay schema, then runs `V0`, `V2`, and `V4` across `clean`, `bandwidth_200kbps`, `loss_2pct`, `delay_50ms_jitter20ms`, and `outage_5s` at MQTT QoS `0` and `1`. Each run uses a 30 second wall-clock replay, a 5x speedup, a 200-sensor target, and burst mode. The portability check is `final-aot-validation-20260403`, built from a bounded slice of the AoT weekly archive dataset [@aotCyberGIS] with a smaller validation matrix. The live demo evidence comes from `final-demo-20260403`.

## 3. Results

The clean qos0 run shows the expected tradeoff. V0 preserves the most immediate delivery path with a p95 display latency of 131.8 ms, whereas V4 increases p95 latency to 682.0 ms in exchange for frame consolidation. This is visible in the latency CDF and the message-rate plots in [report/assets/figures/intel_clean_qos0_latency_cdf.png](assets/figures/intel_clean_qos0_latency_cdf.png) and [report/assets/figures/intel_outage_qos1_message_rate_over_time.png](assets/figures/intel_outage_qos1_message_rate_over_time.png).

The explicit Intel qos0 bandwidth comparison answers the first paper question directly. Compared with V0, V2 increased downstream payload bytes by 8.1% under clean, 8.1% under bandwidth_200kbps, 9.8% under loss_2pct, 7.5% under outage_5s. V4 increased downstream payload bytes by 46.2% under clean, 46.2% under bandwidth_200kbps, 48.5% under loss_2pct, 66.3% under outage_5s. Peak per-second downstream payload rate also moved upward rather than downward: V2 increased by 28.6% under clean, 5.3% under bandwidth_200kbps, 7.8% under loss_2pct, 5.3% under outage_5s, while V4 increased by 39.6% under clean, 14.3% under bandwidth_200kbps, 17.0% under loss_2pct, 14.3% under outage_5s. In this evidence set, the smart paths reduce render cadence and frame count rather than downstream payload-byte volume. The paper-ready table for this claim is [report/assets/tables/intel_bandwidth_vs_v0.md](assets/tables/intel_bandwidth_vs_v0.md).

The outage qos1 run makes the UI tradeoff clearer. V0 emitted 116 downstream frames, while V4 emitted 5. At the same time, V4's aggregate envelopes pushed downstream bytes from 10605 in V0 to 15621 in V4. The result is not a blanket bandwidth win; it is a cadence and interpretability win. This is the right framing for the project, and it avoids overselling aggregate framing as a byte-minimization technique.

The broker-backed QoS1 runs did not trigger large duplicate counts in this local setup. In fact, the measured exact duplicate-drop counter remained at 0 across the Intel primary QoS1 matrix, so the QoS discussion in this report is necessarily cautious. The final claims here concern observed end-to-end behavior in this environment rather than a general statement that QoS1 duplicates are common in every deployment.

AoT provides a smaller portability check rather than the main performance claim set. On the clean qos0 validation run, V0 reached a p95 latency of 30.0 ms and emitted 439 frames, while V4 reached 277.0 ms and emitted 18 frames. That result is directionally consistent with the Intel evidence and shows that the smart path remains operational on a second public source.

The demo evidence captures the qualitative effect directly. The final captured baseline dashboard ended with frameCount=60, staleCount=48, and latestRowCount=48, while the smart dashboard ended with frameCount=4, staleCount=92, and latestRowCount=92. Both sides surfaced stale rows during the outage window, but the V4 side did so with far fewer rendered frames and a larger retained latest-row set in the captured end state. The screenshots in [report/assets/figures/final_demo_compare.png](assets/figures/final_demo_compare.png), [report/assets/figures/final_demo_baseline_dashboard.png](assets/figures/final_demo_baseline_dashboard.png), and [report/assets/figures/final_demo_smart_dashboard.png](assets/figures/final_demo_smart_dashboard.png) are the evidence for that claim.

## 4. Discussion

The final evidence supports a narrow conclusion. Agrasandhani's smart path is useful when the operator values stable rendering and last-known-good freshness cues more than minimum per-message latency. The data does not support a blanket claim that V4 minimizes downstream bytes, and the QoS1 experiments in this local broker configuration do not justify a strong empirical duplicate-rate claim beyond the measured counters. Those are acceptable limits for a six-page project report because the central contribution is the observable baseline-versus-smart tradeoff, not a universal broker benchmark.

## 5. Reproducibility and Deliverables

All committed report assets under `report/assets/` are regenerated from ignored local logs via `experiments/build_report_assets.py`, and the exact local run commands are captured in `experiments/logs/final-deliverables-*/manifest.json`. The reproducibility steps live in [report/reproducibility.md](reproducibility.md), the related-work notes live in [report/related_work_notes.md](related_work_notes.md), and the deliverable cross-check is in [report/deliverable_gate.md](deliverable_gate.md).

## References

The bibliography entries are stored in [report/references.bib](references.bib).
