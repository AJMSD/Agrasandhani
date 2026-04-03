from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BurstConfig:
    enabled: bool = False
    start_s: float = 0.0
    duration_s: float = 0.0
    speed_multiplier: float = 1.0


def compute_target_offset_s(*, relative_ms: int, replay_speed: float, burst: BurstConfig) -> float:
    effective_replay_speed = max(replay_speed, 0.001)
    relative_s = max(relative_ms, 0) / 1_000.0

    if (
        not burst.enabled
        or burst.duration_s <= 0
        or burst.speed_multiplier <= 1.0
        or relative_s <= burst.start_s
    ):
        return relative_s / effective_replay_speed

    burst_start_s = max(burst.start_s, 0.0)
    burst_end_s = burst_start_s + burst.duration_s
    baseline_prefix_s = burst_start_s / effective_replay_speed

    if relative_s <= burst_end_s:
        burst_elapsed_s = relative_s - burst_start_s
        return baseline_prefix_s + (burst_elapsed_s / (effective_replay_speed * burst.speed_multiplier))

    burst_section_s = burst.duration_s / (effective_replay_speed * burst.speed_multiplier)
    after_burst_s = (relative_s - burst_end_s) / effective_replay_speed
    return baseline_prefix_s + burst_section_s + after_burst_s
