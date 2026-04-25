from __future__ import annotations

import argparse
import json
import math
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments import run_replicated_phase6
from experiments import run_v3_adaptive_parameter_sweep as parameter_sweep
from experiments.run_demo import run_demo, validate_environment as validate_demo_environment
from experiments.run_final_deliverables import build_demo_config
from experiments.sweep_aggregation import load_summary_rows

BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_ROOT = BASE_DIR / "experiments" / "logs"
DEFAULT_FROZEN_MANIFEST = BASE_DIR / "report" / "assets" / "evidence_manifest.json"
REPORT_PREFIX = "replicated-equivalence"

SWEEP_ROOT_KEYS = {
    "intel_primary": "intel_sweep_dir",
    "aot_validation": "aot_sweep_dir",
    "intel_v2_batch_window": "intel_batch_sweep_dir",
    "intel_v1_v2_isolation": "intel_v1_v2_sweep_dir",
    "intel_v2_vs_v3_adaptive": "intel_adaptive_sweep_dir",
    "intel_v3_adaptive_parameter_sweep": "intel_adaptive_parameter_sweep_dir",
}

PHASE6_SWEEP_NAMES = {
    "intel_primary",
    "aot_validation",
    "intel_v2_batch_window",
    "intel_v1_v2_isolation",
    "intel_v2_vs_v3_adaptive",
}

DEMO_ARTIFACTS = (
    "manifest.json",
    "demo_compare.png",
    "baseline_dashboard/dashboard_measurements.csv",
    "baseline_dashboard/dashboard_summary.json",
    "baseline_dashboard/dashboard.png",
    "smart_dashboard/dashboard_measurements.csv",
    "smart_dashboard/dashboard_summary.json",
    "smart_dashboard/dashboard.png",
)

CONDITION_EXACT_FIELDS = (
    "condition_id",
    "variant",
    "scenario",
    "mqtt_qos",
    "batch_window_ms",
    "adaptive_send_slow_ms",
    "adaptive_step_up_ms",
    "adaptive_step_down_ms",
    "adaptive_min_batch_window_ms",
    "adaptive_max_batch_window_ms",
    "adaptive_queue_high_watermark",
    "adaptive_queue_low_watermark",
    "adaptive_recovery_streak",
    "n",
    "trial_ids",
    "trial_indices",
    "impairment_seeds",
    "schema_version",
)

SUMMARY_EXACT_FIELDS = (
    "condition_id",
    "trial_id",
    "trial_index",
    "impairment_seed",
    "variant",
    "scenario",
    "mqtt_qos",
    "batch_window_ms",
    "adaptive_send_slow_ms",
    "adaptive_step_up_ms",
    "adaptive_step_down_ms",
    "adaptive_min_batch_window_ms",
    "adaptive_max_batch_window_ms",
    "adaptive_queue_high_watermark",
    "adaptive_queue_low_watermark",
    "adaptive_recovery_streak",
    "schema_version",
)

DEMO_MANIFEST_EXACT_FIELDS = (
    "scenario_name",
    "scenario_total_duration_s",
    "duration_s",
    "replay_speed",
    "sensor_limit",
    "mqtt_qos",
    "burst_enabled",
    "burst_start_s",
    "burst_duration_s",
    "burst_speed_multiplier",
    "capture_artifacts",
)

PATH_FIELDS = {
    "run_dir",
    "summary_path",
    "trial_run_dirs",
    "trial_summary_paths",
    "data_file",
    "compare_url",
    "artifact_paths",
    "services",
}


@dataclass(slots=True)
class CheckResult:
    name: str
    status: str
    blocking_findings: list[str]
    notes: list[str]
    additive_fields: list[str]
    largest_metric_deltas: list[dict[str, object]]
    details: dict[str, object]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(BASE_DIR).as_posix()
    except ValueError:
        return path.as_posix()


