from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = PROJECT_ROOT / "report"
REPORT_ASSETS_DIR = REPORT_DIR / "assets"
PAPER_DIR = PROJECT_ROOT / "research_paper"
LOGS_DIR = PROJECT_ROOT / "experiments" / "logs"
MANIFEST_OUTPUT_PATH = REPORT_ASSETS_DIR / "final_submission_manifest.json"
DELIVERABLE_GATE_PATH = REPORT_DIR / "deliverable_gate.md"

CORE_SUBMISSION_FILES = [
    "simulator/preprocess_common.py",
    "simulator/preprocess_intel_lab.py",
    "simulator/preprocess_aot.py",
    "simulator/replay_publisher.py",
    "simulator/replay_timing.py",
    "gateway/app.py",
    "gateway/forwarder.py",
    "gateway/mqtt_ingest.py",
    "gateway/schemas.py",
    "ui/index.html",
    "ui/demo_compare.html",
    "experiments/analyze_run.py",
    "experiments/impairment_proxy.py",
    "experiments/run_sweep.py",
    "experiments/run_demo.py",
    "experiments/run_final_deliverables.py",
    "experiments/build_report_assets.py",
    "experiments/build_run_registry.py",
    "experiments/package_paper_assets.py",
    "experiments/sweep_aggregation.py",
    "experiments/run_replicated_phase6.py",
    "experiments/run_batch_window_sweep.py",
    "experiments/run_v1_v2_isolation_sweep.py",
    "experiments/run_adaptive_impairment_sweep.py",
    "experiments/run_v3_adaptive_parameter_sweep.py",
    "experiments/reproduce_all.sh",
    "experiments/freeze_final_submission.py",
]

DOCUMENTATION_FILES = [
    "README.md",
    "experiments/logs/run_registry.json",
]

EXPLICIT_EXCLUSIONS = [
    {
        "path": "PRD.md",
        "reason": "Planning artifact; not part of the frozen submission package.",
    },
    {
        "path": "PROJECT_CHECKLIST.md",
        "reason": "Execution checklist; retained in the repo but excluded from the frozen submission package.",
    },
    {
        "path": "q&a.md",
        "reason": "Scratch planning notes; not part of the frozen submission package.",
    },
    {
        "path": "research-analysis.md",
        "reason": "Working analysis notes; not part of the frozen submission package.",
    },
]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _project_relative(path: Path, project_root: Path) -> str:
    return path.relative_to(project_root).as_posix()


