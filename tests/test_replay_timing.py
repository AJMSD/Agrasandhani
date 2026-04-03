from __future__ import annotations

import unittest

from simulator.replay_timing import BurstConfig, compute_target_offset_s


class ReplayTimingTests(unittest.TestCase):
    def test_baseline_replay_uses_plain_replay_speed(self) -> None:
        offset_s = compute_target_offset_s(
            relative_ms=4_000,
            replay_speed=2.0,
            burst=BurstConfig(),
        )
        self.assertEqual(offset_s, 2.0)

    def test_burst_only_accelerates_inside_the_configured_window(self) -> None:
        burst = BurstConfig(enabled=True, start_s=2.0, duration_s=2.0, speed_multiplier=4.0)
        self.assertEqual(
            compute_target_offset_s(relative_ms=1_000, replay_speed=1.0, burst=burst),
            1.0,
        )
        self.assertEqual(
            compute_target_offset_s(relative_ms=3_000, replay_speed=1.0, burst=burst),
            2.25,
        )

    def test_after_burst_the_saved_time_is_preserved(self) -> None:
        burst = BurstConfig(enabled=True, start_s=2.0, duration_s=2.0, speed_multiplier=4.0)
        self.assertEqual(
            compute_target_offset_s(relative_ms=5_000, replay_speed=1.0, burst=burst),
            3.5,
        )


if __name__ == "__main__":
    unittest.main()
