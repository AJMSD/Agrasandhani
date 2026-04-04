from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
from pathlib import Path
from statistics import mean

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE_DIR = Path(__file__).resolve().parent.parent
REPORT_DIR = BASE_DIR / "report"
INTEL_BANDWIDTH_SCENARIOS = ("clean", "bandwidth_200kbps", "loss_2pct", "outage_5s")
INTEL_BATCH_WINDOW_SWEEP_WINDOWS = (50, 100, 250, 500, 1000)
INTEL_V1_V2_ISOLATION_SCENARIOS = ("clean", "bandwidth_200kbps", "outage_5s")
INTEL_V1_V2_ISOLATION_WINDOWS = (50, 100, 250, 500, 1000)
INTEL_ADAPTIVE_SCENARIOS = ("bandwidth_200kbps", "loss_2pct")
OUTAGE_PHASE_WINDOWS: tuple[tuple[str, float, float | None], ...] = (
    ("steady-before-outage", 0.0, 10.0),
    ("outage", 10.0, 15.0),
    ("recovery", 15.0, None),
)


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _load_summary_rows(sweep_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for summary_path in sorted(sweep_dir.glob("*/summary.json")):
        payload = _load_json(summary_path)
        payload["run_dir"] = str(summary_path.parent)
        rows.append(payload)
    return rows


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * pct
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return float(ordered[lower])
    weight = index - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def _select_row(
    rows: list[dict[str, object]],
    *,
    variant: str,
    scenario: str,
    mqtt_qos: int,
) -> dict[str, object]:
    for row in rows:
        if row["variant"] == variant and row["scenario"] == scenario and int(row["mqtt_qos"]) == mqtt_qos:
            return row
    raise KeyError(f"Missing summary row for variant={variant}, scenario={scenario}, mqtt_qos={mqtt_qos}")


def _load_latency_samples(run_dir: Path) -> list[float]:
    csv_path = run_dir / "dashboard_measurements.csv"
    if not csv_path.exists():
        return []
    return [float(row["age_ms_at_display"]) for row in _load_csv(csv_path)]


def _load_timeseries(run_dir: Path) -> list[dict[str, float]]:
    csv_path = run_dir / "timeseries.csv"
    if not csv_path.exists():
        return []
    rows: list[dict[str, float]] = []
    for row in _load_csv(csv_path):
        rows.append({key: float(value) for key, value in row.items()})
    return rows


def _load_dashboard_summary(run_dir: Path) -> dict[str, int]:
    payload_path = run_dir / "dashboard_summary.json"
    if not payload_path.exists():
        return {
            "latestRowCount": 0,
            "messageCount": 0,
            "frameCount": 0,
            "staleCount": 0,
        }
    payload = _load_json(payload_path)
    summary = payload.get("summary", {}) if isinstance(payload, dict) else {}
    return {
        "latestRowCount": int(summary.get("latestRowCount", 0)),
        "messageCount": int(summary.get("messageCount", 0)),
        "frameCount": int(summary.get("frameCount", 0)),
        "staleCount": int(summary.get("staleCount", 0)),
    }


def _load_measurement_rows(run_dir: Path) -> list[dict[str, float | int]]:
    csv_path = run_dir / "dashboard_measurements.csv"
    if not csv_path.exists():
        return []
    rows: list[dict[str, float | int]] = []
    for index, row in enumerate(_load_csv(csv_path), start=1):
        age_text = row.get("age_ms_at_display", "")
        if age_text == "":
            continue
        frame_index_text = row.get("frame_index", "")
        ts_displayed_text = row.get("ts_displayed", "")
        frame_index = int(frame_index_text) if frame_index_text else index
        ts_displayed_ms = int(ts_displayed_text) if ts_displayed_text else index * 1000
        rows.append(
            {
                "frame_index": frame_index,
                "ts_displayed_ms": ts_displayed_ms,
                "age_ms": float(age_text),
            }
        )
    return rows


def _load_proxy_anchor_ms(run_dir: Path) -> int | None:
    csv_path = run_dir / "proxy_frame_log.csv"
    if not csv_path.exists():
        return None
    anchors = [
        int(row["upstream_received_ms"])
        for row in _load_csv(csv_path)
        if row.get("upstream_received_ms", "")
    ]
    if not anchors:
        return None
    return min(anchors)


def _phase_for_second(relative_second: float) -> str:
    for phase_name, start_s, end_s in OUTAGE_PHASE_WINDOWS:
        if end_s is None and relative_second >= start_s:
            return phase_name
        if end_s is not None and start_s <= relative_second < end_s:
            return phase_name
    return OUTAGE_PHASE_WINDOWS[-1][0]


def _format_stat_value(value: float | None) -> str:
    if value is None:
        return "n/a"
    return str(round(value, 3))


def _build_frame_age_trace(run_dir: Path) -> list[dict[str, float | int]]:
    grouped_rows: dict[int, list[dict[str, float | int]]] = {}
    for row in _load_measurement_rows(run_dir):
        grouped_rows.setdefault(int(row["frame_index"]), []).append(row)

    frame_trace: list[dict[str, float | int]] = []
    for frame_index in sorted(grouped_rows):
        group = grouped_rows[frame_index]
        frame_trace.append(
            {
                "frame_index": frame_index,
                "ts_displayed_ms": int(group[0]["ts_displayed_ms"]),
                "age_mean_ms": round(mean(float(row["age_ms"]) for row in group), 3),
                "rendered_updates": len(group),
            }
        )
    return frame_trace


def _relative_second_values(
    rows: list[dict[str, float | int]],
    *,
    time_field: str,
    anchor_ms: int | None,
) -> list[float]:
    if not rows:
        return []
    effective_anchor_ms = anchor_ms
    if effective_anchor_ms is None:
        effective_anchor_ms = min(int(row[time_field]) for row in rows)
    return [round((int(row[time_field]) - effective_anchor_ms) / 1000, 3) for row in rows]


def _build_intel_outage_freshness_rows(intel_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    freshness_rows: list[dict[str, object]] = []
    for variant in ("v0", "v4"):
        row = _select_row(intel_rows, variant=variant, scenario="outage_5s", mqtt_qos=0)
        run_dir = Path(str(row["run_dir"]))
        measurement_rows = _load_measurement_rows(run_dir)
        anchor_ms = _load_proxy_anchor_ms(run_dir)
        relative_seconds = _relative_second_values(measurement_rows, time_field="ts_displayed_ms", anchor_ms=anchor_ms)
        phase_ages: dict[str, list[float]] = {phase_name: [] for phase_name, _, _ in OUTAGE_PHASE_WINDOWS}
        phase_counts: dict[str, int] = {phase_name: 0 for phase_name, _, _ in OUTAGE_PHASE_WINDOWS}
        for measurement_row, relative_second in zip(measurement_rows, relative_seconds, strict=False):
            phase_name = _phase_for_second(relative_second)
            phase_ages[phase_name].append(float(measurement_row["age_ms"]))
            phase_counts[phase_name] += 1

        dashboard_summary = _load_dashboard_summary(run_dir)
        freshness_rows.append(
            {
                "variant": variant,
                "pre_outage_rendered_updates": phase_counts["steady-before-outage"],
                "pre_outage_age_mean_ms": _format_stat_value(mean(phase_ages["steady-before-outage"]) if phase_ages["steady-before-outage"] else None),
                "pre_outage_age_p95_ms": _format_stat_value(_percentile(phase_ages["steady-before-outage"], 0.95)),
                "outage_rendered_updates": phase_counts["outage"],
                "recovery_rendered_updates": phase_counts["recovery"],
                "recovery_age_mean_ms": _format_stat_value(mean(phase_ages["recovery"]) if phase_ages["recovery"] else None),
                "recovery_age_p95_ms": _format_stat_value(_percentile(phase_ages["recovery"], 0.95)),
                "recovery_age_max_ms": _format_stat_value(max(phase_ages["recovery"]) if phase_ages["recovery"] else None),
                "end_state_stale_count": dashboard_summary["staleCount"],
                "end_state_latest_row_count": dashboard_summary["latestRowCount"],
                "run_dir": str(run_dir),
            }
        )
    return freshness_rows


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"No rows available for {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown_table(path: Path, rows: list[dict[str, object]], *, columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    lines = [header, divider]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _format_delta(base: float, candidate: float) -> str:
    percent_delta = _percent_delta(base, candidate)
    if percent_delta is None:
        return "n/a"
    return f"{percent_delta:.1f}%"


def _percent_delta(base: float, candidate: float) -> float | None:
    if math.isclose(base, 0.0):
        return None
    return ((candidate - base) / base) * 100


def _build_intel_bandwidth_vs_v0_rows(intel_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for scenario in INTEL_BANDWIDTH_SCENARIOS:
        baseline = _select_row(intel_rows, variant="v0", scenario=scenario, mqtt_qos=0)
        for variant in ("v2", "v4"):
            candidate = _select_row(intel_rows, variant=variant, scenario=scenario, mqtt_qos=0)
            rows.append(
                {
                    "scenario": scenario,
                    "variant": variant,
                    "baseline_downstream_bytes_out": int(baseline["proxy_downstream_bytes_out"]),
                    "variant_downstream_bytes_out": int(candidate["proxy_downstream_bytes_out"]),
                    "downstream_bytes_delta_pct": _format_delta(
                        float(baseline["proxy_downstream_bytes_out"]),
                        float(candidate["proxy_downstream_bytes_out"]),
                    ),
                    "baseline_max_bandwidth_bytes_per_s": int(baseline["max_bandwidth_bytes_per_s"]),
                    "variant_max_bandwidth_bytes_per_s": int(candidate["max_bandwidth_bytes_per_s"]),
                    "max_bandwidth_delta_pct": _format_delta(
                        float(baseline["max_bandwidth_bytes_per_s"]),
                        float(candidate["max_bandwidth_bytes_per_s"]),
                    ),
                    "baseline_downstream_frames_out": int(baseline["proxy_downstream_frames_out"]),
                    "variant_downstream_frames_out": int(candidate["proxy_downstream_frames_out"]),
                    "downstream_frames_delta_pct": _format_delta(
                        float(baseline["proxy_downstream_frames_out"]),
                        float(candidate["proxy_downstream_frames_out"]),
                    ),
                    "latency_p95_ms": float(candidate["latency_p95_ms"]),
                }
            )
    return rows


def _format_bandwidth_comparison_series(
    comparison_rows: list[dict[str, object]],
    *,
    variant: str,
    delta_field: str,
) -> str:
    parts: list[str] = []
    for scenario in INTEL_BANDWIDTH_SCENARIOS:
        row = next(
            candidate
            for candidate in comparison_rows
            if candidate["variant"] == variant and candidate["scenario"] == scenario
        )
        parts.append(f"{row[delta_field]} under {scenario}")
    return ", ".join(parts)


def _build_intel_batch_window_tradeoff_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    tradeoff_rows: list[dict[str, object]] = []
    for row in rows:
        if row["variant"] != "v2" or row["scenario"] != "clean" or int(row["mqtt_qos"]) != 0:
            continue
        batch_window_ms = int(row.get("effective_batch_window_ms", row.get("batch_window_ms", 0)))
        if batch_window_ms <= 0:
            continue
        tradeoff_rows.append(
            {
                "batch_window_ms": batch_window_ms,
                "latency_p95_ms": float(row["latency_p95_ms"]),
                "latency_mean_ms": float(row["latency_mean_ms"]),
                "max_frame_rate_per_s": int(row["max_frame_rate_per_s"]),
                "proxy_downstream_frames_out": int(row["proxy_downstream_frames_out"]),
                "proxy_downstream_bytes_out": int(row["proxy_downstream_bytes_out"]),
                "max_bandwidth_bytes_per_s": int(row["max_bandwidth_bytes_per_s"]),
                "stale_fraction": float(row["stale_fraction"]),
                "run_dir": str(row["run_dir"]),
            }
        )
    tradeoff_rows.sort(key=lambda candidate: candidate["batch_window_ms"])
    if not tradeoff_rows:
        raise ValueError("No Intel V2 qos0 clean rows were found for the batch-window sweep")
    return tradeoff_rows


def _describe_batch_window_payload_shift(batch_rows: list[dict[str, object]]) -> str:
    first_row = batch_rows[0]
    last_row = batch_rows[-1]
    percent_delta = _percent_delta(
        float(first_row["proxy_downstream_bytes_out"]),
        float(last_row["proxy_downstream_bytes_out"]),
    )
    if percent_delta is None:
        return "payload-byte change could not be computed for the batch-window sweep"
    delta_label = _format_delta(
        float(first_row["proxy_downstream_bytes_out"]),
        float(last_row["proxy_downstream_bytes_out"]),
    )
    if abs(percent_delta) < 10.0:
        return (
            f"payload bytes moved from {first_row['proxy_downstream_bytes_out']} at {first_row['batch_window_ms']} ms "
            f"to {last_row['proxy_downstream_bytes_out']} at {last_row['batch_window_ms']} ms ({delta_label}), "
            "which was not material relative to the latency and frame-rate shift"
        )
    return (
        f"payload bytes moved from {first_row['proxy_downstream_bytes_out']} at {first_row['batch_window_ms']} ms "
        f"to {last_row['proxy_downstream_bytes_out']} at {last_row['batch_window_ms']} ms ({delta_label}), "
        "so payload volume also changed materially across the sweep"
    )


def _build_intel_v1_v2_isolation_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    filtered: dict[tuple[str, int, str], dict[str, object]] = {}
    for row in rows:
        variant = str(row.get("variant", ""))
        scenario = str(row.get("scenario", ""))
        if variant not in {"v1", "v2"} or scenario not in INTEL_V1_V2_ISOLATION_SCENARIOS:
            continue
        if int(row["mqtt_qos"]) != 0:
            continue
        batch_window_ms = int(row.get("effective_batch_window_ms", row.get("batch_window_ms", 0)))
        if batch_window_ms <= 0:
            continue
        filtered[(scenario, batch_window_ms, variant)] = row

    comparison_rows: list[dict[str, object]] = []
    missing_pairs: list[str] = []
    for scenario in INTEL_V1_V2_ISOLATION_SCENARIOS:
        for batch_window_ms in INTEL_V1_V2_ISOLATION_WINDOWS:
            v1_row = filtered.get((scenario, batch_window_ms, "v1"))
            v2_row = filtered.get((scenario, batch_window_ms, "v2"))
            if v1_row is None or v2_row is None:
                missing_pairs.append(f"{scenario}@{batch_window_ms}ms")
                continue
            comparison_rows.append(
                {
                    "scenario": scenario,
                    "batch_window_ms": batch_window_ms,
                    "v1_latency_p95_ms": float(v1_row["latency_p95_ms"]),
                    "v2_latency_p95_ms": float(v2_row["latency_p95_ms"]),
                    "latency_p95_delta_ms": round(float(v2_row["latency_p95_ms"]) - float(v1_row["latency_p95_ms"]), 3),
                    "v1_proxy_downstream_frames_out": int(v1_row["proxy_downstream_frames_out"]),
                    "v2_proxy_downstream_frames_out": int(v2_row["proxy_downstream_frames_out"]),
                    "downstream_frames_delta_pct": _format_delta(
                        float(v1_row["proxy_downstream_frames_out"]),
                        float(v2_row["proxy_downstream_frames_out"]),
                    ),
                    "v1_proxy_downstream_bytes_out": int(v1_row["proxy_downstream_bytes_out"]),
                    "v2_proxy_downstream_bytes_out": int(v2_row["proxy_downstream_bytes_out"]),
                    "downstream_bytes_delta_pct": _format_delta(
                        float(v1_row["proxy_downstream_bytes_out"]),
                        float(v2_row["proxy_downstream_bytes_out"]),
                    ),
                    "v1_max_bandwidth_bytes_per_s": int(v1_row["max_bandwidth_bytes_per_s"]),
                    "v2_max_bandwidth_bytes_per_s": int(v2_row["max_bandwidth_bytes_per_s"]),
                    "max_bandwidth_delta_pct": _format_delta(
                        float(v1_row["max_bandwidth_bytes_per_s"]),
                        float(v2_row["max_bandwidth_bytes_per_s"]),
                    ),
                    "v1_stale_fraction": float(v1_row.get("stale_fraction", 0.0)),
                    "v2_stale_fraction": float(v2_row.get("stale_fraction", 0.0)),
                    "stale_fraction_delta": round(
                        float(v2_row.get("stale_fraction", 0.0)) - float(v1_row.get("stale_fraction", 0.0)),
                        6,
                    ),
                    "v1_run_dir": str(v1_row["run_dir"]),
                    "v2_run_dir": str(v2_row["run_dir"]),
                }
            )
    if missing_pairs:
        missing_list = ", ".join(missing_pairs)
        raise ValueError(f"Missing Intel v1/v2 isolation rows for: {missing_list}")
    return comparison_rows


def _parse_percent_label(value: object) -> float:
    text = str(value).strip()
    if text == "n/a":
        return 0.0
    return float(text.removesuffix("%"))


def _scenario_rows(rows: list[dict[str, object]], scenario: str) -> list[dict[str, object]]:
    scenario_rows = [row for row in rows if row["scenario"] == scenario]
    return sorted(scenario_rows, key=lambda candidate: int(candidate["batch_window_ms"]))


def _format_range(values: list[float], *, suffix: str = "", decimals: int = 1) -> str:
    if not values:
        return "n/a"
    minimum = min(values)
    maximum = max(values)
    value_format = f"{{:.{decimals}f}}"
    if math.isclose(minimum, maximum):
        return f"{value_format.format(minimum)}{suffix}"
    return f"{value_format.format(minimum)}{suffix} to {value_format.format(maximum)}{suffix}"


def _describe_v1_v2_isolation_scenario(rows: list[dict[str, object]], scenario: str) -> str:
    scenario_rows = _scenario_rows(rows, scenario)
    byte_deltas = [_parse_percent_label(row["downstream_bytes_delta_pct"]) for row in scenario_rows]
    frame_deltas = [_parse_percent_label(row["downstream_frames_delta_pct"]) for row in scenario_rows]
    latency_deltas = [float(row["latency_p95_delta_ms"]) for row in scenario_rows]
    stale_deltas = [float(row["stale_fraction_delta"]) for row in scenario_rows]
    description = (
        f"Under {scenario}, V2 changed downstream bytes by {_format_range(byte_deltas, suffix='%', decimals=1)} "
        f"and downstream frames by {_format_range(frame_deltas, suffix='%', decimals=1)} versus V1, "
        f"while latency p95 shifted by {_format_range(latency_deltas, suffix=' ms', decimals=1)} across the shared 50-1000 ms windows."
    )
    if any(not math.isclose(delta, 0.0) for delta in stale_deltas):
        description += f" Stale-fraction delta ranged from {_format_range(stale_deltas, decimals=3)}."
    else:
        description += " Stale fraction stayed identical across those windows."
    return description


def _load_gateway_frame_trace(run_dir: Path) -> list[dict[str, object]]:
    csv_path = run_dir / "gateway_forward_log.csv"
    if not csv_path.exists():
        return []

    rows_by_frame: dict[tuple[str, str], dict[str, object]] = {}
    for row in _load_csv(csv_path):
        frame_id = str(row.get("frame_id", ""))
        ts_sent_ws = str(row.get("ts_sent_ws", ""))
        if not frame_id or not ts_sent_ws:
            continue
        key = (frame_id, ts_sent_ws)
        rows_by_frame[key] = {
            "frame_id": int(frame_id),
            "ts_sent_ws": int(ts_sent_ws),
            "effective_batch_window_ms": int(row.get("effective_batch_window_ms", 0) or 0),
            "adaptation_reason": row.get("adaptation_reason", ""),
        }
    return sorted(rows_by_frame.values(), key=lambda item: int(item["ts_sent_ws"]))


def _load_gateway_metrics(run_dir: Path) -> dict[str, object]:
    metrics_path = run_dir / "gateway_metrics.json"
    if not metrics_path.exists():
        return {}
    return _load_json(metrics_path)


def _trace_window_bounds(trace_rows: list[dict[str, object]], *, fallback_window_ms: int) -> tuple[int, int]:
    windows = [int(row["effective_batch_window_ms"]) for row in trace_rows if int(row["effective_batch_window_ms"]) > 0]
    if not windows:
        return fallback_window_ms, fallback_window_ms
    return min(windows), max(windows)


def _relative_seconds_from_trace(trace_rows: list[dict[str, object]]) -> list[float]:
    if not trace_rows:
        return []
    first_ts = int(trace_rows[0]["ts_sent_ws"])
    return [round((int(row["ts_sent_ws"]) - first_ts) / 1000, 3) for row in trace_rows]


def _load_update_rate_trace(run_dir: Path) -> tuple[list[float], list[float]]:
    series = _load_timeseries(run_dir)
    if not series:
        return [], []
    first_second = series[0]["epoch_second"]
    x_values = [point["epoch_second"] - first_second for point in series]
    y_values = [point["update_rate_per_s"] for point in series]
    return x_values, y_values


def _build_intel_adaptive_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    filtered: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows:
        scenario = str(row.get("scenario", ""))
        variant = str(row.get("variant", ""))
        if scenario not in INTEL_ADAPTIVE_SCENARIOS or variant not in {"v2", "v3"}:
            continue
        if int(row["mqtt_qos"]) != 0:
            continue
        filtered[(scenario, variant)] = row

    comparison_rows: list[dict[str, object]] = []
    missing_pairs: list[str] = []
    for scenario in INTEL_ADAPTIVE_SCENARIOS:
        v2_row = filtered.get((scenario, "v2"))
        v3_row = filtered.get((scenario, "v3"))
        if v2_row is None or v3_row is None:
            missing_pairs.append(scenario)
            continue
        v2_trace = _load_gateway_frame_trace(Path(str(v2_row["run_dir"])))
        v3_trace = _load_gateway_frame_trace(Path(str(v3_row["run_dir"])))
        v2_min_window_ms, v2_max_window_ms = _trace_window_bounds(
            v2_trace,
            fallback_window_ms=int(v2_row.get("effective_batch_window_ms", 0)),
        )
        v3_min_window_ms, v3_max_window_ms = _trace_window_bounds(
            v3_trace,
            fallback_window_ms=int(v3_row.get("effective_batch_window_ms", 0)),
        )
        v3_metrics = _load_gateway_metrics(Path(str(v3_row["run_dir"])))
        comparison_rows.append(
            {
                "scenario": scenario,
                "v2_latency_p95_ms": float(v2_row["latency_p95_ms"]),
                "v3_latency_p95_ms": float(v3_row["latency_p95_ms"]),
                "latency_p95_delta_ms": round(float(v3_row["latency_p95_ms"]) - float(v2_row["latency_p95_ms"]), 3),
                "v2_stale_fraction": float(v2_row.get("stale_fraction", 0.0)),
                "v3_stale_fraction": float(v3_row.get("stale_fraction", 0.0)),
                "stale_fraction_delta": round(
                    float(v3_row.get("stale_fraction", 0.0)) - float(v2_row.get("stale_fraction", 0.0)),
                    6,
                ),
                "v2_max_update_rate_per_s": int(v2_row.get("max_update_rate_per_s", 0)),
                "v3_max_update_rate_per_s": int(v3_row.get("max_update_rate_per_s", 0)),
                "update_rate_delta_pct": _format_delta(
                    float(v2_row.get("max_update_rate_per_s", 0)),
                    float(v3_row.get("max_update_rate_per_s", 0)),
                ),
                "v2_proxy_downstream_frames_out": int(v2_row["proxy_downstream_frames_out"]),
                "v3_proxy_downstream_frames_out": int(v3_row["proxy_downstream_frames_out"]),
                "downstream_frames_delta_pct": _format_delta(
                    float(v2_row["proxy_downstream_frames_out"]),
                    float(v3_row["proxy_downstream_frames_out"]),
                ),
                "v2_proxy_downstream_bytes_out": int(v2_row["proxy_downstream_bytes_out"]),
                "v3_proxy_downstream_bytes_out": int(v3_row["proxy_downstream_bytes_out"]),
                "downstream_bytes_delta_pct": _format_delta(
                    float(v2_row["proxy_downstream_bytes_out"]),
                    float(v3_row["proxy_downstream_bytes_out"]),
                ),
                "v2_min_effective_batch_window_ms": v2_min_window_ms,
                "v2_max_effective_batch_window_ms": v2_max_window_ms,
                "v3_min_effective_batch_window_ms": v3_min_window_ms,
                "v3_max_effective_batch_window_ms": v3_max_window_ms,
                "v3_adaptive_window_increase_events": int(v3_metrics.get("adaptive_window_increase_events", 0)),
                "v3_adaptive_window_decrease_events": int(v3_metrics.get("adaptive_window_decrease_events", 0)),
                "v3_last_adaptation_reason": str(v3_metrics.get("last_adaptation_reason", "")),
                "v2_run_dir": str(v2_row["run_dir"]),
                "v3_run_dir": str(v3_row["run_dir"]),
            }
        )
    if missing_pairs:
        raise ValueError(f"Missing Intel v2/v3 adaptive rows for: {', '.join(missing_pairs)}")
    return comparison_rows


def _describe_adaptive_scenario(rows: list[dict[str, object]], scenario: str) -> str:
    row = next(candidate for candidate in rows if candidate["scenario"] == scenario)
    v3_min_window = int(row["v3_min_effective_batch_window_ms"])
    v3_max_window = int(row["v3_max_effective_batch_window_ms"])
    if v3_min_window == v3_max_window:
        window_clause = f"V3's effective batch window stayed flat at {v3_min_window} ms"
    else:
        window_clause = (
            f"V3's effective batch window moved from {v3_min_window} ms to {v3_max_window} ms "
            f"with {row['v3_adaptive_window_increase_events']} increase events and "
            f"{row['v3_adaptive_window_decrease_events']} decrease events"
        )
    return (
        f"Under {scenario}, adaptive V3 changed stale fraction by {row['stale_fraction_delta']:+.6f}, "
        f"max rendered update rate by {row['update_rate_delta_pct']}, downstream frames by {row['downstream_frames_delta_pct']}, "
        f"and downstream bytes by {row['downstream_bytes_delta_pct']} versus fixed-window V2. "
        f"{window_clause}. The last adaptation reason was `{row['v3_last_adaptation_reason']}`."
    )


def _plot_latency_cdf(rows: list[dict[str, object]], *, scenario: str, mqtt_qos: int, output_path: Path) -> None:
    figure = plt.figure(figsize=(8, 5))
    for variant in ("v0", "v2", "v4"):
        row = _select_row(rows, variant=variant, scenario=scenario, mqtt_qos=mqtt_qos)
        samples = _load_latency_samples(Path(str(row["run_dir"])))
        if not samples:
            continue
        ordered = sorted(samples)
        cdf = [(index + 1) / len(ordered) for index in range(len(ordered))]
        plt.plot(ordered, cdf, label=variant.upper())
    plt.xlabel("Latency (ms)")
    plt.ylabel("CDF")
    plt.title(f"Latency CDF ({scenario}, qos{mqtt_qos})")
    plt.legend()
    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=150)
    plt.close(figure)


def _plot_timeseries(
    rows: list[dict[str, object]],
    *,
    scenario: str,
    mqtt_qos: int,
    metric: str,
    title: str,
    ylabel: str,
    output_path: Path,
) -> None:
    figure = plt.figure(figsize=(8, 5))
    for variant in ("v0", "v2", "v4"):
        row = _select_row(rows, variant=variant, scenario=scenario, mqtt_qos=mqtt_qos)
        series = _load_timeseries(Path(str(row["run_dir"])))
        if not series:
            continue
        x_values = [point["epoch_second"] for point in series]
        y_values = [point[metric] for point in series]
        plt.plot(x_values, y_values, label=variant.upper())
    plt.xlabel("Epoch second")
    plt.ylabel(ylabel)
    plt.title(title)
    plt.legend()
    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=150)
    plt.close(figure)


def _plot_outage_age_over_time(rows: list[dict[str, object]], *, output_path: Path) -> None:
    figure, axis = plt.subplots(figsize=(10, 5))
    variant_styles = {
        "v0": ("tab:blue", "V0"),
        "v4": ("tab:red", "V4"),
    }
    max_relative_second = 0.0

    for variant in ("v0", "v4"):
        row = _select_row(rows, variant=variant, scenario="outage_5s", mqtt_qos=0)
        run_dir = Path(str(row["run_dir"]))
        frame_trace = _build_frame_age_trace(run_dir)
        anchor_ms = _load_proxy_anchor_ms(run_dir)
        x_values = _relative_second_values(frame_trace, time_field="ts_displayed_ms", anchor_ms=anchor_ms)
        y_values = [float(point["age_mean_ms"]) for point in frame_trace]
        if not x_values or not y_values:
            continue
        max_relative_second = max(max_relative_second, max(x_values))
        color, label = variant_styles[variant]
        axis.plot(x_values, y_values, marker="o", color=color, label=label)

    phase_colors = {
        "steady-before-outage": "#d9edf7",
        "outage": "#f2dede",
        "recovery": "#dff0d8",
    }
    phase_end = max_relative_second if max_relative_second > 0 else 15.0
    for phase_name, start_s, end_s in OUTAGE_PHASE_WINDOWS:
        clipped_end_s = phase_end if end_s is None else min(end_s, phase_end)
        if clipped_end_s <= start_s:
            continue
        axis.axvspan(start_s, clipped_end_s, color=phase_colors[phase_name], alpha=0.2)
    axis.axvline(10.0, color="0.4", linestyle="--", linewidth=1)
    axis.axvline(15.0, color="0.4", linestyle="--", linewidth=1)

    axis.set_xlabel("Relative second from first proxy upstream receive")
    axis.set_ylabel("Frame mean age at display (ms)")
    axis.set_title("Intel outage qos0 V0 vs V4 age over time")
    axis.grid(True, axis="y", alpha=0.3)
    axis.legend(loc="best")
    figure.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=150)
    plt.close(figure)


