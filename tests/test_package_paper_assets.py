from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from experiments.package_paper_assets import package_assets


EXPECTED_FIGURES = [
    "main_outage_frame_rate.png",
    "intel_clean_qos0_latency_cdf.png",
    "intel_outage_qos0_v0_vs_v4_age_over_time.png",
    "intel_delay_qos0_inter_frame_gap_cdf.png",
    "intel_qos_comparison.png",
    "intel_v2_batch_window_tradeoff.png",
    "intel_v1_vs_v2_isolation.png",
    "intel_v2_vs_v3_adaptive_impairment.png",
    "final_demo_compare.png",
    "intel_outage_qos1_bandwidth_over_time.png",
    "intel_outage_qos1_message_rate_over_time.png",
]

EXPECTED_TABLES = [
    "intel_main_summary_table.csv",
    "intel_bandwidth_vs_v0.csv",
    "intel_bandwidth_vs_v0.md",
    "intel_outage_qos0_v0_vs_v4_freshness.csv",
    "intel_outage_qos0_v0_vs_v4_freshness.md",
    "intel_jitter_summary.csv",
    "intel_jitter_summary.md",
    "intel_qos_comparison.csv",
    "intel_qos_comparison.md",
    "intel_v2_batch_window_tradeoff.csv",
    "intel_v2_batch_window_tradeoff.md",
    "intel_v1_vs_v2_isolation.csv",
    "intel_v1_vs_v2_isolation.md",
    "intel_v2_vs_v3_adaptive_impairment.csv",
    "intel_v2_vs_v3_adaptive_impairment.md",
    "intel_v3_adaptive_parameter_sweep.csv",
    "intel_v3_adaptive_parameter_sweep.md",
    "intel_claim_guardrail_review.md",
]


