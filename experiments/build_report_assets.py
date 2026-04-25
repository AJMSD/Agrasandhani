from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
from pathlib import Path
from statistics import mean

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from experiments.analyze_run import collect_proxy_inter_frame_gaps, collect_run_summary
from experiments.sweep_aggregation import (
    CONDITION_AGGREGATES_FILENAME,
    aggregate_summary_rows,
    load_summary_rows,
)

BASE_DIR = Path(__file__).resolve().parent.parent
REPORT_DIR = BASE_DIR / "report"
SCENARIOS_DIR = BASE_DIR / "experiments" / "scenarios"
INTEL_PRIMARY_SCENARIOS = ("clean", "bandwidth_200kbps", "loss_2pct", "delay_50ms_jitter20ms", "outage_5s")
INTEL_BANDWIDTH_SCENARIOS = ("clean", "bandwidth_200kbps", "loss_2pct", "outage_5s")
INTEL_BATCH_WINDOW_SWEEP_WINDOWS = (50, 100, 250, 500, 1000)
INTEL_V1_V2_ISOLATION_SCENARIOS = ("clean", "bandwidth_200kbps", "outage_5s")
INTEL_V1_V2_ISOLATION_WINDOWS = (50, 100, 250, 500, 1000)
INTEL_ADAPTIVE_SCENARIOS = ("bandwidth_200kbps", "loss_2pct", "delay_50ms_jitter20ms")
OUTAGE_SCENARIO = "outage_5s"
PAPER_MAIN_VARIANTS = ("v0", "v2", "v4")
BYTE_CLAIM_FALLBACK_WORDING = "Agrasandhani reduced downstream frame cadence and message burstiness, not payload bytes, in this setup."
ADAPTIVE_CLAIM_FALLBACK_WORDING = "Under the tested thresholds, adaptive control did not materially outperform fixed-window batching."


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


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


def _normalized_phase_name(scenario: str) -> str:
    if scenario == "clean":
        return "steady-state"
    return "impairment-window"


def _scenario_phase_windows(scenario: str, *, total_duration_s: float | None = None) -> list[tuple[str, float, float | None]]:
    scenario_path = SCENARIOS_DIR / f"{scenario}.json"
    if scenario_path.exists():
        payload = _load_json(scenario_path)
        raw_phases = payload.get("phases", []) if isinstance(payload, dict) else []
        if isinstance(raw_phases, list) and raw_phases:
            if len(raw_phases) == 1:
                phase = raw_phases[0]
                duration_s = phase.get("duration_s")
                if duration_s is None:
                    duration_s = total_duration_s
                return [(_normalized_phase_name(scenario), 0.0, float(duration_s) if duration_s is not None else None)]
            windows: list[tuple[str, float, float | None]] = []
            phase_start_s = 0.0
            for index, phase in enumerate(raw_phases):
                phase_name = str(phase.get("name", f"phase-{index + 1}"))
                duration_s = phase.get("duration_s")
                phase_end_s = None if duration_s is None else phase_start_s + float(duration_s)
                if index == len(raw_phases) - 1 and total_duration_s is not None:
                    phase_end_s = total_duration_s
                windows.append((phase_name, phase_start_s, phase_end_s))
                if phase_end_s is None:
                    break
                phase_start_s = phase_end_s
            return windows

    return [(_normalized_phase_name(scenario), 0.0, total_duration_s)]


def _phase_for_second(relative_second: float, phase_windows: list[tuple[str, float, float | None]]) -> str:
    for phase_name, start_s, end_s in phase_windows:
        if end_s is None and relative_second >= start_s:
            return phase_name
        if end_s is not None and start_s <= relative_second < end_s:
            return phase_name
    if not phase_windows:
        return "analysis-window"
    return phase_windows[-1][0]


def _phase_color(phase_name: str) -> str:
    if phase_name in {"steady-state", "steady-before-outage"}:
        return "#d9edf7"
    if phase_name in {"impairment-window", "outage"}:
        return "#f2dede"
    if phase_name == "recovery":
        return "#dff0d8"
    return "#ececec"


def _shade_phase_windows(
    axis: plt.Axes,
    *,
    phase_windows: list[tuple[str, float, float | None]],
    phase_end_s: float,
) -> None:
    for phase_name, start_s, end_s in phase_windows:
        clipped_end_s = phase_end_s if end_s is None else min(end_s, phase_end_s)
        if clipped_end_s <= start_s:
            continue
        axis.axvspan(start_s, clipped_end_s, color=_phase_color(phase_name), alpha=0.2)
    for _, _, end_s in phase_windows[:-1]:
        if end_s is None or end_s >= phase_end_s:
            continue
        axis.axvline(end_s, color="0.4", linestyle="--", linewidth=1)


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
    phase_windows = _scenario_phase_windows(OUTAGE_SCENARIO)
    for variant in ("v0", "v4"):
        row = _select_row(intel_rows, variant=variant, scenario="outage_5s", mqtt_qos=0)
        run_dir = Path(str(row["run_dir"]))
        measurement_rows = _load_measurement_rows(run_dir)
        anchor_ms = _load_proxy_anchor_ms(run_dir)
        relative_seconds = _relative_second_values(measurement_rows, time_field="ts_displayed_ms", anchor_ms=anchor_ms)
        phase_ages: dict[str, list[float]] = {phase_name: [] for phase_name, _, _ in phase_windows}
        phase_counts: dict[str, int] = {phase_name: 0 for phase_name, _, _ in phase_windows}
        for measurement_row, relative_second in zip(measurement_rows, relative_seconds, strict=False):
            phase_name = _phase_for_second(relative_second, phase_windows)
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


def _jitter_summary_row(
    summary_row: dict[str, object],
    *,
    source_sweep: str,
    comparison_family: str,
) -> dict[str, object]:
    run_dir = Path(str(summary_row["run_dir"]))
    derived_summary = summary_row if int(summary_row.get("n", 1) or 1) > 1 else collect_run_summary(run_dir)
    effective_batch_window_ms = int(derived_summary.get("effective_batch_window_ms") or summary_row.get("effective_batch_window_ms", 0))
    max_frame_rate_per_s = int(derived_summary.get("max_frame_rate_per_s") or summary_row.get("max_frame_rate_per_s", 0))
    return {
        "source_sweep": source_sweep,
        "comparison_family": comparison_family,
        "variant": str(summary_row.get("variant", derived_summary.get("variant", ""))),
        "scenario": str(summary_row.get("scenario", derived_summary.get("scenario", ""))),
        "mqtt_qos": int(summary_row.get("mqtt_qos", derived_summary.get("mqtt_qos", 0)) or 0),
        "proxy_inter_frame_gap_sample_count": int(derived_summary.get("proxy_inter_frame_gap_sample_count", 0)),
        "proxy_inter_frame_gap_mean_ms": float(derived_summary.get("proxy_inter_frame_gap_mean_ms", 0.0)),
        "proxy_inter_frame_gap_p50_ms": float(derived_summary.get("proxy_inter_frame_gap_p50_ms", 0.0)),
        "proxy_inter_frame_gap_p95_ms": float(derived_summary.get("proxy_inter_frame_gap_p95_ms", 0.0)),
        "proxy_inter_frame_gap_p99_ms": float(derived_summary.get("proxy_inter_frame_gap_p99_ms", 0.0)),
        "proxy_inter_frame_gap_stddev_ms": float(derived_summary.get("proxy_inter_frame_gap_stddev_ms", 0.0)),
        "proxy_frame_rate_stddev_per_s": float(derived_summary.get("proxy_frame_rate_stddev_per_s", 0.0)),
        "effective_batch_window_ms": effective_batch_window_ms,
        "max_frame_rate_per_s": max_frame_rate_per_s,
        "run_dir": str(run_dir),
    }


def _build_intel_jitter_summary_rows(
    intel_rows: list[dict[str, object]],
    *,
    intel_sweep_dir: Path,
    adaptive_rows: list[dict[str, object]] | None = None,
    adaptive_sweep_dir: Path | None = None,
) -> list[dict[str, object]]:
    rows = [
        _jitter_summary_row(
            row,
            source_sweep=intel_sweep_dir.name,
            comparison_family="intel_primary",
        )
        for row in _run_rows(
            intel_rows,
            variants=PAPER_MAIN_VARIANTS,
            scenarios=INTEL_PRIMARY_SCENARIOS,
            qos_values=(0, 1),
        )
    ]
    if adaptive_rows is not None and adaptive_sweep_dir is not None:
        rows.extend(
            _jitter_summary_row(
                row,
                source_sweep=adaptive_sweep_dir.name,
                comparison_family="intel_adaptive_v2_vs_v3",
            )
            for row in _run_rows(
                adaptive_rows,
                variants=("v2", "v3"),
                scenarios=INTEL_ADAPTIVE_SCENARIOS,
                qos_values=(0,),
            )
        )
    rows.sort(
        key=lambda row: (
            str(row["comparison_family"]),
            str(row["scenario"]),
            int(row["mqtt_qos"]),
            str(row["variant"]),
        )
    )
    return rows


def _canonical_report_asset_path(*parts: str) -> str:
    return "/".join(("report", "assets", *parts))


def _canonical_logs_path(*parts: str) -> str:
    return "/".join(("experiments", "logs", *parts))


def _source_path(path: Path) -> str:
    try:
        return path.relative_to(BASE_DIR).as_posix()
    except ValueError:
        return path.as_posix()


def _aggregate_artifacts(*sweep_dirs: Path | None) -> list[str]:
    artifacts: list[str] = []
    seen: set[str] = set()
    for sweep_dir in sweep_dirs:
        if sweep_dir is None:
            continue
        artifact = _source_path(sweep_dir / CONDITION_AGGREGATES_FILENAME)
        if artifact in seen:
            continue
        seen.add(artifact)
        artifacts.append(artifact)
    return artifacts


def _run_rows(
    rows: list[dict[str, object]],
    *,
    variants: tuple[str, ...] | None = None,
    scenarios: tuple[str, ...] | None = None,
    qos_values: tuple[int, ...] | None = None,
) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    for row in rows:
        if variants is not None and str(row["variant"]) not in variants:
            continue
        if scenarios is not None and str(row["scenario"]) not in scenarios:
            continue
        if qos_values is not None and int(row["mqtt_qos"]) not in qos_values:
            continue
        selected.append(row)
    return sorted(selected, key=lambda candidate: str(candidate["run_id"]))


def _run_ids(rows: list[dict[str, object]]) -> list[str]:
    run_ids: set[str] = set()
    for row in rows:
        trial_run_ids = row.get("trial_run_ids")
        if isinstance(trial_run_ids, list) and trial_run_ids:
            run_ids.update(str(run_id) for run_id in trial_run_ids)
            continue
        if "run_id" in row:
            run_ids.add(str(row["run_id"]))
            continue
        if "run_dir" in row:
            run_ids.add(Path(str(row["run_dir"])).name)
    return sorted(run_ids)


def _summary_artifacts(rows: list[dict[str, object]]) -> list[str]:
    artifacts: set[str] = set()
    for row in rows:
        trial_summary_paths = row.get("trial_summary_paths")
        if isinstance(trial_summary_paths, list) and trial_summary_paths:
            artifacts.update(_source_path(Path(str(path))) for path in trial_summary_paths)
            continue
        artifacts.add(_source_path(Path(str(row["run_dir"])) / "summary.json"))
    return sorted(artifacts)


def _run_file_artifacts(rows: list[dict[str, object]], *filenames: str) -> list[str]:
    artifacts: set[str] = set()
    for row in rows:
        trial_run_dirs = row.get("trial_run_dirs")
        run_dirs = trial_run_dirs if isinstance(trial_run_dirs, list) and trial_run_dirs else [row["run_dir"]]
        for run_dir in run_dirs:
            resolved_run_dir = Path(str(run_dir))
            for filename in filenames:
                artifacts.add(_source_path(resolved_run_dir / filename))
    return sorted(artifacts)


def _inventory_entry(
    *,
    asset_path: str,
    asset_kind: str,
    source_sweep_ids: list[str],
    source_artifacts: list[str],
    source_run_ids: list[str] | None = None,
    aggregate_input_artifacts: list[str] | None = None,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "asset_path": asset_path,
        "asset_kind": asset_kind,
        "source_sweep_ids": source_sweep_ids,
        "source_artifacts": source_artifacts,
        "aggregate_input_artifacts": aggregate_input_artifacts or [],
        "generation_script": "experiments/build_report_assets.py",
    }
    if source_run_ids is not None:
        entry["source_run_ids"] = source_run_ids
    return entry