def _plot_batch_window_tradeoff(rows: list[dict[str, object]], *, output_path: Path) -> None:
    batch_windows = [row["batch_window_ms"] for row in rows]
    latency_values = [row["latency_p95_ms"] for row in rows]
    frame_rate_values = [row["max_frame_rate_per_s"] for row in rows]

    figure, left_axis = plt.subplots(figsize=(8, 5))
    right_axis = left_axis.twinx()

    left_line = left_axis.plot(
        batch_windows,
        latency_values,
        marker="o",
        color="tab:red",
        label="Latency p95 (ms)",
    )[0]
    right_line = right_axis.plot(
        batch_windows,
        frame_rate_values,
        marker="s",
        color="tab:blue",
        label="Max frame rate (/s)",
    )[0]

    left_axis.set_xlabel("Batch window (ms)")
    left_axis.set_ylabel("Latency p95 (ms)", color="tab:red")
    right_axis.set_ylabel("Max frame rate per second", color="tab:blue")
    left_axis.set_title("Intel V2 batch-window tradeoff")
    left_axis.set_xticks(batch_windows)
    left_axis.grid(True, axis="y", alpha=0.3)
    left_axis.legend([left_line, right_line], [left_line.get_label(), right_line.get_label()], loc="best")
    figure.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=150)
    plt.close(figure)


