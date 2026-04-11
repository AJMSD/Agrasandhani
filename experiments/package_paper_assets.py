from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path


REPORT_ASSET_SPECS: list[dict[str, str]] = [
    {
        "paper_subdir": "figures",
        "filename": "main_outage_frame_rate.png",
        "paper_asset_kind": "figure",
        "role": "main",
        "proves": "Primary outage cadence result showing V2 and V4 sharply reduce downstream frame cadence versus V0.",
        "placement_reason": "Core headline figure for the main gateway stability story.",
    },
    {
        "paper_subdir": "figures",
        "filename": "intel_clean_qos0_latency_cdf.png",
        "paper_asset_kind": "figure",
        "role": "main",
        "proves": "Clean-path latency tradeoff showing the batching variants increase display latency relative to V0.",
        "placement_reason": "Keeps the main paper honest about the latency cost of stabilization.",
    },
    {
        "paper_subdir": "figures",
        "filename": "intel_outage_qos0_v0_vs_v4_age_over_time.png",
        "paper_asset_kind": "figure",
        "role": "main",
        "proves": "Freshness and visibility tradeoff showing V4 preserves visible state through outage at higher age.",
        "placement_reason": "Main freshness tradeoff figure for the outage story.",
    },
    {
        "paper_subdir": "tables",
        "filename": "intel_main_summary_table.csv",
        "paper_asset_kind": "table",
        "role": "main",
        "proves": "Compact cross-variant summary table for the main Intel comparisons.",
        "placement_reason": "Single compact table for the main paper asset slate.",
    },
    {
        "paper_subdir": "tables",
        "filename": "intel_bandwidth_vs_v0.csv",
        "paper_asset_kind": "table",
        "role": "appendix",
        "proves": "Bounded byte-audit source table showing the smart variants did not reduce downstream payload bytes versus V0.",
        "placement_reason": "Needed for claim traceability, but too detailed for the main paper.",
    },
    {
        "paper_subdir": "tables",
        "filename": "intel_bandwidth_vs_v0.md",
        "paper_asset_kind": "table",
        "role": "appendix",
        "proves": "Readable byte-claim fallback summary for the main Intel scenarios.",
        "placement_reason": "Supporting negative-result explanation kept out of the main narrative.",
    },
    {
        "paper_subdir": "tables",
        "filename": "intel_outage_qos0_v0_vs_v4_freshness.csv",
        "paper_asset_kind": "table",
        "role": "appendix",
        "proves": "Source freshness summary for the outage age/visibility comparison.",
        "placement_reason": "Supports the main freshness figure without taking table space in the paper body.",
    },
    {
        "paper_subdir": "tables",
        "filename": "intel_outage_qos0_v0_vs_v4_freshness.md",
        "paper_asset_kind": "table",
        "role": "appendix",
        "proves": "Readable freshness and retention summary for the outage comparison.",
        "placement_reason": "Appendix detail for the freshness tradeoff.",
    },
    {
        "paper_subdir": "figures",
        "filename": "intel_delay_qos0_inter_frame_gap_cdf.png",
        "paper_asset_kind": "figure",
        "role": "appendix",
        "proves": "Proxy-side inter-frame-gap CDF that locks the jitter source of truth to downstream sent-frame timing.",
        "placement_reason": "Important stability evidence, but supporting rather than headline.",
    },
    {
        "paper_subdir": "tables",
        "filename": "intel_jitter_summary.csv",
        "paper_asset_kind": "table",
        "role": "appendix",
        "proves": "Source jitter summary with proxy inter-frame-gap and frame-rate variability metrics.",
        "placement_reason": "Appendix reference table for the stability treatment.",
    },
    {
        "paper_subdir": "tables",
        "filename": "intel_jitter_summary.md",
        "paper_asset_kind": "table",
        "role": "appendix",
        "proves": "Readable jitter/stability summary tied to proxy-side metrics.",
        "placement_reason": "Supporting stability summary kept out of the main paper.",
    },
    {
        "paper_subdir": "figures",
        "filename": "intel_qos_comparison.png",
        "paper_asset_kind": "figure",
        "role": "appendix",
        "proves": "Side-by-side QoS0 versus QoS1 comparison across the Intel matrix.",
        "placement_reason": "Useful setup-specific context, but not part of the core five-asset slate.",
    },
    {
        "paper_subdir": "tables",
        "filename": "intel_qos_comparison.csv",
        "paper_asset_kind": "table",
        "role": "appendix",
        "proves": "Source QoS comparison table with latency and downstream-byte deltas.",
        "placement_reason": "Appendix support for the bounded QoS discussion.",
    },
    {
        "paper_subdir": "tables",
        "filename": "intel_qos_comparison.md",
        "paper_asset_kind": "table",
        "role": "appendix",
        "proves": "Readable QoS comparison summary for setup-specific behavior.",
        "placement_reason": "Supporting QoS detail kept out of the main paper.",
    },
    {
        "paper_subdir": "figures",
        "filename": "intel_v2_batch_window_tradeoff.png",
        "paper_asset_kind": "figure",
        "role": "appendix",
        "proves": "Batch-window sweep figure showing latency increases as cadence falls with larger windows.",
        "placement_reason": "Ablation detail that supports the story without crowding the main paper.",
    },
    {
        "paper_subdir": "tables",
        "filename": "intel_v2_batch_window_tradeoff.csv",
        "paper_asset_kind": "table",
        "role": "appendix",
        "proves": "Source batch-window sweep summary across the tested windows.",
        "placement_reason": "Appendix reference for the batch-window ablation.",
    },
    {
        "paper_subdir": "tables",
        "filename": "intel_v2_batch_window_tradeoff.md",
        "paper_asset_kind": "table",
        "role": "appendix",
        "proves": "Readable batch-window tradeoff summary with latency, frames, and bytes.",
        "placement_reason": "Supporting ablation detail kept out of the main narrative.",
    },
    {
        "paper_subdir": "figures",
        "filename": "intel_v1_vs_v2_isolation.png",
        "paper_asset_kind": "figure",
        "role": "appendix",
        "proves": "Isolation figure showing the marginal effect of compaction beyond batching alone.",
        "placement_reason": "Negative/mixed ablation result that belongs in appendix-ready support.",
    },
    {
        "paper_subdir": "tables",
        "filename": "intel_v1_vs_v2_isolation.csv",
        "paper_asset_kind": "table",
        "role": "appendix",
        "proves": "Source isolation summary for V1 versus V2 across shared scenarios and windows.",
        "placement_reason": "Appendix reference for the mixed compaction result.",
    },
    {
        "paper_subdir": "tables",
        "filename": "intel_v1_vs_v2_isolation.md",
        "paper_asset_kind": "table",
        "role": "appendix",
        "proves": "Readable isolation summary for the V1 versus V2 comparison.",
        "placement_reason": "Supporting negative-result detail kept out of the main paper.",
    },
    {
        "paper_subdir": "figures",
        "filename": "intel_v2_vs_v3_adaptive_impairment.png",
        "paper_asset_kind": "figure",
        "role": "appendix",
        "proves": "Adaptive comparison figure showing the tested V3 controller did not materially beat fixed-window V2.",
        "placement_reason": "Important null-result evidence, but not part of the main claim-carrying slate.",
    },
    {
        "paper_subdir": "tables",
        "filename": "intel_v2_vs_v3_adaptive_impairment.csv",
        "paper_asset_kind": "table",
        "role": "appendix",
        "proves": "Source adaptive comparison table for the replicated V2 versus V3 impairment runs.",
        "placement_reason": "Appendix reference for the bounded adaptive claim.",
    },
    {
        "paper_subdir": "tables",
        "filename": "intel_v2_vs_v3_adaptive_impairment.md",
        "paper_asset_kind": "table",
        "role": "appendix",
        "proves": "Readable adaptive comparison summary for the replicated V2 versus V3 runs.",
        "placement_reason": "Supporting null-result explanation kept out of the main paper.",
    },
    {
        "paper_subdir": "tables",
        "filename": "intel_v3_adaptive_parameter_sweep.csv",
        "paper_asset_kind": "table",
        "role": "appendix",
        "proves": "Source bounded V3-only parameter sweep table used to test whether adaptation ever triggers and helps.",
        "placement_reason": "Appendix evidence for the adaptive fallback classification.",
    },
    {
        "paper_subdir": "tables",
        "filename": "intel_v3_adaptive_parameter_sweep.md",
        "paper_asset_kind": "table",
        "role": "appendix",
        "proves": "Readable bounded V3 parameter sweep summary supporting the adaptive null result.",
        "placement_reason": "Supporting parameter-sweep detail kept out of the main narrative.",
    },
    {
        "paper_subdir": "tables",
        "filename": "intel_claim_guardrail_review.md",
        "paper_asset_kind": "table",
        "role": "appendix",
        "proves": "Explicit guardrail wording for bounded claim language and prohibited overstatements.",
        "placement_reason": "Appendix-ready traceability artifact rather than a paper body table.",
    },
    {
        "paper_subdir": "figures",
        "filename": "final_demo_compare.png",
        "paper_asset_kind": "figure",
        "role": "appendix",
        "proves": "Captured demo comparison showing the visible dashboard difference between baseline and smart modes.",
        "placement_reason": "Useful qualitative support, but not part of the core measured-paper slate.",
    },
    {
        "paper_subdir": "figures",
        "filename": "intel_outage_qos1_bandwidth_over_time.png",
        "paper_asset_kind": "figure",
        "role": "appendix",
        "proves": "Outage bandwidth trace showing when downstream payload bytes are emitted during disruption and recovery.",
        "placement_reason": "Already cited supporting context that should remain package-ready, not headline evidence.",
    },
    {
        "paper_subdir": "figures",
        "filename": "intel_outage_qos1_message_rate_over_time.png",
        "paper_asset_kind": "figure",
        "role": "appendix",
        "proves": "Outage message-rate trace showing pacing changes through disruption and recovery.",
        "placement_reason": "Already cited supporting context that stays available without joining the main five-asset slate.",
    },
]