def _build_old_evidence_inventory(
    *,
    intel_sweep_dir: Path,
    aot_sweep_dir: Path,
    demo_dir: Path,
    intel_batch_sweep_dir: Path | None = None,
    intel_v1_v2_sweep_dir: Path | None = None,
    intel_adaptive_sweep_dir: Path | None = None,
    intel_adaptive_parameter_sweep_dir: Path | None = None,
    intel_rows: list[dict[str, object]],
    aot_rows: list[dict[str, object]],
    intel_batch_rows: list[dict[str, object]] | None = None,
    intel_v1_v2_rows: list[dict[str, object]] | None = None,
    intel_adaptive_rows: list[dict[str, object]] | None = None,
    intel_adaptive_parameter_rows: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    intel_qos0_rows = _run_rows(
        intel_rows,
        variants=PAPER_MAIN_VARIANTS,
        scenarios=INTEL_BANDWIDTH_SCENARIOS,
        qos_values=(0,),
    )
    intel_qos_pair_rows = _run_rows(
        intel_rows,
        variants=PAPER_MAIN_VARIANTS,
        scenarios=INTEL_BANDWIDTH_SCENARIOS,
        qos_values=(0, 1),
    )
    intel_clean_qos0_rows = _run_rows(
        intel_rows,
        variants=PAPER_MAIN_VARIANTS,
        scenarios=("clean",),
        qos_values=(0,),
    )
    intel_outage_qos1_rows = _run_rows(
        intel_rows,
        variants=PAPER_MAIN_VARIANTS,
        scenarios=("outage_5s",),
        qos_values=(1,),
    )
    intel_outage_v0_v4_rows = _run_rows(
        intel_rows,
        variants=("v0", "v4"),
        scenarios=("outage_5s",),
        qos_values=(0,),
    )
    intel_outage_main_rows = _run_rows(
        intel_rows,
        variants=PAPER_MAIN_VARIANTS,
        scenarios=("outage_5s",),
        qos_values=(0,),
    )
    intel_primary_jitter_rows = _run_rows(
        intel_rows,
        variants=PAPER_MAIN_VARIANTS,
        scenarios=INTEL_PRIMARY_SCENARIOS,
        qos_values=(0, 1),
    )
    intel_delay_qos0_rows = _run_rows(
        intel_rows,
        variants=PAPER_MAIN_VARIANTS,
        scenarios=("delay_50ms_jitter20ms",),
        qos_values=(0,),
    )
    key_claim_rows = sorted(intel_rows + aot_rows, key=lambda candidate: str(candidate["run_id"]))
    jitter_source_sweep_ids = [intel_sweep_dir.name]
    jitter_source_run_ids = set(_run_ids(intel_primary_jitter_rows))
    jitter_source_artifacts = set(
        _run_file_artifacts(
            intel_primary_jitter_rows,
            "proxy_frame_log.csv",
            "gateway_metrics.json",
        )
    )
    if intel_adaptive_rows is not None:
        jitter_source_sweep_ids.extend(_comparison_source_sweep_ids(intel_adaptive_rows, "v2", "v3"))
        jitter_source_run_ids |= set(_comparison_source_run_ids(intel_adaptive_rows, "v2", "v3"))
        jitter_source_artifacts |= set(
            _comparison_source_artifacts(
                intel_adaptive_rows,
                prefixes=("v2", "v3"),
                filenames=("proxy_frame_log.csv", "gateway_metrics.json"),
            )
        )
    key_claim_source_sweep_ids = {intel_sweep_dir.name, aot_sweep_dir.name, demo_dir.parent.name}
    key_claim_source_run_ids = set(_run_ids(key_claim_rows))
    key_claim_source_artifacts = set(_summary_artifacts(key_claim_rows)) | {
        _source_path(demo_dir / "baseline_dashboard" / "dashboard_summary.json"),
        _source_path(demo_dir / "smart_dashboard" / "dashboard_summary.json"),
    }
    guardrail_source_sweep_ids = {intel_sweep_dir.name}
    guardrail_source_run_ids = set(_run_ids(intel_rows))
    guardrail_source_artifacts = set(_summary_artifacts(intel_rows)) | set(
        _run_file_artifacts(
            intel_outage_v0_v4_rows,
            "dashboard_measurements.csv",
            "dashboard_summary.json",
            "proxy_frame_log.csv",
        )
    )
    if intel_adaptive_rows is not None:
        adaptive_sweep_ids = set(_comparison_source_sweep_ids(intel_adaptive_rows, "v2", "v3"))
        adaptive_run_ids = set(_comparison_source_run_ids(intel_adaptive_rows, "v2", "v3"))
        adaptive_artifacts = set(
            _comparison_source_artifacts(
                intel_adaptive_rows,
                prefixes=("v2", "v3"),
                filenames=("summary.json", "gateway_forward_log.csv", "timeseries.csv", "gateway_metrics.json"),
            )
        )
        key_claim_source_sweep_ids |= adaptive_sweep_ids
        key_claim_source_run_ids |= adaptive_run_ids
        key_claim_source_artifacts |= adaptive_artifacts
        guardrail_source_sweep_ids |= adaptive_sweep_ids
        guardrail_source_run_ids |= adaptive_run_ids
        guardrail_source_artifacts |= adaptive_artifacts
    if intel_adaptive_parameter_rows is not None:
        adaptive_parameter_sweep_ids = set(
            _comparison_source_sweep_ids(intel_adaptive_parameter_rows, "baseline_v2", "v3")
        )
        adaptive_parameter_run_ids = set(
            _comparison_source_run_ids(intel_adaptive_parameter_rows, "baseline_v2", "v3")
        )
        adaptive_parameter_artifacts = set(
            _comparison_source_artifacts(
                intel_adaptive_parameter_rows,
                prefixes=("baseline_v2", "v3"),
                filenames=("summary.json", "gateway_forward_log.csv", "timeseries.csv", "gateway_metrics.json"),
            )
        )
        key_claim_source_sweep_ids |= adaptive_parameter_sweep_ids
        key_claim_source_run_ids |= adaptive_parameter_run_ids
        key_claim_source_artifacts |= adaptive_parameter_artifacts
        guardrail_source_sweep_ids |= adaptive_parameter_sweep_ids
        guardrail_source_run_ids |= adaptive_parameter_run_ids
        guardrail_source_artifacts |= adaptive_parameter_artifacts

    intel_aggregate_inputs = _aggregate_artifacts(intel_sweep_dir)
    aot_aggregate_inputs = _aggregate_artifacts(aot_sweep_dir)
    batch_aggregate_inputs = _aggregate_artifacts(intel_batch_sweep_dir)
    isolation_aggregate_inputs = _aggregate_artifacts(intel_v1_v2_sweep_dir)
    adaptive_aggregate_inputs = _aggregate_artifacts(intel_adaptive_sweep_dir)
    adaptive_parameter_aggregate_inputs = _aggregate_artifacts(intel_adaptive_parameter_sweep_dir)
    jitter_aggregate_inputs = _aggregate_artifacts(intel_sweep_dir, intel_adaptive_sweep_dir)
    key_claim_aggregate_inputs = set(_aggregate_artifacts(intel_sweep_dir, aot_sweep_dir))
    guardrail_aggregate_inputs = set(_aggregate_artifacts(intel_sweep_dir))
    if intel_adaptive_rows is not None:
        key_claim_aggregate_inputs |= set(adaptive_aggregate_inputs)
        guardrail_aggregate_inputs |= set(adaptive_aggregate_inputs)
    if intel_adaptive_parameter_rows is not None:
        key_claim_aggregate_inputs |= set(adaptive_parameter_aggregate_inputs)
        guardrail_aggregate_inputs |= set(adaptive_parameter_aggregate_inputs)

    entries = [
        _inventory_entry(
            asset_path=_canonical_report_asset_path("figures", "intel_clean_qos0_latency_cdf.png"),
            asset_kind="figure",
            source_sweep_ids=[intel_sweep_dir.name],
            source_run_ids=_run_ids(intel_clean_qos0_rows),
            source_artifacts=_run_file_artifacts(intel_clean_qos0_rows, "dashboard_measurements.csv"),
            aggregate_input_artifacts=intel_aggregate_inputs,
        ),
        _inventory_entry(
            asset_path=_canonical_report_asset_path("figures", "intel_outage_qos1_bandwidth_over_time.png"),
            asset_kind="figure",
            source_sweep_ids=[intel_sweep_dir.name],
            source_run_ids=_run_ids(intel_outage_qos1_rows),
            source_artifacts=_run_file_artifacts(intel_outage_qos1_rows, "timeseries.csv"),
            aggregate_input_artifacts=intel_aggregate_inputs,
        ),
        _inventory_entry(
            asset_path=_canonical_report_asset_path("figures", "intel_outage_qos1_message_rate_over_time.png"),
            asset_kind="figure",
            source_sweep_ids=[intel_sweep_dir.name],
            source_run_ids=_run_ids(intel_outage_qos1_rows),
            source_artifacts=_run_file_artifacts(intel_outage_qos1_rows, "timeseries.csv"),
            aggregate_input_artifacts=intel_aggregate_inputs,
        ),
        _inventory_entry(
            asset_path=_canonical_report_asset_path("figures", "intel_outage_qos0_v0_vs_v4_age_over_time.png"),
            asset_kind="figure",
            source_sweep_ids=[intel_sweep_dir.name],
            source_run_ids=_run_ids(intel_outage_v0_v4_rows),
            source_artifacts=_run_file_artifacts(
                intel_outage_v0_v4_rows,
                "dashboard_measurements.csv",
                "proxy_frame_log.csv",
            ),
            aggregate_input_artifacts=intel_aggregate_inputs,
        ),
        _inventory_entry(
            asset_path=_canonical_report_asset_path("figures", "main_outage_frame_rate.png"),
            asset_kind="figure",
            source_sweep_ids=[intel_sweep_dir.name],
            source_run_ids=_run_ids(intel_outage_main_rows),
            source_artifacts=_run_file_artifacts(intel_outage_main_rows, "timeseries.csv"),
            aggregate_input_artifacts=intel_aggregate_inputs,
        ),
        _inventory_entry(
            asset_path=_canonical_report_asset_path("figures", "intel_delay_qos0_inter_frame_gap_cdf.png"),
            asset_kind="figure",
            source_sweep_ids=[intel_sweep_dir.name],
            source_run_ids=_run_ids(intel_delay_qos0_rows),
            source_artifacts=_run_file_artifacts(
                intel_delay_qos0_rows,
                "proxy_frame_log.csv",
            ),
            aggregate_input_artifacts=intel_aggregate_inputs,
        ),
        _inventory_entry(
            asset_path=_canonical_report_asset_path("figures", "intel_qos_comparison.png"),
            asset_kind="figure",
            source_sweep_ids=[intel_sweep_dir.name],
            source_run_ids=_run_ids(intel_qos_pair_rows),
            source_artifacts=_summary_artifacts(intel_qos_pair_rows),
            aggregate_input_artifacts=intel_aggregate_inputs,
        ),
        _inventory_entry(
            asset_path=_canonical_report_asset_path("figures", "final_demo_compare.png"),
            asset_kind="figure",
            source_sweep_ids=[demo_dir.parent.name],
            source_artifacts=[_source_path(demo_dir / "demo_compare.png")],
            aggregate_input_artifacts=[],
        ),
        _inventory_entry(
            asset_path=_canonical_report_asset_path("figures", "final_demo_baseline_dashboard.png"),
            asset_kind="figure",
            source_sweep_ids=[demo_dir.parent.name],
            source_artifacts=[_source_path(demo_dir / "baseline_dashboard" / "dashboard.png")],
            aggregate_input_artifacts=[],
        ),
        _inventory_entry(
            asset_path=_canonical_report_asset_path("figures", "final_demo_smart_dashboard.png"),
            asset_kind="figure",
            source_sweep_ids=[demo_dir.parent.name],
            source_artifacts=[_source_path(demo_dir / "smart_dashboard" / "dashboard.png")],
            aggregate_input_artifacts=[],
        ),
        _inventory_entry(
            asset_path=_canonical_report_asset_path("tables", "intel_primary_run_summary.csv"),
            asset_kind="table",
            source_sweep_ids=[intel_sweep_dir.name],
            source_run_ids=_run_ids(intel_rows),
            source_artifacts=_summary_artifacts(intel_rows),
            aggregate_input_artifacts=intel_aggregate_inputs,
        ),
        _inventory_entry(
            asset_path=_canonical_report_asset_path("tables", "intel_primary_run_summary.md"),
            asset_kind="table",
            source_sweep_ids=[intel_sweep_dir.name],
            source_run_ids=_run_ids(intel_rows),
            source_artifacts=_summary_artifacts(intel_rows),
            aggregate_input_artifacts=intel_aggregate_inputs,
        ),
        _inventory_entry(
            asset_path=_canonical_report_asset_path("tables", "intel_bandwidth_vs_v0.csv"),
            asset_kind="table",
            source_sweep_ids=[intel_sweep_dir.name],
            source_run_ids=_run_ids(intel_qos0_rows),
            source_artifacts=_summary_artifacts(intel_qos0_rows),
            aggregate_input_artifacts=intel_aggregate_inputs,
        ),
        _inventory_entry(
            asset_path=_canonical_report_asset_path("tables", "intel_bandwidth_vs_v0.md"),
            asset_kind="table",
            source_sweep_ids=[intel_sweep_dir.name],
            source_run_ids=_run_ids(intel_qos0_rows),
            source_artifacts=_summary_artifacts(intel_qos0_rows),
            aggregate_input_artifacts=intel_aggregate_inputs,
        ),
        _inventory_entry(
            asset_path=_canonical_report_asset_path("tables", "intel_qos_comparison.csv"),
            asset_kind="table",
            source_sweep_ids=[intel_sweep_dir.name],
            source_run_ids=_run_ids(intel_qos_pair_rows),
            source_artifacts=_summary_artifacts(intel_qos_pair_rows),
            aggregate_input_artifacts=intel_aggregate_inputs,
        ),
        _inventory_entry(
            asset_path=_canonical_report_asset_path("tables", "intel_qos_comparison.md"),
            asset_kind="table",
            source_sweep_ids=[intel_sweep_dir.name],
            source_run_ids=_run_ids(intel_qos_pair_rows),
            source_artifacts=_summary_artifacts(intel_qos_pair_rows),
            aggregate_input_artifacts=intel_aggregate_inputs,
        ),
        _inventory_entry(
            asset_path=_canonical_report_asset_path("tables", "intel_condensed_summary.csv"),
            asset_kind="table",
            source_sweep_ids=[intel_sweep_dir.name],
            source_run_ids=_run_ids(intel_qos0_rows),
            source_artifacts=_summary_artifacts(intel_qos0_rows),
            aggregate_input_artifacts=intel_aggregate_inputs,
        ),
        _inventory_entry(
            asset_path=_canonical_report_asset_path("tables", "intel_condensed_summary.md"),
            asset_kind="table",
            source_sweep_ids=[intel_sweep_dir.name],
            source_run_ids=_run_ids(intel_qos0_rows),
            source_artifacts=_summary_artifacts(intel_qos0_rows),
            aggregate_input_artifacts=intel_aggregate_inputs,
        ),
        _inventory_entry(
            asset_path=_canonical_report_asset_path("tables", "intel_main_summary_table.csv"),
            asset_kind="table",
            source_sweep_ids=[intel_sweep_dir.name],
            source_run_ids=_run_ids(intel_qos0_rows),
            source_artifacts=_summary_artifacts(intel_qos0_rows),
            aggregate_input_artifacts=intel_aggregate_inputs,
        ),
        _inventory_entry(
            asset_path=_canonical_report_asset_path("tables", "intel_main_summary_table.md"),
            asset_kind="table",
            source_sweep_ids=[intel_sweep_dir.name],
            source_run_ids=_run_ids(intel_qos0_rows),
            source_artifacts=_summary_artifacts(intel_qos0_rows),
            aggregate_input_artifacts=intel_aggregate_inputs,
        ),
        _inventory_entry(
            asset_path=_canonical_report_asset_path("tables", "intel_outage_qos0_v0_vs_v4_freshness.csv"),
            asset_kind="table",
            source_sweep_ids=[intel_sweep_dir.name],
            source_run_ids=_run_ids(intel_outage_v0_v4_rows),
            source_artifacts=_run_file_artifacts(
                intel_outage_v0_v4_rows,
                "dashboard_measurements.csv",
                "dashboard_summary.json",
                "proxy_frame_log.csv",
            ),
            aggregate_input_artifacts=intel_aggregate_inputs,
        ),
        _inventory_entry(
            asset_path=_canonical_report_asset_path("tables", "intel_outage_qos0_v0_vs_v4_freshness.md"),
            asset_kind="table",
            source_sweep_ids=[intel_sweep_dir.name],
            source_run_ids=_run_ids(intel_outage_v0_v4_rows),
            source_artifacts=_run_file_artifacts(
                intel_outage_v0_v4_rows,
                "dashboard_measurements.csv",
                "dashboard_summary.json",
                "proxy_frame_log.csv",
            ),
            aggregate_input_artifacts=intel_aggregate_inputs,
        ),
        _inventory_entry(
            asset_path=_canonical_report_asset_path("tables", "intel_jitter_summary.csv"),
            asset_kind="table",
            source_sweep_ids=sorted(jitter_source_sweep_ids),
            source_run_ids=sorted(jitter_source_run_ids),
            source_artifacts=sorted(jitter_source_artifacts),
            aggregate_input_artifacts=jitter_aggregate_inputs,
        ),
        _inventory_entry(
            asset_path=_canonical_report_asset_path("tables", "intel_jitter_summary.md"),
            asset_kind="table",
            source_sweep_ids=sorted(jitter_source_sweep_ids),
            source_run_ids=sorted(jitter_source_run_ids),
            source_artifacts=sorted(jitter_source_artifacts),
            aggregate_input_artifacts=jitter_aggregate_inputs,
        ),
        _inventory_entry(
            asset_path=_canonical_report_asset_path("tables", "aot_validation_summary.csv"),
            asset_kind="table",
            source_sweep_ids=[aot_sweep_dir.name],
            source_run_ids=_run_ids(aot_rows),
            source_artifacts=_summary_artifacts(aot_rows),
            aggregate_input_artifacts=aot_aggregate_inputs,
        ),
        _inventory_entry(
            asset_path=_canonical_report_asset_path("tables", "intel_key_claims.md"),
            asset_kind="table",
            source_sweep_ids=sorted(key_claim_source_sweep_ids),
            source_run_ids=sorted(key_claim_source_run_ids),
            source_artifacts=sorted(key_claim_source_artifacts),
            aggregate_input_artifacts=sorted(key_claim_aggregate_inputs),
        ),
        _inventory_entry(
            asset_path=_canonical_report_asset_path("tables", "intel_claim_guardrail_review.md"),
            asset_kind="table",
            source_sweep_ids=sorted(guardrail_source_sweep_ids),
            source_run_ids=sorted(guardrail_source_run_ids),
            source_artifacts=sorted(guardrail_source_artifacts),
            aggregate_input_artifacts=sorted(guardrail_aggregate_inputs),
        ),
    ]

    if intel_batch_rows is not None:
        entries.extend(
            [
                _inventory_entry(
                    asset_path=_canonical_report_asset_path("figures", "intel_v2_batch_window_tradeoff.png"),
                    asset_kind="figure",
                    source_sweep_ids=[_summary_row_sweep_name(intel_batch_rows[0])],
                    source_run_ids=_run_ids(intel_batch_rows),
                    source_artifacts=_summary_artifacts(intel_batch_rows),
                    aggregate_input_artifacts=batch_aggregate_inputs,
                ),
                _inventory_entry(
                    asset_path=_canonical_report_asset_path("tables", "intel_v2_batch_window_tradeoff.csv"),
                    asset_kind="table",
                    source_sweep_ids=[_summary_row_sweep_name(intel_batch_rows[0])],
                    source_run_ids=_run_ids(intel_batch_rows),
                    source_artifacts=_summary_artifacts(intel_batch_rows),
                    aggregate_input_artifacts=batch_aggregate_inputs,
                ),
                _inventory_entry(
                    asset_path=_canonical_report_asset_path("tables", "intel_v2_batch_window_tradeoff.md"),
                    asset_kind="table",
                    source_sweep_ids=[_summary_row_sweep_name(intel_batch_rows[0])],
                    source_run_ids=_run_ids(intel_batch_rows),
                    source_artifacts=_summary_artifacts(intel_batch_rows),
                    aggregate_input_artifacts=batch_aggregate_inputs,
                ),
            ]
        )
    if intel_v1_v2_rows is not None:
        entries.extend(
            [
                _inventory_entry(
                    asset_path=_canonical_report_asset_path("figures", "intel_v1_vs_v2_isolation.png"),
                    asset_kind="figure",
                    source_sweep_ids=[Path(str(intel_v1_v2_rows[0]["v1_run_dir"])).parent.name],
                    source_run_ids=sorted(
                        {
                            str(Path(str(row["v1_run_dir"])).name)
                            for row in intel_v1_v2_rows
                        }
                        | {
                            str(Path(str(row["v2_run_dir"])).name)
                            for row in intel_v1_v2_rows
                        }
                    ),
                    source_artifacts=sorted(
                        {
                            _source_path(Path(str(row["v1_run_dir"])) / "summary.json")
                            for row in intel_v1_v2_rows
                        }
                        | {
                            _source_path(Path(str(row["v2_run_dir"])) / "summary.json")
                            for row in intel_v1_v2_rows
                        }
                    ),
                    aggregate_input_artifacts=isolation_aggregate_inputs,
                ),
                _inventory_entry(
                    asset_path=_canonical_report_asset_path("tables", "intel_v1_vs_v2_isolation.csv"),
                    asset_kind="table",
                    source_sweep_ids=[Path(str(intel_v1_v2_rows[0]["v1_run_dir"])).parent.name],
                    source_run_ids=sorted(
                        {
                            str(Path(str(row["v1_run_dir"])).name)
                            for row in intel_v1_v2_rows
                        }
                        | {
                            str(Path(str(row["v2_run_dir"])).name)
                            for row in intel_v1_v2_rows
                        }
                    ),
                    source_artifacts=sorted(
                        {
                            _source_path(Path(str(row["v1_run_dir"])) / "summary.json")
                            for row in intel_v1_v2_rows
                        }
                        | {
                            _source_path(Path(str(row["v2_run_dir"])) / "summary.json")
                            for row in intel_v1_v2_rows
                        }
                    ),
                    aggregate_input_artifacts=isolation_aggregate_inputs,
                ),
                _inventory_entry(
                    asset_path=_canonical_report_asset_path("tables", "intel_v1_vs_v2_isolation.md"),
                    asset_kind="table",
                    source_sweep_ids=[Path(str(intel_v1_v2_rows[0]["v1_run_dir"])).parent.name],
                    source_run_ids=sorted(
                        {
                            str(Path(str(row["v1_run_dir"])).name)
                            for row in intel_v1_v2_rows
                        }
                        | {
                            str(Path(str(row["v2_run_dir"])).name)
                            for row in intel_v1_v2_rows
                        }
                    ),
                    source_artifacts=sorted(
                        {
                            _source_path(Path(str(row["v1_run_dir"])) / "summary.json")
                            for row in intel_v1_v2_rows
                        }
                        | {
                            _source_path(Path(str(row["v2_run_dir"])) / "summary.json")
                            for row in intel_v1_v2_rows
                        }
                    ),
                    aggregate_input_artifacts=isolation_aggregate_inputs,
                ),
            ]
        )
    if intel_adaptive_rows is not None:
        entries.extend(
            [
                _inventory_entry(
                    asset_path=_canonical_report_asset_path("figures", "intel_v2_vs_v3_adaptive_impairment.png"),
                    asset_kind="figure",
                    source_sweep_ids=_comparison_source_sweep_ids(intel_adaptive_rows, "v2", "v3"),
                    source_run_ids=_comparison_source_run_ids(intel_adaptive_rows, "v2", "v3"),
                    source_artifacts=_comparison_source_artifacts(
                        intel_adaptive_rows,
                        prefixes=("v2", "v3"),
                        filenames=("summary.json", "gateway_forward_log.csv", "timeseries.csv", "gateway_metrics.json"),
                    ),
                    aggregate_input_artifacts=adaptive_aggregate_inputs,
                ),
                _inventory_entry(
                    asset_path=_canonical_report_asset_path("tables", "intel_v2_vs_v3_adaptive_impairment.csv"),
                    asset_kind="table",
                    source_sweep_ids=_comparison_source_sweep_ids(intel_adaptive_rows, "v2", "v3"),
                    source_run_ids=_comparison_source_run_ids(intel_adaptive_rows, "v2", "v3"),
                    source_artifacts=_comparison_source_artifacts(
                        intel_adaptive_rows,
                        prefixes=("v2", "v3"),
                        filenames=("summary.json", "gateway_forward_log.csv", "timeseries.csv", "gateway_metrics.json"),
                    ),
                    aggregate_input_artifacts=adaptive_aggregate_inputs,
                ),
                _inventory_entry(
                    asset_path=_canonical_report_asset_path("tables", "intel_v2_vs_v3_adaptive_impairment.md"),
                    asset_kind="table",
                    source_sweep_ids=_comparison_source_sweep_ids(intel_adaptive_rows, "v2", "v3"),
                    source_run_ids=_comparison_source_run_ids(intel_adaptive_rows, "v2", "v3"),
                    source_artifacts=_comparison_source_artifacts(
                        intel_adaptive_rows,
                        prefixes=("v2", "v3"),
                        filenames=("summary.json", "gateway_forward_log.csv", "timeseries.csv", "gateway_metrics.json"),
                    ),
                    aggregate_input_artifacts=adaptive_aggregate_inputs,
                ),
            ]
        )
    if intel_adaptive_parameter_rows is not None:
        entries.extend(
            [
                _inventory_entry(
                    asset_path=_canonical_report_asset_path("tables", "intel_v3_adaptive_parameter_sweep.csv"),
                    asset_kind="table",
                    source_sweep_ids=_comparison_source_sweep_ids(
                        intel_adaptive_parameter_rows,
                        "baseline_v2",
                        "v3",
                    ),
                    source_run_ids=_comparison_source_run_ids(
                        intel_adaptive_parameter_rows,
                        "baseline_v2",
                        "v3",
                    ),
                    source_artifacts=_comparison_source_artifacts(
                        intel_adaptive_parameter_rows,
                        prefixes=("baseline_v2", "v3"),
                        filenames=("summary.json", "gateway_forward_log.csv", "timeseries.csv", "gateway_metrics.json"),
                    ),
                    aggregate_input_artifacts=adaptive_parameter_aggregate_inputs,
                ),
                _inventory_entry(
                    asset_path=_canonical_report_asset_path("tables", "intel_v3_adaptive_parameter_sweep.md"),
                    asset_kind="table",
                    source_sweep_ids=_comparison_source_sweep_ids(
                        intel_adaptive_parameter_rows,
                        "baseline_v2",
                        "v3",
                    ),
                    source_run_ids=_comparison_source_run_ids(
                        intel_adaptive_parameter_rows,
                        "baseline_v2",
                        "v3",
                    ),
                    source_artifacts=_comparison_source_artifacts(
                        intel_adaptive_parameter_rows,
                        prefixes=("baseline_v2", "v3"),
                        filenames=("summary.json", "gateway_forward_log.csv", "timeseries.csv", "gateway_metrics.json"),
                    ),
                    aggregate_input_artifacts=adaptive_parameter_aggregate_inputs,
                ),
            ]
        )

    entries.sort(key=lambda entry: str(entry["asset_path"]))
    return {
        "schema_version": 1,
        "inventory_scope": "current committed report figures/tables",
        "entries": entries,
    }


def _format_delta(base: float, candidate: float) -> str:
    percent_delta = _percent_delta(base, candidate)
    if percent_delta is None:
        return "n/a"
    return f"{percent_delta:.1f}%"


def _percent_delta(base: float, candidate: float) -> float | None:
    if math.isclose(base, 0.0):
        return None
    return ((candidate - base) / base) * 100


def _summary_row_trial_run_dirs(row: dict[str, object]) -> list[Path]:
    trial_run_dirs = row.get("trial_run_dirs")
    if isinstance(trial_run_dirs, list) and trial_run_dirs:
        return [Path(str(run_dir)) for run_dir in trial_run_dirs]
    return [Path(str(row["run_dir"]))]


def _sweep_name_from_run_dir(run_dir: Path) -> str:
    if run_dir.name.startswith("trial-"):
        return run_dir.parent.parent.name
    return run_dir.parent.name


def _summary_row_sweep_name(row: dict[str, object]) -> str:
    return _sweep_name_from_run_dir(_summary_row_trial_run_dirs(row)[0])


def _comparison_trial_run_dirs(row: dict[str, object], *prefixes: str) -> list[Path]:
    run_dirs: list[Path] = []
    for prefix in prefixes:
        trial_run_dirs = row.get(f"{prefix}_trial_run_dirs")
        if isinstance(trial_run_dirs, list) and trial_run_dirs:
            run_dirs.extend(Path(str(run_dir)) for run_dir in trial_run_dirs)
            continue
        single_run_dir = row.get(f"{prefix}_run_dir")
        if single_run_dir:
            run_dirs.append(Path(str(single_run_dir)))
    deduped: list[Path] = []
    seen: set[str] = set()
    for run_dir in run_dirs:
        key = str(run_dir)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(run_dir)
    return deduped


def _comparison_trial_run_ids(row: dict[str, object], *prefixes: str) -> list[str]:
    run_ids: list[str] = []
    for prefix in prefixes:
        trial_run_ids = row.get(f"{prefix}_trial_run_ids")
        if isinstance(trial_run_ids, list) and trial_run_ids:
            run_ids.extend(str(run_id) for run_id in trial_run_ids)
            continue
        single_run_dir = row.get(f"{prefix}_run_dir")
        if single_run_dir:
            run_ids.append(Path(str(single_run_dir)).name)
    deduped: list[str] = []
    seen: set[str] = set()
    for run_id in run_ids:
        if run_id in seen:
            continue
        seen.add(run_id)
        deduped.append(run_id)
    return deduped


def _comparison_source_sweep_ids(rows: list[dict[str, object]], *prefixes: str) -> list[str]:
    return sorted(
        {
            _sweep_name_from_run_dir(run_dir)
            for row in rows
            for run_dir in _comparison_trial_run_dirs(row, *prefixes)
        }
    )


def _comparison_source_run_ids(rows: list[dict[str, object]], *prefixes: str) -> list[str]:
    return sorted(
        {
            run_id
            for row in rows
            for run_id in _comparison_trial_run_ids(row, *prefixes)
        }
    )


def _comparison_source_artifacts(
    rows: list[dict[str, object]],
    *,
    prefixes: tuple[str, ...],
    filenames: tuple[str, ...],
) -> list[str]:
    return sorted(
        {
            _source_path(run_dir / filename)
            for row in rows
            for run_dir in _comparison_trial_run_dirs(row, *prefixes)
            for filename in filenames
        }
    )


def _load_trial_records(row: dict[str, object]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for run_dir in _summary_row_trial_run_dirs(row):
        summary = _load_json(run_dir / "summary.json")
        manifest_path = run_dir / "manifest.json"
        manifest = _load_json(manifest_path) if manifest_path.exists() else {}
        summary["run_dir"] = str(run_dir)
        summary["run_id"] = summary.get("run_id", manifest.get("run_id", run_dir.name))
        summary["trial_id"] = summary.get("trial_id", manifest.get("trial_id"))
        summary["trial_index"] = summary.get("trial_index", manifest.get("trial_index"))
        summary["impairment_seed"] = summary.get("impairment_seed", manifest.get("impairment_seed"))
        records.append(summary)
    records.sort(
        key=lambda record: (
            int(record.get("trial_index") or 10**9),
            str(record.get("run_id", record.get("run_dir", ""))),
        )
    )
    return records


def _collect_gateway_metric_numbers(
    row: dict[str, object],
    metric_name: str,
) -> list[float]:
    values: list[float] = []
    for run_dir in _summary_row_trial_run_dirs(row):
        metric_value = _load_gateway_metrics(run_dir).get(metric_name)
        if metric_value is None:
            continue
        values.append(float(metric_value))
    if values:
        return values
    fallback = row.get(metric_name)
    if fallback is None:
        return []
    return [float(fallback)]


def _collect_gateway_metric_texts(
    row: dict[str, object],
    metric_name: str,
) -> list[str]:
    values: list[str] = []
    for run_dir in _summary_row_trial_run_dirs(row):
        metric_value = _load_gateway_metrics(run_dir).get(metric_name)
        if metric_value is None:
            continue
        text = str(metric_value)
        if text:
            values.append(text)
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped


def _condition_window_bounds(row: dict[str, object]) -> tuple[int, int]:
    fallback_window_ms = int(row.get("effective_batch_window_ms", 0) or 0)
    min_windows: list[int] = []
    max_windows: list[int] = []
    for run_dir in _summary_row_trial_run_dirs(row):
        min_window_ms, max_window_ms = _trace_window_bounds(
            _load_gateway_frame_trace(run_dir),
            fallback_window_ms=fallback_window_ms,
        )
        min_windows.append(min_window_ms)
        max_windows.append(max_window_ms)
    if not min_windows:
        return fallback_window_ms, fallback_window_ms
    return min(min_windows), max(max_windows)


def _trial_direction_details(
    baseline_row: dict[str, object],
    candidate_row: dict[str, object],
    metric_name: str,
) -> tuple[list[int], list[float], list[str]]:
    baseline_trials = {
        int(record["impairment_seed"]): record
        for record in _load_trial_records(baseline_row)
        if record.get("impairment_seed") is not None
    }
    candidate_trials = {
        int(record["impairment_seed"]): record
        for record in _load_trial_records(candidate_row)
        if record.get("impairment_seed") is not None
    }
    shared_seeds = sorted(set(baseline_trials) & set(candidate_trials))
    trial_delta_pcts: list[float] = []
    trial_directions: list[str] = []
    for seed in shared_seeds:
        baseline_value = float(baseline_trials[seed][metric_name])
        candidate_value = float(candidate_trials[seed][metric_name])
        percent_delta = _percent_delta(baseline_value, candidate_value)
        if percent_delta is not None:
            trial_delta_pcts.append(round(percent_delta, 3))
        if candidate_value < baseline_value:
            trial_directions.append("lower")
        elif candidate_value > baseline_value:
            trial_directions.append("higher")
        else:
            trial_directions.append("equal")
    return shared_seeds, trial_delta_pcts, trial_directions


def _trial_direction_consistent(trial_directions: list[str]) -> bool:
    return len(set(trial_directions)) <= 1


def _byte_reduction_scenario_classification(
    baseline_row: dict[str, object],
    candidate_row: dict[str, object],
) -> str:
    _, _, trial_directions = _trial_direction_details(
        baseline_row,
        candidate_row,
        "proxy_downstream_bytes_out",
    )
    if trial_directions and all(direction == "lower" for direction in trial_directions):
        return "supports_byte_reduction"
    if trial_directions and all(direction == "higher" for direction in trial_directions):
        return "contradicts_byte_reduction"
    return "mixed"


def _byte_claim_status(bandwidth_rows: list[dict[str, object]]) -> dict[str, str]:
    for variant in ("v2", "v4"):
        variant_rows = [row for row in bandwidth_rows if row["variant"] == variant]
        clean_supported = any(
            row["scenario"] == "clean" and row["scenario_byte_claim_classification"] == "supports_byte_reduction"
            for row in variant_rows
        )
        impaired_supported_count = sum(
            1
            for row in variant_rows
            if row["scenario"] != "clean" and row["scenario_byte_claim_classification"] == "supports_byte_reduction"
        )
        if clean_supported and impaired_supported_count >= 2:
            return {"status": "supported", "variant": variant}
    return {"status": "fallback", "fallback_wording": BYTE_CLAIM_FALLBACK_WORDING}


def _adaptive_threshold_flags(
    *,
    baseline_row: dict[str, object],
    candidate_row: dict[str, object],
    candidate_min_window_ms: int,
    candidate_max_window_ms: int,
    candidate_increase_events: float,
    candidate_decrease_events: float,
) -> dict[str, object]:
    inter_frame_gap_stddev_delta_ms = round(
        float(candidate_row["proxy_inter_frame_gap_stddev_ms"]) - float(baseline_row["proxy_inter_frame_gap_stddev_ms"]),
        3,
    )
    frame_rate_stddev_delta_per_s = round(
        float(candidate_row["proxy_frame_rate_stddev_per_s"]) - float(baseline_row["proxy_frame_rate_stddev_per_s"]),
        3,
    )
    latency_p95_delta_pct = _percent_delta(
        float(baseline_row["latency_p95_ms"]),
        float(candidate_row["latency_p95_ms"]),
    )
    downstream_bytes_delta_pct_raw = _percent_delta(
        float(baseline_row["proxy_downstream_bytes_out"]),
        float(candidate_row["proxy_downstream_bytes_out"]),
    )
    window_adjusted = (
        candidate_min_window_ms != candidate_max_window_ms
        or not math.isclose(candidate_increase_events, 0.0)
        or not math.isclose(candidate_decrease_events, 0.0)
    )
    stability_improvements: list[str] = []
    if inter_frame_gap_stddev_delta_ms < 0:
        stability_improvements.append("proxy_inter_frame_gap_stddev_ms")
    if frame_rate_stddev_delta_per_s < 0:
        stability_improvements.append("proxy_frame_rate_stddev_per_s")
    latency_guardrail_ok = latency_p95_delta_pct is not None and latency_p95_delta_pct <= 10.0
    byte_guardrail_ok = downstream_bytes_delta_pct_raw is not None and downstream_bytes_delta_pct_raw <= 10.0
    return {
        "window_adjusted": window_adjusted,
        "stability_improvements": stability_improvements,
        "latency_guardrail_ok": latency_guardrail_ok,
        "byte_guardrail_ok": byte_guardrail_ok,
        "inter_frame_gap_stddev_delta_ms": inter_frame_gap_stddev_delta_ms,
        "frame_rate_stddev_delta_per_s": frame_rate_stddev_delta_per_s,
        "latency_p95_delta_pct_raw": latency_p95_delta_pct,
        "downstream_bytes_delta_pct_raw": downstream_bytes_delta_pct_raw,
    }


def _adaptive_claim_status(parameter_rows: list[dict[str, object]]) -> dict[str, str]:
    rows_by_config: dict[str, list[dict[str, object]]] = {}
    for row in parameter_rows:
        rows_by_config.setdefault(str(row["config_id"]), []).append(row)
    for config_id, config_rows in rows_by_config.items():
        supporting_rows = [
            row
            for row in config_rows
            if row["window_adjusted"] and row["stability_improved"] and row["latency_guardrail_ok"] and row["byte_guardrail_ok"]
        ]
        if len(supporting_rows) >= 2:
            return {"status": "supported", "config_id": config_id}
    return {"status": "fallback", "fallback_wording": ADAPTIVE_CLAIM_FALLBACK_WORDING}


def _latency_stats(row: dict[str, object], *, prefix: str = "latency") -> dict[str, float]:
    return {
        f"{prefix}_mean_ms": float(row["latency_mean_ms"]),
        f"{prefix}_p50_ms": float(row["latency_p50_ms"]),
        f"{prefix}_p95_ms": float(row["latency_p95_ms"]),
        f"{prefix}_p99_ms": float(row["latency_p99_ms"]),
    }


def _build_intel_bandwidth_vs_v0_rows(intel_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for scenario in INTEL_BANDWIDTH_SCENARIOS:
        baseline = _select_row(intel_rows, variant="v0", scenario=scenario, mqtt_qos=0)
        for variant in ("v2", "v4"):
            candidate = _select_row(intel_rows, variant=variant, scenario=scenario, mqtt_qos=0)
            shared_seeds, trial_delta_pcts, trial_directions = _trial_direction_details(
                baseline,
                candidate,
                "proxy_downstream_bytes_out",
            )
            rows.append(
                {
                    "scenario": scenario,
                    "variant": variant,
                    "baseline_n": int(baseline.get("n", 1) or 1),
                    "variant_n": int(candidate.get("n", 1) or 1),
                    "shared_impairment_seeds": shared_seeds,
                    "baseline_trial_run_ids": list(baseline.get("trial_run_ids", [baseline["run_id"]])),
                    "variant_trial_run_ids": list(candidate.get("trial_run_ids", [candidate["run_id"]])),
                    "baseline_downstream_bytes_out": round(float(baseline["proxy_downstream_bytes_out"]), 3),
                    "baseline_downstream_bytes_out_stddev": round(
                        float(baseline.get("proxy_downstream_bytes_out_stddev", 0.0)),
                        3,
                    ),
                    "variant_downstream_bytes_out": round(float(candidate["proxy_downstream_bytes_out"]), 3),
                    "variant_downstream_bytes_out_stddev": round(
                        float(candidate.get("proxy_downstream_bytes_out_stddev", 0.0)),
                        3,
                    ),
                    "downstream_bytes_delta_pct": _format_delta(
                        float(baseline["proxy_downstream_bytes_out"]),
                        float(candidate["proxy_downstream_bytes_out"]),
                    ),
                    "trial_byte_delta_pcts": trial_delta_pcts,
                    "trial_direction_consistent": _trial_direction_consistent(trial_directions),
                    "trial_directions": trial_directions,
                    "scenario_byte_claim_classification": _byte_reduction_scenario_classification(baseline, candidate),
                    "baseline_max_bandwidth_bytes_per_s": round(float(baseline["max_bandwidth_bytes_per_s"]), 3),
                    "baseline_max_bandwidth_bytes_per_s_stddev": round(
                        float(baseline.get("max_bandwidth_bytes_per_s_stddev", 0.0)),
                        3,
                    ),
                    "variant_max_bandwidth_bytes_per_s": round(float(candidate["max_bandwidth_bytes_per_s"]), 3),
                    "variant_max_bandwidth_bytes_per_s_stddev": round(
                        float(candidate.get("max_bandwidth_bytes_per_s_stddev", 0.0)),
                        3,
                    ),
                    "max_bandwidth_delta_pct": _format_delta(
                        float(baseline["max_bandwidth_bytes_per_s"]),
                        float(candidate["max_bandwidth_bytes_per_s"]),
                    ),
                    "baseline_downstream_frames_out": round(float(baseline["proxy_downstream_frames_out"]), 3),
                    "baseline_downstream_frames_out_stddev": round(
                        float(baseline.get("proxy_downstream_frames_out_stddev", 0.0)),
                        3,
                    ),
                    "variant_downstream_frames_out": round(float(candidate["proxy_downstream_frames_out"]), 3),
                    "variant_downstream_frames_out_stddev": round(
                        float(candidate.get("proxy_downstream_frames_out_stddev", 0.0)),
                        3,
                    ),
                    "downstream_frames_delta_pct": _format_delta(
                        float(baseline["proxy_downstream_frames_out"]),
                        float(candidate["proxy_downstream_frames_out"]),
                    ),
                    **_latency_stats(baseline, prefix="baseline_latency"),
                    **_latency_stats(candidate, prefix="variant_latency"),
                    "baseline_latency_p95_ms_stddev": round(float(baseline.get("latency_p95_ms_stddev", 0.0)), 3),
                    "variant_latency_p95_ms_stddev": round(float(candidate.get("latency_p95_ms_stddev", 0.0)), 3),
                }
            )
    return rows


def _build_intel_condensed_summary_rows(intel_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for scenario in INTEL_BANDWIDTH_SCENARIOS:
        for variant in ("v0", "v2", "v4"):
            try:
                source = _select_row(intel_rows, variant=variant, scenario=scenario, mqtt_qos=0)
            except KeyError:
                continue
            rows.append(
                {
                    "variant": variant,
                    "scenario": scenario,
                    "mqtt_qos": 0,
                    **_latency_stats(source),
                    "proxy_downstream_frames_out": int(source["proxy_downstream_frames_out"]),
                    "proxy_downstream_bytes_out": int(source["proxy_downstream_bytes_out"]),
                    "stale_fraction": float(source.get("stale_fraction", 0.0)),
                }
            )
    if not rows:
        raise ValueError("No Intel rows were found for condensed summary outputs")
    return rows


def _build_intel_main_summary_rows(intel_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for scenario in INTEL_BANDWIDTH_SCENARIOS:
        for variant in PAPER_MAIN_VARIANTS:
            try:
                source = _select_row(intel_rows, variant=variant, scenario=scenario, mqtt_qos=0)
            except KeyError:
                continue
            rows.append(
                {
                    "Variant": variant.upper(),
                    "Downstream Frames": int(source["proxy_downstream_frames_out"]),
                    "Downstream Bytes": int(source["proxy_downstream_bytes_out"]),
                    "Latency mean": float(source["latency_mean_ms"]),
                    "Latency p50": float(source["latency_p50_ms"]),
                    "Latency p95": float(source["latency_p95_ms"]),
                    "Latency p99": float(source["latency_p99_ms"]),
                    "Stale Fraction": float(source.get("stale_fraction", 0.0)),
                    "Scenario": scenario,
                }
            )
    if not rows:
        raise ValueError("No Intel qos0 rows were found for main summary outputs")
    return rows


def _build_intel_qos_comparison_rows(intel_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for scenario in INTEL_BANDWIDTH_SCENARIOS:
        for variant in ("v0", "v2", "v4"):
            try:
                qos0_row = _select_row(intel_rows, variant=variant, scenario=scenario, mqtt_qos=0)
                qos1_row = _select_row(intel_rows, variant=variant, scenario=scenario, mqtt_qos=1)
            except KeyError:
                continue
            rows.append(
                {
                    "scenario": scenario,
                    "variant": variant,
                    **{f"qos0_{key}": value for key, value in _latency_stats(qos0_row).items()},
                    **{f"qos1_{key}": value for key, value in _latency_stats(qos1_row).items()},
                    "latency_p95_delta_ms": round(float(qos1_row["latency_p95_ms"]) - float(qos0_row["latency_p95_ms"]), 3),
                    "qos0_duplicates_dropped": int(qos0_row.get("duplicates_dropped", 0)),
                    "qos1_duplicates_dropped": int(qos1_row.get("duplicates_dropped", 0)),
                    "qos0_gateway_mqtt_in_msgs": int(qos0_row.get("gateway_mqtt_in_msgs", 0)),
                    "qos1_gateway_mqtt_in_msgs": int(qos1_row.get("gateway_mqtt_in_msgs", 0)),
                    "gateway_mqtt_in_msgs_delta_pct": _format_delta(
                        float(qos0_row.get("gateway_mqtt_in_msgs", 0)),
                        float(qos1_row.get("gateway_mqtt_in_msgs", 0)),
                    ),
                    "qos0_proxy_downstream_bytes_out": int(qos0_row["proxy_downstream_bytes_out"]),
                    "qos1_proxy_downstream_bytes_out": int(qos1_row["proxy_downstream_bytes_out"]),
                    "downstream_bytes_delta_pct": _format_delta(
                        float(qos0_row["proxy_downstream_bytes_out"]),
                        float(qos1_row["proxy_downstream_bytes_out"]),
                    ),
                    "qos0_proxy_downstream_frames_out": int(qos0_row["proxy_downstream_frames_out"]),
                    "qos1_proxy_downstream_frames_out": int(qos1_row["proxy_downstream_frames_out"]),
                    "downstream_frames_delta_pct": _format_delta(
                        float(qos0_row["proxy_downstream_frames_out"]),
                        float(qos1_row["proxy_downstream_frames_out"]),
                    ),
                    "qos0_stale_fraction": float(qos0_row.get("stale_fraction", 0.0)),
                    "qos1_stale_fraction": float(qos1_row.get("stale_fraction", 0.0)),
                    "stale_fraction_delta": round(
                        float(qos1_row.get("stale_fraction", 0.0)) - float(qos0_row.get("stale_fraction", 0.0)),
                        6,
                    ),
                    "qos0_run_dir": str(qos0_row["run_dir"]),
                    "qos1_run_dir": str(qos1_row["run_dir"]),
                }
            )
    if not rows:
        raise ValueError("No paired qos0/qos1 Intel rows were found for QoS comparison outputs")
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


def _format_qos_comparison_series(
    comparison_rows: list[dict[str, object]],
    *,
    variant: str,
    delta_field: str,
) -> str:
    variant_rows = [row for row in comparison_rows if row["variant"] == variant]
    variant_rows = sorted(
        variant_rows,
        key=lambda candidate: INTEL_BANDWIDTH_SCENARIOS.index(str(candidate["scenario"])),
    )
    if not variant_rows:
        return "n/a"
    parts: list[str] = []
    for row in variant_rows:
        parts.append(f"{row[delta_field]} under {row['scenario']}")
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
                **_latency_stats(row),
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
                    **{f"v1_{key}": value for key, value in _latency_stats(v1_row).items()},
                    **{f"v2_{key}": value for key, value in _latency_stats(v2_row).items()},
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
        v2_min_window_ms, v2_max_window_ms = _condition_window_bounds(v2_row)
        v3_min_window_ms, v3_max_window_ms = _condition_window_bounds(v3_row)
        v3_increase_events = _collect_gateway_metric_numbers(v3_row, "adaptive_window_increase_events")
        v3_decrease_events = _collect_gateway_metric_numbers(v3_row, "adaptive_window_decrease_events")
        threshold_flags = _adaptive_threshold_flags(
            baseline_row=v2_row,
            candidate_row=v3_row,
            candidate_min_window_ms=v3_min_window_ms,
            candidate_max_window_ms=v3_max_window_ms,
            candidate_increase_events=mean(v3_increase_events) if v3_increase_events else 0.0,
            candidate_decrease_events=mean(v3_decrease_events) if v3_decrease_events else 0.0,
        )
        comparison_rows.append(
            {
                "scenario": scenario,
                "v2_n": int(v2_row.get("n", 1) or 1),
                "v3_n": int(v3_row.get("n", 1) or 1),
                "v2_trial_run_ids": list(v2_row.get("trial_run_ids", [v2_row["run_id"]])),
                "v3_trial_run_ids": list(v3_row.get("trial_run_ids", [v3_row["run_id"]])),
                "v2_trial_run_dirs": [str(path) for path in _summary_row_trial_run_dirs(v2_row)],
                "v3_trial_run_dirs": [str(path) for path in _summary_row_trial_run_dirs(v3_row)],
                **{f"v2_{key}": value for key, value in _latency_stats(v2_row).items()},
                **{f"v3_{key}": value for key, value in _latency_stats(v3_row).items()},
                "latency_p95_delta_ms": round(float(v3_row["latency_p95_ms"]) - float(v2_row["latency_p95_ms"]), 3),
                "latency_p95_delta_pct": _format_delta(
                    float(v2_row["latency_p95_ms"]),
                    float(v3_row["latency_p95_ms"]),
                ),
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
                "v2_proxy_inter_frame_gap_stddev_ms": round(float(v2_row.get("proxy_inter_frame_gap_stddev_ms", 0.0)), 3),
                "v3_proxy_inter_frame_gap_stddev_ms": round(float(v3_row.get("proxy_inter_frame_gap_stddev_ms", 0.0)), 3),
                "v2_proxy_frame_rate_stddev_per_s": round(float(v2_row.get("proxy_frame_rate_stddev_per_s", 0.0)), 3),
                "v3_proxy_frame_rate_stddev_per_s": round(float(v3_row.get("proxy_frame_rate_stddev_per_s", 0.0)), 3),
                "inter_frame_gap_stddev_delta_ms": threshold_flags["inter_frame_gap_stddev_delta_ms"],
                "frame_rate_stddev_delta_per_s": threshold_flags["frame_rate_stddev_delta_per_s"],
                "v3_adaptive_window_increase_events": round(mean(v3_increase_events), 3) if v3_increase_events else 0.0,
                "v3_adaptive_window_decrease_events": round(mean(v3_decrease_events), 3) if v3_decrease_events else 0.0,
                "v3_last_adaptation_reasons": _collect_gateway_metric_texts(v3_row, "last_adaptation_reason"),
                "window_adjusted": threshold_flags["window_adjusted"],
                "stability_improved": bool(threshold_flags["stability_improvements"]),
                "stability_improvement_metrics": threshold_flags["stability_improvements"],
                "latency_guardrail_ok": threshold_flags["latency_guardrail_ok"],
                "byte_guardrail_ok": threshold_flags["byte_guardrail_ok"],
                "scenario_supports_positive_adaptive_claim": (
                    threshold_flags["window_adjusted"]
                    and bool(threshold_flags["stability_improvements"])
                    and threshold_flags["latency_guardrail_ok"]
                    and threshold_flags["byte_guardrail_ok"]
                ),
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
    last_reasons = row.get("v3_last_adaptation_reasons", [])
    last_reason_clause = (
        f"The last adaptation reasons across trials were `{'; '.join(str(reason) for reason in last_reasons)}`."
        if isinstance(last_reasons, list) and last_reasons
        else ""
    )
    return (
        f"Under {scenario}, adaptive V3 changed stale fraction by {row['stale_fraction_delta']:+.6f}, "
        f"max rendered update rate by {row['update_rate_delta_pct']}, downstream frames by {row['downstream_frames_delta_pct']}, "
        f"and downstream bytes by {row['downstream_bytes_delta_pct']} versus fixed-window V2. "
        f"{window_clause}. {last_reason_clause}"
    )


def _build_intel_v3_adaptive_parameter_sweep_rows(
    baseline_rows: list[dict[str, object]],
    parameter_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    baseline_by_scenario = {
        str(row["scenario"]): row
        for row in baseline_rows
        if str(row.get("variant", "")) == "v2" and int(row.get("mqtt_qos", 0) or 0) == 0
    }
    comparison_rows: list[dict[str, object]] = []
    for parameter_row in sorted(
        parameter_rows,
        key=lambda row: (
            str(row.get("scenario", "")),
            int(row.get("adaptive_send_slow_ms", 0) or 0),
            int(row.get("adaptive_step_up_ms", 0) or 0),
            int(row.get("adaptive_max_batch_window_ms", 0) or 0),
        ),
    ):
        scenario = str(parameter_row.get("scenario", ""))
        baseline_row = baseline_by_scenario.get(scenario)
        if baseline_row is None:
            raise ValueError(f"Missing replicated V2 baseline row for adaptive parameter sweep scenario: {scenario}")
        v3_min_window_ms, v3_max_window_ms = _condition_window_bounds(parameter_row)
        v3_increase_events = _collect_gateway_metric_numbers(parameter_row, "adaptive_window_increase_events")
        v3_decrease_events = _collect_gateway_metric_numbers(parameter_row, "adaptive_window_decrease_events")
        threshold_flags = _adaptive_threshold_flags(
            baseline_row=baseline_row,
            candidate_row=parameter_row,
            candidate_min_window_ms=v3_min_window_ms,
            candidate_max_window_ms=v3_max_window_ms,
            candidate_increase_events=mean(v3_increase_events) if v3_increase_events else 0.0,
            candidate_decrease_events=mean(v3_decrease_events) if v3_decrease_events else 0.0,
        )
        comparison_rows.append(
            {
                "config_id": str(parameter_row["condition_id"]).split("-")[-1],
                "scenario": scenario,
                "baseline_v2_n": int(baseline_row.get("n", 1) or 1),
                "v3_n": int(parameter_row.get("n", 1) or 1),
                "adaptive_send_slow_ms": int(parameter_row.get("adaptive_send_slow_ms", 0) or 0),
                "adaptive_step_up_ms": int(parameter_row.get("adaptive_step_up_ms", 0) or 0),
                "adaptive_max_batch_window_ms": int(parameter_row.get("adaptive_max_batch_window_ms", 0) or 0),
                "baseline_v2_trial_run_ids": list(baseline_row.get("trial_run_ids", [baseline_row["run_id"]])),
                "v3_trial_run_ids": list(parameter_row.get("trial_run_ids", [parameter_row["run_id"]])),
                "baseline_v2_trial_run_dirs": [str(path) for path in _summary_row_trial_run_dirs(baseline_row)],
                "v3_trial_run_dirs": [str(path) for path in _summary_row_trial_run_dirs(parameter_row)],
                **{f"baseline_v2_{key}": value for key, value in _latency_stats(baseline_row).items()},
                **{f"v3_{key}": value for key, value in _latency_stats(parameter_row).items()},
                "latency_p95_delta_ms": round(
                    float(parameter_row["latency_p95_ms"]) - float(baseline_row["latency_p95_ms"]),
                    3,
                ),
                "latency_p95_delta_pct": _format_delta(
                    float(baseline_row["latency_p95_ms"]),
                    float(parameter_row["latency_p95_ms"]),
                ),
                "baseline_v2_proxy_downstream_bytes_out": round(float(baseline_row["proxy_downstream_bytes_out"]), 3),
                "v3_proxy_downstream_bytes_out": round(float(parameter_row["proxy_downstream_bytes_out"]), 3),
                "downstream_bytes_delta_pct": _format_delta(
                    float(baseline_row["proxy_downstream_bytes_out"]),
                    float(parameter_row["proxy_downstream_bytes_out"]),
                ),
                "baseline_v2_proxy_downstream_frames_out": round(float(baseline_row["proxy_downstream_frames_out"]), 3),
                "v3_proxy_downstream_frames_out": round(float(parameter_row["proxy_downstream_frames_out"]), 3),
                "downstream_frames_delta_pct": _format_delta(
                    float(baseline_row["proxy_downstream_frames_out"]),
                    float(parameter_row["proxy_downstream_frames_out"]),
                ),
                "baseline_v2_proxy_inter_frame_gap_stddev_ms": round(
                    float(baseline_row.get("proxy_inter_frame_gap_stddev_ms", 0.0)),
                    3,
                ),
                "v3_proxy_inter_frame_gap_stddev_ms": round(
                    float(parameter_row.get("proxy_inter_frame_gap_stddev_ms", 0.0)),
                    3,
                ),
                "baseline_v2_proxy_frame_rate_stddev_per_s": round(
                    float(baseline_row.get("proxy_frame_rate_stddev_per_s", 0.0)),
                    3,
                ),
                "v3_proxy_frame_rate_stddev_per_s": round(
                    float(parameter_row.get("proxy_frame_rate_stddev_per_s", 0.0)),
                    3,
                ),
                "inter_frame_gap_stddev_delta_ms": threshold_flags["inter_frame_gap_stddev_delta_ms"],
                "frame_rate_stddev_delta_per_s": threshold_flags["frame_rate_stddev_delta_per_s"],
                "v3_min_effective_batch_window_ms": v3_min_window_ms,
                "v3_max_effective_batch_window_ms": v3_max_window_ms,
                "v3_adaptive_window_increase_events": round(mean(v3_increase_events), 3) if v3_increase_events else 0.0,
                "v3_adaptive_window_decrease_events": round(mean(v3_decrease_events), 3) if v3_decrease_events else 0.0,
                "v3_last_adaptation_reasons": _collect_gateway_metric_texts(parameter_row, "last_adaptation_reason"),
                "window_adjusted": threshold_flags["window_adjusted"],
                "stability_improved": bool(threshold_flags["stability_improvements"]),
                "stability_improvement_metrics": threshold_flags["stability_improvements"],
                "latency_guardrail_ok": threshold_flags["latency_guardrail_ok"],
                "byte_guardrail_ok": threshold_flags["byte_guardrail_ok"],
                "scenario_supports_positive_adaptive_claim": (
                    threshold_flags["window_adjusted"]
                    and bool(threshold_flags["stability_improvements"])
                    and threshold_flags["latency_guardrail_ok"]
                    and threshold_flags["byte_guardrail_ok"]
                ),
            }
        )
    return comparison_rows


def _describe_delay_jitter_stability(rows: list[dict[str, object]]) -> str:
    selected_rows = {
        str(row["variant"]): row
        for row in rows
        if row["comparison_family"] == "intel_primary"
        and row["scenario"] == "delay_50ms_jitter20ms"
        and int(row["mqtt_qos"]) == 0
    }
    v0_row = selected_rows["v0"]
    v2_row = selected_rows["v2"]
    v4_row = selected_rows["v4"]
    return (
        f"On the Intel delay_50ms_jitter20ms qos0 path, the proxy-side source-of-truth table shows "
        f"V0 with inter-frame-gap p95 {v0_row['proxy_inter_frame_gap_p95_ms']} ms and frame-rate stddev "
        f"{v0_row['proxy_frame_rate_stddev_per_s']} /s, while V2 reports {v2_row['proxy_inter_frame_gap_p95_ms']} ms "
        f"and {v2_row['proxy_frame_rate_stddev_per_s']} /s, and V4 reports {v4_row['proxy_inter_frame_gap_p95_ms']} ms "
        f"and {v4_row['proxy_frame_rate_stddev_per_s']} /s. The bounded interpretation is pacing shape rather than "
        "lower delay: smart variants emit fewer downstream frames, and the stability evidence should be read from "
        "proxy inter-frame-gap and frame-rate variability rather than dashboard row cadence."
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


def _plot_inter_frame_gap_cdf(
    rows: list[dict[str, object]],
    *,
    scenario: str,
    mqtt_qos: int,
    output_path: Path,
) -> None:
    figure = plt.figure(figsize=(8, 5))
    for variant in PAPER_MAIN_VARIANTS:
        row = _select_row(rows, variant=variant, scenario=scenario, mqtt_qos=mqtt_qos)
        samples = collect_proxy_inter_frame_gaps(Path(str(row["run_dir"])))
        if not samples:
            continue
        ordered = sorted(samples)
        cdf = [(index + 1) / len(ordered) for index in range(len(ordered))]
        plt.plot(ordered, cdf, label=variant.upper())
    plt.xlabel("Inter-frame gap (ms)")
    plt.ylabel("CDF")
    plt.title(f"Proxy inter-frame-gap CDF ({scenario}, qos{mqtt_qos})")
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

    phase_end = max_relative_second if max_relative_second > 0 else 15.0
    _shade_phase_windows(
        axis,
        phase_windows=_scenario_phase_windows(OUTAGE_SCENARIO, total_duration_s=phase_end),
        phase_end_s=phase_end,
    )

    axis.set_xlabel("Relative second from first proxy upstream receive")
    axis.set_ylabel("Frame mean age at display (ms)")
    axis.set_title("Intel outage qos0 V0 vs V4 age over time")
    axis.grid(True, axis="y", alpha=0.3)
    axis.legend(loc="best")
    figure.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=150)
    plt.close(figure)


def _plot_main_outage_frame_rate(rows: list[dict[str, object]], *, output_path: Path) -> None:
    figure, axis = plt.subplots(figsize=(10, 5))
    styles = {
        "v0": ("tab:blue", "V0"),
        "v2": ("tab:orange", "V2"),
        "v4": ("tab:green", "V4"),
    }
    max_relative_second = 0.0

    for variant in PAPER_MAIN_VARIANTS:
        row = _select_row(rows, variant=variant, scenario="outage_5s", mqtt_qos=0)
        series = _load_timeseries(Path(str(row["run_dir"])))
        if not series:
            continue
        first_second = series[0]["epoch_second"]
        x_values = [point["epoch_second"] - first_second for point in series]
        y_values = [point["frame_rate_per_s"] for point in series]
        max_relative_second = max(max_relative_second, max(x_values, default=0.0))
        color, label = styles[variant]
        axis.plot(x_values, y_values, marker="o", color=color, label=label)

    phase_end = max_relative_second if max_relative_second > 0 else 20.0
    _shade_phase_windows(
        axis,
        phase_windows=_scenario_phase_windows(OUTAGE_SCENARIO, total_duration_s=phase_end),
        phase_end_s=phase_end,
    )

    axis.set_xlabel("Relative second from first proxy frame")
    axis.set_ylabel("Downstream frames per second")
    axis.set_title("Downstream Frame Rate Over the outage_5s Condition: V0 vs V2 vs V4")
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


def _plot_qos_comparison(rows: list[dict[str, object]], *, output_path: Path) -> None:
    figure, axes = plt.subplots(2, 2, figsize=(12, 9), sharex=True)
    scenario_positions = list(range(len(INTEL_BANDWIDTH_SCENARIOS)))
    variant_styles = {
        "v0": ("tab:blue", "o"),
        "v2": ("tab:orange", "s"),
        "v4": ("tab:green", "^"),
    }

    for variant in ("v0", "v2", "v4"):
        variant_rows = [row for row in rows if row["variant"] == variant]
        variant_rows = sorted(
            variant_rows,
            key=lambda candidate: INTEL_BANDWIDTH_SCENARIOS.index(str(candidate["scenario"])),
        )
        if not variant_rows:
            continue
        color, marker = variant_styles[variant]
        x_values = [INTEL_BANDWIDTH_SCENARIOS.index(str(row["scenario"])) for row in variant_rows]
        qos0_latency = [float(row["qos0_latency_p95_ms"]) for row in variant_rows]
        qos1_latency = [float(row["qos1_latency_p95_ms"]) for row in variant_rows]
        qos0_bytes = [float(row["qos0_proxy_downstream_bytes_out"]) for row in variant_rows]
        qos1_bytes = [float(row["qos1_proxy_downstream_bytes_out"]) for row in variant_rows]
        qos0_duplicates = [float(row["qos0_duplicates_dropped"]) for row in variant_rows]
        qos1_duplicates = [float(row["qos1_duplicates_dropped"]) for row in variant_rows]
        qos0_stale = [float(row["qos0_stale_fraction"]) for row in variant_rows]
        qos1_stale = [float(row["qos1_stale_fraction"]) for row in variant_rows]

        axes[0, 0].plot(x_values, qos0_latency, marker=marker, linestyle="--", color=color, label=f"{variant.upper()} qos0")
        axes[0, 0].plot(x_values, qos1_latency, marker=marker, linestyle="-", color=color, label=f"{variant.upper()} qos1", alpha=0.8)
        axes[0, 1].plot(x_values, qos0_bytes, marker=marker, linestyle="--", color=color, label=f"{variant.upper()} qos0")
        axes[0, 1].plot(x_values, qos1_bytes, marker=marker, linestyle="-", color=color, label=f"{variant.upper()} qos1", alpha=0.8)
        axes[1, 0].plot(x_values, qos0_duplicates, marker=marker, linestyle="--", color=color, label=f"{variant.upper()} qos0")
        axes[1, 0].plot(x_values, qos1_duplicates, marker=marker, linestyle="-", color=color, label=f"{variant.upper()} qos1", alpha=0.8)
        axes[1, 1].plot(x_values, qos0_stale, marker=marker, linestyle="--", color=color, label=f"{variant.upper()} qos0")
        axes[1, 1].plot(x_values, qos1_stale, marker=marker, linestyle="-", color=color, label=f"{variant.upper()} qos1", alpha=0.8)

    axes[0, 0].set_title("Latency p95 by QoS")
    axes[0, 0].set_ylabel("Latency p95 (ms)")
    axes[0, 1].set_title("Downstream bytes by QoS")
    axes[0, 1].set_ylabel("Bytes out")
    axes[1, 0].set_title("Exact duplicates dropped by QoS")
    axes[1, 0].set_ylabel("Duplicate drops")
    axes[1, 1].set_title("Stale fraction by QoS")
    axes[1, 1].set_ylabel("Stale fraction")

    for axis in axes.flatten():
        axis.set_xticks(scenario_positions)
        axis.set_xticklabels(INTEL_BANDWIDTH_SCENARIOS, rotation=25, ha="right")
        axis.grid(True, axis="y", alpha=0.3)
    axes[0, 0].legend(loc="best", fontsize=8)
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
        f"During the outage phase, browser display samples whose display time fell in the phase dropped to {v0_row['outage_rendered_updates']} for V0 and "
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
    intel_qos_rows: list[dict[str, object]],
    intel_batch_rows: list[dict[str, object]] | None = None,
    intel_v1_v2_rows: list[dict[str, object]] | None = None,
    intel_adaptive_rows: list[dict[str, object]] | None = None,
    intel_adaptive_parameter_rows: list[dict[str, object]] | None = None,
) -> str:
    bandwidth_rows = _build_intel_bandwidth_vs_v0_rows(intel_rows)
    byte_claim_status = _byte_claim_status(bandwidth_rows)
    clean_v0 = _select_row(intel_rows, variant="v0", scenario="clean", mqtt_qos=0)
    clean_v2 = _select_row(intel_rows, variant="v2", scenario="clean", mqtt_qos=0)
    clean_v4 = _select_row(intel_rows, variant="v4", scenario="clean", mqtt_qos=0)
    outage_v0 = _select_row(intel_rows, variant="v0", scenario="outage_5s", mqtt_qos=1)
    outage_v2 = _select_row(intel_rows, variant="v2", scenario="outage_5s", mqtt_qos=1)
    outage_v4 = _select_row(intel_rows, variant="v4", scenario="outage_5s", mqtt_qos=1)
    baseline_demo = _load_demo_summary(demo_dir, "baseline")
    smart_demo = _load_demo_summary(demo_dir, "smart")

    qos1_duplicates = sum(int(row["qos1_duplicates_dropped"]) for row in intel_qos_rows)
    qos_msg_overhead_samples = [
        _parse_percent_label(row["gateway_mqtt_in_msgs_delta_pct"])
        for row in intel_qos_rows
        if row["gateway_mqtt_in_msgs_delta_pct"] != "n/a"
    ]
    avg_qos_msg_overhead = mean(qos_msg_overhead_samples) if qos_msg_overhead_samples else 0.0
    aot_clean_v0 = _select_row(aot_rows, variant="v0", scenario="clean", mqtt_qos=0)
    aot_clean_v4 = _select_row(aot_rows, variant="v4", scenario="clean", mqtt_qos=0)

    lines = [
        (
            f"- Section 7 byte-claim classification: `{byte_claim_status.get('fallback_wording', 'supported')}` "
            "Intel qos0 downstream payload bytes did not drop below V0 in the paper-ready bandwidth comparison: "
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
            f"- Intel qos0 versus qos1 explicit comparison now reports side-by-side deltas: V0 bytes changed by "
            f"{_format_qos_comparison_series(intel_qos_rows, variant='v0', delta_field='downstream_bytes_delta_pct')}; "
            f"V2 bytes changed by {_format_qos_comparison_series(intel_qos_rows, variant='v2', delta_field='downstream_bytes_delta_pct')}; "
            f"V4 bytes changed by {_format_qos_comparison_series(intel_qos_rows, variant='v4', delta_field='downstream_bytes_delta_pct')}."
        ),
        (
            f"- Exact duplicate-drop count across the Intel qos1 comparison matrix was {qos1_duplicates}, "
            f"with average MQTT-ingress overhead of {avg_qos_msg_overhead:.2f}% versus qos0."
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
    if intel_adaptive_parameter_rows is not None:
        adaptive_claim_status = _adaptive_claim_status(intel_adaptive_parameter_rows)
        supporting_rows = [
            row
            for row in intel_adaptive_parameter_rows
            if row["scenario_supports_positive_adaptive_claim"]
        ]
        lines.insert(
            4,
            (
                f"- Section 7 adaptive-claim classification: `{adaptive_claim_status.get('fallback_wording', 'supported')}` "
                f"The bounded V3 parameter sweep produced {len(supporting_rows)} scenario-level rows that met the window-adjustment, "
                "stability-improvement, latency, and byte guardrails. "
                "The paper-facing sweep summary is `report/assets/tables/intel_v3_adaptive_parameter_sweep.md`."
            ),
        )
    return "\n".join(lines) + "\n"


def _build_claim_guardrail_review(
    intel_rows: list[dict[str, object]],
    intel_qos_rows: list[dict[str, object]],
    intel_outage_freshness_rows: list[dict[str, object]],
    intel_adaptive_rows: list[dict[str, object]] | None = None,
    intel_adaptive_parameter_rows: list[dict[str, object]] | None = None,
) -> str:
    bandwidth_rows = _build_intel_bandwidth_vs_v0_rows(intel_rows)
    byte_claim_status = _byte_claim_status(bandwidth_rows)
    adaptive_claim_status = _adaptive_claim_status(intel_adaptive_parameter_rows or [])
    clean_v0 = _select_row(intel_rows, variant="v0", scenario="clean", mqtt_qos=0)
    clean_v4 = _select_row(intel_rows, variant="v4", scenario="clean", mqtt_qos=0)
    qos1_duplicates = sum(int(row["qos1_duplicates_dropped"]) for row in intel_qos_rows)

    table_rows = [
        {
            "guardrail": "Do not claim downstream byte reduction unless replicated bytes fall below V0 across the checklist threshold",
            "blocked_unbounded_claim": "Agrasandhani reduces downstream payload bytes.",
            "measured_evidence": (
                f"Replicated Intel byte-audit status is `{byte_claim_status['status']}`; "
                f"clean/V2 delta is {_format_bandwidth_comparison_series(bandwidth_rows, variant='v2', delta_field='downstream_bytes_delta_pct')}, "
                f"and clean/V4 delta is {_format_bandwidth_comparison_series(bandwidth_rows, variant='v4', delta_field='downstream_bytes_delta_pct')}."
            ),
            "safe_wording": byte_claim_status.get("fallback_wording", "Keep the byte claim variant-specific and explicitly replicated."),
        },
        {
            "guardrail": "Do not headline adaptive control unless the bounded sweep shows real adjustment plus 2-of-3 guarded wins",
            "blocked_unbounded_claim": "Adaptive control materially outperformed fixed-window batching.",
            "measured_evidence": (
                f"Default adaptive comparison rows cover {len(intel_adaptive_rows or [])} scenarios and bounded parameter-sweep status is "
                f"`{adaptive_claim_status['status']}`."
            ),
            "safe_wording": adaptive_claim_status.get(
                "fallback_wording",
                "Name the supporting config explicitly and keep the claim limited to the measured scenarios.",
            ),
        },
        {
            "guardrail": "Do not claim lower latency unless measured",
            "blocked_unbounded_claim": "Agrasandhani lowers latency overall.",
            "measured_evidence": (
                f"Intel clean qos0 p95 latency is {clean_v0['latency_p95_ms']} ms for V0 and "
                f"{clean_v4['latency_p95_ms']} ms for V4; latency increased on this path."
            ),
            "safe_wording": "V4 trades latency for stability and lower frame churn in this setup.",
        },
        {
            "guardrail": "Do not claim improved reliability unless reliability is defined",
            "blocked_unbounded_claim": "QoS1 improves reliability for this system in general.",
            "measured_evidence": (
                f"Intel qos1 exact duplicate-drop counter totals {qos1_duplicates} in the current local matrix; "
                "this does not define or quantify reliability as a broad property."
            ),
            "safe_wording": "In this local setup, qos0 and qos1 showed mixed latency deltas with zero observed exact duplicate drops.",
        },
        {
            "guardrail": "Do not claim reduced network loss",
            "blocked_unbounded_claim": "Agrasandhani reduces network packet loss.",
            "measured_evidence": (
                "The experiments use scenario-driven impairment injection and report application-level outcomes; "
                "no direct network-loss reduction metric is measured."
            ),
            "safe_wording": "The smart path provides graceful degradation and clearer dashboard behavior under the tested impairment scenarios.",
        },
        {
            "guardrail": "Use safer measured wording for bounded paper claims",
            "blocked_unbounded_claim": "Universal performance improvements across all metrics.",
            "measured_evidence": _describe_outage_freshness(intel_outage_freshness_rows),
            "safe_wording": (
                "Prefer bounded wording such as reduces downstream frame cadence, improves freshness visibility under degraded "
                "networks, reduces duplicate and redundant transmissions when measured, and provides graceful outage behavior."
            ),
        },
    ]

    columns = [
        "guardrail",
        "blocked_unbounded_claim",
        "measured_evidence",
        "safe_wording",
    ]
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join(["---"] * len(columns)) + " |"
    lines = [header, separator]
    for row in table_rows:
        lines.append("| " + " | ".join(str(row[column]) for column in columns) + " |")

    return (
        "# Intel Claim Guardrail Review\n\n"
        "This review blocks unbounded paper claims and ties each statement to measured evidence from the current local runs.\n\n"
        + "\n".join(lines)
        + "\n"
    )


def _build_claim_to_evidence_map(
    *,
    intel_sweep_dir: Path,
    batch_sweep_dir: Path | None = None,
    isolation_sweep_dir: Path | None = None,
    adaptive_sweep_dir: Path | None = None,
    adaptive_parameter_sweep_dir: Path | None = None,
) -> str:
    adaptive_source = (
        f"{adaptive_sweep_dir}/v2-qos0-*; {adaptive_sweep_dir}/v3-qos0-*"
        if adaptive_sweep_dir is not None
        else "report/assets/tables/intel_jitter_summary.csv"
    )
    adaptive_parameter_source = (
        f"; {adaptive_parameter_sweep_dir}/v3-qos0-*"
        if adaptive_parameter_sweep_dir is not None
        else ""
    )
    batch_source = (
        f"{batch_sweep_dir}/*/summary.json"
        if batch_sweep_dir is not None
        else "report/assets/tables/intel_v2_batch_window_tradeoff.csv"
    )
    isolation_source = (
        f"{isolation_sweep_dir}/*/summary.json"
        if isolation_sweep_dir is not None
        else "report/assets/tables/intel_v1_vs_v2_isolation.csv"
    )
    rows = [
        (
            "Smart gateway variants reduce downstream frame rate (~95-97%) vs naive forwarding and stabilize stream around outage/recovery.",
            "main_outage_frame_rate.png; intel_bandwidth_vs_v0.md",
            f"{intel_sweep_dir}/*/timeseries.csv; report/assets/tables/intel_bandwidth_vs_v0.csv",
            "experiments/build_report_assets.py",
        ),
        (
            "Proxy inter-frame gaps are the canonical jitter/stability source of truth; delay/jitter evidence is read from proxy sent-frame timing, not dashboard row cadence.",
            "intel_delay_qos0_inter_frame_gap_cdf.png; intel_jitter_summary.md",
            f"{intel_sweep_dir}/*/proxy_frame_log.csv; {adaptive_source}",
            "experiments/analyze_run.py; experiments/build_report_assets.py",
        ),
        (
            BYTE_CLAIM_FALLBACK_WORDING,
            "intel_bandwidth_vs_v0.md; main_outage_frame_rate.png",
            "report/assets/tables/intel_bandwidth_vs_v0.csv",
            "experiments/build_report_assets.py",
        ),
        (
            "Larger batch windows trade higher latency for fewer frames and different byte volume.",
            "intel_v2_batch_window_tradeoff.png; intel_v2_batch_window_tradeoff.md",
            batch_source,
            "experiments/run_batch_window_sweep.py; experiments/build_report_assets.py",
        ),
        (
            "Dedup/compaction had small or mixed effects beyond batching.",
            "intel_v1_vs_v2_isolation.png; intel_v1_vs_v2_isolation.md",
            isolation_source,
            "experiments/run_v1_v2_isolation_sweep.py; experiments/build_report_assets.py",
        ),
        (
            ADAPTIVE_CLAIM_FALLBACK_WORDING,
            "intel_v2_vs_v3_adaptive_impairment.png; intel_v2_vs_v3_adaptive_impairment.md; intel_v3_adaptive_parameter_sweep.md",
            "report/assets/tables/intel_v2_vs_v3_adaptive_impairment.csv; report/assets/tables/intel_v3_adaptive_parameter_sweep.csv",
            "experiments/run_adaptive_impairment_sweep.py; experiments/build_report_assets.py",
        ),
        (
            "Last-known-good improves visibility/retention but not freshness (age increases).",
            "intel_outage_qos0_v0_vs_v4_age_over_time.png; intel_outage_qos0_v0_vs_v4_freshness.md",
            f"{intel_sweep_dir}/v0-qos0-outage_5s/*; {intel_sweep_dir}/v4-qos0-outage_5s/*",
            "experiments/build_report_assets.py",
        ),
        (
            "QoS0 vs QoS1 produced minimal differences in this setup.",
            "intel_qos_comparison.png; intel_qos_comparison.md",
            "report/assets/tables/intel_qos_comparison.csv",
            "experiments/build_report_assets.py",
        ),
    ]
    lines = [
        "# Claim To Evidence Map",
        "",
        "Each major paper claim is mapped to generated artifacts, source data, and generation scripts.",
        "",
        "| Claim | Figure/Table | Source CSV/Log | Generated By |",
        "| --- | --- | --- | --- |",
    ]
    for claim, artifact, source, script in rows:
        lines.append(f"| {claim} | {artifact} | {source} | {script} |")
    lines.append("")
    return "\n".join(lines)


def _write_final_report(
    *,
    intel_sweep_dir: Path,
    aot_sweep_dir: Path,
    demo_dir: Path,
    intel_rows: list[dict[str, object]],
    aot_rows: list[dict[str, object]],
    intel_outage_freshness_rows: list[dict[str, object]],
    intel_qos_rows: list[dict[str, object]],
    intel_jitter_rows: list[dict[str, object]],
    intel_batch_rows: list[dict[str, object]] | None = None,
    intel_v1_v2_rows: list[dict[str, object]] | None = None,
    intel_adaptive_rows: list[dict[str, object]] | None = None,
    intel_adaptive_parameter_rows: list[dict[str, object]] | None = None,
) -> None:
    bandwidth_rows = _build_intel_bandwidth_vs_v0_rows(intel_rows)
    byte_claim_status = _byte_claim_status(bandwidth_rows)
    adaptive_claim_status = _adaptive_claim_status(intel_adaptive_parameter_rows or [])
    clean_v0 = _select_row(intel_rows, variant="v0", scenario="clean", mqtt_qos=0)
    clean_v4 = _select_row(intel_rows, variant="v4", scenario="clean", mqtt_qos=0)
    outage_v0 = _select_row(intel_rows, variant="v0", scenario="outage_5s", mqtt_qos=1)
    outage_v4 = _select_row(intel_rows, variant="v4", scenario="outage_5s", mqtt_qos=1)
    aot_clean_v0 = _select_row(aot_rows, variant="v0", scenario="clean", mqtt_qos=0)
    aot_clean_v4 = _select_row(aot_rows, variant="v4", scenario="clean", mqtt_qos=0)
    demo_baseline = _load_demo_summary(demo_dir, "baseline")
    demo_smart = _load_demo_summary(demo_dir, "smart")
    qos1_duplicates = sum(int(row["qos1_duplicates_dropped"]) for row in intel_qos_rows)

    report_text = f"""# Agrasandhani Final Report

## Abstract

Agrasandhani explores a local MQTT-to-WebSocket sensor pipeline that can either forward every message directly or apply batching, compaction, adaptive-capable flushing, and last-known-good freshness semantics. The final evaluation uses a real Intel Berkeley Lab replay as the primary workload, a smaller AoT validation replay, and a captured live demo. Across the Intel clean qos0 run, the raw baseline reached a latency p95 of {clean_v0['latency_p95_ms']} ms while V4 reached {clean_v4['latency_p95_ms']} ms, reflecting the deliberate latency-for-stability tradeoff introduced by batching and retained state. The explicit Intel qos0 bandwidth comparison did not show a downstream payload-byte reduction versus V0; Section 7 therefore locks the fallback wording `{byte_claim_status.get('fallback_wording', BYTE_CLAIM_FALLBACK_WORDING)}`. Under the Intel outage qos1 run, V4 reduced downstream frame count from {outage_v0['proxy_downstream_frames_out']} to {outage_v4['proxy_downstream_frames_out']} over the full outage_5s condition while keeping stale rows visible through the outage window, which made the live comparison materially easier to interpret.

## 1. Introduction

The project goal is to make bursty IoT replay traffic easier to visualize without losing the ability to trace timing and freshness behavior. MQTT remains a natural fit for lightweight sensing pipelines, but its QoS modes and duplicate semantics still require careful interpretation in downstream gateways [@mqtt311]. For broader pub/sub context, Kafka emphasizes log-oriented throughput and replay semantics rather than low-overhead device messaging [@kreps2011kafka], while later comparative work highlights how RabbitMQ and Kafka occupy different operating points in the reliability-throughput design space [@dobbelaere2017kafka]. For sensing-pipeline inspiration, SENSELET++ demonstrates the value of pairing sensing infrastructure with a reproducible visualization path [@tian2021senseletpp].

## 2. Workloads and Method

The primary evidence run is `{intel_sweep_dir.name}`. It uses a bounded slice of the Intel Berkeley Lab deployment data [@intelLabData] preprocessed into Agrasandhani's normalized replay schema, then runs `V0`, `V2`, and `V4` across `clean`, `bandwidth_200kbps`, `loss_2pct`, `delay_50ms_jitter20ms`, and `outage_5s` at MQTT QoS `0` and `1`. Each run uses a 30 second wall-clock replay, a 5x speedup, a 200-sensor target, and burst mode. The portability check is `{aot_sweep_dir.name}`, built from a bounded slice of the AoT weekly archive dataset [@aotCyberGIS] with a smaller validation matrix. The live demo evidence comes from `{demo_dir.parent.name}`.

For these evidence runs, impairments are injected on the gateway-to-dashboard last hop using the application-layer impairment proxy. Optional host-level shaping exists in the repository, but the reported downstream traffic metrics in this report are proxy-level outputs (`proxy_downstream_bytes_out`, `proxy_downstream_frames_out`).

### 2.1 Latency metrics

The paper standardizes on four latency summaries throughout the report assets: mean, p50, p95, and p99. p95 remains the headline comparison in the prose because it captures the high-end user-visible delay most directly, but the generated tables now carry the full set so the claims and metrics stay aligned with [experiments/analyze_run.py](../experiments/analyze_run.py).

### 2.2 Stability metrics and phase handling

The source-of-truth stability metric is the proxy-side inter-frame gap, defined as `diff(downstream_sent_ms)` over proxy `sent` events. The supporting stability signals are proxy frame-rate variability and the gateway's effective batch window, but the dashboard export itself is not treated as a frame clock because it is event-driven per rendered row. Phase-aware interpretation is scenario-driven: `clean` is analyzed as steady-state only; `bandwidth_200kbps`, `loss_2pct`, and `delay_50ms_jitter20ms` are treated as full-run impairment windows; and `outage_5s` preserves the explicit `steady-before-outage`, `outage`, and `recovery` phases from the scenario definition. The annotated outage cadence figure therefore remains the phase-aware visual for disruption and recovery, while the delay/jitter CDF acts as the compact whole-run jitter view for a full-run impairment case.

## 3. Results

The clean qos0 run shows the expected tradeoff. V0 preserves the most immediate delivery path with a p95 display latency of {clean_v0['latency_p95_ms']} ms, whereas V4 increases p95 latency to {clean_v4['latency_p95_ms']} ms in exchange for frame consolidation. This is visible in the latency CDF and the message-rate plots in [report/assets/figures/intel_clean_qos0_latency_cdf.png](assets/figures/intel_clean_qos0_latency_cdf.png) and [report/assets/figures/intel_outage_qos1_message_rate_over_time.png](assets/figures/intel_outage_qos1_message_rate_over_time.png).

The explicit Intel qos0 bandwidth comparison answers the first paper question directly. Compared with V0, V2 increased downstream payload bytes by {_format_bandwidth_comparison_series(bandwidth_rows, variant='v2', delta_field='downstream_bytes_delta_pct')}. V4 increased downstream payload bytes by {_format_bandwidth_comparison_series(bandwidth_rows, variant='v4', delta_field='downstream_bytes_delta_pct')}. Peak per-second downstream payload rate also moved upward rather than downward: V2 increased by {_format_bandwidth_comparison_series(bandwidth_rows, variant='v2', delta_field='max_bandwidth_delta_pct')}, while V4 increased by {_format_bandwidth_comparison_series(bandwidth_rows, variant='v4', delta_field='max_bandwidth_delta_pct')}. In this evidence set, the smart paths reduce render cadence and frame count rather than downstream payload-byte volume. Section 7 locks the byte-claim fallback wording `{byte_claim_status.get('fallback_wording', BYTE_CLAIM_FALLBACK_WORDING)}`. The paper-ready table for this claim is [report/assets/tables/intel_bandwidth_vs_v0.md](assets/tables/intel_bandwidth_vs_v0.md).

The new jitter summary table locks the proxy-side source of truth for stability and keeps the phase handling explicit. {_describe_delay_jitter_stability(intel_jitter_rows)} The compact artifacts for this phase are [report/assets/tables/intel_jitter_summary.md](assets/tables/intel_jitter_summary.md) and [report/assets/figures/intel_delay_qos0_inter_frame_gap_cdf.png](assets/figures/intel_delay_qos0_inter_frame_gap_cdf.png), while [report/assets/figures/main_outage_frame_rate.png](assets/figures/main_outage_frame_rate.png) remains the phase-annotated outage plot for steady-state, outage, and recovery.
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
The Intel V2 versus V3 adaptive impairment sweep answers the fourth paper question directly. Here, V2 is fixed-window batching and V3 is adaptive batching under the same base `250 ms` configuration. {" ".join(_describe_adaptive_scenario(intel_adaptive_rows, scenario) for scenario in INTEL_ADAPTIVE_SCENARIOS)} This is the right framing for the paper: the adaptive claim should be limited to the measured stale-fraction, cadence, and window-trace changes under these impairments, not generalized into a broader backlog or reliability claim. The paper-ready outputs for this task are [report/assets/tables/intel_v2_vs_v3_adaptive_impairment.md](assets/tables/intel_v2_vs_v3_adaptive_impairment.md) and [report/assets/figures/intel_v2_vs_v3_adaptive_impairment.png](assets/figures/intel_v2_vs_v3_adaptive_impairment.png).
"""
    if intel_adaptive_parameter_rows is not None:
        supporting_rows = [
            row for row in intel_adaptive_parameter_rows if row["scenario_supports_positive_adaptive_claim"]
        ]
        report_text += f"""
The bounded Section 7 V3-only parameter sweep compares each adaptive override set against the reused replicated V2 baseline from `{intel_sweep_dir.name}`-adjacent adaptive evidence. Across the tested grid, {len(supporting_rows)} scenario-level rows met the window-adjustment, stability-improvement, latency, and byte guardrails. Section 7 therefore locks the adaptive fallback wording `{adaptive_claim_status.get('fallback_wording', ADAPTIVE_CLAIM_FALLBACK_WORDING)}`. The paper-ready sweep summary is [report/assets/tables/intel_v3_adaptive_parameter_sweep.md](assets/tables/intel_v3_adaptive_parameter_sweep.md).
"""
    report_text += f"""
The Intel qos0 outage freshness trace answers the fifth paper question directly. For this task, the paper-ready freshness signal is age-of-information over time rather than stale-fraction over time, because the current dashboard export records age only on rendered updates and does not sample idle stale transitions between renders. {_describe_outage_freshness(intel_outage_freshness_rows)} The end-state `staleCount` and `latestRowCount` values remain useful supporting context, but the primary evidence is the age trace in [report/assets/figures/intel_outage_qos0_v0_vs_v4_age_over_time.png](assets/figures/intel_outage_qos0_v0_vs_v4_age_over_time.png) together with the compact summary table [report/assets/tables/intel_outage_qos0_v0_vs_v4_freshness.md](assets/tables/intel_outage_qos0_v0_vs_v4_freshness.md).

The Intel qos0 versus qos1 comparison answers the next paper-readiness question directly with a side-by-side table and figure. Across the Intel matrix (`v0`, `v2`, `v4` by `clean`, `bandwidth_200kbps`, `loss_2pct`, and `outage_5s`), the measured exact duplicate-drop counter for qos1 stayed at {qos1_duplicates}. QoS1 versus QoS0 downstream bytes changed by {_format_qos_comparison_series(intel_qos_rows, variant='v0', delta_field='downstream_bytes_delta_pct')} for V0, {_format_qos_comparison_series(intel_qos_rows, variant='v2', delta_field='downstream_bytes_delta_pct')} for V2, and {_format_qos_comparison_series(intel_qos_rows, variant='v4', delta_field='downstream_bytes_delta_pct')} for V4. Latency p95 deltas are captured in the same table so the paper can make a bounded statement about observed setup-specific behavior rather than asserting broader reliability guarantees. The paper-ready outputs for this task are [report/assets/tables/intel_qos_comparison.md](assets/tables/intel_qos_comparison.md) and [report/assets/figures/intel_qos_comparison.png](assets/figures/intel_qos_comparison.png).

The condensed summary table now provides a compact scan view across `v0`, `v2`, and `v4` on `clean`, `bandwidth_200kbps`, `loss_2pct`, and `outage_5s` under qos0, with latency mean, p50, p95, p99, downstream frames, downstream bytes, and stale fraction in one place. This is the paper-facing quick-read table at [report/assets/tables/intel_condensed_summary.md](assets/tables/intel_condensed_summary.md).

The proxy-side jitter summary table complements that condensed view by carrying the inter-frame-gap sample count, mean, p50, p95, p99, standard deviation, proxy frame-rate standard deviation, and effective batch window for the Intel primary matrix plus the targeted adaptive sweep. This keeps the Section 5 stability treatment tied to raw proxy timing without rewriting the frozen run roots.

The explicit claim-guardrail review is captured in [report/assets/tables/intel_claim_guardrail_review.md](assets/tables/intel_claim_guardrail_review.md). It blocks unbounded claims about latency, reliability, and network-loss reduction unless directly measured and defined in this setup, and it records safer bounded wording that matches the measured evidence.
"""
    report_text += """

The main outage frame-rate figure is [report/assets/figures/main_outage_frame_rate.png](assets/figures/main_outage_frame_rate.png), and it is the paper's primary outage result. Read in continuity terms, the figure shows that V0 stays burstier and more variable through the outage window, while V2 and V4 compress the stream into a steadier, lower-cadence display that keeps the dashboard easier to track during outage and recovery. V4 is the most aggressive at stabilizing cadence, but the interpretation is not that it increases throughput; it is that the smart gateway makes the outage visually manageable by trading raw frame frequency for continuity.

The outage bandwidth-over-time trace is [report/assets/figures/intel_outage_qos1_bandwidth_over_time.png](assets/figures/intel_outage_qos1_bandwidth_over_time.png). It is useful for seeing when downstream payload bytes are emitted during the outage and recovery window, but it should not be read as evidence of a payload-byte reduction. That interpretation stays consistent with [report/assets/tables/intel_bandwidth_vs_v0.md](assets/tables/intel_bandwidth_vs_v0.md), where V2 and V4 both increase downstream bytes versus V0 in every Intel qos0 scenario, including outage_5s.

"""
    report_text += f"""

The outage qos1 run makes the UI tradeoff clearer. V0 emitted {outage_v0['proxy_downstream_frames_out']} downstream frames, while V4 emitted {outage_v4['proxy_downstream_frames_out']}. At the same time, V4's aggregate envelopes pushed downstream bytes from {outage_v0['proxy_downstream_bytes_out']} in V0 to {outage_v4['proxy_downstream_bytes_out']} in V4. The result is not a blanket bandwidth win; it is a cadence and interpretability win. This is the right framing for the project, and it avoids overselling aggregate framing as a byte-minimization technique.

The broker-backed QoS1 runs did not trigger large duplicate counts in this local setup. In fact, the measured exact duplicate-drop counter remained at {qos1_duplicates} across the Intel primary QoS1 matrix, so the QoS discussion in this report is necessarily cautious. The final claims here concern observed end-to-end behavior in this environment rather than a general statement that QoS1 duplicates are common in every deployment.

AoT provides a smaller portability check rather than the main performance claim set. On the clean qos0 validation run, V0 reached a p95 latency of {aot_clean_v0['latency_p95_ms']} ms and emitted {aot_clean_v0['proxy_downstream_frames_out']} frames, while V4 reached {aot_clean_v4['latency_p95_ms']} ms and emitted {aot_clean_v4['proxy_downstream_frames_out']} frames. That result is directionally consistent with the Intel evidence and shows that the smart path remains operational on a second public source.

The demo evidence captures the qualitative effect directly. The final captured baseline dashboard ended with frameCount={demo_baseline['frameCount']}, staleCount={demo_baseline['staleCount']}, and latestRowCount={demo_baseline['latestRowCount']}, while the smart dashboard ended with frameCount={demo_smart['frameCount']}, staleCount={demo_smart['staleCount']}, and latestRowCount={demo_smart['latestRowCount']}. Both sides surfaced stale rows during the outage window, but the V4 side did so with far fewer rendered frames and a larger retained latest-row set in the captured end state. The screenshots in [report/assets/figures/final_demo_compare.png](assets/figures/final_demo_compare.png), [report/assets/figures/final_demo_baseline_dashboard.png](assets/figures/final_demo_baseline_dashboard.png), and [report/assets/figures/final_demo_smart_dashboard.png](assets/figures/final_demo_smart_dashboard.png) are the evidence for that claim.

## 4. Discussion

The final evidence supports a narrow conclusion. Agrasandhani's smart path is useful when the operator values stable rendering and last-known-good freshness cues more than minimum per-message latency. The data does not support a blanket claim that V4 minimizes downstream bytes, so the byte story remains `{byte_claim_status.get('fallback_wording', BYTE_CLAIM_FALLBACK_WORDING)}`. The adaptive story also remains `{adaptive_claim_status.get('fallback_wording', ADAPTIVE_CLAIM_FALLBACK_WORDING)}`. The QoS1 experiments in this local broker configuration do not justify a strong empirical duplicate-rate claim beyond the measured counters. Those are acceptable limits for a six-page project report because the central contribution is the observable baseline-versus-smart tradeoff, not a universal broker benchmark.

## 5. Reproducibility and Deliverables

Report assets under `report/assets/` are regenerated from ignored local logs via `experiments/build_report_assets.py`, and the exact local run commands are captured in `experiments/logs/final-deliverables-*/manifest.json`. The remote setup and rerun instructions live in the root README; generated report notes may also be kept locally under `report/`.

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
    intel_adaptive_parameter_sweep_dir: Path | None = None,
) -> None:
    freshness_summary_tables = ", [report/assets/tables/intel_outage_qos0_v0_vs_v4_freshness.csv](assets/tables/intel_outage_qos0_v0_vs_v4_freshness.csv), [report/assets/tables/intel_outage_qos0_v0_vs_v4_freshness.md](assets/tables/intel_outage_qos0_v0_vs_v4_freshness.md), [report/assets/figures/intel_outage_qos0_v0_vs_v4_age_over_time.png](assets/figures/intel_outage_qos0_v0_vs_v4_age_over_time.png)"
    condensed_summary_tables = ", [report/assets/tables/intel_condensed_summary.csv](assets/tables/intel_condensed_summary.csv), [report/assets/tables/intel_condensed_summary.md](assets/tables/intel_condensed_summary.md)"
    jitter_summary_tables = ", [report/assets/tables/intel_jitter_summary.csv](assets/tables/intel_jitter_summary.csv), [report/assets/tables/intel_jitter_summary.md](assets/tables/intel_jitter_summary.md), [report/assets/figures/intel_delay_qos0_inter_frame_gap_cdf.png](assets/figures/intel_delay_qos0_inter_frame_gap_cdf.png), [report/assets/figures/main_outage_frame_rate.png](assets/figures/main_outage_frame_rate.png)"
    guardrail_summary_tables = ", [report/assets/tables/intel_claim_guardrail_review.md](assets/tables/intel_claim_guardrail_review.md)"
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
    adaptive_parameter_sweep_line = ""
    adaptive_parameter_summary_tables = ""
    if intel_adaptive_parameter_sweep_dir is not None:
        adaptive_parameter_sweep_line = (
            f"- Intel V3 adaptive parameter sweep run id: `{intel_adaptive_parameter_sweep_dir.name}` at "
            f"`{intel_adaptive_parameter_sweep_dir}`\n"
        )
        adaptive_parameter_summary_tables = (
            ", [report/assets/tables/intel_v3_adaptive_parameter_sweep.csv](assets/tables/intel_v3_adaptive_parameter_sweep.csv), "
            "[report/assets/tables/intel_v3_adaptive_parameter_sweep.md](assets/tables/intel_v3_adaptive_parameter_sweep.md)"
        )
    content = f"""# Deliverable Completion Gate

## M1-M3 System Path

- Replay simulator and preprocessors: [simulator/replay_publisher.py](../simulator/replay_publisher.py), [simulator/preprocess_intel_lab.py](../simulator/preprocess_intel_lab.py), [simulator/preprocess_aot.py](../simulator/preprocess_aot.py)
- Gateway and dashboard path: [gateway/app.py](../gateway/app.py), [ui/index.html](../ui/index.html)
- Impairment and experiment harnesses: [experiments/impairment_proxy.py](../experiments/impairment_proxy.py), [experiments/run_sweep.py](../experiments/run_sweep.py), [experiments/run_demo.py](../experiments/run_demo.py)

## M4 Evidence Path

- Intel primary sweep run id: `{intel_sweep_dir.name}` at `{intel_sweep_dir}`
- AoT validation run id: `{aot_sweep_dir.name}` at `{aot_sweep_dir}`
- Demo capture run id: `{demo_dir.parent.name}` at `{demo_dir}`
{batch_sweep_line}{isolation_sweep_line}{adaptive_sweep_line}{adaptive_parameter_sweep_line}- Final evidence manifest: [report/assets/evidence_manifest.json](assets/evidence_manifest.json)
- Final summary tables: [report/assets/tables/intel_primary_run_summary.csv](assets/tables/intel_primary_run_summary.csv), [report/assets/tables/intel_bandwidth_vs_v0.csv](assets/tables/intel_bandwidth_vs_v0.csv), [report/assets/tables/intel_bandwidth_vs_v0.md](assets/tables/intel_bandwidth_vs_v0.md), [report/assets/tables/intel_qos_comparison.csv](assets/tables/intel_qos_comparison.csv), [report/assets/tables/intel_qos_comparison.md](assets/tables/intel_qos_comparison.md), [report/assets/figures/intel_qos_comparison.png](assets/figures/intel_qos_comparison.png){freshness_summary_tables}{batch_summary_tables}{isolation_summary_tables}{adaptive_summary_tables}{adaptive_parameter_summary_tables}{condensed_summary_tables}{jitter_summary_tables}{guardrail_summary_tables}, [report/assets/tables/aot_validation_summary.csv](assets/tables/aot_validation_summary.csv), [report/assets/tables/intel_key_claims.md](assets/tables/intel_key_claims.md), [report/assets/CLAIM_TO_EVIDENCE_MAP.md](assets/CLAIM_TO_EVIDENCE_MAP.md)
- Final figures: [report/assets/figures](assets/figures)

## M5 Deliverables

- Final runner: [experiments/run_final_deliverables.py](../experiments/run_final_deliverables.py)
- Report asset builder: [experiments/build_report_assets.py](../experiments/build_report_assets.py)
- Remote reproducibility instructions: [README.md](../README.md)
- Local generated report draft: [report/final_report.md](final_report.md)
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
    intel_adaptive_parameter_sweep_dir: Path | None = None,
) -> dict[str, object]:
    intel_trial_rows = load_summary_rows(intel_sweep_dir)
    aot_trial_rows = load_summary_rows(aot_sweep_dir)
    intel_rows = aggregate_summary_rows(intel_trial_rows)
    aot_rows = aggregate_summary_rows(aot_trial_rows)
    bandwidth_rows = _build_intel_bandwidth_vs_v0_rows(intel_rows)
    intel_qos_rows = _build_intel_qos_comparison_rows(intel_rows)
    intel_condensed_rows = _build_intel_condensed_summary_rows(intel_rows)
    intel_main_summary_rows = _build_intel_main_summary_rows(intel_rows)
    intel_outage_freshness_rows = _build_intel_outage_freshness_rows(intel_rows)
    intel_batch_rows = (
        _build_intel_batch_window_tradeoff_rows(aggregate_summary_rows(load_summary_rows(intel_batch_sweep_dir)))
        if intel_batch_sweep_dir is not None
        else None
    )
    intel_v1_v2_rows = (
        _build_intel_v1_v2_isolation_rows(aggregate_summary_rows(load_summary_rows(intel_v1_v2_sweep_dir)))
        if intel_v1_v2_sweep_dir is not None
        else None
    )
    intel_adaptive_trial_rows = load_summary_rows(intel_adaptive_sweep_dir) if intel_adaptive_sweep_dir is not None else None
    intel_adaptive_source_rows = (
        aggregate_summary_rows(intel_adaptive_trial_rows)
        if intel_adaptive_trial_rows is not None
        else None
    )
    intel_adaptive_rows = (
        _build_intel_adaptive_rows(intel_adaptive_source_rows)
        if intel_adaptive_source_rows is not None
        else None
    )
    intel_adaptive_parameter_source_rows = (
        aggregate_summary_rows(load_summary_rows(intel_adaptive_parameter_sweep_dir))
        if intel_adaptive_parameter_sweep_dir is not None
        else None
    )
    intel_adaptive_parameter_rows = (
        _build_intel_v3_adaptive_parameter_sweep_rows(intel_adaptive_source_rows, intel_adaptive_parameter_source_rows)
        if intel_adaptive_source_rows is not None and intel_adaptive_parameter_source_rows is not None
        else None
    )
    intel_jitter_rows = _build_intel_jitter_summary_rows(
        intel_rows,
        intel_sweep_dir=intel_sweep_dir,
        adaptive_rows=intel_adaptive_source_rows,
        adaptive_sweep_dir=intel_adaptive_sweep_dir,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    figures_dir = output_dir / "figures"
    tables_dir = output_dir / "tables"
    figures_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    _write_csv(tables_dir / "intel_primary_run_summary.csv", intel_trial_rows)
    _write_csv(tables_dir / "aot_validation_summary.csv", aot_trial_rows)
    _write_csv(tables_dir / "intel_bandwidth_vs_v0.csv", bandwidth_rows)
    _write_csv(tables_dir / "intel_qos_comparison.csv", intel_qos_rows)
    _write_csv(tables_dir / "intel_condensed_summary.csv", intel_condensed_rows)
    _write_csv(tables_dir / "intel_main_summary_table.csv", intel_main_summary_rows)
    _write_csv(tables_dir / "intel_outage_qos0_v0_vs_v4_freshness.csv", intel_outage_freshness_rows)
    _write_csv(tables_dir / "intel_jitter_summary.csv", intel_jitter_rows)
    _write_markdown_table(
        tables_dir / "intel_primary_run_summary.md",
        intel_trial_rows,
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
        tables_dir / "intel_jitter_summary.md",
        intel_jitter_rows,
        columns=[
            "source_sweep",
            "comparison_family",
            "variant",
            "scenario",
            "mqtt_qos",
            "proxy_inter_frame_gap_sample_count",
            "proxy_inter_frame_gap_mean_ms",
            "proxy_inter_frame_gap_p50_ms",
            "proxy_inter_frame_gap_p95_ms",
            "proxy_inter_frame_gap_p99_ms",
            "proxy_inter_frame_gap_stddev_ms",
            "proxy_frame_rate_stddev_per_s",
            "effective_batch_window_ms",
            "max_frame_rate_per_s",
            "run_dir",
        ],
    )
    _write_markdown_table(
        tables_dir / "intel_bandwidth_vs_v0.md",
        bandwidth_rows,
        columns=[
            "scenario",
            "variant",
            "baseline_n",
            "variant_n",
            "baseline_downstream_bytes_out",
            "baseline_downstream_bytes_out_stddev",
            "variant_downstream_bytes_out",
            "variant_downstream_bytes_out_stddev",
            "downstream_bytes_delta_pct",
            "shared_impairment_seeds",
            "trial_byte_delta_pcts",
            "trial_direction_consistent",
            "scenario_byte_claim_classification",
            "baseline_max_bandwidth_bytes_per_s",
            "baseline_max_bandwidth_bytes_per_s_stddev",
            "variant_max_bandwidth_bytes_per_s",
            "variant_max_bandwidth_bytes_per_s_stddev",
            "max_bandwidth_delta_pct",
            "baseline_downstream_frames_out",
            "baseline_downstream_frames_out_stddev",
            "variant_downstream_frames_out",
            "variant_downstream_frames_out_stddev",
            "downstream_frames_delta_pct",
            "baseline_latency_mean_ms",
            "baseline_latency_p50_ms",
            "baseline_latency_p95_ms",
            "baseline_latency_p95_ms_stddev",
            "baseline_latency_p99_ms",
            "variant_latency_mean_ms",
            "variant_latency_p50_ms",
            "variant_latency_p95_ms",
            "variant_latency_p95_ms_stddev",
            "variant_latency_p99_ms",
        ],
    )
    _write_markdown_table(
        tables_dir / "intel_qos_comparison.md",
        intel_qos_rows,
        columns=[
            "scenario",
            "variant",
            "qos0_latency_mean_ms",
            "qos0_latency_p50_ms",
            "qos0_latency_p95_ms",
            "qos0_latency_p99_ms",
            "qos1_latency_mean_ms",
            "qos1_latency_p50_ms",
            "qos1_latency_p95_ms",
            "qos1_latency_p99_ms",
            "latency_p95_delta_ms",
            "qos0_duplicates_dropped",
            "qos1_duplicates_dropped",
            "qos0_gateway_mqtt_in_msgs",
            "qos1_gateway_mqtt_in_msgs",
            "gateway_mqtt_in_msgs_delta_pct",
            "qos0_proxy_downstream_bytes_out",
            "qos1_proxy_downstream_bytes_out",
            "downstream_bytes_delta_pct",
            "qos0_proxy_downstream_frames_out",
            "qos1_proxy_downstream_frames_out",
            "downstream_frames_delta_pct",
            "qos0_stale_fraction",
            "qos1_stale_fraction",
            "stale_fraction_delta",
            "qos0_run_dir",
            "qos1_run_dir",
        ],
    )
    _write_markdown_table(
        tables_dir / "intel_condensed_summary.md",
        intel_condensed_rows,
        columns=[
            "variant",
            "scenario",
            "mqtt_qos",
            "latency_mean_ms",
            "latency_p50_ms",
            "latency_p95_ms",
            "latency_p99_ms",
            "proxy_downstream_frames_out",
            "proxy_downstream_bytes_out",
            "stale_fraction",
        ],
    )
    _write_markdown_table(
        tables_dir / "intel_main_summary_table.md",
        intel_main_summary_rows,
        columns=[
            "Variant",
            "Downstream Frames",
            "Downstream Bytes",
            "Latency mean",
            "Latency p50",
            "Latency p95",
            "Latency p99",
            "Stale Fraction",
            "Scenario",
        ],
    )
    if intel_batch_rows is not None:
        _write_csv(tables_dir / "intel_v2_batch_window_tradeoff.csv", intel_batch_rows)
        _write_markdown_table(
            tables_dir / "intel_v2_batch_window_tradeoff.md",
            intel_batch_rows,
            columns=[
                "batch_window_ms",
                "latency_mean_ms",
                "latency_p50_ms",
                "latency_p95_ms",
                "latency_p99_ms",
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
                "v1_latency_mean_ms",
                "v1_latency_p50_ms",
                "v1_latency_p95_ms",
                "v1_latency_p99_ms",
                "v2_latency_mean_ms",
                "v2_latency_p50_ms",
                "v2_latency_p95_ms",
                "v2_latency_p99_ms",
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
                "v2_n",
                "v3_n",
                "v2_latency_mean_ms",
                "v2_latency_p50_ms",
                "v2_latency_p95_ms",
                "v2_latency_p99_ms",
                "v3_latency_mean_ms",
                "v3_latency_p50_ms",
                "v3_latency_p95_ms",
                "v3_latency_p99_ms",
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
                "v2_proxy_inter_frame_gap_stddev_ms",
                "v3_proxy_inter_frame_gap_stddev_ms",
                "inter_frame_gap_stddev_delta_ms",
                "v2_proxy_frame_rate_stddev_per_s",
                "v3_proxy_frame_rate_stddev_per_s",
                "frame_rate_stddev_delta_per_s",
                "v3_adaptive_window_increase_events",
                "v3_adaptive_window_decrease_events",
                "stability_improvement_metrics",
                "v3_last_adaptation_reasons",
                "window_adjusted",
                "stability_improved",
                "latency_guardrail_ok",
                "byte_guardrail_ok",
                "scenario_supports_positive_adaptive_claim",
                "v2_run_dir",
                "v3_run_dir",
            ],
        )
    if intel_adaptive_parameter_rows is not None:
        _write_csv(tables_dir / "intel_v3_adaptive_parameter_sweep.csv", intel_adaptive_parameter_rows)
        _write_markdown_table(
            tables_dir / "intel_v3_adaptive_parameter_sweep.md",
            intel_adaptive_parameter_rows,
            columns=[
                "config_id",
                "scenario",
                "adaptive_send_slow_ms",
                "adaptive_step_up_ms",
                "adaptive_max_batch_window_ms",
                "baseline_v2_n",
                "v3_n",
                "baseline_v2_latency_p95_ms",
                "v3_latency_p95_ms",
                "latency_p95_delta_pct",
                "baseline_v2_proxy_downstream_bytes_out",
                "v3_proxy_downstream_bytes_out",
                "downstream_bytes_delta_pct",
                "baseline_v2_proxy_inter_frame_gap_stddev_ms",
                "v3_proxy_inter_frame_gap_stddev_ms",
                "inter_frame_gap_stddev_delta_ms",
                "baseline_v2_proxy_frame_rate_stddev_per_s",
                "v3_proxy_frame_rate_stddev_per_s",
                "frame_rate_stddev_delta_per_s",
                "v3_min_effective_batch_window_ms",
                "v3_max_effective_batch_window_ms",
                "v3_adaptive_window_increase_events",
                "v3_adaptive_window_decrease_events",
                "stability_improvement_metrics",
                "v3_last_adaptation_reasons",
                "window_adjusted",
                "stability_improved",
                "latency_guardrail_ok",
                "byte_guardrail_ok",
                "scenario_supports_positive_adaptive_claim",
            ],
        )
    (tables_dir / "intel_key_claims.md").write_text(
        _build_key_claims(
            intel_rows,
            aot_rows,
            demo_dir,
            intel_outage_freshness_rows,
            intel_qos_rows,
            intel_batch_rows,
            intel_v1_v2_rows,
            intel_adaptive_rows,
            intel_adaptive_parameter_rows,
        ),
        encoding="utf-8",
    )
    (tables_dir / "intel_claim_guardrail_review.md").write_text(
        _build_claim_guardrail_review(
            intel_rows,
            intel_qos_rows,
            intel_outage_freshness_rows,
            intel_adaptive_rows,
            intel_adaptive_parameter_rows,
        ),
        encoding="utf-8",
    )

    _plot_latency_cdf(
        intel_rows,
        scenario="clean",
        mqtt_qos=0,
        output_path=figures_dir / "intel_clean_qos0_latency_cdf.png",
    )
    _plot_inter_frame_gap_cdf(
        intel_rows,
        scenario="delay_50ms_jitter20ms",
        mqtt_qos=0,
        output_path=figures_dir / "intel_delay_qos0_inter_frame_gap_cdf.png",
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
    _plot_main_outage_frame_rate(
        intel_rows,
        output_path=figures_dir / "main_outage_frame_rate.png",
    )
    _plot_qos_comparison(
        intel_qos_rows,
        output_path=figures_dir / "intel_qos_comparison.png",
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
    old_evidence_inventory = _build_old_evidence_inventory(
        intel_sweep_dir=intel_sweep_dir,
        aot_sweep_dir=aot_sweep_dir,
        demo_dir=demo_dir,
        intel_batch_sweep_dir=intel_batch_sweep_dir,
        intel_v1_v2_sweep_dir=intel_v1_v2_sweep_dir,
        intel_adaptive_sweep_dir=intel_adaptive_sweep_dir,
        intel_adaptive_parameter_sweep_dir=intel_adaptive_parameter_sweep_dir,
        intel_rows=intel_rows,
        aot_rows=aot_rows,
        intel_batch_rows=intel_batch_rows,
        intel_v1_v2_rows=intel_v1_v2_rows,
        intel_adaptive_rows=intel_adaptive_rows,
        intel_adaptive_parameter_rows=intel_adaptive_parameter_rows,
    )
    old_evidence_inventory["compatibility_mirror_of"] = _canonical_report_asset_path("evidence_manifest.json")
    (output_dir / "old_evidence_inventory.json").write_text(
        json.dumps(old_evidence_inventory, indent=2),
        encoding="utf-8",
    )
    (output_dir / "CLAIM_TO_EVIDENCE_MAP.md").write_text(
        _build_claim_to_evidence_map(
            intel_sweep_dir=intel_sweep_dir,
            batch_sweep_dir=intel_batch_sweep_dir,
            isolation_sweep_dir=intel_v1_v2_sweep_dir,
            adaptive_sweep_dir=intel_adaptive_sweep_dir,
            adaptive_parameter_sweep_dir=intel_adaptive_parameter_sweep_dir,
        ),
        encoding="utf-8",
    )

    manifest = {
        "schema_version": 2,
        "intel_sweep_dir": str(intel_sweep_dir),
        "aot_sweep_dir": str(aot_sweep_dir),
        "demo_dir": str(demo_dir),
        "intel_batch_sweep_dir": str(intel_batch_sweep_dir) if intel_batch_sweep_dir is not None else None,
        "intel_v1_v2_sweep_dir": str(intel_v1_v2_sweep_dir) if intel_v1_v2_sweep_dir is not None else None,
        "intel_adaptive_sweep_dir": str(intel_adaptive_sweep_dir) if intel_adaptive_sweep_dir is not None else None,
        "intel_adaptive_parameter_sweep_dir": (
            str(intel_adaptive_parameter_sweep_dir)
            if intel_adaptive_parameter_sweep_dir is not None
            else None
        ),
        "intel_runs": [row["run_id"] for row in intel_trial_rows],
        "aot_runs": [row["run_id"] for row in aot_trial_rows],
        "run_registry_path": _canonical_logs_path("run_registry.json"),
        "old_evidence_inventory_path": _canonical_report_asset_path("old_evidence_inventory.json"),
        "claim_map_path": _canonical_report_asset_path("CLAIM_TO_EVIDENCE_MAP.md"),
        "asset_provenance": old_evidence_inventory["entries"],
        "generated_figures": [
            str(Path(entry["asset_path"]))
            for entry in old_evidence_inventory["entries"]
            if entry["asset_path"].startswith("report/assets/figures/")
        ],
        "generated_tables": [
            str(Path(entry["asset_path"]))
            for entry in old_evidence_inventory["entries"]
            if entry["asset_path"].startswith("report/assets/tables/")
        ],
    }
    (output_dir / "evidence_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    _write_final_report(
        intel_sweep_dir=intel_sweep_dir,
        aot_sweep_dir=aot_sweep_dir,
        demo_dir=demo_dir,
        intel_rows=intel_rows,
        aot_rows=aot_rows,
        intel_outage_freshness_rows=intel_outage_freshness_rows,
        intel_qos_rows=intel_qos_rows,
        intel_jitter_rows=intel_jitter_rows,
        intel_batch_rows=intel_batch_rows,
        intel_v1_v2_rows=intel_v1_v2_rows,
        intel_adaptive_rows=intel_adaptive_rows,
        intel_adaptive_parameter_rows=intel_adaptive_parameter_rows,
    )
    _write_deliverable_gate(
        intel_sweep_dir=intel_sweep_dir,
        aot_sweep_dir=aot_sweep_dir,
        demo_dir=demo_dir,
        output_dir=output_dir,
        intel_batch_sweep_dir=intel_batch_sweep_dir,
        intel_v1_v2_sweep_dir=intel_v1_v2_sweep_dir,
        intel_adaptive_sweep_dir=intel_adaptive_sweep_dir,
        intel_adaptive_parameter_sweep_dir=intel_adaptive_parameter_sweep_dir,
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
    parser.add_argument("--intel-adaptive-parameter-sweep-dir", type=Path)
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
        intel_adaptive_parameter_sweep_dir=args.intel_adaptive_parameter_sweep_dir,
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