def _dedupe_preserve_order(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        ordered.append(path)
    return ordered


def _existing_repo_files(project_root: Path, relative_paths: list[str]) -> list[str]:
    existing: list[str] = []
    for relative_path in relative_paths:
        if (project_root / relative_path).exists():
            existing.append(relative_path)
    return existing


def _existing_sections(paper_dir: Path, project_root: Path) -> list[str]:
    return []


def _paper_manifest_files(
    *,
    paper_manifest: dict[str, Any],
    project_root: Path,
) -> list[str]:
    paths = [
        "research_paper/assets/paper_assets_manifest.json",
        paper_manifest.get("paper_asset_index_path"),
        paper_manifest.get("generated_latex_table"),
        *paper_manifest.get("main_paper_assets", []),
        *paper_manifest.get("appendix_assets", []),
    ]
    paths.extend(
        item["paper_asset_path"]
        for item in paper_manifest.get("paper_native_assets", [])
        if item.get("paper_asset_path")
    )
    return _existing_repo_files(project_root, _dedupe_preserve_order([path for path in paths if path]))


def _report_manifest_files(
    *,
    evidence_manifest: dict[str, Any],
    manifest_output_path: Path,
    project_root: Path,
) -> list[str]:
    paths = [
        "report/assets/evidence_manifest.json",
        "report/assets/old_evidence_inventory.json",
        "report/assets/CLAIM_TO_EVIDENCE_MAP.md",
        _project_relative(manifest_output_path, project_root),
        *evidence_manifest.get("generated_figures", []),
        *evidence_manifest.get("generated_tables", []),
    ]
    normalized_paths = [Path(path).as_posix() for path in paths]
    return _dedupe_preserve_order(normalized_paths)


def _collect_submission_files(
    *,
    project_root: Path,
    report_dir: Path,
    paper_dir: Path,
    logs_dir: Path,
    manifest_output_path: Path,
) -> dict[str, list[str]]:
    evidence_manifest = _read_json(report_dir / "assets" / "evidence_manifest.json")
    paper_manifest = _read_json(paper_dir / "assets" / "paper_assets_manifest.json")

    groups = {
        "core_pipeline_files": _existing_repo_files(project_root, CORE_SUBMISSION_FILES),
        "documentation_files": _existing_repo_files(project_root, DOCUMENTATION_FILES),
        "report_asset_files": _report_manifest_files(
            evidence_manifest=evidence_manifest,
            manifest_output_path=manifest_output_path,
            project_root=project_root,
        ),
        "paper_source_files": _existing_repo_files(
            project_root,
            ["research_paper/main.tex", "research_paper/references.bib"],
        )
        + _existing_sections(paper_dir, project_root),
        "paper_asset_files": _paper_manifest_files(
            paper_manifest=paper_manifest,
            project_root=project_root,
        ),
    }
    groups["documentation_files"] = _dedupe_preserve_order(groups["documentation_files"])
    groups["paper_source_files"] = _dedupe_preserve_order(groups["paper_source_files"])
    groups["paper_asset_files"] = _dedupe_preserve_order(groups["paper_asset_files"])
    groups["validation_files"] = _existing_repo_files(
        project_root,
        [_project_relative(path, project_root) for path in sorted((project_root / "tests").glob("test_*.py"))]
        + ["experiments/capture_dashboard.mjs"],
    )
    return groups


def _canonical_evidence_roots(logs_dir: Path, project_root: Path) -> list[dict[str, str]]:
    run_registry = _read_json(logs_dir / "run_registry.json")
    return [
        {
            "path": Path(entry["path"]).as_posix(),
            "classification": entry["classification"],
        }
        for entry in run_registry.get("canonical_roots", [])
    ]


def _summarize_command_output(name: str, stdout: str, stderr: str) -> str:
    text = stdout or stderr
    if name == "unittest_suite":
        match = re.search(r"Ran (\d+) tests? in ([0-9.]+)s", text)
        if match:
            status_line = "OK" if re.search(r"^OK$", text, re.MULTILINE) else text.strip().splitlines()[-1]
            return f"Ran {match.group(1)} tests in {match.group(2)}s; {status_line}"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else "No output."


def _run_command(command: list[str], *, cwd: Path, name: str) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        return {
            "name": name,
            "command": command,
            "status": "failed",
            "blocking": True,
            "returncode": None,
            "summary": str(exc),
            "stdout": "",
            "stderr": "",
        }

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    return {
        "name": name,
        "command": command,
        "status": "passed" if completed.returncode == 0 else "failed",
        "blocking": True,
        "returncode": completed.returncode,
        "summary": _summarize_command_output(name, stdout, stderr),
        "stdout": stdout,
        "stderr": stderr,
    }


def _check_tex_paths(paper_dir: Path) -> dict[str, Any]:
    tex_files = [paper_dir / "main.tex"]
    missing: list[dict[str, str]] = []
    patterns = [
        re.compile(r"\\input\{([^}]+)\}"),
        re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}"),
        re.compile(r"\\bibliography\{([^}]+)\}"),
    ]

    for tex_file in tex_files:
        text = tex_file.read_text(encoding="utf-8")
        for pattern in patterns:
            for raw_reference in pattern.findall(text):
                for piece in (part.strip() for part in raw_reference.split(",")):
                    if not piece:
                        continue
                    candidate = paper_dir / piece
                    candidates = [candidate, candidate.with_suffix(".tex"), candidate.with_suffix(".bib")]
                    if not any(option.exists() for option in candidates):
                        missing.append(
                            {
                                "source": tex_file.relative_to(paper_dir).as_posix(),
                                "reference": piece,
                            }
                        )

    return {
        "name": "tex_reference_paths",
        "status": "passed" if not missing else "failed",
        "blocking": True,
        "missing_references": missing,
    }


def _check_citations(paper_dir: Path) -> dict[str, Any]:
    bib_keys = set(
        re.findall(
            r"@[A-Za-z]+\{\s*([^,\s]+)",
            (paper_dir / "references.bib").read_text(encoding="utf-8"),
        )
    )
    tex_files = [paper_dir / "main.tex"]
    used_keys: set[str] = set()
    for tex_file in tex_files:
        text = tex_file.read_text(encoding="utf-8")
        for raw_keys in re.findall(r"\\cite[a-zA-Z*]*\{([^}]+)\}", text):
            used_keys.update(key.strip() for key in raw_keys.split(",") if key.strip())

    missing_keys = sorted(key for key in used_keys if key not in bib_keys)
    return {
        "name": "citation_keys",
        "status": "passed" if not missing_keys else "failed",
        "blocking": True,
        "missing_citations": missing_keys,
    }


