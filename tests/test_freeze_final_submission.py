from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from experiments.freeze_final_submission import freeze_final_submission


class FreezeFinalSubmissionTests(unittest.TestCase):
    def test_freeze_writes_manifest_and_blocks_on_unmanaged_report_asset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            repo_root = Path(tmp_dir_name)
            paths = self._create_repo_fixture(repo_root, include_unmanaged_report_asset=True)

            manifest = freeze_final_submission(
                project_root=repo_root,
                report_dir=paths["report_dir"],
                paper_dir=paths["paper_dir"],
                logs_dir=paths["logs_dir"],
                manifest_output_path=paths["manifest_output_path"],
                deliverable_gate_path=paths["deliverable_gate_path"],
                command_runner=self._passing_command_runner,
                which_lookup=lambda _tool: None,
            )

            self.assertEqual(manifest["status"], "blocked")
            self.assertIsNone(manifest["manual_signoff_draft"])
            self.assertIn(
                "report/assets/final_submission_manifest.json",
                manifest["included_submission_files"],
            )
            self.assertIn(
                "report/assets/figures/file.png",
                "\n".join(manifest["validation"]["blocking_findings"]),
            )
            self.assertIn(
                "LaTeX toolchain unavailable; source tree frozen as build-ready only.",
                manifest["environment_limitations"],
            )
            self.assertTrue(paths["manifest_output_path"].exists())
            self.assertTrue(paths["deliverable_gate_path"].exists())
            deliverable_gate = paths["deliverable_gate_path"].read_text(encoding="utf-8")
            self.assertIn("Freeze status: `blocked`", deliverable_gate)
            self.assertIn("Unmanaged report asset present: report/assets/figures/file.png", deliverable_gate)
            saved_manifest = json.loads(paths["manifest_output_path"].read_text(encoding="utf-8"))
            self.assertEqual(saved_manifest["status"], "blocked")

    def test_freeze_drafts_manual_signoff_only_when_validation_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            repo_root = Path(tmp_dir_name)
            paths = self._create_repo_fixture(repo_root, include_unmanaged_report_asset=False)

            manifest = freeze_final_submission(
                project_root=repo_root,
                report_dir=paths["report_dir"],
                paper_dir=paths["paper_dir"],
                logs_dir=paths["logs_dir"],
                manifest_output_path=paths["manifest_output_path"],
                deliverable_gate_path=paths["deliverable_gate_path"],
                command_runner=self._passing_command_runner,
                which_lookup=lambda tool: f"C:/tools/{tool}.exe",
            )

            self.assertEqual(manifest["status"], "passed")
            self.assertIsNotNone(manifest["manual_signoff_draft"])
            self.assertEqual(manifest["validation"]["blocking_findings"], [])
            self.assertEqual(manifest["environment_limitations"], [])
            static_check_statuses = {
                check["name"]: check["status"]
                for check in manifest["validation"]["static_checks"]
            }
            self.assertEqual(static_check_statuses["tex_reference_paths"], "passed")
            self.assertEqual(static_check_statuses["citation_keys"], "passed")
            self.assertEqual(static_check_statuses["report_asset_inventory"], "passed")
            self.assertEqual(static_check_statuses["paper_asset_inventory"], "passed")
            self.assertEqual(static_check_statuses["document_provenance_anchors"], "passed")
            self.assertEqual(static_check_statuses["latex_toolchain"], "passed")
            self.assertIn(
                "Broad downstream-byte reduction remains unsupported; keep the fallback wording from report/assets/tables/intel_key_claims.md.",
                manifest["manual_signoff_draft"]["recommended_points"],
            )

    def _create_repo_fixture(
        self,
        repo_root: Path,
        *,
        include_unmanaged_report_asset: bool,
    ) -> dict[str, Path]:
        report_dir = repo_root / "report"
        report_assets_dir = report_dir / "assets"
        report_figures_dir = report_assets_dir / "figures"
        report_tables_dir = report_assets_dir / "tables"
        paper_dir = repo_root / "research_paper"
        paper_figures_dir = paper_dir / "figures"
        paper_tables_dir = paper_dir / "tables"
        sections_dir = paper_dir / "Sections"
        logs_dir = repo_root / "experiments" / "logs"

        for directory in (
            report_figures_dir,
            report_tables_dir,
            paper_figures_dir,
            paper_tables_dir,
            sections_dir,
            logs_dir,
            repo_root / "gateway",
            repo_root / "ui",
            repo_root / "simulator",
            repo_root / "experiments",
            repo_root / "tests",
        ):
            directory.mkdir(parents=True, exist_ok=True)

        self._write(repo_root / "gateway" / "server.py", "print('gateway')\n")
        self._write(repo_root / "ui" / "dashboard.html", "<html></html>\n")
        self._write(repo_root / "simulator" / "replay_mqtt.py", "print('replay')\n")
        self._write(repo_root / "simulator" / "preprocess_intel_lab.py", "print('intel')\n")
        self._write(repo_root / "simulator" / "preprocess_aot.py", "print('aot')\n")
        self._write(repo_root / "experiments" / "analyze_run.py", "print('analyze')\n")
        self._write(repo_root / "experiments" / "impairment_proxy.py", "print('proxy')\n")
        self._write(repo_root / "experiments" / "run_sweep.py", "print('sweep')\n")
        self._write(repo_root / "experiments" / "run_demo.py", "print('demo')\n")
        self._write(repo_root / "experiments" / "run_final_deliverables.py", "print('final')\n")
        self._write(repo_root / "experiments" / "build_report_assets.py", "print('report assets')\n")
        self._write(repo_root / "experiments" / "build_run_registry.py", "print('registry')\n")
        self._write(repo_root / "experiments" / "package_paper_assets.py", "print('paper assets')\n")
        self._write(repo_root / "experiments" / "sweep_aggregation.py", "print('aggregate')\n")
        self._write(repo_root / "experiments" / "run_replicated_phase6.py", "print('phase6')\n")
        self._write(repo_root / "experiments" / "run_batch_window_sweep.py", "print('batch')\n")
        self._write(repo_root / "experiments" / "run_v1_v2_isolation_sweep.py", "print('iso')\n")
        self._write(repo_root / "experiments" / "run_adaptive_impairment_sweep.py", "print('adaptive')\n")
        self._write(repo_root / "experiments" / "run_v3_adaptive_parameter_sweep.py", "print('adaptive sweep')\n")
        self._write(repo_root / "experiments" / "reproduce_all.sh", "#!/usr/bin/env bash\n")
        self._write(repo_root / "experiments" / "capture_dashboard.mjs", "console.log('ok');\n")
        self._write(repo_root / "tests" / "test_example.py", "print('test')\n")

        self._write(repo_root / "README_reproducibility.md", "")
        self._write(report_dir / "final_report.md", "")
        self._write(report_dir / "reproducibility.md", "")
        self._write(report_dir / "experiment_pipeline_audit.md", "pipeline audit\n")
        self._write(report_dir / "metric_definitions.md", "metric definitions\n")
        self._write(report_dir / "deliverable_gate.md", "placeholder\n")

        self._write(report_figures_dir / "intel_clean_qos0_latency_cdf.png", "png\n")
        self._write(report_tables_dir / "intel_primary_run_summary.csv", "run_id\n")
        self._write(report_tables_dir / "intel_primary_run_summary.md", "| run_id |\n")
        self._write(report_assets_dir / "CLAIM_TO_EVIDENCE_MAP.md", "claim map\n")
        self._write(report_assets_dir / "old_evidence_inventory.json", json.dumps({"entries": []}, indent=2))

        evidence_manifest = {
            "schema_version": 2,
            "intel_sweep_dir": "experiments/logs/final-intel-primary-replicated-20260408-135251",
            "aot_sweep_dir": "experiments/logs/final-aot-validation-replicated-20260408-135251",
            "demo_dir": "experiments/logs/final-demo-20260403/demo",
            "run_registry_path": "experiments/logs/run_registry.json",
            "old_evidence_inventory_path": "report/assets/old_evidence_inventory.json",
            "claim_map_path": "report/assets/CLAIM_TO_EVIDENCE_MAP.md",
            "asset_provenance": [
                {"asset_path": "report/assets/figures/intel_clean_qos0_latency_cdf.png"},
                {"asset_path": "report/assets/tables/intel_primary_run_summary.csv"},
                {"asset_path": "report/assets/tables/intel_primary_run_summary.md"},
            ],
            "generated_figures": [
                "report/assets/figures/intel_clean_qos0_latency_cdf.png",
            ],
            "generated_tables": [
                "report/assets/tables/intel_primary_run_summary.csv",
                "report/assets/tables/intel_primary_run_summary.md",
            ],
        }
        self._write(report_assets_dir / "evidence_manifest.json", json.dumps(evidence_manifest, indent=2))

        if include_unmanaged_report_asset:
            self._write(report_figures_dir / "file.png", "extra\n")

        self._write(sections_dir / "introduction.tex", "Intro with citation \\cite{mqtt311}.\n")
        self._write(sections_dir / "approach-cs537.png", "png\n")
        self._write(
            paper_dir / "main.tex",
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            "\\input{Sections/introduction}\n"
            "\\includegraphics{Sections/approach-cs537.png}\n"
            "\\bibliography{references}\n"
            "\\end{document}\n",
        )
        self._write(
            paper_dir / "references.bib",
            "@misc{mqtt311,\n  title = {MQTT}\n}\n",
        )
        self._write(paper_figures_dir / "main_outage_frame_rate.png", "png\n")
        self._write(paper_tables_dir / "intel_main_summary_table.tex", "\\begin{tabular}{}\\end{tabular}\n")
        self._write(paper_tables_dir / "paper_asset_index.md", "asset index\n")
        paper_assets_manifest = {
            "main_paper_assets": [
                "research_paper/figures/main_outage_frame_rate.png",
            ],
            "appendix_assets": [],
            "generated_latex_table": "research_paper/tables/intel_main_summary_table.tex",
            "paper_asset_index_path": "research_paper/tables/paper_asset_index.md",
            "paper_native_assets": [
                {
                    "paper_asset_path": "research_paper/Sections/approach-cs537.png",
                }
            ],
        }
        self._write(
            paper_tables_dir / "paper_assets_manifest.json",
            json.dumps(paper_assets_manifest, indent=2),
        )

        run_registry = {
            "canonical_roots": [
                {
                    "path": "experiments/logs/final-intel-primary-replicated-20260408-135251",
                    "classification": "primary-evidence",
                },
                {
                    "path": "experiments/logs/final-aot-validation-replicated-20260408-135251",
                    "classification": "validation",
                },
                {
                    "path": "experiments/logs/final-demo-20260403",
                    "classification": "demo",
                },
            ]
        }
        self._write(logs_dir / "run_registry.json", json.dumps(run_registry, indent=2))

        reproducibility_content = (
            "report/assets/evidence_manifest.json\n"
            "experiments/logs/run_registry.json\n"
            "research_paper/tables/paper_assets_manifest.json\n"
            "experiments/logs/final-intel-primary-replicated-20260408-135251\n"
            "experiments/logs/final-aot-validation-replicated-20260408-135251\n"
            "experiments/logs/final-demo-20260403\n"
        )
        self._write(repo_root / "README_reproducibility.md", reproducibility_content)
        self._write(report_dir / "reproducibility.md", reproducibility_content)
        self._write(
            report_dir / "final_report.md",
            "final-intel-primary-replicated-20260408-135251\n"
            "final-aot-validation-replicated-20260408-135251\n"
            "final-demo-20260403\n",
        )

        return {
            "report_dir": report_dir,
            "paper_dir": paper_dir,
            "logs_dir": logs_dir,
            "manifest_output_path": report_assets_dir / "final_submission_manifest.json",
            "deliverable_gate_path": report_dir / "deliverable_gate.md",
        }

    def _write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _passing_command_runner(self, command: list[str], *, cwd: Path, name: str) -> dict[str, object]:
        return {
            "name": name,
            "command": command,
            "status": "passed",
            "blocking": True,
            "returncode": 0,
            "summary": "ok",
            "stdout": "",
            "stderr": "",
        }


if __name__ == "__main__":
    unittest.main()
