from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from experiments.sweep_aggregation import aggregate_summary_rows, load_summary_rows


def _load_latency_samples(run_dir: Path) -> list[float]:
    csv_path = run_dir / "dashboard_measurements.csv"
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        return [float(row["age_ms_at_display"]) for row in csv.DictReader(handle)]


def _load_timeseries(run_dir: Path) -> list[dict[str, float]]:
    csv_path = run_dir / "timeseries.csv"
    if not csv_path.exists():
        return []
    rows: list[dict[str, float]] = []
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            rows.append({key: float(value) for key, value in row.items()})
    return rows


def plot_sweep(sweep_dir: Path) -> None:
    trial_rows = load_summary_rows(sweep_dir)
    if not trial_rows:
        raise SystemExit(f"No per-run summaries found under {sweep_dir}")
    summary_rows = aggregate_summary_rows(trial_rows)

    output_dir = sweep_dir / "plots"
    output_dir.mkdir(parents=True, exist_ok=True)

    grouped_runs: dict[str, list[Path]] = defaultdict(list)
    for payload in trial_rows:
        label = f"{payload['variant']} | {payload['scenario']} | qos{payload['mqtt_qos']}"
        grouped_runs[label].append(Path(str(payload["run_dir"])))

    figure = plt.figure(figsize=(10, 6))
    for label, run_dirs in sorted(grouped_runs.items()):
        samples: list[float] = []
        for run_dir in run_dirs:
            samples.extend(_load_latency_samples(run_dir))
        if not samples:
            continue
        ordered = sorted(samples)
        cdf = [(index + 1) / len(ordered) for index in range(len(ordered))]
        plt.plot(ordered, cdf, label=label)
    plt.xlabel("Latency (ms)")
    plt.ylabel("CDF")
    plt.title("Latency CDF by variant/scenario")
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(output_dir / "latency_cdf.png", dpi=150)
    plt.close(figure)

    for metric, title, filename in [
        ("bandwidth_bytes_per_s", "Bandwidth over time", "bandwidth_over_time.png"),
        ("update_rate_per_s", "Rendered update rate over time", "message_rate_over_time.png"),
    ]:
        figure = plt.figure(figsize=(10, 6))
        for label, run_dirs in sorted(grouped_runs.items()):
            series = _load_timeseries(run_dirs[0]) if run_dirs else []
            if not series:
                continue
            plt.plot(
                range(len(series)),
                [row[metric] for row in series],
                label=label,
            )
        plt.xlabel("Relative second")
        plt.ylabel(metric)
        plt.title(title)
        plt.legend(fontsize=8)
        plt.tight_layout()
        plt.savefig(output_dir / filename, dpi=150)
        plt.close(figure)

    figure = plt.figure(figsize=(10, 6))
    labels = [f"{row['variant']} | {row['scenario']} | qos{row['mqtt_qos']}" for row in summary_rows]
    stale_values = [float(row.get("stale_fraction", 0.0) or 0.0) for row in summary_rows]
    plt.barh(labels, stale_values)
    plt.xlabel("Stale fraction")
    plt.title("Stale fraction by run")
    plt.tight_layout()
    plt.savefig(output_dir / "stale_fraction.png", dpi=150)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate M4 plots from a sweep directory.")
    parser.add_argument("sweep_dir", type=Path)
    args = parser.parse_args()
    plot_sweep(args.sweep_dir)


if __name__ == "__main__":
    main()
