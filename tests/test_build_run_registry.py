from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from experiments.build_run_registry import build_registry


class BuildRunRegistryTests(unittest.TestCase):
    def test_build_registry_classifies_replicated_roots_legacy_roots_and_exploratory_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            repo_root = Path(tmp_dir_name)
            logs_dir = repo_root / "experiments" / "logs"
            manifest_path = repo_root / "report" / "assets" / "evidence_manifest.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)

            current_intel = logs_dir / "final-intel-primary-replicated-20260408-135251"
            current_aot = logs_dir / "final-aot-validation-replicated-20260408-135251"
            demo_dir = logs_dir / "final-demo-20260403" / "demo"
            current_batch = logs_dir / "intel-v2-batch-window-replicated-20260408-135251"
            current_isolation = logs_dir / "intel-v1-v2-isolation-replicated-20260408-135251"
            current_adaptive = logs_dir / "intel-v2-v3-adaptive-replicated-20260408-135251"
            current_adaptive_param = logs_dir / "intel-v3-adaptive-parameter-sweep-20260408-190517"

            for path in [
                current_intel / "v0-qos0-clean" / "trial-01-seed-53701",
                current_aot / "v0-qos0-clean" / "trial-01-seed-53701",
                demo_dir / "baseline_dashboard",
                current_batch / "v2-qos0-clean-bw50ms" / "trial-01-seed-53701",
                current_isolation / "v1-qos0-clean-bw50ms" / "trial-01-seed-53701",
                current_adaptive / "v2-qos0-bandwidth_200kbps" / "trial-01-seed-53701",
                current_adaptive_param / "cfgparam01-bandwidth_200kbps" / "trial-01-seed-53701",
                logs_dir / "final-intel-primary-20260403" / "v0-qos0-clean",
                logs_dir / "final-aot-validation-20260403" / "v0-qos0-clean",
                logs_dir / "intel-v2-v3-adaptive-20260404" / "v2-qos0-bandwidth_200kbps",
                logs_dir / "smoke-m4-20260403" / "v4-qos0-clean",
                logs_dir / "final-deliverables-20260409",
            ]:
                path.mkdir(parents=True, exist_ok=True)

            (manifest_path).write_text(
                json.dumps(
                    {
                        "intel_sweep_dir": "experiments/logs/final-intel-primary-replicated-20260408-135251",
                        "aot_sweep_dir": "experiments/logs/final-aot-validation-replicated-20260408-135251",
                        "demo_dir": "experiments/logs/final-demo-20260403/demo",
                        "intel_batch_sweep_dir": "experiments/logs/intel-v2-batch-window-replicated-20260408-135251",
                        "intel_v1_v2_sweep_dir": "experiments/logs/intel-v1-v2-isolation-replicated-20260408-135251",
                        "intel_adaptive_sweep_dir": "experiments/logs/intel-v2-v3-adaptive-replicated-20260408-135251",
                        "intel_adaptive_parameter_sweep_dir": "experiments/logs/intel-v3-adaptive-parameter-sweep-20260408-190517",
                    }
                ),
                encoding="utf-8",
            )

            registry = build_registry(repo_root=repo_root, logs_dir=logs_dir, manifest_path=manifest_path)

            self.assertEqual(registry["schema_version"], 2)
            canonical_roots = {
                (entry["path"], entry["classification"])
                for entry in registry["canonical_roots"]
            }
            self.assertIn(
                (
                    "experiments/logs/intel-v3-adaptive-parameter-sweep-20260408-190517",
                    "ablation",
                ),
                canonical_roots,
            )

            legacy_root = self._entry_by_path(registry, "experiments/logs/final-intel-primary-20260403")
            self.assertEqual(legacy_root["classification"], "legacy")
            self.assertEqual(legacy_root["kind"], "legacy-root")
            self.assertFalse(legacy_root["canonical"])
            self.assertEqual(
                legacy_root["canonical_path"],
                "experiments/logs/final-intel-primary-replicated-20260408-135251",
            )

            legacy_run_dir = self._entry_by_path(
                registry,
                "experiments/logs/final-intel-primary-20260403/v0-qos0-clean",
            )
            self.assertEqual(legacy_run_dir["classification"], "legacy")
            self.assertEqual(legacy_run_dir["kind"], "legacy-run-dir")
            self.assertEqual(
                legacy_run_dir["canonical_path"],
                "experiments/logs/final-intel-primary-replicated-20260408-135251/v0-qos0-clean",
            )

            old_aot_root = self._entry_by_path(registry, "experiments/logs/final-aot-validation-20260403")
            self.assertEqual(old_aot_root["classification"], "legacy")

            exploratory_root = self._entry_by_path(registry, "experiments/logs/smoke-m4-20260403")
            self.assertEqual(exploratory_root["classification"], "exploratory")
            self.assertEqual(exploratory_root["kind"], "exploratory-root")

            self.assertTrue(
                any(
                    excluded["path"] == "experiments/logs/final-deliverables-20260409"
                    for excluded in registry["excluded_support_directories"]
                )
            )

    def _entry_by_path(self, registry: dict[str, object], path: str) -> dict[str, object]:
        for entry in registry["entries"]:
            if entry["path"] == path:
                return entry
        raise AssertionError(f"Missing registry entry for {path}")


if __name__ == "__main__":
    unittest.main()