def _check_report_assets(project_root: Path, expected_report_files: list[str]) -> dict[str, Any]:
    report_assets_dir = project_root / "report" / "assets"
    actual = {
        _project_relative(path, project_root)
        for path in report_assets_dir.rglob("*")
        if path.is_file()
    }
    expected = set(expected_report_files)
    extra = sorted(actual - expected)
    missing = sorted(expected - actual)
    return {
        "name": "report_asset_inventory",
        "status": "passed" if not extra and not missing else "failed",
        "blocking": True,
        "extra_files": extra,
        "missing_files": missing,
    }


def _check_paper_assets(project_root: Path, expected_paper_files: list[str]) -> dict[str, Any]:
    paper_root = project_root / "research_paper"
    actual = {
        _project_relative(path, project_root)
        for path in paper_root.rglob("*")
        if path.is_file() and path.suffix in {".png", ".tex", ".md", ".json", ".csv", ".bib"}
    }
    expected = set(expected_paper_files)
    extra = sorted(path for path in actual - expected if path.startswith("research_paper/assets/"))
    missing = sorted(expected - actual)
    return {
        "name": "paper_asset_inventory",
        "status": "passed" if not extra and not missing else "failed",
        "blocking": True,
        "extra_files": extra,
        "missing_files": missing,
    }


def _check_doc_anchors(
    *,
    project_root: Path,
    evidence_manifest: dict[str, Any],
    canonical_roots: list[dict[str, str]],
) -> dict[str, Any]:
    checks = {
        "README.md": [
            "report/assets/evidence_manifest.json",
            "experiments/logs/run_registry.json",
            *[entry["path"] for entry in canonical_roots],
        ],
    }
    missing: list[dict[str, Any]] = []
    for relative_path, anchors in checks.items():
        content = (project_root / relative_path).read_text(encoding="utf-8")
        missing_anchors = [anchor for anchor in anchors if anchor not in content]
        if missing_anchors:
            missing.append({"document": relative_path, "missing_anchors": missing_anchors})

    return {
        "name": "document_provenance_anchors",
        "status": "passed" if not missing else "failed",
        "blocking": True,
        "missing": missing,
    }


def _check_latex_toolchain(which_lookup: Any) -> dict[str, Any]:
    availability = {tool: which_lookup(tool) for tool in ("latexmk", "pdflatex", "biber")}
    missing = [tool for tool, location in availability.items() if location is None]
    return {
        "name": "latex_toolchain",
        "status": "warning" if missing else "passed",
        "blocking": False,
        "available_tools": availability,
        "missing_tools": missing,
        "limitation": (
            "LaTeX toolchain unavailable; source tree frozen as build-ready only."
            if missing
            else ""
        ),
    }


def _draft_manual_signoff() -> dict[str, Any]:
    return {
        "status": "draft",
        "summary": "Freeze validation passed; manual research-significance confirmation is still required before the project is declared fully frozen.",
        "recommended_points": [
            "Broad downstream-byte reduction remains unsupported; keep the fallback wording from report/assets/tables/intel_key_claims.md.",
            "Adaptive control remains a null-result/supporting claim, not a headline result.",
            "Keep the current main-paper asset slate recorded in research_paper/assets/paper_asset_index.md.",
            "No extra reruns are recommended before freeze because the bounded Section 7 hard stop is already locked.",
        ],
    }


def _build_manifest(
    *,
    project_root: Path,
    report_dir: Path,
    paper_dir: Path,
    logs_dir: Path,
    manifest_output_path: Path,
    validation: dict[str, Any] | None,
    manual_signoff_draft: dict[str, Any] | None,
) -> dict[str, Any]:
    evidence_manifest = _read_json(report_dir / "assets" / "evidence_manifest.json")
    groups = _collect_submission_files(
        project_root=project_root,
        report_dir=report_dir,
        paper_dir=paper_dir,
        logs_dir=logs_dir,
        manifest_output_path=manifest_output_path,
    )
    canonical_roots = _canonical_evidence_roots(logs_dir, project_root)
    included_submission_files = _dedupe_preserve_order(
        groups["core_pipeline_files"]
        + groups["documentation_files"]
        + groups["report_asset_files"]
        + groups["paper_source_files"]
        + groups["paper_asset_files"]
    )
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": validation["status"] if validation is not None else "pending",
        "included_submission_files": included_submission_files,
        "submission_file_groups": {
            key: value
            for key, value in groups.items()
            if key != "validation_files"
        },
        "validation_inputs": groups["validation_files"],
        "canonical_evidence_roots": canonical_roots,
        "explicit_exclusions": EXPLICIT_EXCLUSIONS,
        "validation": validation,
        "environment_limitations": validation.get("environment_limitations", []) if validation else [],
        "manual_signoff_draft": manual_signoff_draft,
        "source_manifests": {
            "report_evidence_manifest_path": "report/assets/evidence_manifest.json",
            "report_claim_map_path": "report/assets/CLAIM_TO_EVIDENCE_MAP.md",
            "paper_asset_manifest_path": "research_paper/assets/paper_assets_manifest.json",
            "run_registry_path": "experiments/logs/run_registry.json",
        },
        "expected_provenance_anchors": {
            "intel_sweep_dir": evidence_manifest["intel_sweep_dir"],
            "aot_sweep_dir": evidence_manifest["aot_sweep_dir"],
            "demo_dir": evidence_manifest["demo_dir"],
        },
    }


