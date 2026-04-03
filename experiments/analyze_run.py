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


def analyze_run(run_dir: Path, *, late_threshold_ms: int = 1000) -> dict[str, Any]:
    gateway_rows = _load_csv(run_dir / "gateway_forward_log.csv")
    proxy_rows = _load_csv(run_dir / "proxy_frame_log.csv")
    browser_rows = _load_csv(run_dir / "dashboard_measurements.csv")
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8")) if (run_dir / "manifest.json").exists() else {}

    latencies = [float(row["age_ms_at_display"]) for row in browser_rows]
    stale_flags = [row["stale_at_display"].lower() == "true" for row in browser_rows]

    if gateway_rows and "metric_type" in gateway_rows[0]:
        gateway_keys = {(row["sensor_id"], row.get("metric_type", ""), row["msg_id"], row["ts_sent"]) for row in gateway_rows}
        browser_keys = {(row["sensor_id"], row.get("metric_type", ""), row["msg_id"], row["ts_sent"]) for row in browser_rows}
    else:
        gateway_keys = {(row["sensor_id"], row["msg_id"], row["ts_sent"]) for row in gateway_rows}
        browser_keys = {(row["sensor_id"], row["msg_id"], row["ts_sent"]) for row in browser_rows}
    missing_updates = sorted(gateway_keys - browser_keys)

    missing_by_sensor: dict[str, int] = defaultdict(int)
    for missing in missing_updates:
        missing_by_sensor[missing[0]] += 1

    bandwidth_by_second: Counter[int] = Counter()
    frame_rate_by_second: Counter[int] = Counter()
    for row in proxy_rows:
        if row["event"] != "sent" or not row["downstream_sent_ms"]:
            continue
        second = int(int(row["downstream_sent_ms"]) / 1000)
        payload_bytes = int(row["payload_bytes"])
        bandwidth_by_second[second] += payload_bytes
        frame_rate_by_second[second] += 1

    update_rate_by_second: Counter[int] = Counter()
    for row in browser_rows:
        second = int(int(row["ts_displayed"]) / 1000)
        update_rate_by_second[second] += 1

    gateway_metrics = {}
    proxy_metrics = {}
    if (run_dir / "gateway_metrics.json").exists():
        gateway_metrics = json.loads((run_dir / "gateway_metrics.json").read_text(encoding="utf-8"))
    if (run_dir / "proxy_metrics.json").exists():
        proxy_metrics = json.loads((run_dir / "proxy_metrics.json").read_text(encoding="utf-8"))

    summary = {
        "run_id": manifest.get("run_id", run_dir.name),
        "variant": manifest.get("variant", ""),
        "scenario": manifest.get("scenario", ""),
        "mqtt_qos": manifest.get("mqtt_qos", ""),
        "browser_event_count": len(browser_rows),
        "gateway_update_count": len(gateway_rows),
        "proxy_sent_frame_count": sum(1 for row in proxy_rows if row["event"] == "sent"),
        "latency_mean_ms": round(fmean(latencies), 3) if latencies else 0.0,
        "latency_p50_ms": round(_percentile(latencies, 0.5), 3),
        "latency_p95_ms": round(_percentile(latencies, 0.95), 3),
        "latency_p99_ms": round(_percentile(latencies, 0.99), 3),
        "freshness_stddev_ms": round(pstdev(latencies), 3) if len(latencies) > 1 else 0.0,
        "stale_fraction": round((sum(stale_flags) / len(stale_flags)) if stale_flags else 0.0, 6),
        "late_threshold_ms": late_threshold_ms,
        "late_count": sum(1 for value in latencies if value > late_threshold_ms),
        "missing_update_count": len(missing_updates),
        "missing_sensor_count": len(missing_by_sensor),
        "gateway_mqtt_in_msgs": gateway_metrics.get("mqtt_in_msgs", 0),
        "proxy_dropped_frames": proxy_metrics.get("dropped_frames", 0),
        "proxy_downstream_frames_out": proxy_metrics.get("downstream_frames_out", 0),
        "proxy_downstream_bytes_out": proxy_metrics.get("downstream_bytes_out", 0),
        "max_bandwidth_bytes_per_s": max(bandwidth_by_second.values(), default=0),
        "max_frame_rate_per_s": max(frame_rate_by_second.values(), default=0),
        "max_update_rate_per_s": max(update_rate_by_second.values(), default=0),
    }

    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    with (run_dir / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary.keys()))
        writer.writeheader()
        writer.writerow(summary)

    seconds = sorted(set(bandwidth_by_second) | set(frame_rate_by_second) | set(update_rate_by_second))
    with (run_dir / "timeseries.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["epoch_second", "bandwidth_bytes_per_s", "frame_rate_per_s", "update_rate_per_s"])
        for second in seconds:
            writer.writerow([
                second,
                bandwidth_by_second.get(second, 0),
                frame_rate_by_second.get(second, 0),
                update_rate_by_second.get(second, 0),
            ])

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Derive M4 metrics from a single experiment run directory.")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--late-threshold-ms", type=int, default=1000)
    args = parser.parse_args()
    print(json.dumps(analyze_run(args.run_dir, late_threshold_ms=args.late_threshold_ms), indent=2))


if __name__ == "__main__":
    main()