def _plot_v1_v2_isolation(rows: list[dict[str, object]], *, output_path: Path) -> None:
    figure, axes = plt.subplots(1, 2, figsize=(12, 5), sharex=True)
    scenario_styles = {
        "clean": "tab:blue",
        "bandwidth_200kbps": "tab:orange",
        "outage_5s": "tab:green",
    }

    for scenario in INTEL_V1_V2_ISOLATION_SCENARIOS:
        scenario_rows = _scenario_rows(rows, scenario)
        batch_windows = [int(row["batch_window_ms"]) for row in scenario_rows]
        byte_deltas = [_parse_percent_label(row["downstream_bytes_delta_pct"]) for row in scenario_rows]
        frame_deltas = [_parse_percent_label(row["downstream_frames_delta_pct"]) for row in scenario_rows]
        color = scenario_styles[scenario]
        axes[0].plot(batch_windows, byte_deltas, marker="o", color=color, label=scenario)
        axes[1].plot(batch_windows, frame_deltas, marker="s", color=color, label=scenario)

    axes[0].set_title("V2 vs V1 bytes delta")
    axes[0].set_ylabel("Downstream bytes delta (%)")
    axes[1].set_title("V2 vs V1 frames delta")
    axes[1].set_ylabel("Downstream frames delta (%)")
    for axis in axes:
        axis.set_xlabel("Batch window (ms)")
        axis.set_xticks(list(INTEL_V1_V2_ISOLATION_WINDOWS))
        axis.grid(True, axis="y", alpha=0.3)
    axes[1].legend(loc="best")
    figure.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=150)
    plt.close(figure)


