# Metric Definitions

This document is the canonical reference for the Phase 4 metric vocabulary used by Agrasandhani. The implementation source of truth is [`experiments/analyze_run.py`](../experiments/analyze_run.py). Existing field names remain unchanged for compatibility, but every metric is labeled by the stage where it is observed.

## Stage labels

- `gateway`: smart-gateway ingest or forwarder state observed before the impairment proxy.
- `proxy`: gateway-to-dashboard last-hop traffic observed by `proxy_frame_log.csv`.
- `dashboard`: rendered browser-side state observed by `dashboard_measurements.csv` and `dashboard_summary.json`.

## Latency and freshness age

### `age_ms_at_display` (`dashboard`)

- Formula: `ts_displayed - ts_sent`
- Units: milliseconds
- Source log: `dashboard_measurements.csv`
- Meaning: age of the update when it was rendered on the dashboard

### `latency_mean_ms`, `latency_p50_ms`, `latency_p95_ms`, `latency_p99_ms` (`dashboard`)

- Formula: mean and percentiles over all `age_ms_at_display` values in `dashboard_measurements.csv`
- Units: milliseconds
- Source log: `dashboard_measurements.csv`
- Meaning: dashboard-visible end-to-end latency summaries

### `freshness_stddev_ms` (`dashboard`)

- Formula: population standard deviation of `age_ms_at_display`
- Units: milliseconds
- Source log: `dashboard_measurements.csv`
- Meaning: spread of rendered age values; this is a freshness-dispersion metric, not the primary jitter metric

## Volume and cadence

All proxy volume and cadence metrics are derived from proxy rows where `event == sent`. Dropped rows do not count toward downstream bytes, downstream frames, per-second bandwidth, or per-second frame rate.

### `proxy_downstream_frames_out` (`proxy`)

- Formula: count of `proxy_frame_log.csv` rows with `event == sent`
- Units: frames
- Source log: `proxy_frame_log.csv`
- Meaning: total number of frames emitted toward the dashboard

### `proxy_downstream_bytes_out` (`proxy`)

- Formula: sum of `payload_bytes` over `proxy_frame_log.csv` rows with `event == sent`
- Units: bytes
- Source log: `proxy_frame_log.csv`
- Meaning: total downstream payload volume observed at the impairment proxy

### `bandwidth_bytes_per_s` / `max_bandwidth_bytes_per_s` (`proxy`)

- Formula: for each second bucket `floor(downstream_sent_ms / 1000)`, sum `payload_bytes` across proxy `sent` rows; `max_bandwidth_bytes_per_s` is the maximum bucket value
- Units: bytes per second
- Source logs: `proxy_frame_log.csv`, `timeseries.csv`
- Meaning: per-second downstream payload rate and its peak value

### `frame_rate_per_s` / `max_frame_rate_per_s` (`proxy`)

- Formula: for each second bucket `floor(downstream_sent_ms / 1000)`, count proxy `sent` rows; `max_frame_rate_per_s` is the maximum bucket value
- Units: frames per second
- Source logs: `proxy_frame_log.csv`, `timeseries.csv`
- Meaning: per-second downstream frame cadence and its peak value

### `update_rate_per_s` / `max_update_rate_per_s` (`dashboard`)

- Formula: for each second bucket `floor(ts_displayed / 1000)`, count rows in `dashboard_measurements.csv`; `max_update_rate_per_s` is the maximum bucket value
- Units: rendered updates per second
- Source logs: `dashboard_measurements.csv`, `timeseries.csv`
- Meaning: dashboard-side render/update cadence, separate from proxy frame cadence

## Stage-specific counts

### `gateway_mqtt_in_msgs` (`gateway`)

- Formula: `mqtt_in_msgs` from `gateway_metrics.json`
- Units: messages
- Source log: `gateway_metrics.json`
- Meaning: total MQTT messages ingested by the gateway

### `gateway_update_count` (`gateway`)

- Formula: row count of `gateway_forward_log.csv`
- Units: forwarded updates
- Source log: `gateway_forward_log.csv`
- Meaning: update rows written by the gateway forwarder log

### `proxy_sent_frame_count` (`proxy`)

- Formula: count of proxy `sent` rows
- Units: frames
- Source log: `proxy_frame_log.csv`
- Meaning: compatibility alias for the number of downstream frames actually sent

### `browser_event_count` (`dashboard`)

- Formula: row count of `dashboard_measurements.csv`
- Units: rendered update rows
- Source log: `dashboard_measurements.csv`
- Meaning: number of rendered dashboard update records captured during the run

### `dashboard_message_count`, `dashboard_frame_count`, `dashboard_stale_count` (`dashboard`)

- Formula: `messageCount`, `frameCount`, and `staleCount` from `dashboard_summary.json`
- Units: counts
- Source log: `dashboard_summary.json`
- Meaning:
  - `dashboard_message_count`: total rendered message/update count reported by the dashboard capture
  - `dashboard_frame_count`: total dashboard frame count reported by the dashboard capture
  - `dashboard_stale_count`: number of stale rows in the dashboard end-state summary

## Loss, missing updates, and TTL-linked stale behavior

### `missing_update_count` (`gateway` -> `dashboard`)

