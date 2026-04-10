from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


SUPPORT_ROOT_REASONS = {
    "generated_inputs": "Generated replay CSV cache; support data, not an experiment directory.",
    "generated_source_slices": "Generated source-slice cache; support data, not an experiment directory.",
    "final-source-downloads": "Raw source download cache; support data, not an experiment directory.",
}

SUPPORT_ROOT_PREFIX_REASONS = {
    "final-deliverables-": "Deliverables manifest/support root; not an experiment directory.",
}

SUPPORT_DIR_REASONS = {
    "plots": "Helper plot directory inside a sweep root; not a canonical run directory.",
}

EXPLORATORY_PREFIX = "smoke-"
EXPLORATORY_REGEX = re.compile(r"^m\d")
STAMP_SUFFIX_RE = re.compile(r"^(?P<family>.+)-\d{8}(?:-\d{6})?$")


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    logs_dir = repo_root / "experiments" / "logs"
    manifest_path = repo_root / "report" / "assets" / "evidence_manifest.json"
    output_path = logs_dir / "run_registry.json"

    parser = argparse.ArgumentParser(
        description="Build the canonical run registry for experiments/logs."
    )
    parser.add_argument("--logs-dir", type=Path, default=logs_dir)
    parser.add_argument("--manifest-path", type=Path, default=manifest_path)
    parser.add_argument("--output", type=Path, default=output_path)
    return parser.parse_args()