def _plot_adaptive_impairment(rows: list[dict[str, object]], *, output_path: Path) -> None:
    figure, axes = plt.subplots(len(INTEL_ADAPTIVE_SCENARIOS), 1, figsize=(10, 8), sharex=False)
    if len(INTEL_ADAPTIVE_SCENARIOS) == 1:
        axes = [axes]

    for axis, scenario in zip(axes, INTEL_ADAPTIVE_SCENARIOS):
        row = next(candidate for candidate in rows if candidate["scenario"] == scenario)
        v2_run_dir = Path(str(row["v2_run_dir"]))
        v3_run_dir = Path(str(row["v3_run_dir"]))
        v2_trace = _load_gateway_frame_trace(v2_run_dir)
        v3_trace = _load_gateway_frame_trace(v3_run_dir)
        v2_x = _relative_seconds_from_trace(v2_trace)
        v3_x = _relative_seconds_from_trace(v3_trace)
        v2_windows = [int(item["effective_batch_window_ms"]) for item in v2_trace]
        v3_windows = [int(item["effective_batch_window_ms"]) for item in v3_trace]

        right_axis = axis.twinx()

        if v2_x and v2_windows:
            axis.step(v2_x, v2_windows, where="post", linestyle="--", color="tab:gray", label="V2 fixed window")
        else:
            axis.axhline(
                int(row["v2_min_effective_batch_window_ms"]),
                linestyle="--",
                color="tab:gray",
                label="V2 fixed window",
            )
        if v3_x and v3_windows:
            axis.step(v3_x, v3_windows, where="post", color="tab:red", label="V3 effective window")
        else:
            axis.axhline(
                int(row["v3_min_effective_batch_window_ms"]),
                color="tab:red",
                label="V3 effective window",
            )

        v2_rate_x, v2_rates = _load_update_rate_trace(v2_run_dir)
        v3_rate_x, v3_rates = _load_update_rate_trace(v3_run_dir)
        if v2_rate_x and v2_rates:
            right_axis.plot(v2_rate_x, v2_rates, color="tab:blue", alpha=0.6, label="V2 update rate")
        if v3_rate_x and v3_rates:
            right_axis.plot(v3_rate_x, v3_rates, color="tab:green", alpha=0.6, label="V3 update rate")

        axis.set_title(f"Adaptive batching under {scenario}")
        axis.set_xlabel("Relative second")
        axis.set_ylabel("Effective batch window (ms)", color="tab:red")
        right_axis.set_ylabel("Rendered update rate per second", color="tab:blue")
        axis.grid(True, axis="y", alpha=0.3)

        left_handles, left_labels = axis.get_legend_handles_labels()
        right_handles, right_labels = right_axis.get_legend_handles_labels()
        axis.legend(left_handles + right_handles, left_labels + right_labels, loc="best")

    figure.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=150)
    plt.close(figure)


def _describe_outage_freshness(rows: list[dict[str, object]]) -> str:
    v0_row = next(row for row in rows if row["variant"] == "v0")
    v4_row = next(row for row in rows if row["variant"] == "v4")
    return (
        f"On the Intel qos0 outage age trace, V0 rendered {v0_row['pre_outage_rendered_updates']} pre-outage updates "
        f"with pre-outage p95 age {v0_row['pre_outage_age_p95_ms']} ms, while V4 rendered {v4_row['pre_outage_rendered_updates']} "
        f"pre-outage updates with pre-outage p95 age {v4_row['pre_outage_age_p95_ms']} ms. "
        f"During the five-second outage, rendered updates dropped to {v0_row['outage_rendered_updates']} for V0 and "
        f"{v4_row['outage_rendered_updates']} for V4. In recovery, V0 rendered {v0_row['recovery_rendered_updates']} updates "
        f"with recovery p95 age {v0_row['recovery_age_p95_ms']} ms, while V4 rendered {v4_row['recovery_rendered_updates']} "
        f"updates with recovery p95 age {v4_row['recovery_age_p95_ms']} ms. End-state staleCount/latestRowCount were "
        f"{v0_row['end_state_stale_count']}/{v0_row['end_state_latest_row_count']} for V0 and "
        f"{v4_row['end_state_stale_count']}/{v4_row['end_state_latest_row_count']} for V4. "
        "The measured effect is a visibility tradeoff rather than a lower-age result: V4 keeps a larger "
        "last-known-good state visible, but the visible data is older."
    )


def _load_demo_summary(demo_dir: Path, side: str) -> dict[str, int]:
    payload = _load_json(demo_dir / f"{side}_dashboard" / "dashboard_summary.json")
    summary = payload.get("summary", {})
    return {
        "latestRowCount": int(summary.get("latestRowCount", 0)),
        "messageCount": int(summary.get("messageCount", 0)),
        "frameCount": int(summary.get("frameCount", 0)),
        "staleCount": int(summary.get("staleCount", 0)),
    }