class PackagePaperAssetsTests(unittest.TestCase):
    def test_package_assets_curates_main_and_appendix_assets_and_cleans_stale_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            base_dir = Path(tmp_dir_name)
            report_assets_dir = base_dir / "report" / "assets"
            paper_dir = base_dir / "research_paper"
            figures_dir = report_assets_dir / "figures"
            tables_dir = report_assets_dir / "tables"
            figures_dir.mkdir(parents=True, exist_ok=True)
            tables_dir.mkdir(parents=True, exist_ok=True)
            (paper_dir / "Sections").mkdir(parents=True, exist_ok=True)
            (paper_dir / "Sections" / "approach-cs537.png").write_bytes(b"architecture")

            for filename in EXPECTED_FIGURES:
                (figures_dir / filename).write_bytes(b"png")
            for filename in EXPECTED_TABLES:
                if filename == "intel_main_summary_table.csv":
                    (tables_dir / filename).write_text(
                        "Variant,Downstream Frames,Downstream Bytes,Latency p95,Stale Fraction,Scenario\n"
                        "v0,120,10000,10,0.0,clean\n",
                        encoding="utf-8",
                    )
                else:
                    (tables_dir / filename).write_text("content\n", encoding="utf-8")

            claim_map_path = report_assets_dir / "CLAIM_TO_EVIDENCE_MAP.md"
            claim_map_path.write_text("sentinel claim map\n", encoding="utf-8")

            stale_figure = paper_dir / "figures" / "obsolete_legacy.png"
            stale_figure.parent.mkdir(parents=True, exist_ok=True)
            stale_figure.write_bytes(b"old")
            stale_table = paper_dir / "tables" / "intel_main_summary_table.md"
            stale_table.parent.mkdir(parents=True, exist_ok=True)
            stale_table.write_text("old main summary\n", encoding="utf-8")
            previous_manifest = {
                "schema_version": 2,
                "packaged_assets": [
                    {"paper_asset_path": "research_paper/figures/obsolete_legacy.png"},
                    {"paper_asset_path": "research_paper/tables/intel_main_summary_table.md"},
                ],
                "generated_latex_table": "research_paper/tables/intel_main_summary_table.tex",
                "paper_asset_index_path": "research_paper/tables/paper_asset_index.md",
            }
            (paper_dir / "tables" / "paper_assets_manifest.json").write_text(
                json.dumps(previous_manifest, indent=2),
                encoding="utf-8",
            )

            evidence_manifest = {
                "schema_version": 2,
                "claim_map_path": "report/assets/CLAIM_TO_EVIDENCE_MAP.md",
                "asset_provenance": [],
            }
            for filename in EXPECTED_FIGURES:
                evidence_manifest["asset_provenance"].append(
                    self._report_entry(
                        asset_path=f"report/assets/figures/{filename}",
                        asset_kind="figure",
                    )
                )
            for filename in EXPECTED_TABLES:
                evidence_manifest["asset_provenance"].append(
                    self._report_entry(
                        asset_path=f"report/assets/tables/{filename}",
                        asset_kind="table",
                    )
                )
            (report_assets_dir / "evidence_manifest.json").write_text(
                json.dumps(evidence_manifest, indent=2),
                encoding="utf-8",
            )

            manifest = package_assets(report_assets_dir=report_assets_dir, paper_dir=paper_dir)

            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(manifest["claim_map_path"], "report/assets/CLAIM_TO_EVIDENCE_MAP.md")
            self.assertEqual(manifest["copied_figures"], EXPECTED_FIGURES)
            self.assertEqual(manifest["copied_tables"], EXPECTED_TABLES)
            self.assertEqual(
                manifest["generated_latex_table"],
                "research_paper/tables/intel_main_summary_table.tex",
            )
            self.assertEqual(
                manifest["paper_asset_index_path"],
                "research_paper/tables/paper_asset_index.md",
            )
            self.assertEqual(claim_map_path.read_text(encoding="utf-8"), "sentinel claim map\n")

            self.assertFalse(stale_figure.exists())
            self.assertFalse(stale_table.exists())

            self.assertTrue((paper_dir / "tables" / "paper_assets_manifest.json").exists())
            self.assertTrue((paper_dir / "tables" / "paper_asset_index.md").exists())
            self.assertTrue((paper_dir / "tables" / "intel_main_summary_table.tex").exists())
            self.assertFalse((paper_dir / "tables" / "intel_main_summary_table.md").exists())
            self.assertTrue((paper_dir / "figures" / "main_outage_frame_rate.png").exists())
            self.assertTrue((paper_dir / "figures" / "intel_delay_qos0_inter_frame_gap_cdf.png").exists())
            self.assertTrue((paper_dir / "tables" / "intel_v3_adaptive_parameter_sweep.md").exists())

            self.assertEqual(len(manifest["packaged_assets"]), len(EXPECTED_FIGURES) + len(EXPECTED_TABLES) + 1)
            self.assertEqual(len(manifest["paper_native_assets"]), 1)

            latex_entry = self._paper_entry_by_path(
                manifest["packaged_assets"],
                "research_paper/tables/intel_main_summary_table.tex",
            )
            self.assertEqual(latex_entry["role"], "main")
            self.assertIn("Main-paper LaTeX table", latex_entry["proves"])
            self.assertEqual(
                latex_entry["source_report_asset_path"],
                "report/assets/tables/intel_main_summary_table.csv",
            )
            self.assertEqual(
                latex_entry["aggregate_input_artifacts"],
                ["experiments/logs/final-intel-primary-replicated-20260408-135251/condition_aggregates.json"],
            )
            self.assertEqual(
                latex_entry["generation_script"],
                "experiments/build_report_assets.py; experiments/package_paper_assets.py",
            )

            main_figure_entry = self._paper_entry_by_path(
                manifest["packaged_assets"],
                "research_paper/figures/main_outage_frame_rate.png",
            )
            self.assertEqual(main_figure_entry["paper_asset_kind"], "figure")
            self.assertEqual(main_figure_entry["role"], "main")
            self.assertTrue(main_figure_entry["placement_reason"])

            appendix_entry = self._paper_entry_by_path(
                manifest["packaged_assets"],
                "research_paper/tables/intel_claim_guardrail_review.md",
            )
            self.assertEqual(appendix_entry["role"], "appendix")
            self.assertIn("guardrail", appendix_entry["proves"].lower())
            self.assertTrue(appendix_entry["placement_reason"])

            for entry in manifest["packaged_assets"]:
                self.assertIn(entry["role"], {"main", "appendix"})
                self.assertTrue(entry["proves"])
                self.assertTrue(entry["placement_reason"])

            paper_native_entry = manifest["paper_native_assets"][0]
            self.assertEqual(paper_native_entry["paper_asset_path"], "research_paper/Sections/approach-cs537.png")
            self.assertEqual(paper_native_entry["role"], "main")
            self.assertEqual(paper_native_entry["asset_origin"], "paper-native")

            asset_index = (paper_dir / "tables" / "paper_asset_index.md").read_text(encoding="utf-8")
            self.assertIn("## Main Paper Assets", asset_index)
            self.assertIn("## Appendix-Ready Supporting Assets", asset_index)
            self.assertIn("research_paper/Sections/approach-cs537.png", asset_index)
            self.assertIn("research_paper/tables/intel_claim_guardrail_review.md", asset_index)

    def _report_entry(self, *, asset_path: str, asset_kind: str) -> dict[str, object]:
        return {
            "asset_path": asset_path,
            "asset_kind": asset_kind,
            "source_sweep_ids": ["final-intel-primary-replicated-20260408-135251"],
            "source_run_ids": ["v0-qos0-clean-trial-01-seed-53701"],
            "source_artifacts": [
                "experiments/logs/final-intel-primary-replicated-20260408-135251/v0-qos0-clean/trial-01-seed-53701/summary.json"
            ],
            "aggregate_input_artifacts": [
                "experiments/logs/final-intel-primary-replicated-20260408-135251/condition_aggregates.json"
            ],
            "generation_script": "experiments/build_report_assets.py",
        }

    def _paper_entry_by_path(self, entries: list[dict[str, object]], paper_asset_path: str) -> dict[str, object]:
        for entry in entries:
            if entry["paper_asset_path"] == paper_asset_path:
                return entry
        raise AssertionError(f"Missing paper asset entry for {paper_asset_path}")


if __name__ == "__main__":
    unittest.main()