def _run_validation(
    *,
    project_root: Path,
    report_dir: Path,
    paper_dir: Path,
    logs_dir: Path,
    manifest_output_path: Path,
    command_runner: Any,
    which_lookup: Any,
) -> dict[str, Any]:
    evidence_manifest = _read_json(report_dir / "assets" / "evidence_manifest.json")
    groups = _collect_submission_files(
        project_root=project_root,
        report_dir=report_dir,
        paper_dir=paper_dir,
        logs_dir=logs_dir,
        manifest_output_path=manifest_output_path,
    )
    canonical_roots = _canonical_evidence_roots(logs_dir, project_root)
    command_results = [
        command_runner(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=project_root,
            name="unittest_suite",
        ),
        command_runner(
            ["node", "experiments/capture_dashboard.mjs", "--check-only"],
            cwd=project_root,
            name="dashboard_capture_preflight",
        ),
    ]
    static_checks = [
        _check_tex_paths(paper_dir),
        _check_citations(paper_dir),
        _check_report_assets(project_root, groups["report_asset_files"]),
        _check_paper_assets(project_root, groups["paper_source_files"] + groups["paper_asset_files"]),
        _check_doc_anchors(
            project_root=project_root,
            evidence_manifest=evidence_manifest,
            canonical_roots=canonical_roots,
        ),
        _check_latex_toolchain(which_lookup),
    ]

    environment_limitations = [
        check["limitation"]
        for check in static_checks
        if check["name"] == "latex_toolchain" and check.get("limitation")
    ]
    blocking_findings: list[str] = []
    for result in command_results:
        if result["blocking"] and result["status"] != "passed":
            blocking_findings.append(f"{result['name']} failed: {result['summary']}")
    for check in static_checks:
        if not check["blocking"] or check["status"] == "passed":
            continue
        if check["name"] == "report_asset_inventory":
            for extra_file in check["extra_files"]:
                blocking_findings.append(f"Unmanaged report asset present: {extra_file}")
            for missing_file in check["missing_files"]:
                blocking_findings.append(f"Expected report asset missing: {missing_file}")
            continue
        if check["name"] == "paper_asset_inventory":
            for extra_file in check["extra_files"]:
                blocking_findings.append(f"Unexpected packaged paper asset present: {extra_file}")
            for missing_file in check["missing_files"]:
                blocking_findings.append(f"Expected packaged paper asset missing: {missing_file}")
            continue
        if check["name"] == "tex_reference_paths":
            for missing_reference in check["missing_references"]:
                blocking_findings.append(
                    f"Missing TeX reference in {missing_reference['source']}: {missing_reference['reference']}"
                )
            continue
        if check["name"] == "citation_keys":
            for key in check["missing_citations"]:
                blocking_findings.append(f"Missing bibliography entry for citation key: {key}")
            continue
        if check["name"] == "document_provenance_anchors":
            for document in check["missing"]:
                blocking_findings.append(
                    f"Missing provenance anchors in {document['document']}: {', '.join(document['missing_anchors'])}"
                )

    return {
        "status": "passed" if not blocking_findings else "blocked",
        "command_results": command_results,
        "static_checks": static_checks,
        "blocking_findings": blocking_findings,
        "environment_limitations": environment_limitations,
    }