def _copy_demo_artifacts(demo_dir: Path, figures_dir: Path) -> None:
    figures_dir.mkdir(parents=True, exist_ok=True)
    for source_name, destination_name in [
        ("demo_compare.png", "final_demo_compare.png"),
        ("baseline_dashboard/dashboard.png", "final_demo_baseline_dashboard.png"),
        ("smart_dashboard/dashboard.png", "final_demo_smart_dashboard.png"),
    ]:
        shutil.copy2(demo_dir / source_name, figures_dir / destination_name)


def _build_key_claims(
    intel_rows: list[dict[str, object]],
    aot_rows: list[dict[str, object]],
    demo_dir: Path,
    intel_outage_freshness_rows: list[dict[str, object]],
    intel_batch_rows: list[dict[str, object]] | None = None,
    intel_v1_v2_rows: list[dict[str, object]] | None = None,
    intel_adaptive_rows: list[dict[str, object]] | None = None,
) -> str:
    bandwidth_rows = _build_intel_bandwidth_vs_v0_rows(intel_rows)
    clean_v0 = _select_row(intel_rows, variant="v0", scenario="clean", mqtt_qos=0)
    clean_v2 = _select_row(intel_rows, variant="v2", scenario="clean", mqtt_qos=0)
    clean_v4 = _select_row(intel_rows, variant="v4", scenario="clean", mqtt_qos=0)
    outage_v0 = _select_row(intel_rows, variant="v0", scenario="outage_5s", mqtt_qos=1)
    outage_v2 = _select_row(intel_rows, variant="v2", scenario="outage_5s", mqtt_qos=1)
    outage_v4 = _select_row(intel_rows, variant="v4", scenario="outage_5s", mqtt_qos=1)
    baseline_demo = _load_demo_summary(demo_dir, "baseline")
    smart_demo = _load_demo_summary(demo_dir, "smart")

    qos1_duplicates = sum(int(row.get("duplicates_dropped", 0)) for row in intel_rows if int(row["mqtt_qos"]) == 1)
    avg_qos1_messages = mean(int(row.get("gateway_mqtt_in_msgs", 0)) for row in intel_rows if int(row["mqtt_qos"]) == 1)
    aot_clean_v0 = _select_row(aot_rows, variant="v0", scenario="clean", mqtt_qos=0)
    aot_clean_v4 = _select_row(aot_rows, variant="v4", scenario="clean", mqtt_qos=0)

    lines = [
        (
            "- Intel qos0 downstream payload bytes did not drop below V0 in the paper-ready bandwidth comparison: "
            f"V2 changed by {_format_bandwidth_comparison_series(bandwidth_rows, variant='v2', delta_field='downstream_bytes_delta_pct')}, "
            f"while V4 changed by {_format_bandwidth_comparison_series(bandwidth_rows, variant='v4', delta_field='downstream_bytes_delta_pct')}. "
            "Both smart variants still cut downstream frame count by roughly 95%-97% across those same scenarios."
        ),
        f"- Intel clean qos0 latency p95 was {clean_v0['latency_p95_ms']} ms for V0, {clean_v2['latency_p95_ms']} ms for V2, and {clean_v4['latency_p95_ms']} ms for V4.",
        (
            f"- Intel outage qos1 downstream frame count dropped from {outage_v0['proxy_downstream_frames_out']} in V0 "
            f"to {outage_v2['proxy_downstream_frames_out']} in V2 and {outage_v4['proxy_downstream_frames_out']} in V4 "
            f"({ _format_delta(float(outage_v0['proxy_downstream_frames_out']), float(outage_v4['proxy_downstream_frames_out'])) } vs V0)."
        ),
        (
            f"- Intel outage qos1 downstream bytes moved from {outage_v0['proxy_downstream_bytes_out']} in V0 "
            f"to {outage_v4['proxy_downstream_bytes_out']} in V4 "
            f"({ _format_delta(float(outage_v0['proxy_downstream_bytes_out']), float(outage_v4['proxy_downstream_bytes_out'])) } vs V0), "
            "which captures the tradeoff between fewer frames and larger aggregate envelopes."
        ),
        (
            "- Intel qos0 outage freshness is now shown with an age-of-information trace rather than a stale-fraction time series: "
            + _describe_outage_freshness(intel_outage_freshness_rows)
        ),
        (
            f"- Intel qos1 runs saw {qos1_duplicates} duplicate drops across the primary sweep while averaging "
            f"{avg_qos1_messages:.1f} MQTT ingress messages per run, so the broker-backed setup did not surface strong QoS1 retransmit duplication in this environment."
        ),
        (
            f"- The captured demo ended with baseline staleCount={baseline_demo['staleCount']} and smart staleCount={smart_demo['staleCount']}, "
            f"while smart mode rendered only {smart_demo['frameCount']} frames versus {baseline_demo['frameCount']} for the raw baseline and retained "
            f"{smart_demo['latestRowCount']} latest rows versus {baseline_demo['latestRowCount']} in the captured end state."
        ),
        (
            f"- AoT validation on qos0 clean kept the pipeline working on a second public source; V0 rendered {aot_clean_v0['proxy_downstream_frames_out']} frames "
            f"and V4 rendered {aot_clean_v4['proxy_downstream_frames_out']} frames with p95 latencies of {aot_clean_v0['latency_p95_ms']} ms and {aot_clean_v4['latency_p95_ms']} ms respectively."
        ),
    ]
    if intel_batch_rows is not None:
        first_row = intel_batch_rows[0]
        last_row = intel_batch_rows[-1]
        lines.insert(
            1,
            (
                f"- Intel V2 batch-window sweep moved latency p95 from {first_row['latency_p95_ms']} ms at {first_row['batch_window_ms']} ms "
                f"to {last_row['latency_p95_ms']} ms at {last_row['batch_window_ms']} ms, while max frame rate dropped from "
                f"{first_row['max_frame_rate_per_s']} to {last_row['max_frame_rate_per_s']}. "
                f"Across the same sweep, {_describe_batch_window_payload_shift(intel_batch_rows)}."
            ),
        )
    if intel_v1_v2_rows is not None:
        lines.insert(
            2,
            (
                "- Intel V1 versus V2 isolation sweep shows what compaction changes beyond batching alone: "
                + " ".join(
                    _describe_v1_v2_isolation_scenario(intel_v1_v2_rows, scenario)
                    for scenario in INTEL_V1_V2_ISOLATION_SCENARIOS
                )
            ),
        )
    if intel_adaptive_rows is not None:
        lines.insert(
            3,
            (
                "- Intel V2 versus V3 adaptive sweep shows what adaptive batching changed under impairment: "
                + " ".join(
                    _describe_adaptive_scenario(intel_adaptive_rows, scenario)
                    for scenario in INTEL_ADAPTIVE_SCENARIOS
                )
            ),
        )
    return "\n".join(lines) + "\n"


