#!/usr/bin/env python3
"""
Turn your REAL measurements into statistics and graphs.

Reads:
  experiments/results.csv        (written by latency_test.py)
  experiments/cost_results.csv   (written by cost_calculator.py; optional)
Writes (to experiments/graphs/):
  1_request_vs_latency.png
  2_first_vs_last_request.png
  3_memory_vs_latency.png        (only if rows have a memory_mb value)
  4_memory_vs_cost.png           (only if cost_results.csv exists)
  summary.csv                    (spreadsheet-ready statistics per run)

This script NEVER invents data. If a CSV is empty it tells you what to do first.

Usage (from the project root):
  python experiments/analysis.py
"""

import csv
import math
import os
import statistics
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_CSV = os.path.join(HERE, "results.csv")
COST_CSV = os.path.join(HERE, "cost_results.csv")
GRAPH_DIR = os.path.join(HERE, "graphs")


def percentile(sorted_values, p):
    if not sorted_values:
        return float("nan")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * p / 100
    lower, upper = math.floor(position), math.ceil(position)
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (position - lower)


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_results():
    rows = []
    for raw in read_csv(RESULTS_CSV):
        try:
            rows.append(
                {
                    "run_id": raw["run_id"],
                    "request_number": int(raw["request_number"]),
                    "latency_ms": float(raw["latency_ms"]),
                    "success": raw["success"].strip().lower() == "true",
                    "memory_mb": raw.get("memory_mb", "").strip(),
                    "method": raw.get("method", ""),
                    "path": raw.get("path", ""),
                }
            )
        except (KeyError, ValueError):
            print(f"Skipping a malformed row: {raw}")
    return rows


def stats(latencies):
    ordered = sorted(latencies)
    return {
        "count": len(ordered),
        "average_ms": statistics.fmean(ordered),
        "median_ms": percentile(ordered, 50),
        "p95_ms": percentile(ordered, 95),
        "p99_ms": percentile(ordered, 99),
        "min_ms": ordered[0],
        "max_ms": ordered[-1],
    }


def group_by_run(rows):
    runs = defaultdict(list)
    for row in rows:
        runs[row["run_id"]].append(row)
    for run_rows in runs.values():
        run_rows.sort(key=lambda r: r["request_number"])
    return dict(sorted(runs.items()))


