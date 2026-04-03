from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from experiments.impairment import ImpairmentScenario, ImpairmentSession, ProxyMetrics, TokenBucket, load_scenario


class ImpairmentTests(unittest.TestCase):
    def test_load_scenario_supports_repo_json(self) -> None:
        scenario = load_scenario(Path("experiments/scenarios/outage_5s.json"))
        self.assertEqual(scenario.name, "outage_5s")
        self.assertEqual(len(scenario.phases), 3)
        self.assertTrue(scenario.phases[1].outage)

    def test_seeded_loss_behavior_is_deterministic(self) -> None:
        scenario = ImpairmentScenario.model_validate(
            {
                "version": 1,
                "name": "loss-seeded",
                "phases": [{"name": "lossy", "duration_s": 10, "loss_rate": 0.5}],
            }
        )
        first = ImpairmentSession(scenario, seed=17)
        second = ImpairmentSession(scenario, seed=17)

        first_results = [first.plan(payload_bytes=64, now_s=100.0 + index).should_drop for index in range(8)]
        second_results = [second.plan(payload_bytes=64, now_s=100.0 + index).should_drop for index in range(8)]

        self.assertEqual(first_results, second_results)

    def test_outage_phase_clock_starts_on_first_frame(self) -> None:
        scenario = ImpairmentScenario.model_validate(
            {
                "version": 1,
                "name": "outage-timing",
                "phases": [
                    {"name": "steady", "duration_s": 1},
                    {"name": "outage", "duration_s": 1, "outage": True},
                ],
            }
        )
        session = ImpairmentSession(scenario, seed=1)

        first = session.plan(payload_bytes=32, now_s=500.0)
        second = session.plan(payload_bytes=32, now_s=500.8)
        third = session.plan(payload_bytes=32, now_s=501.2)

        self.assertEqual(first.phase_name, "steady")
        self.assertFalse(second.should_drop)
        self.assertEqual(third.phase_name, "outage")
        self.assertTrue(third.should_drop)

    def test_token_bucket_applies_wait_when_over_rate(self) -> None:
        bucket = TokenBucket(100, now_s=10.0)
        self.assertEqual(bucket.consume(50, now_s=10.0), 0)
        self.assertGreater(bucket.consume(75, now_s=10.0), 0)

    def test_metrics_snapshot_contains_uptime_and_phase(self) -> None:
        metrics = ProxyMetrics(upstream_frames_in=1, current_phase="clean")
        snapshot = metrics.snapshot(started_at_monotonic=time.monotonic() - 1.25, scenario_name="clean")
        self.assertEqual(snapshot["current_phase"], "clean")
        self.assertEqual(snapshot["scenario_name"], "clean")
        self.assertGreater(snapshot["process_uptime_s"], 1.0)


if __name__ == "__main__":
    unittest.main()