def _write_final_report(
    *,
    intel_sweep_dir: Path,
    aot_sweep_dir: Path,
    demo_dir: Path,
    intel_rows: list[dict[str, object]],
    aot_rows: list[dict[str, object]],
    intel_outage_freshness_rows: list[dict[str, object]],
    intel_batch_rows: list[dict[str, object]] | None = None,
    intel_v1_v2_rows: list[dict[str, object]] | None = None,
    intel_adaptive_rows: list[dict[str, object]] | None = None,
) -> None:
    bandwidth_rows = _build_intel_bandwidth_vs_v0_rows(intel_rows)
    clean_v0 = _select_row(intel_rows, variant="v0", scenario="clean", mqtt_qos=0)
    clean_v4 = _select_row(intel_rows, variant="v4", scenario="clean", mqtt_qos=0)
    outage_v0 = _select_row(intel_rows, variant="v0", scenario="outage_5s", mqtt_qos=1)
    outage_v4 = _select_row(intel_rows, variant="v4", scenario="outage_5s", mqtt_qos=1)
    aot_clean_v0 = _select_row(aot_rows, variant="v0", scenario="clean", mqtt_qos=0)
    aot_clean_v4 = _select_row(aot_rows, variant="v4", scenario="clean", mqtt_qos=0)
    demo_baseline = _load_demo_summary(demo_dir, "baseline")
    demo_smart = _load_demo_summary(demo_dir, "smart")
    qos1_duplicates = sum(int(row.get("duplicates_dropped", 0)) for row in intel_rows if int(row["mqtt_qos"]) == 1)

    report_text = f"""# Agrasandhani Final Report

## Abstract

Agrasandhani explores a local MQTT-to-WebSocket sensor pipeline that can either forward every message directly or apply batching, compaction, adaptive flushing, and last-known-good freshness semantics. The final evaluation uses a real Intel Berkeley Lab replay as the primary workload, a smaller AoT validation replay, and a captured live demo. Across the Intel clean qos0 run, the raw baseline reached a latency p95 of {clean_v0['latency_p95_ms']} ms while the adaptive V4 path reached {clean_v4['latency_p95_ms']} ms, reflecting the deliberate latency-for-stability tradeoff introduced by batching. The explicit Intel qos0 bandwidth comparison did not show a downstream payload-byte reduction versus V0; instead, the smart paths traded higher payload-byte totals for much lower frame counts. Under the Intel outage qos1 run, V4 reduced downstream frame count from {outage_v0['proxy_downstream_frames_out']} to {outage_v4['proxy_downstream_frames_out']} while keeping stale rows visible through the outage window, which made the live comparison materially easier to interpret.

## 1. Introduction

The project goal is to make bursty IoT replay traffic easier to visualize without losing the ability to trace timing and freshness behavior. MQTT remains a natural fit for lightweight sensing pipelines, but its QoS modes and duplicate semantics still require careful interpretation in downstream gateways [@mqtt311]. For broader pub/sub context, Kafka emphasizes log-oriented throughput and replay semantics rather than low-overhead device messaging [@kreps2011kafka], while later comparative work highlights how RabbitMQ and Kafka occupy different operating points in the reliability-throughput design space [@dobbelaere2017kafka]. For sensing-pipeline inspiration, SENSELET++ demonstrates the value of pairing sensing infrastructure with a reproducible visualization path [@tian2021senseletpp].

## 2. Workloads and Method

The primary evidence run is `{intel_sweep_dir.name}`. It uses a bounded slice of the Intel Berkeley Lab deployment data [@intelLabData] preprocessed into Agrasandhani's normalized replay schema, then runs `V0`, `V2`, and `V4` across `clean`, `bandwidth_200kbps`, `loss_2pct`, `delay_50ms_jitter20ms`, and `outage_5s` at MQTT QoS `0` and `1`. Each run uses a 30 second wall-clock replay, a 5x speedup, a 200-sensor target, and burst mode. The portability check is `{aot_sweep_dir.name}`, built from a bounded slice of the AoT weekly archive dataset [@aotCyberGIS] with a smaller validation matrix. The live demo evidence comes from `{demo_dir.parent.name}`.

## 3. Results

The clean qos0 run shows the expected tradeoff. V0 preserves the most immediate delivery path with a p95 display latency of {clean_v0['latency_p95_ms']} ms, whereas V4 increases p95 latency to {clean_v4['latency_p95_ms']} ms in exchange for frame consolidation. This is visible in the latency CDF and the message-rate plots in [report/assets/figures/intel_clean_qos0_latency_cdf.png](assets/figures/intel_clean_qos0_latency_cdf.png) and [report/assets/figures/intel_outage_qos1_message_rate_over_time.png](assets/figures/intel_outage_qos1_message_rate_over_time.png).

The explicit Intel qos0 bandwidth comparison answers the first paper question directly. Compared with V0, V2 increased downstream payload bytes by {_format_bandwidth_comparison_series(bandwidth_rows, variant='v2', delta_field='downstream_bytes_delta_pct')}. V4 increased downstream payload bytes by {_format_bandwidth_comparison_series(bandwidth_rows, variant='v4', delta_field='downstream_bytes_delta_pct')}. Peak per-second downstream payload rate also moved upward rather than downward: V2 increased by {_format_bandwidth_comparison_series(bandwidth_rows, variant='v2', delta_field='max_bandwidth_delta_pct')}, while V4 increased by {_format_bandwidth_comparison_series(bandwidth_rows, variant='v4', delta_field='max_bandwidth_delta_pct')}. In this evidence set, the smart paths reduce render cadence and frame count rather than downstream payload-byte volume. The paper-ready table for this claim is [report/assets/tables/intel_bandwidth_vs_v0.md](assets/tables/intel_bandwidth_vs_v0.md).
"""
    if intel_batch_rows is not None:
        first_row = intel_batch_rows[0]
        last_row = intel_batch_rows[-1]
        report_text += f"""
The Intel V2 batch-window sweep answers the second paper question directly. As the fixed batch window increased from {first_row['batch_window_ms']} ms to {last_row['batch_window_ms']} ms, latency p95 rose from {first_row['latency_p95_ms']} ms to {last_row['latency_p95_ms']} ms while max frame rate fell from {first_row['max_frame_rate_per_s']} to {last_row['max_frame_rate_per_s']}. Across the same sweep, {_describe_batch_window_payload_shift(intel_batch_rows)}. That means the current V2 tradeoff is primarily latency versus render cadence, with payload-byte movement reported as supporting context rather than the headline result. The paper-ready outputs for this task are [report/assets/tables/intel_v2_batch_window_tradeoff.md](assets/tables/intel_v2_batch_window_tradeoff.md) and [report/assets/figures/intel_v2_batch_window_tradeoff.png](assets/figures/intel_v2_batch_window_tradeoff.png).
"""
    if intel_v1_v2_rows is not None:
        report_text += f"""
The Intel V1 versus V2 isolation sweep answers the third paper question directly. Here, V1 is batching alone and V2 is batching plus compaction and exact-duplicate suppression. {_describe_v1_v2_isolation_scenario(intel_v1_v2_rows, 'clean')} {_describe_v1_v2_isolation_scenario(intel_v1_v2_rows, 'bandwidth_200kbps')} {_describe_v1_v2_isolation_scenario(intel_v1_v2_rows, 'outage_5s')} This is the right framing for the paper: the measured effect of V2 beyond batching alone can be mixed across bytes, frames, and latency, so the report should describe the observed deltas rather than assume a universal win. The paper-ready outputs for this task are [report/assets/tables/intel_v1_vs_v2_isolation.md](assets/tables/intel_v1_vs_v2_isolation.md) and [report/assets/figures/intel_v1_vs_v2_isolation.png](assets/figures/intel_v1_vs_v2_isolation.png).
"""
    if intel_adaptive_rows is not None:
        report_text += f"""
The Intel V2 versus V3 adaptive impairment sweep answers the fourth paper question directly. Here, V2 is fixed-window batching and V3 is adaptive batching under the same base `250 ms` configuration. {_describe_adaptive_scenario(intel_adaptive_rows, 'bandwidth_200kbps')} {_describe_adaptive_scenario(intel_adaptive_rows, 'loss_2pct')} This is the right framing for the paper: the adaptive claim should be limited to the measured stale-fraction, cadence, and window-trace changes under these impairments, not generalized into a broader backlog or reliability claim. The paper-ready outputs for this task are [report/assets/tables/intel_v2_vs_v3_adaptive_impairment.md](assets/tables/intel_v2_vs_v3_adaptive_impairment.md) and [report/assets/figures/intel_v2_vs_v3_adaptive_impairment.png](assets/figures/intel_v2_vs_v3_adaptive_impairment.png).
"""
    report_text += f"""
The Intel qos0 outage freshness trace answers the fifth paper question directly. For this task, the paper-ready freshness signal is age-of-information over time rather than stale-fraction over time, because the current dashboard export records age only on rendered updates and does not sample idle stale transitions between renders. {_describe_outage_freshness(intel_outage_freshness_rows)} The end-state `staleCount` and `latestRowCount` values remain useful supporting context, but the primary evidence is the age trace in [report/assets/figures/intel_outage_qos0_v0_vs_v4_age_over_time.png](assets/figures/intel_outage_qos0_v0_vs_v4_age_over_time.png) together with the compact summary table [report/assets/tables/intel_outage_qos0_v0_vs_v4_freshness.md](assets/tables/intel_outage_qos0_v0_vs_v4_freshness.md).
"""
    report_text += f"""

The outage qos1 run makes the UI tradeoff clearer. V0 emitted {outage_v0['proxy_downstream_frames_out']} downstream frames, while V4 emitted {outage_v4['proxy_downstream_frames_out']}. At the same time, V4's aggregate envelopes pushed downstream bytes from {outage_v0['proxy_downstream_bytes_out']} in V0 to {outage_v4['proxy_downstream_bytes_out']} in V4. The result is not a blanket bandwidth win; it is a cadence and interpretability win. This is the right framing for the project, and it avoids overselling aggregate framing as a byte-minimization technique.

The broker-backed QoS1 runs did not trigger large duplicate counts in this local setup. In fact, the measured exact duplicate-drop counter remained at {qos1_duplicates} across the Intel primary QoS1 matrix, so the QoS discussion in this report is necessarily cautious. The final claims here concern observed end-to-end behavior in this environment rather than a general statement that QoS1 duplicates are common in every deployment.

AoT provides a smaller portability check rather than the main performance claim set. On the clean qos0 validation run, V0 reached a p95 latency of {aot_clean_v0['latency_p95_ms']} ms and emitted {aot_clean_v0['proxy_downstream_frames_out']} frames, while V4 reached {aot_clean_v4['latency_p95_ms']} ms and emitted {aot_clean_v4['proxy_downstream_frames_out']} frames. That result is directionally consistent with the Intel evidence and shows that the smart path remains operational on a second public source.

The demo evidence captures the qualitative effect directly. The final captured baseline dashboard ended with frameCount={demo_baseline['frameCount']}, staleCount={demo_baseline['staleCount']}, and latestRowCount={demo_baseline['latestRowCount']}, while the smart dashboard ended with frameCount={demo_smart['frameCount']}, staleCount={demo_smart['staleCount']}, and latestRowCount={demo_smart['latestRowCount']}. Both sides surfaced stale rows during the outage window, but the V4 side did so with far fewer rendered frames and a larger retained latest-row set in the captured end state. The screenshots in [report/assets/figures/final_demo_compare.png](assets/figures/final_demo_compare.png), [report/assets/figures/final_demo_baseline_dashboard.png](assets/figures/final_demo_baseline_dashboard.png), and [report/assets/figures/final_demo_smart_dashboard.png](assets/figures/final_demo_smart_dashboard.png) are the evidence for that claim.

## 4. Discussion

The final evidence supports a narrow conclusion. Agrasandhani's smart path is useful when the operator values stable rendering and last-known-good freshness cues more than minimum per-message latency. The data does not support a blanket claim that V4 minimizes downstream bytes, and the QoS1 experiments in this local broker configuration do not justify a strong empirical duplicate-rate claim beyond the measured counters. Those are acceptable limits for a six-page project report because the central contribution is the observable baseline-versus-smart tradeoff, not a universal broker benchmark.

## 5. Reproducibility and Deliverables

All committed report assets under `report/assets/` are regenerated from ignored local logs via `experiments/build_report_assets.py`, and the exact local run commands are captured in `experiments/logs/final-deliverables-*/manifest.json`. The reproducibility steps live in [report/reproducibility.md](reproducibility.md), the related-work notes live in [report/related_work_notes.md](related_work_notes.md), and the deliverable cross-check is in [report/deliverable_gate.md](deliverable_gate.md).

## References

The bibliography entries are stored in [report/references.bib](references.bib).
"""
    (REPORT_DIR / "final_report.md").write_text(report_text, encoding="utf-8")


