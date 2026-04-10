from __future__ import annotations

import json
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any

SUMMARY_FILENAME = "summary.json"
CONDITION_AGGREGATES_FILENAME = "condition_aggregates.json"
AGGREGATED_METRICS = (
    "latency_mean_ms",
    "latency_p50_ms",
    "latency_p95_ms",
    "latency_p99_ms",
    "proxy_downstream_bytes_out",
    "proxy_downstream_frames_out",
    "max_bandwidth_bytes_per_s",
    "max_frame_rate_per_s",
    "max_update_rate_per_s",
    "stale_fraction",
    "freshness_stddev_ms",
    "effective_batch_window_ms",
    "adaptive_window_increase_events",
    "adaptive_window_decrease_events",
    "proxy_inter_frame_gap_mean_ms",
    "proxy_inter_frame_gap_p50_ms",
    "proxy_inter_frame_gap_p95_ms",
    "proxy_inter_frame_gap_p99_ms",
    "proxy_inter_frame_gap_stddev_ms",
    "proxy_frame_rate_stddev_per_s",
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _round_metric(value: float) -> float:
    return round(value, 6)


def _coerce_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def discover_summary_paths(sweep_dir: Path) -> list[Path]:
    return sorted(path for path in sweep_dir.rglob(SUMMARY_FILENAME) if path.parent != sweep_dir)


def _infer_relative_metadata(*, sweep_dir: Path, summary_path: Path) -> tuple[str, str | None]:
    relative_parent = summary_path.parent.relative_to(sweep_dir)
    if len(relative_parent.parts) >= 2 and relative_parent.parts[-1].startswith("trial-"):
        return relative_parent.parts[-2], relative_parent.parts[-1]
    return relative_parent.parts[-1], None


def _manifest_gateway_setting(
    manifest: dict[str, Any],
    env_name: str,
) -> int | str | None:
    gateway_env = manifest.get("effective_gateway_env")
    if not isinstance(gateway_env, dict):
        return None
    value = gateway_env.get(env_name)
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return text


def load_summary_rows(sweep_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for summary_path in discover_summary_paths(sweep_dir):
        payload = _load_json(summary_path)
        manifest_path = summary_path.parent / "manifest.json"
        manifest = _load_json(manifest_path) if manifest_path.exists() else {}
        condition_id, inferred_trial_id = _infer_relative_metadata(sweep_dir=sweep_dir, summary_path=summary_path)

        payload["run_dir"] = str(summary_path.parent)
        payload["summary_path"] = str(summary_path)
        payload["condition_id"] = payload.get("condition_id") or manifest.get("condition_id") or condition_id
        payload["trial_id"] = payload.get("trial_id") or manifest.get("trial_id") or inferred_trial_id
        payload["trial_index"] = payload.get("trial_index", manifest.get("trial_index"))
        payload["impairment_seed"] = payload.get("impairment_seed", manifest.get("impairment_seed"))
        payload["schema_version"] = payload.get("schema_version", manifest.get("schema_version"))
        payload["batch_window_ms"] = payload.get("batch_window_ms", manifest.get("batch_window_ms"))
        for env_name, field_name in [
            ("ADAPTIVE_MIN_BATCH_WINDOW_MS", "adaptive_min_batch_window_ms"),
            ("ADAPTIVE_MAX_BATCH_WINDOW_MS", "adaptive_max_batch_window_ms"),
            ("ADAPTIVE_STEP_UP_MS", "adaptive_step_up_ms"),
            ("ADAPTIVE_STEP_DOWN_MS", "adaptive_step_down_ms"),
            ("ADAPTIVE_QUEUE_HIGH_WATERMARK", "adaptive_queue_high_watermark"),
            ("ADAPTIVE_QUEUE_LOW_WATERMARK", "adaptive_queue_low_watermark"),
            ("ADAPTIVE_SEND_SLOW_MS", "adaptive_send_slow_ms"),
            ("ADAPTIVE_RECOVERY_STREAK", "adaptive_recovery_streak"),
        ]:
            payload[field_name] = payload.get(field_name, _manifest_gateway_setting(manifest, env_name))
        if "run_id" not in payload:
            payload["run_id"] = manifest.get("run_id", summary_path.parent.name)
        rows.append(payload)
    return rows


def _row_sort_key(row: dict[str, Any]) -> tuple[int, str]:
    trial_index = row.get("trial_index")
    if trial_index is None:
        return (10**9, str(row.get("run_id", row.get("run_dir", ""))))
    return (int(trial_index), str(row.get("run_id", row.get("run_dir", ""))))


def _metric_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {
            "mean": 0.0,
            "stddev": 0.0,
            "min": 0.0,
            "max": 0.0,
        }
    return {
        "mean": _round_metric(fmean(values)),
        "stddev": _round_metric(pstdev(values)) if len(values) > 1 else 0.0,
        "min": _round_metric(min(values)),
        "max": _round_metric(max(values)),
    }


def aggregate_summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        condition_id = str(row.get("condition_id") or row.get("run_id") or row.get("run_dir", ""))
        grouped.setdefault(condition_id, []).append(row)

    aggregated_rows: list[dict[str, Any]] = []
    for condition_id, group_rows in sorted(grouped.items()):
        ordered_rows = sorted(group_rows, key=_row_sort_key)
        first_row = dict(ordered_rows[0])
        aggregated = dict(first_row)
        aggregated["condition_id"] = condition_id
        aggregated["run_id"] = condition_id if len(ordered_rows) > 1 else first_row.get("run_id", condition_id)
        aggregated["run_dir"] = str(first_row["run_dir"])
        aggregated["summary_path"] = str(first_row["summary_path"])
        aggregated["n"] = len(ordered_rows)
        aggregated["trial_run_ids"] = [str(row.get("run_id", "")) for row in ordered_rows]
        aggregated["trial_run_dirs"] = [str(row.get("run_dir", "")) for row in ordered_rows]
        aggregated["trial_summary_paths"] = [str(row.get("summary_path", "")) for row in ordered_rows]
        aggregated["trial_ids"] = [row.get("trial_id") for row in ordered_rows if row.get("trial_id") is not None]
        aggregated["trial_indices"] = [int(row["trial_index"]) for row in ordered_rows if row.get("trial_index") is not None]
        aggregated["impairment_seeds"] = [int(row["impairment_seed"]) for row in ordered_rows if row.get("impairment_seed") is not None]

        for metric_name in AGGREGATED_METRICS:
            metric_values = [
                value
                for row in ordered_rows
                if (value := _coerce_float(row.get(metric_name))) is not None
            ]
            if not metric_values:
                continue
            stats = _metric_stats(metric_values)
            aggregated[metric_name] = stats["mean"]
            aggregated[f"{metric_name}_stddev"] = stats["stddev"]
            aggregated[f"{metric_name}_min"] = stats["min"]
            aggregated[f"{metric_name}_max"] = stats["max"]

        aggregated_rows.append(aggregated)
    return aggregated_rows


def write_condition_aggregates(sweep_dir: Path) -> Path:
    raw_rows = load_summary_rows(sweep_dir)
    condition_rows = aggregate_summary_rows(raw_rows)
    payload = {
        "schema_version": 1,
        "sweep_dir": str(sweep_dir),
        "trial_summary_count": len(raw_rows),
        "condition_count": len(condition_rows),
        "conditions": condition_rows,
    }
    output_path = sweep_dir / CONDITION_AGGREGATES_FILENAME
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path