def main():
    rows = load_results()
    if not rows:
        print("No measurements found in experiments/results.csv.")
        print("Collect real data first, after deploying and checking billing:")
        print("  python experiments/latency_test.py --url <API_URL>")
        print("Then run this script again. No graphs were created, and nothing was made up.")
        return 0

    try:
        import matplotlib

        matplotlib.use("Agg")  # draw to files, no window needed
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib is not installed. Run:  pip install -r requirements-dev.txt")
        return 1

    os.makedirs(GRAPH_DIR, exist_ok=True)
    runs = group_by_run(rows)

    # ---- Statistics per run (printed + saved) --------------------------------
    summary_rows = []
    print("Statistics per run (client-observed latency, successful and failed requests included):")
    for run_id, run_rows in runs.items():
        s = stats([r["latency_ms"] for r in run_rows])
        first, last = run_rows[0], run_rows[-1]
        failures = sum(1 for r in run_rows if not r["success"])
        memory = run_rows[0]["memory_mb"]
        summary_rows.append(
            {
                "run_id": run_id,
                "memory_mb": memory,
                "requests": s["count"],
                "failures": failures,
                "first_request_ms": round(first["latency_ms"], 3),
                "last_request_ms": round(last["latency_ms"], 3),
                "average_ms": round(s["average_ms"], 3),
                "median_ms": round(s["median_ms"], 3),
                "p95_ms": round(s["p95_ms"], 3),
                "p99_ms": round(s["p99_ms"], 3),
            }
        )
        print(
            f"  {run_id}: n={s['count']} failures={failures} first={first['latency_ms']:.1f} "
            f"last={last['latency_ms']:.1f} avg={s['average_ms']:.1f} median={s['median_ms']:.1f} "
            f"p95={s['p95_ms']:.1f} p99={s['p99_ms']:.1f} (ms)"
        )
    with open(os.path.join(GRAPH_DIR, "summary.csv"), "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)

    # ---- Graph 1: request number vs latency -----------------------------------
    fig, ax = plt.subplots(figsize=(9, 5))
    for run_id, run_rows in runs.items():
        ax.plot(
            [r["request_number"] for r in run_rows],
            [r["latency_ms"] for r in run_rows],
            marker="o",
            markersize=3,
            linewidth=1,
            label=run_id,
        )
    ax.set_xlabel("Request number (consecutive)")
    ax.set_ylabel("Client-observed latency (ms)")
    ax.set_title("Request number vs latency")
    ax.grid(alpha=0.3)
    if len(runs) <= 8:
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(GRAPH_DIR, "1_request_vs_latency.png"), dpi=150)
    plt.close(fig)

    # ---- Graph 2: first vs last (100th) request --------------------------------
    labels = list(runs.keys())
    firsts = [runs[r][0]["latency_ms"] for r in labels]
    lasts = [runs[r][-1]["latency_ms"] for r in labels]
    last_label = "Request 100" if all(len(runs[r]) == 100 for r in labels) else "Last request"
    positions = range(len(labels))
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar([p - 0.2 for p in positions], firsts, width=0.4, label="Request 1")
    ax.bar([p + 0.2 for p in positions], lasts, width=0.4, label=last_label)
    ax.set_xticks(list(positions))
    ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("Client-observed latency (ms)")
    ax.set_title(f"Request 1 vs {last_label.lower()} (request 1 is not necessarily a cold start)")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(GRAPH_DIR, "2_first_vs_last_request.png"), dpi=150)
    plt.close(fig)
    print("Saved graphs 1 and 2.")

    # ---- Graph 3: memory vs latency (only if memory values were recorded) -------
    by_memory = defaultdict(list)
    for row in rows:
        if row["memory_mb"]:
            by_memory[int(float(row["memory_mb"]))].append(row["latency_ms"])
    if by_memory:
        memories = sorted(by_memory)
        medians = [percentile(sorted(by_memory[m]), 50) for m in memories]
        p95s = [percentile(sorted(by_memory[m]), 95) for m in memories]
        fig, ax = plt.subplots(figsize=(7, 5))
        ax.plot(memories, medians, marker="o", label="Median")
        ax.plot(memories, p95s, marker="s", label="p95")
        ax.set_xticks(memories)
        ax.set_xlabel("Lambda memory (MB)")
        ax.set_ylabel("Client-observed latency (ms)")
        ax.set_title("Lambda memory vs latency")
        ax.legend()
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(os.path.join(GRAPH_DIR, "3_memory_vs_latency.png"), dpi=150)
        plt.close(fig)
        print("Saved graph 3 (memory vs latency).")
    else:
        print("Graph 3 skipped: no memory_mb values yet. Use --memory-mb when running latency_test.py.")

    # ---- Graph 4: memory vs estimated cost ---------------------------------------
    cost_rows = read_csv(COST_CSV)
    if cost_rows:
        points = sorted(
            (int(float(r["memory_mb"])), float(r["cost_per_1000_requests_usd"])) for r in cost_rows
        )
        fig, ax = plt.subplots(figsize=(7, 5))
        ax.plot([p[0] for p in points], [p[1] for p in points], marker="o")
        ax.set_xticks([p[0] for p in points])
        ax.set_xlabel("Lambda memory (MB)")
        ax.set_ylabel("Estimated cost per 1,000 requests (USD)")
        ax.set_title("Lambda memory vs estimated cost")
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(os.path.join(GRAPH_DIR, "4_memory_vs_cost.png"), dpi=150)
        plt.close(fig)
        print("Saved graph 4 (memory vs cost).")
    else:
        print("Graph 4 skipped: experiments/cost_results.csv not found. Run cost_calculator.py first.")

    print(f"Output folder: {GRAPH_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