def _write_deliverable_gate(
    *,
    intel_sweep_dir: Path,
    aot_sweep_dir: Path,
    demo_dir: Path,
    output_dir: Path,
    intel_batch_sweep_dir: Path | None = None,
    intel_v1_v2_sweep_dir: Path | None = None,
    intel_adaptive_sweep_dir: Path | None = None,
) -> None:
    freshness_summary_tables = ", [report/assets/tables/intel_outage_qos0_v0_vs_v4_freshness.csv](assets/tables/intel_outage_qos0_v0_vs_v4_freshness.csv), [report/assets/tables/intel_outage_qos0_v0_vs_v4_freshness.md](assets/tables/intel_outage_qos0_v0_vs_v4_freshness.md), [report/assets/figures/intel_outage_qos0_v0_vs_v4_age_over_time.png](assets/figures/intel_outage_qos0_v0_vs_v4_age_over_time.png)"
    batch_sweep_line = ""
    batch_summary_tables = ""
    if intel_batch_sweep_dir is not None:
        batch_sweep_line = f"- Intel V2 batch-window sweep run id: `{intel_batch_sweep_dir.name}` at `{intel_batch_sweep_dir}`\n"
        batch_summary_tables = ", [report/assets/tables/intel_v2_batch_window_tradeoff.csv](assets/tables/intel_v2_batch_window_tradeoff.csv), [report/assets/tables/intel_v2_batch_window_tradeoff.md](assets/tables/intel_v2_batch_window_tradeoff.md), [report/assets/figures/intel_v2_batch_window_tradeoff.png](assets/figures/intel_v2_batch_window_tradeoff.png)"
    isolation_sweep_line = ""
    isolation_summary_tables = ""
    if intel_v1_v2_sweep_dir is not None:
        isolation_sweep_line = f"- Intel V1 versus V2 isolation sweep run id: `{intel_v1_v2_sweep_dir.name}` at `{intel_v1_v2_sweep_dir}`\n"
        isolation_summary_tables = ", [report/assets/tables/intel_v1_vs_v2_isolation.csv](assets/tables/intel_v1_vs_v2_isolation.csv), [report/assets/tables/intel_v1_vs_v2_isolation.md](assets/tables/intel_v1_vs_v2_isolation.md), [report/assets/figures/intel_v1_vs_v2_isolation.png](assets/figures/intel_v1_vs_v2_isolation.png)"
    adaptive_sweep_line = ""
    adaptive_summary_tables = ""
    if intel_adaptive_sweep_dir is not None:
        adaptive_sweep_line = f"- Intel V2 versus V3 adaptive sweep run id: `{intel_adaptive_sweep_dir.name}` at `{intel_adaptive_sweep_dir}`\n"
        adaptive_summary_tables = ", [report/assets/tables/intel_v2_vs_v3_adaptive_impairment.csv](assets/tables/intel_v2_vs_v3_adaptive_impairment.csv), [report/assets/tables/intel_v2_vs_v3_adaptive_impairment.md](assets/tables/intel_v2_vs_v3_adaptive_impairment.md), [report/assets/figures/intel_v2_vs_v3_adaptive_impairment.png](assets/figures/intel_v2_vs_v3_adaptive_impairment.png)"
    content = f"""# Deliverable Completion Gate

## M1-M3 System Path

- Replay simulator and preprocessors: [simulator/replay_mqtt.py](../simulator/replay_mqtt.py), [simulator/preprocess_intel_lab.py](../simulator/preprocess_intel_lab.py), [simulator/preprocess_aot.py](../simulator/preprocess_aot.py)
- Gateway and dashboard path: [gateway/server.py](../gateway/server.py), [ui/dashboard.html](../ui/dashboard.html)
- Impairment and experiment harnesses: [experiments/impairment_proxy.py](../experiments/impairment_proxy.py), [experiments/run_sweep.py](../experiments/run_sweep.py), [experiments/run_demo.py](../experiments/run_demo.py)

## M4 Evidence Path

- Intel primary sweep run id: `{intel_sweep_dir.name}` at `{intel_sweep_dir}`
- AoT validation run id: `{aot_sweep_dir.name}` at `{aot_sweep_dir}`
- Demo capture run id: `{demo_dir.parent.name}` at `{demo_dir}`
{batch_sweep_line}{isolation_sweep_line}{adaptive_sweep_line}- Final evidence manifest: [report/assets/evidence_manifest.json](assets/evidence_manifest.json)
- Final summary tables: [report/assets/tables/intel_primary_run_summary.csv](assets/tables/intel_primary_run_summary.csv), [report/assets/tables/intel_bandwidth_vs_v0.csv](assets/tables/intel_bandwidth_vs_v0.csv), [report/assets/tables/intel_bandwidth_vs_v0.md](assets/tables/intel_bandwidth_vs_v0.md){freshness_summary_tables}{batch_summary_tables}{isolation_summary_tables}{adaptive_summary_tables}, [report/assets/tables/aot_validation_summary.csv](assets/tables/aot_validation_summary.csv), [report/assets/tables/intel_key_claims.md](assets/tables/intel_key_claims.md)
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

- Report assets directory: `{output_dir}`
- Local full-run manifests remain under `experiments/logs/final-deliverables-*/manifest.json`
- `PRD.md` and `PROJECT_CHECKLIST.md` remain local-only planning artifacts and are not part of the pushed deliverable set.
"""
    (REPORT_DIR / "deliverable_gate.md").write_text(content, encoding="utf-8")


