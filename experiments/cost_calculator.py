#!/usr/bin/env python3
"""
Estimate cost per 1,000 requests from YOUR measurements and YOUR price inputs.

No prices are built in on purpose: AWS prices differ by region and change over time.
Look the numbers up for your region on the AWS pricing pages or the AWS Pricing
Calculator, then pass them in. The Free Tier is NOT applied (worst-case estimate).

Input file (CSV, one row per Lambda memory setting you tested):
  memory_mb,billed_duration_ms
  128,<average Billed Duration from your CloudWatch REPORT lines>
  256,<...>
Use the Billed Duration (not Duration) because that is what AWS charges for.
Use the average over warm invocations, and mention cold-start billing separately.

Example:
  python experiments/cost_calculator.py \
      --input experiments/cost_input.csv \
      --lambda-request-price-per-million <USD> \
      --lambda-gb-second-price <USD> \
      --apigw-price-per-million <USD> \
      --ddb-write-price-per-million <USD> \
      --writes-per-request 1 --reads-per-request 0

Output: experiments/cost_results.csv  (open it in Excel / Google Sheets)

Formula for 1,000 requests
--------------------------
  lambda_requests = 1000 / 1e6 * lambda_request_price_per_million
  lambda_compute  = (memory_mb / 1024) * (billed_duration_ms / 1000) * 1000 * gb_second_price
  api_gateway     = 1000 / 1e6 * apigw_price_per_million
  dynamodb_write  = 1000 * writes_per_request / 1e6 * ddb_write_price_per_million
  dynamodb_read   = 1000 * reads_per_request  / 1e6 * ddb_read_price_per_million
  cloudwatch_logs = 1000 * log_bytes_per_request / 1e9 * logs_price_per_gb
"""

import argparse
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_COLUMNS = [
    "memory_mb",
    "billed_duration_ms",
    "lambda_requests_usd",
    "lambda_compute_usd",
    "api_gateway_usd",
    "dynamodb_write_usd",
    "dynamodb_read_usd",
    "cloudwatch_logs_usd",
    "cost_per_1000_requests_usd",
]


def parse_args():
    p = argparse.ArgumentParser(description="Estimate cost per 1,000 requests from measured billed duration.")
    p.add_argument("--input", default=os.path.join(HERE, "cost_input.csv"))
    p.add_argument("--output", default=os.path.join(HERE, "cost_results.csv"))
    p.add_argument("--lambda-request-price-per-million", type=float, required=True, help="USD per 1M Lambda requests")
    p.add_argument("--lambda-gb-second-price", type=float, required=True, help="USD per GB-second (x86 or Arm, whichever you deployed)")
    p.add_argument("--apigw-price-per-million", type=float, required=True, help="USD per 1M HTTP API requests")
    p.add_argument("--ddb-write-price-per-million", type=float, default=0.0, help="USD per 1M DynamoDB on-demand write request units")
    p.add_argument("--ddb-read-price-per-million", type=float, default=0.0, help="USD per 1M DynamoDB on-demand read request units")
    p.add_argument("--writes-per-request", type=float, default=0.0, help="Write request units per API request (POST /tickets with a small item = 1)")
    p.add_argument("--reads-per-request", type=float, default=0.0, help="Read request units per API request (GET /tickets/{id}: 0.5 for an eventually consistent read of up to 4 KB)")
    p.add_argument("--logs-price-per-gb", type=float, default=0.0, help="USD per GB of CloudWatch Logs ingested")
    p.add_argument("--log-bytes-per-request", type=float, default=0.0, help="Approximate bytes logged per request (see your log group's 'Stored bytes' / requests)")
    return p.parse_args()


def main():
    a = parse_args()
    if not os.path.exists(a.input):
        sys.exit(f"{a.input} not found. Create it with columns: memory_mb,billed_duration_ms (real values from CloudWatch REPORT lines).")

    with open(a.input, newline="", encoding="utf-8") as handle:
        inputs = list(csv.DictReader(handle))
    if not inputs:
        sys.exit("The input file has no data rows. Fill it with real measurements first; nothing was estimated.")

    results = []
    for row in inputs:
        memory_mb = float(row["memory_mb"])
        billed_ms = float(row["billed_duration_ms"])
        lambda_requests = 1000 / 1e6 * a.lambda_request_price_per_million
        lambda_compute = (memory_mb / 1024) * (billed_ms / 1000) * 1000 * a.lambda_gb_second_price
        api_gateway = 1000 / 1e6 * a.apigw_price_per_million
        ddb_write = 1000 * a.writes_per_request / 1e6 * a.ddb_write_price_per_million
        ddb_read = 1000 * a.reads_per_request / 1e6 * a.ddb_read_price_per_million
        logs = 1000 * a.log_bytes_per_request / 1e9 * a.logs_price_per_gb
        total = lambda_requests + lambda_compute + api_gateway + ddb_write + ddb_read + logs
        results.append(
            {
                "memory_mb": int(memory_mb),
                "billed_duration_ms": billed_ms,
                "lambda_requests_usd": f"{lambda_requests:.8f}",
                "lambda_compute_usd": f"{lambda_compute:.8f}",
                "api_gateway_usd": f"{api_gateway:.8f}",
                "dynamodb_write_usd": f"{ddb_write:.8f}",
                "dynamodb_read_usd": f"{ddb_read:.8f}",
                "cloudwatch_logs_usd": f"{logs:.8f}",
                "cost_per_1000_requests_usd": f"{total:.8f}",
            }
        )

    with open(a.output, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(results)

    print(f"Wrote {a.output}")
    for r in results:
        print(f"  {r['memory_mb']} MB @ {r['billed_duration_ms']} ms billed -> {r['cost_per_1000_requests_usd']} USD per 1,000 requests (no Free Tier applied)")
    print("Storage and data transfer are not included; they are negligible for this demo but check your bill.")


if __name__ == "__main__":
    main()