def normalize_path(path: Path, repo_root: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def resolve_manifest_path(raw_path: str, repo_root: Path) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = repo_root / path
    return path


def load_canonical_roots(
    *, repo_root: Path, logs_dir: Path, manifest_path: Path
) -> dict[str, str]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root_specs: list[tuple[str, str]] = []

    for key, classification in (
        ("intel_sweep_dir", "primary-evidence"),
        ("aot_sweep_dir", "validation"),
        ("demo_dir", "demo"),
        ("intel_batch_sweep_dir", "ablation"),
        ("intel_v1_v2_sweep_dir", "ablation"),
        ("intel_adaptive_sweep_dir", "ablation"),
        ("intel_adaptive_parameter_sweep_dir", "ablation"),
    ):
        raw_path = manifest.get(key)
        if not raw_path:
            continue
        resolved_path = resolve_manifest_path(raw_path, repo_root)
        try:
            relative = resolved_path.relative_to(logs_dir)
        except ValueError as exc:
            raise ValueError(
                f"Manifest path {resolved_path} is not under logs dir {logs_dir}"
            ) from exc
        root_name = relative.parts[0]
        if root_name not in dict(root_specs):
            root_specs.append((root_name, classification))

    if not root_specs:
        raise ValueError(
            f"No canonical roots were discovered from manifest {manifest_path}"
        )
    return dict(root_specs)


def support_reason(path: Path, logs_dir: Path) -> str | None:
    relative = path.relative_to(logs_dir)
    if len(relative.parts) == 1:
        root_name = relative.parts[0]
        if root_name in SUPPORT_ROOT_REASONS:
            return SUPPORT_ROOT_REASONS[root_name]
        for prefix, reason in SUPPORT_ROOT_PREFIX_REASONS.items():
            if root_name.startswith(prefix):
                return reason
        return None
    return SUPPORT_DIR_REASONS.get(path.name)


def canonical_root_family(root_name: str) -> str:
    if "-replicated-" in root_name:
        return root_name.split("-replicated-", 1)[0]
    if match := STAMP_SUFFIX_RE.match(root_name):
        return str(match.group("family"))
    return root_name


def collect_directories(
    *, repo_root: Path, logs_dir: Path
) -> tuple[list[Path], list[dict[str, str]]]:
    included: list[Path] = []
    excluded: list[dict[str, str]] = []

    def visit(directory: Path) -> None:
        child_dirs = sorted(
            (child for child in directory.iterdir() if child.is_dir()),
            key=lambda child: child.name,
        )
        for child in child_dirs:
            reason = support_reason(child, logs_dir)
            if reason is not None:
                excluded.append(
                    {
                        "path": normalize_path(child, repo_root),
                        "reason": reason,
                    }
                )
                continue
            included.append(child)
            visit(child)

    visit(logs_dir)
    excluded.sort(key=lambda item: item["path"])
    return included, excluded


def has_relevant_child_dirs(path: Path, logs_dir: Path) -> bool:
    for child in path.iterdir():
        if child.is_dir() and support_reason(child, logs_dir) is None:
            return True
    return False


def demo_root_name(canonical_roots: dict[str, str]) -> str | None:
    for root_name, classification in canonical_roots.items():
        if classification == "demo":
            return root_name
    return None


def legacy_family_target(
    *,
    top_level: str,
    logs_dir: Path,
    canonical_roots: dict[str, str],
) -> Path | None:
    top_level_family = canonical_root_family(top_level)
    for root_name, classification in canonical_roots.items():
        if classification not in {"primary-evidence", "validation", "ablation"}:
            continue
        if root_name == top_level:
            continue
        if canonical_root_family(root_name) != top_level_family:
            continue
        return logs_dir / root_name
    return None


def find_legacy_target(
    *, path: Path, logs_dir: Path, canonical_roots: dict[str, str]
) -> Path | None:
    relative = path.relative_to(logs_dir)
    if len(relative.parts) != 1:
        return None

    name = relative.parts[0]
    demo_root = demo_root_name(canonical_roots)

    for root_name, classification in canonical_roots.items():
        prefix = f"{root_name}-"
        if not name.startswith(prefix):
            continue

        if classification == "demo":
            return logs_dir / root_name / "demo"

        suffix = name[len(prefix) :]
        candidate = logs_dir / root_name / suffix
        if candidate.is_dir():
            return candidate

    if demo_root and name.startswith(f"{demo_root}-"):
        return logs_dir / demo_root / "demo"

    return None


def build_entry(
    *,
    path: Path,
    repo_root: Path,
    logs_dir: Path,
    canonical_roots: dict[str, str],
) -> dict[str, Any]:
    relative = path.relative_to(logs_dir)
    top_level = relative.parts[0]
    parent_path = normalize_path(path.parent, repo_root) if len(relative.parts) > 1 else None

    if top_level in canonical_roots:
        classification = canonical_roots[top_level]
        entry: dict[str, Any] = {
            "path": normalize_path(path, repo_root),
            "classification": classification,
            "canonical": True,
            "parent_path": parent_path,
        }

        if classification == "demo":
            if len(relative.parts) == 1:
                entry["kind"] = "demo-root"
                entry["notes"] = "Frozen demo capture root referenced by the evidence manifest."
            elif relative.parts[1] == "demo" and len(relative.parts) == 2:
                entry["kind"] = "demo-bundle"
                entry["notes"] = "Canonical packaged demo bundle."
            elif relative.parts[1] == "demo":
                entry["kind"] = "demo-capture-dir"
                entry["notes"] = "Nested dashboard capture directory inside the canonical demo bundle."
            else:
                entry["kind"] = "demo-dir"
            return entry

        if len(relative.parts) == 1:
            entry["kind"] = "sweep-root"
            if classification == "primary-evidence":
                entry["notes"] = "Frozen Intel primary evidence root."
            elif classification == "validation":
                entry["notes"] = "Frozen AoT validation root."
            else:
                entry["notes"] = "Frozen ablation or adaptive sweep root."
            return entry

        entry["kind"] = "run-dir"
        return entry

    legacy_root_target = legacy_family_target(
        top_level=top_level,
        logs_dir=logs_dir,
        canonical_roots=canonical_roots,
    )
    if legacy_root_target is not None:
        canonical_path = legacy_root_target.joinpath(*relative.parts[1:]) if len(relative.parts) > 1 else legacy_root_target
        return {
            "path": normalize_path(path, repo_root),
            "classification": "legacy",
            "kind": "legacy-root" if len(relative.parts) == 1 else "legacy-run-dir",
            "canonical": False,
            "parent_path": parent_path,
            "canonical_path": normalize_path(canonical_path, repo_root),
            "notes": "Frozen historical sweep retained for provenance after the replicated evidence package became canonical.",
        }

    legacy_target = find_legacy_target(
        path=path,
        logs_dir=logs_dir,
        canonical_roots=canonical_roots,
    )
    if legacy_target is not None:
        notes = "Partial top-level remnant retained outside its canonical sweep root."
        if demo_root_name(canonical_roots) and path.name.startswith(
            f"{demo_root_name(canonical_roots)}-"
        ):
            notes = "Partial top-level demo remnant retained outside the canonical demo bundle."
        return {
            "path": normalize_path(path, repo_root),
            "classification": "legacy",
            "kind": "legacy-remnant",
            "canonical": False,
            "parent_path": None,
            "canonical_path": normalize_path(legacy_target, repo_root),
            "notes": notes,
        }

    kind = "run-dir"
    if len(relative.parts) == 1 and has_relevant_child_dirs(path, logs_dir):
        kind = "exploratory-root"

    return {
        "path": normalize_path(path, repo_root),
        "classification": "exploratory",
        "kind": kind,
        "canonical": True,
        "parent_path": parent_path,
        "notes": "Local exploratory or smoke artifact outside the frozen evidence package.",
    }


def build_registry(
    *, repo_root: Path, logs_dir: Path, manifest_path: Path
) -> dict[str, Any]:
    canonical_roots = load_canonical_roots(
        repo_root=repo_root,
        logs_dir=logs_dir,
        manifest_path=manifest_path,
    )
    directories, excluded = collect_directories(repo_root=repo_root, logs_dir=logs_dir)
    entries = [
        build_entry(
            path=path,
            repo_root=repo_root,
            logs_dir=logs_dir,
            canonical_roots=canonical_roots,
        )
        for path in directories
    ]
    entries.sort(key=lambda entry: entry["path"])

    counts = Counter(entry["classification"] for entry in entries)
    classification_order = [
        "primary-evidence",
        "validation",
        "demo",
        "ablation",
        "legacy",
        "exploratory",
    ]

    return {
        "schema_version": 2,
        "logs_root": normalize_path(logs_dir, repo_root),
        "scope": "experiment-run-demo-directories-only",
        "canonical_roots": [
            {
                "path": normalize_path(logs_dir / root_name, repo_root),
                "classification": classification,
            }
            for root_name, classification in sorted(canonical_roots.items())
        ],
        "excluded_support_directories": excluded,
        "summary": {
            "entry_count": len(entries),
            "excluded_support_directory_count": len(excluded),
            "classification_counts": {
                classification: counts.get(classification, 0)
                for classification in classification_order
                if counts.get(classification, 0) > 0
            },
        },
        "entries": entries,
    }


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    logs_dir = args.logs_dir.resolve()
    manifest_path = args.manifest_path.resolve()
    output_path = args.output.resolve()

    registry = build_registry(
        repo_root=repo_root,
        logs_dir=logs_dir,
        manifest_path=manifest_path,
    )
    output_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote run registry to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