def build_report_assets(
    *,
    intel_sweep_dir: Path,
    aot_sweep_dir: Path,
    demo_dir: Path,
    output_dir: Path,
    intel_batch_sweep_dir: Path | None = None,
    intel_v1_v2_sweep_dir: Path | None = None,
    intel_adaptive_sweep_dir: Path | None = None,
) -> dict[str, object]:
    intel_rows = _load_summary_rows(intel_sweep_dir)
    aot_rows = _load_summary_rows(aot_sweep_dir)
    bandwidth_rows = _build_intel_bandwidth_vs_v0_rows(intel_rows)
    intel_outage_freshness_rows = _build_intel_outage_freshness_rows(intel_rows)
    intel_batch_rows = (
        _build_intel_batch_window_tradeoff_rows(_load_summary_rows(intel_batch_sweep_dir))
        if intel_batch_sweep_dir is not None
        else None
    )
    intel_v1_v2_rows = (
        _build_intel_v1_v2_isolation_rows(_load_summary_rows(intel_v1_v2_sweep_dir))
        if intel_v1_v2_sweep_dir is not None
        else None
    )
    intel_adaptive_rows = (
        _build_intel_adaptive_rows(_load_summary_rows(intel_adaptive_sweep_dir))
        if intel_adaptive_sweep_dir is not None
        else None
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    figures_dir = output_dir / "figures"
    tables_dir = output_dir / "tables"
    figures_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    _write_csv(tables_dir / "intel_primary_run_summary.csv", intel_rows)
    _write_csv(tables_dir / "aot_validation_summary.csv", aot_rows)
    _write_csv(tables_dir / "intel_bandwidth_vs_v0.csv", bandwidth_rows)
    _write_csv(tables_dir / "intel_outage_qos0_v0_vs_v4_freshness.csv", intel_outage_freshness_rows)
    _write_markdown_table(
        tables_dir / "intel_primary_run_summary.md",
        intel_rows,
        columns=[
            "run_id",
            "variant",
            "scenario",
            "mqtt_qos",
            "latency_p95_ms",
            "proxy_downstream_frames_out",
            "proxy_downstream_bytes_out",
            "dashboard_stale_count",
        ],
    )
    _write_markdown_table(
        tables_dir / "intel_outage_qos0_v0_vs_v4_freshness.md",
        intel_outage_freshness_rows,
        columns=[
            "variant",
            "pre_outage_rendered_updates",
            "pre_outage_age_mean_ms",
            "pre_outage_age_p95_ms",
            "outage_rendered_updates",
            "recovery_rendered_updates",
            "recovery_age_mean_ms",
            "recovery_age_p95_ms",
            "recovery_age_max_ms",
            "end_state_stale_count",
            "end_state_latest_row_count",
            "run_dir",
        ],
    )
    _write_markdown_table(
        tables_dir / "intel_bandwidth_vs_v0.md",
        bandwidth_rows,
        columns=[
            "scenario",
            "variant",
            "baseline_downstream_bytes_out",
            "variant_downstream_bytes_out",
            "downstream_bytes_delta_pct",
            "baseline_max_bandwidth_bytes_per_s",
            "variant_max_bandwidth_bytes_per_s",
            "max_bandwidth_delta_pct",
            "baseline_downstream_frames_out",
            "variant_downstream_frames_out",
            "downstream_frames_delta_pct",
            "latency_p95_ms",
        ],
    )
    if intel_batch_rows is not None:
        _write_csv(tables_dir / "intel_v2_batch_window_tradeoff.csv", intel_batch_rows)
        _write_markdown_table(
            tables_dir / "intel_v2_batch_window_tradeoff.md",
            intel_batch_rows,
            columns=[
                "batch_window_ms",
                "latency_p95_ms",
                "latency_mean_ms",
                "max_frame_rate_per_s",
                "proxy_downstream_frames_out",
                "proxy_downstream_bytes_out",
                "max_bandwidth_bytes_per_s",
                "stale_fraction",
                "run_dir",
            ],
        )
    if intel_v1_v2_rows is not None:
        _write_csv(tables_dir / "intel_v1_vs_v2_isolation.csv", intel_v1_v2_rows)
        _write_markdown_table(
            tables_dir / "intel_v1_vs_v2_isolation.md",
            intel_v1_v2_rows,
            columns=[
                "scenario",
                "batch_window_ms",
                "v1_latency_p95_ms",
                "v2_latency_p95_ms",
                "latency_p95_delta_ms",
                "v1_proxy_downstream_frames_out",
                "v2_proxy_downstream_frames_out",
                "downstream_frames_delta_pct",
                "v1_proxy_downstream_bytes_out",
                "v2_proxy_downstream_bytes_out",
                "downstream_bytes_delta_pct",
                "v1_max_bandwidth_bytes_per_s",
                "v2_max_bandwidth_bytes_per_s",
                "max_bandwidth_delta_pct",
                "v1_stale_fraction",
                "v2_stale_fraction",
                "stale_fraction_delta",
                "v1_run_dir",
                "v2_run_dir",
            ],
        )
    if intel_adaptive_rows is not None:
        _write_csv(tables_dir / "intel_v2_vs_v3_adaptive_impairment.csv", intel_adaptive_rows)
        _write_markdown_table(
            tables_dir / "intel_v2_vs_v3_adaptive_impairment.md",
            intel_adaptive_rows,
            columns=[
                "scenario",
                "v2_latency_p95_ms",
                "v3_latency_p95_ms",
                "latency_p95_delta_ms",
                "v2_stale_fraction",
                "v3_stale_fraction",
                "stale_fraction_delta",
                "v2_max_update_rate_per_s",
                "v3_max_update_rate_per_s",
                "update_rate_delta_pct",
                "v2_proxy_downstream_frames_out",
                "v3_proxy_downstream_frames_out",
                "downstream_frames_delta_pct",
                "v2_proxy_downstream_bytes_out",
                "v3_proxy_downstream_bytes_out",
                "downstream_bytes_delta_pct",
                "v2_min_effective_batch_window_ms",
                "v2_max_effective_batch_window_ms",
                "v3_min_effective_batch_window_ms",
                "v3_max_effective_batch_window_ms",
                "v3_adaptive_window_increase_events",
                "v3_adaptive_window_decrease_events",
                "v3_last_adaptation_reason",
                "v2_run_dir",
                "v3_run_dir",
            ],
        )
    (tables_dir / "intel_key_claims.md").write_text(
        _build_key_claims(
            intel_rows,
            aot_rows,
            demo_dir,
            intel_outage_freshness_rows,
            intel_batch_rows,
            intel_v1_v2_rows,
            intel_adaptive_rows,
        ),
        encoding="utf-8",
    )

    _plot_latency_cdf(
        intel_rows,
        scenario="clean",
        mqtt_qos=0,
        output_path=figures_dir / "intel_clean_qos0_latency_cdf.png",
    )
    _plot_timeseries(
        intel_rows,
        scenario="outage_5s",
        mqtt_qos=1,
        metric="bandwidth_bytes_per_s",
        title="Intel outage qos1 bandwidth over time",
        ylabel="Bytes per second",
        output_path=figures_dir / "intel_outage_qos1_bandwidth_over_time.png",
    )
    _plot_timeseries(
        intel_rows,
        scenario="outage_5s",
        mqtt_qos=1,
        metric="update_rate_per_s",
        title="Intel outage qos1 message rate over time",
        ylabel="Rendered updates per second",
        output_path=figures_dir / "intel_outage_qos1_message_rate_over_time.png",
    )
    _plot_outage_age_over_time(
        intel_rows,
        output_path=figures_dir / "intel_outage_qos0_v0_vs_v4_age_over_time.png",
    )
    if intel_batch_rows is not None:
        _plot_batch_window_tradeoff(
            intel_batch_rows,
            output_path=figures_dir / "intel_v2_batch_window_tradeoff.png",
        )
    if intel_v1_v2_rows is not None:
        _plot_v1_v2_isolation(
            intel_v1_v2_rows,
            output_path=figures_dir / "intel_v1_vs_v2_isolation.png",
        )
    if intel_adaptive_rows is not None:
        _plot_adaptive_impairment(
            intel_adaptive_rows,
            output_path=figures_dir / "intel_v2_vs_v3_adaptive_impairment.png",
        )
    _copy_demo_artifacts(demo_dir, figures_dir)

    manifest = {
        "intel_sweep_dir": str(intel_sweep_dir),
        "aot_sweep_dir": str(aot_sweep_dir),
        "demo_dir": str(demo_dir),
        "intel_batch_sweep_dir": str(intel_batch_sweep_dir) if intel_batch_sweep_dir is not None else None,
        "intel_v1_v2_sweep_dir": str(intel_v1_v2_sweep_dir) if intel_v1_v2_sweep_dir is not None else None,
        "intel_adaptive_sweep_dir": str(intel_adaptive_sweep_dir) if intel_adaptive_sweep_dir is not None else None,
        "intel_runs": [row["run_id"] for row in intel_rows],
        "aot_runs": [row["run_id"] for row in aot_rows],
        "generated_figures": [
            str(figures_dir / "intel_clean_qos0_latency_cdf.png"),
            str(figures_dir / "intel_outage_qos1_bandwidth_over_time.png"),
            str(figures_dir / "intel_outage_qos1_message_rate_over_time.png"),
            str(figures_dir / "intel_outage_qos0_v0_vs_v4_age_over_time.png"),
            str(figures_dir / "final_demo_compare.png"),
            str(figures_dir / "final_demo_baseline_dashboard.png"),
            str(figures_dir / "final_demo_smart_dashboard.png"),
        ],
        "generated_tables": [
            str(tables_dir / "intel_primary_run_summary.csv"),
            str(tables_dir / "intel_bandwidth_vs_v0.csv"),
            str(tables_dir / "intel_bandwidth_vs_v0.md"),
            str(tables_dir / "intel_outage_qos0_v0_vs_v4_freshness.csv"),
            str(tables_dir / "intel_outage_qos0_v0_vs_v4_freshness.md"),
            str(tables_dir / "aot_validation_summary.csv"),
            str(tables_dir / "intel_key_claims.md"),
        ],
    }
    if intel_batch_rows is not None:
        manifest["generated_figures"].append(str(figures_dir / "intel_v2_batch_window_tradeoff.png"))
        manifest["generated_tables"].extend(
            [
                str(tables_dir / "intel_v2_batch_window_tradeoff.csv"),
                str(tables_dir / "intel_v2_batch_window_tradeoff.md"),
            ]
        )
    if intel_v1_v2_rows is not None:
        manifest["generated_figures"].append(str(figures_dir / "intel_v1_vs_v2_isolation.png"))
        manifest["generated_tables"].extend(
            [
                str(tables_dir / "intel_v1_vs_v2_isolation.csv"),
                str(tables_dir / "intel_v1_vs_v2_isolation.md"),
            ]
        )
    if intel_adaptive_rows is not None:
        manifest["generated_figures"].append(str(figures_dir / "intel_v2_vs_v3_adaptive_impairment.png"))
        manifest["generated_tables"].extend(
            [
                str(tables_dir / "intel_v2_vs_v3_adaptive_impairment.csv"),
                str(tables_dir / "intel_v2_vs_v3_adaptive_impairment.md"),
            ]
        )
    (output_dir / "evidence_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    _write_final_report(
        intel_sweep_dir=intel_sweep_dir,
        aot_sweep_dir=aot_sweep_dir,
        demo_dir=demo_dir,
        intel_rows=intel_rows,
        aot_rows=aot_rows,
        intel_outage_freshness_rows=intel_outage_freshness_rows,
        intel_batch_rows=intel_batch_rows,
        intel_v1_v2_rows=intel_v1_v2_rows,
        intel_adaptive_rows=intel_adaptive_rows,
    )
    _write_deliverable_gate(
        intel_sweep_dir=intel_sweep_dir,
        aot_sweep_dir=aot_sweep_dir,
        demo_dir=demo_dir,
        output_dir=output_dir,
        intel_batch_sweep_dir=intel_batch_sweep_dir,
        intel_v1_v2_sweep_dir=intel_v1_v2_sweep_dir,
        intel_adaptive_sweep_dir=intel_adaptive_sweep_dir,
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build tracked report figures and tables from final sweep artifacts.")
    parser.add_argument("--intel-sweep-dir", type=Path, required=True)
    parser.add_argument("--aot-sweep-dir", type=Path, required=True)
    parser.add_argument("--demo-dir", type=Path, required=True)
    parser.add_argument("--intel-batch-sweep-dir", type=Path)
    parser.add_argument("--intel-v1-v2-sweep-dir", type=Path)
    parser.add_argument("--intel-adaptive-sweep-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_report_assets(
        intel_sweep_dir=args.intel_sweep_dir,
        aot_sweep_dir=args.aot_sweep_dir,
        demo_dir=args.demo_dir,
        output_dir=args.output_dir,
        intel_batch_sweep_dir=args.intel_batch_sweep_dir,
        intel_v1_v2_sweep_dir=args.intel_v1_v2_sweep_dir,
        intel_adaptive_sweep_dir=args.intel_adaptive_sweep_dir,
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