PAPER_NATIVE_ASSET_SPECS: list[dict[str, str]] = [
    {
        "paper_asset_path": "research_paper/assets/approach-cs537.png",
        "paper_asset_kind": "figure",
        "role": "main",
        "proves": "System architecture showing the measured replay to MQTT broker to smart gateway to impairment proxy to WebSocket dashboard path.",
        "placement_reason": "Needed for main-paper orientation, but intentionally kept paper-native rather than report-derived.",
    }
]


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        raw_rows = list(csv.DictReader(handle))
    return [{key: (value.strip() if isinstance(value, str) else value) for key, value in row.items()} for row in raw_rows]


def _write_latex_main_summary_table(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "\\begin{table}[t]",
        "\\centering",
        "\\caption{Main condensed Intel summary (QoS0, final primary runs).}",
        "\\label{tab:main-summary}",
        "\\scriptsize",
        "\\begin{tabular}{lrrrrl}",
        "\\toprule",
        "Variant & Frames & Bytes & Latency p95 (ms) & Stale Fraction & Scenario \\\\",
        "\\midrule",
    ]
    for row in rows:
        lines.append(
            f"{row['Variant']} & {row['Downstream Frames']} & {row['Downstream Bytes']} & {row['Latency p95']} & {row['Stale Fraction']} & {row['Scenario']} \\\\"
        )
    lines.extend([
        "\\bottomrule",
        "\\end{tabular}",
        "\\end{table}",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_asset_index(
    path: Path,
    *,
    paper_native_assets: list[dict[str, object]],
    packaged_assets: list[dict[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Paper Asset Index",
        "",
        "This index locks the Section 9 main-paper slate and the appendix-ready supporting bundle.",
        "",
        "## Main Paper Assets",
        "",
        "| Asset | Kind | Source | Proves | Placement Reason |",
        "| --- | --- | --- | --- | --- |",
    ]

    for entry in paper_native_assets + [asset for asset in packaged_assets if asset["role"] == "main"]:
        source = entry.get("source_report_asset_path", "paper-native")
        lines.append(
            f"| `{entry['paper_asset_path']}` | {entry['paper_asset_kind']} | `{source}` | {entry['proves']} | {entry['placement_reason']} |"
        )

    lines.extend([
        "",
        "## Appendix-Ready Supporting Assets",
        "",
        "| Asset | Kind | Source | Proves | Placement Reason |",
        "| --- | --- | --- | --- | --- |",
    ])

    for entry in [asset for asset in packaged_assets if asset["role"] == "appendix"]:
        lines.append(
            f"| `{entry['paper_asset_path']}` | {entry['paper_asset_kind']} | `{entry['source_report_asset_path']}` | {entry['proves']} | {entry['placement_reason']} |"
        )

    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _canonical_report_asset_path(*parts: str) -> str:
    return "/".join(("report", "assets", *parts))


def _canonical_paper_asset_path(*parts: str) -> str:
    return "/".join(("research_paper", *parts))


def _resolve_paper_asset_path(*, paper_dir: Path, canonical_path: str) -> Path:
    parts = Path(canonical_path).parts
    if not parts or parts[0] != paper_dir.name:
        raise ValueError(f"Paper asset path must be rooted at {paper_dir.name}: {canonical_path}")
    return paper_dir.joinpath(*parts[1:])


def _provenance_entries_by_path(evidence_manifest: dict[str, object]) -> dict[str, dict[str, object]]:
    entries = evidence_manifest.get("asset_provenance")
    if not isinstance(entries, list):
        raise ValueError("evidence_manifest.json is missing asset_provenance entries")

    indexed: dict[str, dict[str, object]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        asset_path = entry.get("asset_path")
        if not isinstance(asset_path, str) or not asset_path:
            continue
        indexed[asset_path] = entry
    return indexed


def _combine_generation_scripts(report_generation_script: object) -> str:
    scripts = ["experiments/package_paper_assets.py"]
    if isinstance(report_generation_script, str) and report_generation_script.strip():
        scripts.insert(0, report_generation_script.strip())

    ordered: list[str] = []
    seen: set[str] = set()
    for script in scripts:
        if script in seen:
            continue
        seen.add(script)
        ordered.append(script)
    return "; ".join(ordered)


def _packaged_asset_entry(
    *,
    paper_asset_path: str,
    paper_asset_kind: str,
    source_report_asset_path: str,
    report_entry: dict[str, object],
    role: str,
    proves: str,
    placement_reason: str,
) -> dict[str, object]:
    return {
        "paper_asset_path": paper_asset_path,
        "paper_asset_kind": paper_asset_kind,
        "source_report_asset_path": source_report_asset_path,
        "role": role,
        "proves": proves,
        "placement_reason": placement_reason,
        "source_sweep_ids": list(report_entry.get("source_sweep_ids", [])),
        "source_run_ids": list(report_entry.get("source_run_ids", [])),
        "source_artifacts": list(report_entry.get("source_artifacts", [])),
        "aggregate_input_artifacts": list(report_entry.get("aggregate_input_artifacts", [])),
        "generation_script": _combine_generation_scripts(report_entry.get("generation_script")),
    }


def _copy_report_asset(*, source_dir: Path, destination_dir: Path, filename: str) -> None:
    destination_dir.mkdir(parents=True, exist_ok=True)
    source = source_dir / filename
    if not source.exists():
        raise FileNotFoundError(f"Missing required asset: {source}")
    shutil.copy2(source, destination_dir / filename)


def _previous_managed_paths(manifest_path: Path) -> set[str]:
    if not manifest_path.exists():
        return set()

    manifest = _load_json(manifest_path)
    managed_paths: set[str] = set()
    for entry in manifest.get("packaged_assets", []):
        if isinstance(entry, dict):
            paper_asset_path = entry.get("paper_asset_path")
            if isinstance(paper_asset_path, str) and paper_asset_path:
                managed_paths.add(paper_asset_path)

    for field_name in ("generated_latex_table", "paper_asset_index_path"):
        field_value = manifest.get(field_name)
        if isinstance(field_value, str) and field_value:
            managed_paths.add(field_value)

    return managed_paths


def _remove_stale_managed_assets(*, paper_dir: Path, previous_manifest_path: Path, desired_paths: set[str]) -> None:
    for managed_path in sorted(_previous_managed_paths(previous_manifest_path) - desired_paths):
        resolved = _resolve_paper_asset_path(paper_dir=paper_dir, canonical_path=managed_path)
        if resolved.exists():
            resolved.unlink()


def _paper_native_assets(*, paper_dir: Path) -> list[dict[str, object]]:
    assets: list[dict[str, object]] = []
    for spec in PAPER_NATIVE_ASSET_SPECS:
        resolved = _resolve_paper_asset_path(paper_dir=paper_dir, canonical_path=spec["paper_asset_path"])
        if not resolved.exists():
            raise FileNotFoundError(f"Missing required paper-native asset: {resolved}")
        assets.append(
            {
                "paper_asset_path": spec["paper_asset_path"],
                "paper_asset_kind": spec["paper_asset_kind"],
                "asset_origin": "paper-native",
                "role": spec["role"],
                "proves": spec["proves"],
                "placement_reason": spec["placement_reason"],
            }
        )
    return assets


def package_assets(*, report_assets_dir: Path, paper_dir: Path) -> dict[str, object]:
    figures_src = report_assets_dir / "figures"
    tables_src = report_assets_dir / "tables"
    paper_figures = paper_dir / "figures"
    paper_tables = paper_dir / "tables"
    previous_manifest_path = paper_tables / "paper_assets_manifest.json"

    latex_table_path = _canonical_paper_asset_path("tables", "intel_main_summary_table.tex")
    asset_index_path = _canonical_paper_asset_path("tables", "paper_asset_index.md")

    desired_paths = {
        _canonical_paper_asset_path(spec["paper_subdir"], spec["filename"])
        for spec in REPORT_ASSET_SPECS
    }
    desired_paths.update({latex_table_path, asset_index_path})

    _remove_stale_managed_assets(
        paper_dir=paper_dir,
        previous_manifest_path=previous_manifest_path,
        desired_paths=desired_paths,
    )

    evidence_manifest = _load_json(report_assets_dir / "evidence_manifest.json")
    report_asset_entries = _provenance_entries_by_path(evidence_manifest)

    copied_figures: list[str] = []
    copied_tables: list[str] = []
    packaged_assets: list[dict[str, object]] = []

    for spec in REPORT_ASSET_SPECS:
        source_dir = figures_src if spec["paper_subdir"] == "figures" else tables_src
        destination_dir = paper_figures if spec["paper_subdir"] == "figures" else paper_tables
        _copy_report_asset(
            source_dir=source_dir,
            destination_dir=destination_dir,
            filename=spec["filename"],
        )

        if spec["paper_subdir"] == "figures":
            copied_figures.append(spec["filename"])
        else:
            copied_tables.append(spec["filename"])

        source_report_asset_path = _canonical_report_asset_path(spec["paper_subdir"], spec["filename"])
        packaged_assets.append(
            _packaged_asset_entry(
                paper_asset_path=_canonical_paper_asset_path(spec["paper_subdir"], spec["filename"]),
                paper_asset_kind=spec["paper_asset_kind"],
                source_report_asset_path=source_report_asset_path,
                report_entry=report_asset_entries[source_report_asset_path],
                role=spec["role"],
                proves=spec["proves"],
                placement_reason=spec["placement_reason"],
            )
        )

    main_summary_rows = _read_csv(tables_src / "intel_main_summary_table.csv")
    resolved_latex_table_path = _resolve_paper_asset_path(paper_dir=paper_dir, canonical_path=latex_table_path)
    _write_latex_main_summary_table(resolved_latex_table_path, main_summary_rows)

    main_summary_report_asset_path = _canonical_report_asset_path("tables", "intel_main_summary_table.csv")
    packaged_assets.append(
        _packaged_asset_entry(
            paper_asset_path=latex_table_path,
            paper_asset_kind="table",
            source_report_asset_path=main_summary_report_asset_path,
            report_entry=report_asset_entries[main_summary_report_asset_path],
            role="main",
            proves="Main-paper LaTeX table generated from the compact Intel summary CSV.",
            placement_reason="Main-paper table form derived directly from the locked summary source.",
        )
    )

    packaged_assets.sort(key=lambda entry: str(entry["paper_asset_path"]))
    paper_native_assets = _paper_native_assets(paper_dir=paper_dir)
    resolved_asset_index_path = _resolve_paper_asset_path(paper_dir=paper_dir, canonical_path=asset_index_path)
    _write_asset_index(
        resolved_asset_index_path,
        paper_native_assets=paper_native_assets,
        packaged_assets=packaged_assets,
    )

    main_paper_assets = [
        entry["paper_asset_path"] for entry in paper_native_assets if entry["role"] == "main"
    ] + [
        entry["paper_asset_path"] for entry in packaged_assets if entry["role"] == "main"
    ]
    appendix_assets = [
        entry["paper_asset_path"] for entry in packaged_assets if entry["role"] == "appendix"
    ]

    manifest = {
        "schema_version": 2,
        "report_evidence_manifest_path": _canonical_report_asset_path("evidence_manifest.json"),
        "claim_map_path": evidence_manifest.get("claim_map_path", _canonical_report_asset_path("CLAIM_TO_EVIDENCE_MAP.md")),
        "copied_figures": copied_figures,
        "copied_tables": copied_tables,
        "generated_latex_table": latex_table_path,
        "paper_asset_index_path": asset_index_path,
        "paper_native_assets": paper_native_assets,
        "packaged_assets": packaged_assets,
        "main_paper_assets": main_paper_assets,
        "appendix_assets": appendix_assets,
    }
    previous_manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Copy report assets into research_paper and generate paper-facing table artifacts.")
    parser.add_argument("--report-assets-dir", type=Path, required=True)
    parser.add_argument("--paper-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = package_assets(
        report_assets_dir=args.report_assets_dir,
        paper_dir=args.paper_dir,
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
