from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any


def _load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * pct
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return float(ordered[lower])
    weight = index - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def _round_metric(value: float) -> float:
    return round(value, 3)


def _build_message_key(row: dict[str, str], *, include_metric_type: bool) -> tuple[str, ...]:
    if include_metric_type:
        return (row["sensor_id"], row.get("metric_type", ""), row["msg_id"], row["ts_sent"])
    return (row["sensor_id"], row["msg_id"], row["ts_sent"])


def _ordered_gateway_frames(
    gateway_rows: list[dict[str, str]],
    *,
    include_metric_type: bool,
) -> tuple[list[str], dict[tuple[str, ...], str]] | None:
    if not gateway_rows:
        return [], {}

    frame_ids: list[str] = []
    update_to_frame: dict[tuple[str, ...], str] = {}
    seen_frames: set[str] = set()
    for row in gateway_rows:
        frame_id = row.get("frame_id", "")
        if not frame_id:
            return None
        if frame_id not in seen_frames:
            seen_frames.add(frame_id)
            frame_ids.append(frame_id)
        update_to_frame[_build_message_key(row, include_metric_type=include_metric_type)] = frame_id
    return frame_ids, update_to_frame


def _ordered_proxy_events(proxy_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    ordered_events: list[tuple[int, int, dict[str, object]]] = []
    for index, row in enumerate(proxy_rows):
        if row.get("event") not in {"sent", "dropped"}:
            continue
        upstream_received_ms = row.get("upstream_received_ms", "")
        if not upstream_received_ms:
            return []
        ordered_events.append(
            (
                int(upstream_received_ms),
                index,
                {
                    "event": row["event"],
                    "outage": row.get("outage", "").lower() == "true",
                    "phase_name": row.get("phase_name", ""),
                },
            )
        )
    ordered_events.sort(key=lambda item: (item[0], item[1]))
    return [event for _, _, event in ordered_events]


def _proxy_sent_rows(proxy_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in proxy_rows if row.get("event") == "sent" and row.get("downstream_sent_ms", "")]


def _proxy_inter_frame_gap_metrics(proxy_sent_rows: list[dict[str, str]]) -> dict[str, float | int]:
    sent_times = sorted(int(row["downstream_sent_ms"]) for row in proxy_sent_rows)
    inter_frame_gaps = [float(current - previous) for previous, current in zip(sent_times, sent_times[1:], strict=False)]
    return {
        "proxy_inter_frame_gap_sample_count": len(inter_frame_gaps),
        "proxy_inter_frame_gap_mean_ms": _round_metric(fmean(inter_frame_gaps)) if inter_frame_gaps else 0.0,
        "proxy_inter_frame_gap_p50_ms": _round_metric(_percentile(inter_frame_gaps, 0.5)),
        "proxy_inter_frame_gap_p95_ms": _round_metric(_percentile(inter_frame_gaps, 0.95)),
        "proxy_inter_frame_gap_p99_ms": _round_metric(_percentile(inter_frame_gaps, 0.99)),
        "proxy_inter_frame_gap_stddev_ms": _round_metric(pstdev(inter_frame_gaps)) if len(inter_frame_gaps) > 1 else 0.0,
    }


def collect_proxy_inter_frame_gaps(run_dir: Path) -> list[float]:
    proxy_rows = _load_csv(run_dir / "proxy_frame_log.csv")
    sent_times = sorted(int(row["downstream_sent_ms"]) for row in _proxy_sent_rows(proxy_rows))
    return [float(current - previous) for previous, current in zip(sent_times, sent_times[1:], strict=False)]


def _load_run_inputs(run_dir: Path) -> dict[str, Any]:
    dashboard_summary_payload = _load_json(run_dir / "dashboard_summary.json")
    dashboard_summary = dashboard_summary_payload.get("summary", {}) if isinstance(dashboard_summary_payload, dict) else {}
    return {
        "gateway_rows": _load_csv(run_dir / "gateway_forward_log.csv"),
        "proxy_rows": _load_csv(run_dir / "proxy_frame_log.csv"),
        "browser_rows": _load_csv(run_dir / "dashboard_measurements.csv"),
        "manifest": _load_json(run_dir / "manifest.json"),
        "dashboard_summary": dashboard_summary,
        "gateway_metrics": _load_json(run_dir / "gateway_metrics.json"),
        "proxy_metrics": _load_json(run_dir / "proxy_metrics.json"),
    }


def _timeseries_rows(
    bandwidth_by_second: Counter[int],
    frame_rate_by_second: Counter[int],
    update_rate_by_second: Counter[int],
) -> list[list[int]]:
    seconds = sorted(set(bandwidth_by_second) | set(frame_rate_by_second) | set(update_rate_by_second))
    return [
        [
            second,
            bandwidth_by_second.get(second, 0),
            frame_rate_by_second.get(second, 0),
            update_rate_by_second.get(second, 0),
        ]
        for second in seconds
    ]


def _collect_run_artifacts(
    *,
    run_dir: Path,
    late_threshold_ms: int,
    gateway_rows: list[dict[str, str]],
    proxy_rows: list[dict[str, str]],
    browser_rows: list[dict[str, str]],
    manifest: dict[str, Any],
    dashboard_summary: dict[str, Any],
    gateway_metrics: dict[str, Any],
    proxy_metrics: dict[str, Any],
) -> tuple[dict[str, Any], list[list[int]]]:
    latencies = [float(row["age_ms_at_display"]) for row in browser_rows]
    stale_flags = [row["stale_at_display"].lower() == "true" for row in browser_rows]

    if gateway_rows and "metric_type" in gateway_rows[0]:
        matching_mode = "exact_sensor_metric_msg_ts"
        missing_update_count_exact = True
        gateway_keys = {_build_message_key(row, include_metric_type=True) for row in gateway_rows}
        browser_keys = {_build_message_key(row, include_metric_type=True) for row in browser_rows}
    else:
        matching_mode = "legacy_sensor_msg_ts_approximate"
        missing_update_count_exact = False
        gateway_keys = {_build_message_key(row, include_metric_type=False) for row in gateway_rows}
        browser_keys = {_build_message_key(row, include_metric_type=False) for row in browser_rows}
    missing_updates = sorted(gateway_keys - browser_keys)

    missing_by_sensor: dict[str, int] = defaultdict(int)
    for missing in missing_updates:
        missing_by_sensor[missing[0]] += 1

    proxy_frame_alignment_mode = "unavailable"
    proxy_frame_alignment_note: str | None = None
    missing_updates_outage_drop_count = 0
    missing_updates_non_outage_drop_count = 0
    missing_updates_delivered_frame_count = 0
    missing_updates_unclassified_count = len(missing_updates)

    gateway_frame_info = _ordered_gateway_frames(
        gateway_rows,
        include_metric_type=missing_update_count_exact,
    )
    proxy_events = _ordered_proxy_events(proxy_rows)
    if gateway_frame_info is not None:
        gateway_frame_ids, update_to_frame = gateway_frame_info
        if len(gateway_frame_ids) == len(proxy_events):
            proxy_frame_alignment_mode = "frame_order_exact"
            missing_updates_unclassified_count = 0
            frame_to_proxy_event = {
                frame_id: proxy_event for frame_id, proxy_event in zip(gateway_frame_ids, proxy_events, strict=True)
            }
            for missing_update in missing_updates:
                frame_id = update_to_frame.get(missing_update)
                if frame_id is None:
                    missing_updates_unclassified_count += 1
                    continue
                proxy_event = frame_to_proxy_event.get(frame_id)
                if proxy_event is None:
                    missing_updates_unclassified_count += 1
                elif proxy_event["event"] == "dropped":
                    if proxy_event["outage"]:
                        missing_updates_outage_drop_count += 1
                    else:
                        missing_updates_non_outage_drop_count += 1
                elif proxy_event["event"] == "sent":
                    missing_updates_delivered_frame_count += 1
                else:
                    missing_updates_unclassified_count += 1
        else:
            proxy_frame_alignment_note = (
                "proxy/gateway frame counts do not match; missing-update cause attribution was skipped"
            )
    else:
        proxy_frame_alignment_note = (
            "gateway_forward_log.csv lacks frame_id; missing-update cause attribution was skipped"
        )

    sent_proxy_rows = _proxy_sent_rows(proxy_rows)
    bandwidth_by_second: Counter[int] = Counter()
    frame_rate_by_second: Counter[int] = Counter()
    for row in sent_proxy_rows:
        second = int(int(row["downstream_sent_ms"]) / 1000)
        payload_bytes = int(row["payload_bytes"])
        bandwidth_by_second[second] += payload_bytes
        frame_rate_by_second[second] += 1
    proxy_inter_frame_gap_metrics = _proxy_inter_frame_gap_metrics(sent_proxy_rows)
    proxy_downstream_frames_out = len(sent_proxy_rows)
    proxy_downstream_bytes_out = sum(int(row["payload_bytes"]) for row in sent_proxy_rows)
    proxy_frame_rate_stddev_per_s = _round_metric(pstdev(frame_rate_by_second.values())) if len(frame_rate_by_second) > 1 else 0.0

    update_rate_by_second: Counter[int] = Counter()
    for row in browser_rows:
        second = int(int(row["ts_displayed"]) / 1000)
        update_rate_by_second[second] += 1

    summary = {
        "run_id": manifest.get("run_id", run_dir.name),
        "variant": manifest.get("variant", ""),
        "scenario": manifest.get("scenario", ""),
        "mqtt_qos": manifest.get("mqtt_qos", ""),
        "matching_mode": matching_mode,
        "missing_update_count_exact": missing_update_count_exact,
        "proxy_frame_alignment_mode": proxy_frame_alignment_mode,
        "browser_event_count": len(browser_rows),
        "gateway_update_count": len(gateway_rows),
        "proxy_sent_frame_count": proxy_downstream_frames_out,
        "latency_mean_ms": _round_metric(fmean(latencies)) if latencies else 0.0,
        "latency_p50_ms": _round_metric(_percentile(latencies, 0.5)),
        "latency_p95_ms": _round_metric(_percentile(latencies, 0.95)),
        "latency_p99_ms": _round_metric(_percentile(latencies, 0.99)),
        "freshness_stddev_ms": _round_metric(pstdev(latencies)) if len(latencies) > 1 else 0.0,
        "stale_fraction": round((sum(stale_flags) / len(stale_flags)) if stale_flags else 0.0, 6),
        "late_threshold_ms": late_threshold_ms,
        "late_count": sum(1 for value in latencies if value > late_threshold_ms),
        "missing_update_count": len(missing_updates),
        "missing_updates_outage_drop_count": missing_updates_outage_drop_count,
        "missing_updates_non_outage_drop_count": missing_updates_non_outage_drop_count,
        "missing_updates_delivered_frame_count": missing_updates_delivered_frame_count,
        "missing_updates_unclassified_count": missing_updates_unclassified_count,
        "missing_sensor_count": len(missing_by_sensor),
        "gateway_mqtt_in_msgs": gateway_metrics.get("mqtt_in_msgs", 0),
        "duplicates_dropped": gateway_metrics.get("duplicates_dropped", 0),
        "compacted_dropped": gateway_metrics.get("compacted_dropped", 0),
        "value_dedup_dropped": gateway_metrics.get("value_dedup_dropped", 0),
        "freshness_ttl_ms": gateway_metrics.get("freshness_ttl_ms", 0),
        "effective_batch_window_ms": gateway_metrics.get("effective_batch_window_ms", 0),
        "adaptive_window_increase_events": gateway_metrics.get("adaptive_window_increase_events", 0),
        "adaptive_window_decrease_events": gateway_metrics.get("adaptive_window_decrease_events", 0),
        "last_adaptation_reason": gateway_metrics.get("last_adaptation_reason", ""),
        "stale_sensor_count": gateway_metrics.get("stale_sensor_count", 0),
        "proxy_dropped_frames": proxy_metrics.get("dropped_frames", 0),
        "proxy_downstream_frames_out": proxy_downstream_frames_out,
        "proxy_downstream_bytes_out": proxy_downstream_bytes_out,
        "max_bandwidth_bytes_per_s": max(bandwidth_by_second.values(), default=0),
        "max_frame_rate_per_s": max(frame_rate_by_second.values(), default=0),
        "proxy_frame_rate_stddev_per_s": proxy_frame_rate_stddev_per_s,
        "max_update_rate_per_s": max(update_rate_by_second.values(), default=0),
        "dashboard_stale_count": dashboard_summary.get("staleCount", 0),
        "dashboard_message_count": dashboard_summary.get("messageCount", 0),
        "dashboard_frame_count": dashboard_summary.get("frameCount", 0),
    }
    summary.update(proxy_inter_frame_gap_metrics)
    if not missing_update_count_exact:
        summary["matching_note"] = "gateway_forward_log.csv lacks metric_type; rerun with current schema for exact missing-update analysis"
    if proxy_frame_alignment_note is not None:
        summary["proxy_frame_alignment_note"] = proxy_frame_alignment_note

    return summary, _timeseries_rows(bandwidth_by_second, frame_rate_by_second, update_rate_by_second)


def collect_run_summary(run_dir: Path, *, late_threshold_ms: int = 1000) -> dict[str, Any]:
    run_inputs = _load_run_inputs(run_dir)
    summary, _ = _collect_run_artifacts(
        run_dir=run_dir,
        late_threshold_ms=late_threshold_ms,
        gateway_rows=run_inputs["gateway_rows"],
        proxy_rows=run_inputs["proxy_rows"],
        browser_rows=run_inputs["browser_rows"],
        manifest=run_inputs["manifest"],
        dashboard_summary=run_inputs["dashboard_summary"],
        gateway_metrics=run_inputs["gateway_metrics"],
        proxy_metrics=run_inputs["proxy_metrics"],
    )
    return summary


def analyze_run(run_dir: Path, *, late_threshold_ms: int = 1000) -> dict[str, Any]:
    run_inputs = _load_run_inputs(run_dir)
    summary, timeseries_rows = _collect_run_artifacts(
        run_dir=run_dir,
        late_threshold_ms=late_threshold_ms,
        gateway_rows=run_inputs["gateway_rows"],
        proxy_rows=run_inputs["proxy_rows"],
        browser_rows=run_inputs["browser_rows"],
        manifest=run_inputs["manifest"],
        dashboard_summary=run_inputs["dashboard_summary"],
        gateway_metrics=run_inputs["gateway_metrics"],
        proxy_metrics=run_inputs["proxy_metrics"],
    )

    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    with (run_dir / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary.keys()))
        writer.writeheader()
        writer.writerow(summary)

    with (run_dir / "timeseries.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["epoch_second", "bandwidth_bytes_per_s", "frame_rate_per_s", "update_rate_per_s"])
        writer.writerows(timeseries_rows)

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Derive M4 metrics from a single experiment run directory.")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--late-threshold-ms", type=int, default=1000)
    args = parser.parse_args()
    print(json.dumps(analyze_run(args.run_dir, late_threshold_ms=args.late_threshold_ms), indent=2))


if __name__ == "__main__":
    main()
