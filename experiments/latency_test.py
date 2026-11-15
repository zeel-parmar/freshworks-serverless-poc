#!/usr/bin/env python3
"""
Latency experiment: send N consecutive requests to your API and record each one.

This uses only the Python standard library (no pip install needed).

IMPORTANT - what the numbers mean
---------------------------------
The latency recorded here is CLIENT-OBSERVED. It includes your internet
connection, DNS and TLS setup, API Gateway overhead, Lambda and (for POST)
DynamoDB. It is NOT the same as the Lambda "Duration" in CloudWatch Logs.
To see Lambda's own numbers, read the REPORT lines in CloudWatch (README, section
"Cold start vs warm").

Request 1 is simply "the first request of this run". It is NOT guaranteed to be a
cold start (a warm environment may already exist), and it is not labelled as one.
Only a CloudWatch REPORT line that contains "Init Duration" confirms a cold start.

Examples
--------
  python experiments/latency_test.py --url https://abc123.execute-api.ap-south-1.amazonaws.com
  python experiments/latency_test.py --url https://... --method POST --path /tickets --memory-mb 256
  python experiments/latency_test.py --url https://... --runs 3 --pause-between-runs 600
"""

import argparse
import csv
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

HARD_LIMIT_REQUESTS_PER_RUN = 200
HARD_LIMIT_RUNS = 5
CSV_COLUMNS = [
    "run_id",
    "timestamp",
    "request_number",
    "method",
    "path",
    "status_code",
    "latency_ms",
    "success",
    "memory_mb",
    "note",
]
SYNTHETIC_TICKET = {
    "subject": "Synthetic latency test",
    "description": "Synthetic data created by experiments/latency_test.py",
    "customerEmail": "student@example.com",
}


def percentile(sorted_values, p):
    """Linear-interpolation percentile (same method as numpy's default)."""
    if not sorted_values:
        return float("nan")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * p / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    fraction = position - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction


def send_request(url, method, body, timeout):
    """Send one request. Returns (status_code, latency_ms, success)."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    request = urllib.request.Request(url, data=data, method=method, headers=headers)

    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
            status = response.status
    except urllib.error.HTTPError as error:
        error.read()
        status = error.code
    except (urllib.error.URLError, TimeoutError, OSError):
        status = 0  # 0 = no HTTP response (network error or timeout)
    latency_ms = (time.perf_counter() - start) * 1000
    return status, latency_ms, 200 <= status < 300


def append_rows(path, rows):
    new_file = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)


def summarise(rows, count):
    latencies = sorted(r["latency_ms"] for r in rows)
    successes = sum(1 for r in rows if r["success"])
    first = rows[0]
    last = rows[-1]
    print(f"  Requests sent         : {len(rows)}  (successful: {successes}, failed: {len(rows) - successes})")
    print(f"  Request 1             : {first['latency_ms']:.1f} ms  (status {first['status_code']})")
    label = "Request 100" if count == 100 else f"Request {count} (last)"
    print(f"  {label:<22}: {last['latency_ms']:.1f} ms  (status {last['status_code']})")
    print(f"  Average               : {statistics.fmean(latencies):.1f} ms")
    print(f"  Median                : {percentile(latencies, 50):.1f} ms")
    print(f"  p95                   : {percentile(latencies, 95):.1f} ms")
    print(f"  p99                   : {percentile(latencies, 99):.1f} ms")
    print(f"  Min / Max             : {latencies[0]:.1f} / {latencies[-1]:.1f} ms")


def parse_args():
    parser = argparse.ArgumentParser(description="Measure first vs 100th consecutive request latency.")
    parser.add_argument("--url", required=True, help="API base URL, e.g. https://abc123.execute-api.ap-south-1.amazonaws.com")
    parser.add_argument("--path", default="/health", help="Path to call (default /health, which never writes to DynamoDB)")
    parser.add_argument("--method", default="GET", choices=["GET", "POST"], help="HTTP method (use POST with --path /tickets)")
    parser.add_argument("--count", type=int, default=100, help=f"Requests per run (default 100, max {HARD_LIMIT_REQUESTS_PER_RUN})")
    parser.add_argument("--runs", type=int, default=1, help=f"Repeat the whole experiment (default 1, max {HARD_LIMIT_RUNS})")
    parser.add_argument("--pause-between-runs", type=int, default=0, help="Seconds to wait between runs (an idle gap; it does NOT guarantee a cold start)")
    parser.add_argument("--delay-ms", type=int, default=0, help="Optional pause between consecutive requests, in ms")
    parser.add_argument("--timeout", type=float, default=10.0, help="Seconds before a request is counted as failed")
    parser.add_argument("--memory-mb", default="", help="Lambda memory setting currently deployed (recorded for the memory experiment)")
    parser.add_argument("--note", default="", help="Free-text note saved with every row")
    parser.add_argument("--output", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.csv"), help="CSV file to append to")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation question")
    return parser.parse_args()


def main():
    args = parse_args()

    if not 1 <= args.count <= HARD_LIMIT_REQUESTS_PER_RUN:
        sys.exit(f"--count must be between 1 and {HARD_LIMIT_REQUESTS_PER_RUN}.")
    if not 1 <= args.runs <= HARD_LIMIT_RUNS:
        sys.exit(f"--runs must be between 1 and {HARD_LIMIT_RUNS}.")
    if args.method == "POST" and not args.path.rstrip("/").endswith("/tickets"):
        sys.exit("POST is only meant for --path /tickets.")
    if not args.url.startswith("https://"):
        sys.exit("--url must start with https://")

    url = args.url.rstrip("/") + "/" + args.path.lstrip("/")
    body = SYNTHETIC_TICKET if args.method == "POST" else None
    total = args.count * args.runs

    print(f"About to send {total} request(s) to {args.method} {url}")
    if args.method == "POST":
        print("Each POST writes one synthetic item to DynamoDB (auto-deleted by TTL after a few days).")
    print("These requests can create AWS charges depending on your account. Check Billing first.")
    if not args.yes and input("Continue? [y/N] ").strip().lower() != "y":
        sys.exit("Cancelled. Nothing was sent.")

    for run in range(1, args.runs + 1):
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-r{run}"
        print(f"\nRun {run}/{args.runs} (run_id {run_id})")
        rows = []
        for number in range(1, args.count + 1):
            stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            status, latency_ms, success = send_request(url, args.method, body, args.timeout)
            rows.append(
                {
                    "run_id": run_id,
                    "timestamp": stamp,
                    "request_number": number,
                    "method": args.method,
                    "path": args.path,
                    "status_code": status,
                    "latency_ms": round(latency_ms, 3),
                    "success": success,
                    "memory_mb": args.memory_mb,
                    "note": args.note,
                }
            )
            if args.delay_ms:
                time.sleep(args.delay_ms / 1000)

        append_rows(args.output, rows)
        summarise(rows, args.count)
        print(f"  Saved to {args.output}")

        if run < args.runs and args.pause_between_runs:
            print(f"  Waiting {args.pause_between_runs} s before the next run...")
            time.sleep(args.pause_between_runs)

    print("\nReminder: request 1 is the FIRST request of the run, not a confirmed cold start.")
    print("Check CloudWatch REPORT lines for 'Init Duration' to confirm cold starts.")


if __name__ == "__main__":
    main()