- Formula: count of gateway update keys present in `gateway_forward_log.csv` but absent from `dashboard_measurements.csv`
- Units: updates
- Source logs: `gateway_forward_log.csv`, `dashboard_measurements.csv`
- Matching key:
  - exact mode: `(sensor_id, metric_type, msg_id, ts_sent)`
  - legacy mode: `(sensor_id, msg_id, ts_sent)`
- Meaning: updates the gateway logged but the dashboard capture did not render

### `missing_updates_outage_drop_count` (`proxy`)

- Formula: among missing updates whose gateway frame aligns exactly with ordered proxy events, count proxy events where `event == dropped` and `outage == true`
- Units: updates
- Source logs: `gateway_forward_log.csv`, `proxy_frame_log.csv`, `dashboard_measurements.csv`
- Meaning: missing updates attributable to outage-window downstream drops when exact frame alignment is available

### `missing_updates_non_outage_drop_count` (`proxy`)

- Formula: same alignment rule as above, but count proxy events where `event == dropped` and `outage == false`
- Units: updates
- Source logs: `gateway_forward_log.csv`, `proxy_frame_log.csv`, `dashboard_measurements.csv`
- Meaning: missing updates attributable to non-outage downstream drops when exact frame alignment is available

### `missing_updates_delivered_frame_count` (`proxy`)

- Formula: aligned missing updates whose proxy event is `sent`
- Units: updates
- Source logs: `gateway_forward_log.csv`, `proxy_frame_log.csv`, `dashboard_measurements.csv`
- Meaning: missing updates whose enclosing frame was sent downstream, indicating loss or omission after proxy send

### `missing_updates_unclassified_count` (`gateway` -> `proxy` -> `dashboard`)

- Formula: `missing_update_count` minus the aligned outage-drop, non-outage-drop, and delivered-frame classifications
- Units: updates
- Source logs: `gateway_forward_log.csv`, `proxy_frame_log.csv`, `dashboard_measurements.csv`
- Meaning: missing updates that cannot be attributed because frame alignment is unavailable or incomplete

### `stale_at_display`, `freshness_ttl_ms`, `stale_fraction` (`dashboard`, TTL from `gateway`)

- `freshness_ttl_ms`
  - Formula: `freshness_ttl_ms` from `gateway_metrics.json`
  - Units: milliseconds
  - Source log: `gateway_metrics.json`
  - Meaning: TTL threshold used by the gateway/dashboard freshness semantics during the run
- `stale_at_display`
  - Formula: boolean written per rendered row when the displayed age exceeds the run TTL
  - Units: boolean
  - Source log: `dashboard_measurements.csv`
  - Meaning: whether a rendered row is stale at the time of display
- `stale_fraction`
  - Formula: `count(stale_at_display == true) / count(dashboard_measurements rows)`
  - Units: fraction in `[0, 1]`
  - Source log: `dashboard_measurements.csv`
  - Meaning: fraction of rendered updates that were stale at render time

## Jitter and stability

The primary frame-stability metrics come from proxy `sent` events, not dashboard event rows, because the dashboard export is update-driven rather than a clean frame clock.

### Scenario phase mapping (`proxy` stability interpretation)

- `clean`
  - Phase treatment: steady-state only
  - Interpretation rule: treat the full run as the baseline cadence window with no impairment sub-phases
- `bandwidth_200kbps`, `loss_2pct`, `delay_50ms_jitter20ms`
  - Phase treatment: full-run impairment window
  - Interpretation rule: these scenarios use a single normalized impairment phase across the whole run rather than separate pre/post slices
- `outage_5s`
  - Phase treatment: use the scenario-defined phases from `experiments/scenarios/outage_5s.json`
  - Ordered phases: `steady-before-outage`, `outage`, `recovery`
- General rule
  - When a scenario JSON defines multiple phases, phase-aware stability analysis uses those scenario-defined windows directly
  - When a scenario has only one phase, phase-aware stability analysis uses a normalized whole-run label (`steady-state` for `clean`, `impairment-window` for impaired single-phase scenarios)

### `proxy_inter_frame_gap_*` (`proxy`)

- Base signal: `inter_frame_gap_ms = diff(sorted(downstream_sent_ms))` over proxy `sent` rows
- Units: milliseconds
- Source log: `proxy_frame_log.csv`
- Metrics:
  - `proxy_inter_frame_gap_sample_count`: number of gap samples
  - `proxy_inter_frame_gap_mean_ms`: mean inter-frame gap
  - `proxy_inter_frame_gap_p50_ms`: median inter-frame gap
  - `proxy_inter_frame_gap_p95_ms`: p95 inter-frame gap
  - `proxy_inter_frame_gap_p99_ms`: p99 inter-frame gap
  - `proxy_inter_frame_gap_stddev_ms`: population standard deviation of inter-frame gaps
- Meaning: primary jitter/stability measurements for downstream frame pacing

### `proxy_frame_rate_stddev_per_s` (`proxy`)

- Formula: population standard deviation of per-second `frame_rate_per_s` buckets
- Units: frames per second
- Source logs: `proxy_frame_log.csv`, `timeseries.csv`
- Meaning: supporting frame-rate variability metric across the run

### `effective_batch_window_ms` (`gateway`)

- Formula: `effective_batch_window_ms` from `gateway_metrics.json`
- Units: milliseconds
- Source log: `gateway_metrics.json`
- Meaning: supporting gateway-side pacing signal; useful context for interpreting proxy jitter but not a substitute for observed inter-frame gaps