def _resolve_repo_path(raw_path: str | Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return BASE_DIR / path


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _field_union(rows: Iterable[dict[str, Any]]) -> set[str]:
    fields: set[str] = set()
    for row in rows:
        fields.update(row)
    return fields


def _summary_key(row: dict[str, Any]) -> tuple[str, str]:
    condition_id = str(row.get("condition_id", ""))
    trial_id = row.get("trial_id")
    if trial_id is not None:
        return condition_id, str(trial_id)
    return condition_id, str(row.get("run_id", ""))


def _conditions_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    conditions = payload.get("conditions")
    if not isinstance(conditions, list):
        return {}
    return {str(row.get("condition_id", "")): row for row in conditions if isinstance(row, dict)}


def _numeric_value(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
        return result if math.isfinite(result) else None
    return None


def _values_equal(left: object, right: object) -> bool:
    if isinstance(left, float) or isinstance(right, float):
        left_num = _numeric_value(left)
        right_num = _numeric_value(right)
        if left_num is not None and right_num is not None:
            return math.isclose(left_num, right_num, rel_tol=0.0, abs_tol=1e-9)
    return left == right


def _append_field_findings(
    *,
    scope: str,
    baseline_fields: set[str],
    new_fields: set[str],
    blocking_findings: list[str],
    notes: list[str],
    additive_fields: set[str],
) -> None:
    missing = sorted(baseline_fields - new_fields)
    extra = sorted(new_fields - baseline_fields)
    if missing:
        blocking_findings.append(f"{scope} is missing baseline fields: {', '.join(missing)}")
    if extra:
        additive_fields.update(extra)
        notes.append(f"{scope} has additive fields: {', '.join(extra)}")


def _collect_metric_deltas(
    *,
    sweep_name: str,
    baseline_rows: dict[str, dict[str, Any]],
    new_rows: dict[str, dict[str, Any]],
    exact_fields: tuple[str, ...],
    limit: int = 20,
) -> list[dict[str, object]]:
    deltas: list[dict[str, object]] = []
    skipped = set(exact_fields) | PATH_FIELDS
    for row_id, baseline_row in baseline_rows.items():
        new_row = new_rows.get(row_id)
        if new_row is None:
            continue
        for field in sorted(set(baseline_row) & set(new_row) - skipped):
            baseline_value = _numeric_value(baseline_row.get(field))
            new_value = _numeric_value(new_row.get(field))
            if baseline_value is None or new_value is None:
                continue
            absolute_delta = new_value - baseline_value
            if math.isclose(absolute_delta, 0.0, rel_tol=0.0, abs_tol=1e-9):
                continue
            relative_delta = None if baseline_value == 0 else absolute_delta / abs(baseline_value)
            deltas.append(
                {
                    "sweep": sweep_name,
                    "row_id": row_id,
                    "field": field,
                    "baseline": baseline_value,
                    "new": new_value,
                    "absolute_delta": absolute_delta,
                    "relative_delta": relative_delta,
                }
            )
    deltas.sort(key=lambda row: abs(float(row["absolute_delta"])), reverse=True)
    return deltas[:limit]


def _compare_exact_fields(
    *,
    scope: str,
    baseline_rows: dict[str, dict[str, Any]],
    new_rows: dict[str, dict[str, Any]],
    exact_fields: tuple[str, ...],
    blocking_findings: list[str],
) -> None:
    for row_id, baseline_row in baseline_rows.items():
        new_row = new_rows.get(row_id)
        if new_row is None:
            continue
        for field in exact_fields:
            if field not in baseline_row and field not in new_row:
                continue
            if field not in baseline_row:
                continue
            if field not in new_row:
                blocking_findings.append(f"{scope} {row_id} field {field} is missing")
                continue
            if not _values_equal(baseline_row[field], new_row[field]):
                blocking_findings.append(
                    f"{scope} {row_id} field {field} changed from {baseline_row[field]!r} to {new_row[field]!r}"
                )


def _compare_aggregate_payloads(
    *,
    sweep_name: str,
    baseline_payload: dict[str, Any],
    new_payload: dict[str, Any],
    blocking_findings: list[str],
) -> tuple[list[str], list[str], list[dict[str, object]], dict[str, object]]:
    notes: list[str] = []
    additive_fields: set[str] = set()

    for field in ("schema_version", "trial_summary_count", "condition_count"):
        if baseline_payload.get(field) != new_payload.get(field):
            blocking_findings.append(
                f"{sweep_name} aggregate {field} changed from {baseline_payload.get(field)!r} to {new_payload.get(field)!r}"
            )

    baseline_conditions = _conditions_by_id(baseline_payload)
    new_conditions = _conditions_by_id(new_payload)
    baseline_ids = set(baseline_conditions)
    new_ids = set(new_conditions)
    missing_ids = sorted(baseline_ids - new_ids)
    extra_ids = sorted(new_ids - baseline_ids)
    if missing_ids:
        blocking_findings.append(f"{sweep_name} is missing condition IDs: {', '.join(missing_ids)}")
    if extra_ids:
        blocking_findings.append(f"{sweep_name} has extra condition IDs: {', '.join(extra_ids)}")

    _append_field_findings(
        scope=f"{sweep_name} aggregate conditions",
        baseline_fields=_field_union(baseline_conditions.values()),
        new_fields=_field_union(new_conditions.values()),
        blocking_findings=blocking_findings,
        notes=notes,
        additive_fields=additive_fields,
    )
    _compare_exact_fields(
        scope=f"{sweep_name} condition",
        baseline_rows=baseline_conditions,
        new_rows=new_conditions,
        exact_fields=CONDITION_EXACT_FIELDS,
        blocking_findings=blocking_findings,
    )

    deltas = _collect_metric_deltas(
        sweep_name=sweep_name,
        baseline_rows=baseline_conditions,
        new_rows=new_conditions,
        exact_fields=CONDITION_EXACT_FIELDS,
    )
    if deltas:
        notes.append(f"{sweep_name} has runtime metric deltas")

    details = {
        "baseline_trial_summary_count": baseline_payload.get("trial_summary_count"),
        "new_trial_summary_count": new_payload.get("trial_summary_count"),
        "baseline_condition_count": baseline_payload.get("condition_count"),
        "new_condition_count": new_payload.get("condition_count"),
        "condition_ids_match": not missing_ids and not extra_ids,
    }
    return notes, sorted(additive_fields), deltas, details


def _compare_summary_rows(
    *,
    sweep_name: str,
    baseline_root: Path,
    new_root: Path,
    blocking_findings: list[str],
) -> tuple[list[str], list[str], dict[str, object]]:
    notes: list[str] = []
    additive_fields: set[str] = set()
    baseline_rows = {_summary_key(row): row for row in load_summary_rows(baseline_root)}
    new_rows = {_summary_key(row): row for row in load_summary_rows(new_root)}
    baseline_keys = set(baseline_rows)
    new_keys = set(new_rows)

    missing_keys = sorted(baseline_keys - new_keys)
    extra_keys = sorted(new_keys - baseline_keys)
    if missing_keys:
        blocking_findings.append(f"{sweep_name} is missing trial summaries: {missing_keys[:10]}")
    if extra_keys:
        blocking_findings.append(f"{sweep_name} has extra trial summaries: {extra_keys[:10]}")

    _append_field_findings(
        scope=f"{sweep_name} trial summaries",
        baseline_fields=_field_union(baseline_rows.values()),
        new_fields=_field_union(new_rows.values()),
        blocking_findings=blocking_findings,
        notes=notes,
        additive_fields=additive_fields,
    )
    _compare_exact_fields(
        scope=f"{sweep_name} trial summary",
        baseline_rows={f"{condition}/{trial}": row for (condition, trial), row in baseline_rows.items()},
        new_rows={f"{condition}/{trial}": row for (condition, trial), row in new_rows.items()},
        exact_fields=SUMMARY_EXACT_FIELDS,
        blocking_findings=blocking_findings,
    )
    return (
        notes,
        sorted(additive_fields),
        {
            "baseline_trial_keys": len(baseline_keys),
            "new_trial_keys": len(new_keys),
            "trial_keys_match": not missing_keys and not extra_keys,
        },
    )


def compare_sweep_roots(*, sweep_name: str, baseline_root: Path, new_root: Path) -> CheckResult:
    blocking_findings: list[str] = []
    notes: list[str] = []
    additive_fields: set[str] = set()
    metric_deltas: list[dict[str, object]] = []
    details: dict[str, object] = {
        "baseline_root": _repo_path(baseline_root),
        "new_root": _repo_path(new_root),
    }

    baseline_aggregate_path = baseline_root / "condition_aggregates.json"
    new_aggregate_path = new_root / "condition_aggregates.json"
    for label, path in (("baseline", baseline_aggregate_path), ("new", new_aggregate_path)):
        if not path.exists():
            blocking_findings.append(f"{sweep_name} {label} aggregate is missing: {_repo_path(path)}")

    if not blocking_findings:
        aggregate_notes, aggregate_additive, aggregate_deltas, aggregate_details = _compare_aggregate_payloads(
            sweep_name=sweep_name,
            baseline_payload=_load_json(baseline_aggregate_path),
            new_payload=_load_json(new_aggregate_path),
            blocking_findings=blocking_findings,
        )
        notes.extend(aggregate_notes)
        additive_fields.update(aggregate_additive)
        metric_deltas.extend(aggregate_deltas)
        details.update(aggregate_details)

        summary_notes, summary_additive, summary_details = _compare_summary_rows(
            sweep_name=sweep_name,
            baseline_root=baseline_root,
            new_root=new_root,
            blocking_findings=blocking_findings,
        )
        notes.extend(summary_notes)
        additive_fields.update(summary_additive)
        details.update(summary_details)

    status = "failed" if blocking_findings else ("passed_with_notes" if notes else "passed")
    return CheckResult(
        name=sweep_name,
        status=status,
        blocking_findings=blocking_findings,
        notes=notes,
        additive_fields=sorted(additive_fields),
        largest_metric_deltas=metric_deltas[:20],
        details=details,
    )


def _load_demo_summary(root: Path, side: str) -> dict[str, Any]:
    return _load_json(root / f"{side}_dashboard" / "dashboard_summary.json")


def compare_demo_roots(*, baseline_root: Path, new_root: Path) -> CheckResult:
    blocking_findings: list[str] = []
    notes: list[str] = []
    additive_fields: set[str] = set()
    metric_deltas: list[dict[str, object]] = []
    details: dict[str, object] = {
        "baseline_root": _repo_path(baseline_root),
        "new_root": _repo_path(new_root),
    }

    for artifact in DEMO_ARTIFACTS:
        baseline_path = baseline_root / artifact
        new_path = new_root / artifact
        if not baseline_path.exists():
            blocking_findings.append(f"demo baseline artifact is missing: {_repo_path(baseline_path)}")
        if not new_path.exists():
            blocking_findings.append(f"demo new artifact is missing: {_repo_path(new_path)}")

    if not blocking_findings:
        baseline_manifest = _load_json(baseline_root / "manifest.json")
        new_manifest = _load_json(new_root / "manifest.json")
        _compare_exact_fields(
            scope="demo manifest",
            baseline_rows={"demo": baseline_manifest},
            new_rows={"demo": new_manifest},
            exact_fields=DEMO_MANIFEST_EXACT_FIELDS,
            blocking_findings=blocking_findings,
        )
        _append_field_findings(
            scope="demo manifest",
            baseline_fields=set(baseline_manifest),
            new_fields=set(new_manifest),
            blocking_findings=blocking_findings,
            notes=notes,
            additive_fields=additive_fields,
        )

        for side in ("baseline", "smart"):
            baseline_summary = _load_demo_summary(baseline_root, side)
            new_summary = _load_demo_summary(new_root, side)
            _append_field_findings(
                scope=f"demo {side} dashboard summary",
                baseline_fields=set(baseline_summary),
                new_fields=set(new_summary),
                blocking_findings=blocking_findings,
                notes=notes,
                additive_fields=additive_fields,
            )
            side_deltas = _collect_metric_deltas(
                sweep_name=f"demo_{side}",
                baseline_rows={side: baseline_summary},
                new_rows={side: new_summary},
                exact_fields=(),
            )
            if side_deltas:
                notes.append(f"demo {side} dashboard summary has runtime metric deltas")
            metric_deltas.extend(side_deltas)

    status = "failed" if blocking_findings else ("passed_with_notes" if notes else "passed")
    return CheckResult(
        name="demo",
        status=status,
        blocking_findings=blocking_findings,
        notes=notes,
        additive_fields=sorted(additive_fields),
        largest_metric_deltas=metric_deltas[:20],
        details=details,
    )


def _result_to_dict(result: CheckResult) -> dict[str, object]:
    return {
        "name": result.name,
        "status": result.status,
        "blocking_findings": result.blocking_findings,
        "notes": result.notes,
        "additive_fields": result.additive_fields,
        "largest_metric_deltas": result.largest_metric_deltas,
        "details": result.details,
    }


def _overall_status(results: list[CheckResult]) -> str:
    if any(result.blocking_findings for result in results):
        return "failed"
    if any(result.notes or result.additive_fields or result.largest_metric_deltas for result in results):
        return "passed_with_notes"
    return "passed"


def _phase6_new_roots(phase6_manifest: dict[str, Any]) -> dict[str, str]:
    roots: dict[str, str] = {}
    entries = phase6_manifest.get("executed_sweeps") or phase6_manifest.get("sweeps") or []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", ""))
        if name in PHASE6_SWEEP_NAMES:
            raw_root = entry.get("sweep_dir") or entry.get("output_root")
            if raw_root:
                roots[name] = str(raw_root)
    return roots


def build_new_roots(*, phase6_manifest: dict[str, Any], stamp: str, demo_dir: Path | None = None) -> dict[str, str]:
    roots = _phase6_new_roots(phase6_manifest)
    roots["intel_v3_adaptive_parameter_sweep"] = _repo_path(LOGS_ROOT / f"intel-v3-adaptive-parameter-sweep-{stamp}")
    roots["demo"] = _repo_path(demo_dir or (LOGS_ROOT / f"final-demo-{stamp}" / "demo"))
    return roots


def _frozen_roots(frozen_manifest: dict[str, Any]) -> dict[str, str]:
    roots = {
        name: str(frozen_manifest[key])
        for name, key in SWEEP_ROOT_KEYS.items()
        if frozen_manifest.get(key)
    }
    if frozen_manifest.get("demo_dir"):
        roots["demo"] = str(frozen_manifest["demo_dir"])
    return roots


def compare_against_frozen(
    *,
    frozen_manifest_path: Path,
    new_roots: dict[str, str],
    stamp: str,
    phase6_manifest_path: Path | None = None,
) -> dict[str, object]:
    frozen_manifest = _load_json(frozen_manifest_path)
    frozen_roots = _frozen_roots(frozen_manifest)
    results: list[CheckResult] = []

    for name in sorted(SWEEP_ROOT_KEYS):
        baseline_raw = frozen_roots.get(name)
        new_raw = new_roots.get(name)
        if baseline_raw is None or new_raw is None:
            results.append(
                CheckResult(
                    name=name,
                    status="failed",
                    blocking_findings=[f"{name} root mapping is incomplete"],
                    notes=[],
                    additive_fields=[],
                    largest_metric_deltas=[],
                    details={"baseline_root": baseline_raw, "new_root": new_raw},
                )
            )
            continue
        results.append(
            compare_sweep_roots(
                sweep_name=name,
                baseline_root=_resolve_repo_path(baseline_raw),
                new_root=_resolve_repo_path(new_raw),
            )
        )

    if frozen_roots.get("demo") and new_roots.get("demo"):
        results.append(
            compare_demo_roots(
                baseline_root=_resolve_repo_path(frozen_roots["demo"]),
                new_root=_resolve_repo_path(new_roots["demo"]),
            )
        )
    else:
        results.append(
            CheckResult(
                name="demo",
                status="failed",
                blocking_findings=["demo root mapping is incomplete"],
                notes=[],
                additive_fields=[],
                largest_metric_deltas=[],
                details={"baseline_root": frozen_roots.get("demo"), "new_root": new_roots.get("demo")},
            )
        )

    all_deltas = [
        delta
        for result in results
        for delta in result.largest_metric_deltas
    ]
    all_deltas.sort(key=lambda row: abs(float(row["absolute_delta"])), reverse=True)
    blocking_findings = [
        finding
        for result in results
        for finding in result.blocking_findings
    ]
    additive_fields = sorted({field for result in results for field in result.additive_fields})
    notes = [note for result in results for note in result.notes]

    payload: dict[str, object] = {
        "schema_version": 1,
        "generated_at_utc": _utc_now_iso(),
        "stamp": stamp,
        "status": _overall_status(results),
        "frozen_manifest_path": _repo_path(frozen_manifest_path),
        "phase6_manifest_path": _repo_path(phase6_manifest_path) if phase6_manifest_path is not None else None,
        "frozen_roots": frozen_roots,
        "new_roots": new_roots,
        "blocking_findings": blocking_findings,
        "notes": notes,
        "additive_fields": additive_fields,
        "largest_metric_deltas": all_deltas[:25],
        "checks": [_result_to_dict(result) for result in results],
    }
    return payload


def _render_markdown_report(report: dict[str, object]) -> str:
    lines = [
        "# Replicated Equivalence Report",
        "",
        f"- Stamp: `{report['stamp']}`",
        f"- Status: `{report['status']}`",
        f"- Frozen manifest: `{report['frozen_manifest_path']}`",
        "",
        "## Findings",
    ]
    blocking_findings = report.get("blocking_findings") or []
    if blocking_findings:
        lines.extend(f"- BLOCKING: {finding}" for finding in blocking_findings)
    else:
        lines.append("- No blocking findings.")

    additive_fields = report.get("additive_fields") or []
    if additive_fields:
        lines.append(f"- Additive fields: `{', '.join(str(field) for field in additive_fields)}`")

    deltas = report.get("largest_metric_deltas") or []
    if deltas:
        lines.append("")
        lines.append("## Largest Metric Deltas")
        for delta in deltas[:10]:
            lines.append(
                "- "
                f"{delta['sweep']} {delta['row_id']} {delta['field']}: "
                f"{delta['baseline']} -> {delta['new']}"
            )
    lines.append("")
    return "\n".join(lines)


def _build_parameter_config(*, stamp: str, data_file: Path, mqtt_host: str, mqtt_port: int) -> parameter_sweep.V3AdaptiveParameterSweepConfig:
    return parameter_sweep.V3AdaptiveParameterSweepConfig(
        sweep_id=f"intel-v3-adaptive-parameter-sweep-{stamp}",
        data_file=data_file,
        scenarios=list(parameter_sweep.DEFAULT_SCENARIOS),
        duration_s=30,
        replay_speed=5.0,
        sensor_limit=200,
        batch_window_ms=250,
        gateway_host="127.0.0.1",
        gateway_port=8000,
        proxy_host="127.0.0.1",
        proxy_port=9000,
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port,
        run_browser=True,
        trial_seeds=list(run_replicated_phase6.TARGETED_TRIAL_SEEDS),
    )


def _ensure_extra_roots_available(*, stamp: str) -> None:
    paths = [
        LOGS_ROOT / f"intel-v3-adaptive-parameter-sweep-{stamp}",
        LOGS_ROOT / f"final-demo-{stamp}" / "demo",
    ]
    existing = [path for path in paths if path.exists()]
    if existing:
        existing_text = ", ".join(_repo_path(path) for path in existing)
        raise SystemExit(f"Equivalence execution would overwrite existing artifacts: {existing_text}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run and compare the replicated paper evidence matrix.")
    parser.add_argument("--stamp", default=f"replicated-equivalence-{time.strftime('%Y%m%d-%H%M%S')}")
    parser.add_argument("--intel-input", type=Path, default=run_replicated_phase6.DEFAULT_INTEL_INPUT)
    parser.add_argument("--aot-input", type=Path, default=run_replicated_phase6.DEFAULT_AOT_INPUT)
    parser.add_argument("--frozen-manifest-path", type=Path, default=DEFAULT_FROZEN_MANIFEST)
    parser.add_argument("--mqtt-host", default="127.0.0.1")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute the replicated sweeps, V3 parameter sweep, and demo before comparing.",
    )
    return parser.parse_args(argv)


def run_replicated_equivalence_check(args: argparse.Namespace) -> dict[str, object]:
    if not args.frozen_manifest_path.exists():
        raise SystemExit(f"Frozen evidence manifest was not found: {args.frozen_manifest_path}")

    phase6_args = run_replicated_phase6.parse_args(
        [
            "--stamp",
            args.stamp,
            "--intel-input",
            str(args.intel_input),
            "--aot-input",
            str(args.aot_input),
            "--mqtt-host",
            args.mqtt_host,
            "--mqtt-port",
            str(args.mqtt_port),
            *(["--execute"] if args.execute else []),
        ]
    )

    if args.execute:
        _ensure_extra_roots_available(stamp=args.stamp)

    phase6_manifest_path, phase6_manifest = run_replicated_phase6.run_phase6(phase6_args)
    demo_dir: Path | None = None

    if args.execute:
        phase6_paths = run_replicated_phase6.build_phase6_paths(args.stamp)
        parameter_config = _build_parameter_config(
            stamp=args.stamp,
            data_file=phase6_paths.intel_replay_csv,
            mqtt_host=args.mqtt_host,
            mqtt_port=args.mqtt_port,
        )
        parameter_sweep.run_v3_adaptive_parameter_sweep(parameter_config)

        demo_config = build_demo_config(
            stamp=args.stamp,
            data_file=phase6_paths.intel_replay_csv,
            mqtt_host=args.mqtt_host,
            mqtt_port=args.mqtt_port,
        )
        validate_demo_environment(demo_config)
        demo_dir = run_demo(demo_config)

    new_roots = build_new_roots(
        phase6_manifest=phase6_manifest,
        stamp=args.stamp,
        demo_dir=demo_dir,
    )
    report = compare_against_frozen(
        frozen_manifest_path=args.frozen_manifest_path,
        new_roots=new_roots,
        stamp=args.stamp,
        phase6_manifest_path=phase6_manifest_path,
    )
    report["mode"] = "execute" if args.execute else "plan-only"

    report_path = LOGS_ROOT / f"{REPORT_PREFIX}-{args.stamp}.json"
    markdown_path = LOGS_ROOT / f"{REPORT_PREFIX}-{args.stamp}.md"
    report["report_path"] = _repo_path(report_path)
    report["markdown_report_path"] = _repo_path(markdown_path)
    _write_json(report_path, report)
    markdown_path.write_text(_render_markdown_report(report), encoding="utf-8")
    return report


def main() -> None:
    report = run_replicated_equivalence_check(parse_args())
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