def _render_deliverable_gate(manifest: dict[str, Any]) -> str:
    validation = manifest["validation"] or {}
    lines = [
        "# Final Submission Freeze",
        "",
        f"- Generated at: `{manifest['generated_at_utc']}`",
        f"- Freeze status: `{manifest['status']}`",
        "",
        "## Frozen Submission Package",
        "",
    ]

    group_titles = {
        "core_pipeline_files": "Core Pipeline Files",
        "documentation_files": "Documentation and Registries",
        "report_asset_files": "Report Assets and Provenance Files",
        "paper_source_files": "Paper Source Files",
        "paper_asset_files": "Packaged Paper Assets",
    }
    for group_key, title in group_titles.items():
        group_paths = manifest["submission_file_groups"][group_key]
        lines.append(f"### {title}")
        lines.append("")
        for path in group_paths:
            lines.append(f"- `{path}`")
        lines.append("")

    lines.extend(
        [
            "## Canonical Evidence Roots",
            "",
        ]
    )
    for entry in manifest["canonical_evidence_roots"]:
        lines.append(f"- `{entry['path']}` (`{entry['classification']}`)")
    lines.append("")

    lines.extend(
        [
            "## Validation Summary",
            "",
        ]
    )
    for result in validation.get("command_results", []):
        lines.append(
            f"- `{result['name']}`: `{result['status']}`"
            + (f" ({result['summary']})" if result.get("summary") else "")
        )
    for check in validation.get("static_checks", []):
        lines.append(f"- `{check['name']}`: `{check['status']}`")
    lines.append("")

    if validation.get("blocking_findings"):
        lines.extend(["## Blocking Findings", ""])
        for finding in validation["blocking_findings"]:
            lines.append(f"- {finding}")
        lines.append("")

    if manifest.get("environment_limitations"):
        lines.extend(["## Environment Limitations", ""])
        for limitation in manifest["environment_limitations"]:
            lines.append(f"- {limitation}")
        lines.append("")

    lines.extend(["## Explicit Exclusions", ""])
    for exclusion in manifest["explicit_exclusions"]:
        lines.append(f"- `{exclusion['path']}`: {exclusion['reason']}")
    lines.append("")

    if manifest.get("manual_signoff_draft") is not None:
        lines.extend(["## Draft Manual Sign-off", ""])
        lines.append(f"- {manifest['manual_signoff_draft']['summary']}")
        for point in manifest["manual_signoff_draft"]["recommended_points"]:
            lines.append(f"- {point}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def freeze_final_submission(
    *,
    project_root: Path = PROJECT_ROOT,
    report_dir: Path = REPORT_DIR,
    paper_dir: Path = PAPER_DIR,
    logs_dir: Path = LOGS_DIR,
    manifest_output_path: Path = MANIFEST_OUTPUT_PATH,
    deliverable_gate_path: Path = DELIVERABLE_GATE_PATH,
    command_runner: Any = _run_command,
    which_lookup: Any = shutil.which,
) -> dict[str, Any]:
    manifest_output_path.parent.mkdir(parents=True, exist_ok=True)
    deliverable_gate_path.parent.mkdir(parents=True, exist_ok=True)

    provisional_manifest = _build_manifest(
        project_root=project_root,
        report_dir=report_dir,
        paper_dir=paper_dir,
        logs_dir=logs_dir,
        manifest_output_path=manifest_output_path,
        validation={
            "status": "pending",
            "command_results": [],
            "static_checks": [],
            "blocking_findings": [],
            "environment_limitations": [],
        },
        manual_signoff_draft=None,
    )
    manifest_output_path.write_text(json.dumps(provisional_manifest, indent=2), encoding="utf-8")

    validation = _run_validation(
        project_root=project_root,
        report_dir=report_dir,
        paper_dir=paper_dir,
        logs_dir=logs_dir,
        manifest_output_path=manifest_output_path,
        command_runner=command_runner,
        which_lookup=which_lookup,
    )
    manual_signoff_draft = _draft_manual_signoff() if validation["status"] == "passed" else None
    final_manifest = _build_manifest(
        project_root=project_root,
        report_dir=report_dir,
        paper_dir=paper_dir,
        logs_dir=logs_dir,
        manifest_output_path=manifest_output_path,
        validation=validation,
        manual_signoff_draft=manual_signoff_draft,
    )
    manifest_output_path.write_text(json.dumps(final_manifest, indent=2), encoding="utf-8")
    deliverable_gate_path.write_text(_render_deliverable_gate(final_manifest), encoding="utf-8")
    return final_manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Freeze the final submission package from existing report and paper artifacts.")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    parser.add_argument("--paper-dir", type=Path, default=PAPER_DIR)
    parser.add_argument("--logs-dir", type=Path, default=LOGS_DIR)
    parser.add_argument("--manifest-output-path", type=Path, default=MANIFEST_OUTPUT_PATH)
    parser.add_argument("--deliverable-gate-path", type=Path, default=DELIVERABLE_GATE_PATH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    manifest = freeze_final_submission(
        project_root=args.project_root,
        report_dir=args.report_dir,
        paper_dir=args.paper_dir,
        logs_dir=args.logs_dir,
        manifest_output_path=args.manifest_output_path,
        deliverable_gate_path=args.deliverable_gate_path,
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
