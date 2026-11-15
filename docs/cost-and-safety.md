# Cost and safety guide

Read this whole page before you run `scripts/deploy.sh`.

## The most important facts

1. **Deploying creates real resources in a real AWS account.** Nothing in this project deploys anything automatically. You must run `scripts/deploy.sh` yourself and type two confirmations.
2. **AWS Budgets are alerts, not hard spending caps.** A budget sends you an email or notification when spending (or forecast spending) passes a threshold. It does **not** stop services, and charges keep accruing after the alert. Billing data can also lag by hours. Delete the stack when you finish testing.
3. **Do not assume this project is free.** Eligibility for the Free Tier or credits depends on your account's age, type and status. Check your own account (below) and treat any estimate as a worst case with no free allowance.
4. **No guarantee of zero cost.** The tiny volumes here usually cost very little, but this guide does not promise any amount.

## Step 1: check your account before deploying

| What to check | Where |
|---|---|
| Current charges | AWS Console -> Billing and Cost Management -> **Bills** |
| Credits and their expiry dates | Billing and Cost Management -> **Credits** |
| Free Tier usage and what applies to *your* account | Billing and Cost Management -> **Free Tier** |
| Account plan | AWS announced a new Free Tier in July 2025 for accounts created after 15 July 2025: up to $200 in credits and a plan that lasts up to 6 months or until credits run out. Older accounts follow the previous Free Tier rules. Confirm which applies to you in the console, not from this document |
| Which region you are in | Top-right region selector. Resources are created only in the region you choose in `deploy.sh` |

If credits do not exist or have expired, charges go to the card on the account.

## Step 2: create a budget alert

1. Billing and Cost Management -> **Budgets** -> **Create budget**.
2. Choose **Zero spend budget** (alerts as soon as spending above the free allowance begins) or a **Monthly cost budget** with a very low amount you can afford.
3. Add your email address for alerts, at both actual and forecasted thresholds.
4. Remember: this only warns you.

## Which resources can cost money

| Resource | When it charges | How this project limits it |
|---|---|---|
| **API Gateway HTTP API** | Per request received | Throttling (rate 5 and burst 10) in `template.yaml` rejects bursts. `latency_test.py` allows at most 200 requests per run and 5 runs |
| **Lambda** | Per request plus memory (GB) x billed duration (seconds). Cold-start INIT time is billed for on-demand ZIP functions on managed runtimes since 1 August 2025 | Memory limited to 128, 256 or 512 MB. Timeout 10 seconds. No provisioned concurrency |
| **DynamoDB (on-demand)** | Per write and read request unit, plus stored data | On-demand mode has no idle capacity charge. Items are small and auto-deleted by TTL after 7 days (TTL deletions are not charged as writes) |
| **CloudWatch Logs** | Per GB ingested and per GB-month stored | Retention is 7 days. The code logs only IDs and status codes |
| **S3 bucket created by SAM** | Per GB stored, plus requests | Holds the zipped code (a few KB). It is **not** deleted with the stack. See cleanup below |
| **Data transfer out** | Per GB leaving AWS to the internet | Responses are a few hundred bytes |
| **IAM role** | No charge | Least privilege: only `PutItem` and `GetItem` on this one table |

**Not used on purpose:** EC2, NAT Gateway, RDS, EKS, load balancers, provisioned concurrency, multi-region setups. NAT Gateways and load balancers in particular charge by the hour even when idle.

## Step 3: avoid unnecessary spending

- Deploy to **one region only**.
- Run `invoke_api.sh` first (2 requests). Run the 100-request latency test only after that works.
- Use `GET /health` for the latency test unless you specifically need to test writes.
- Run the memory experiment (3 deployments) only after the basic experiment works.
- Do not leave load tests running. Press Ctrl+C to stop `latency_test.py` or `k6`.
- Do not paste real customer data anywhere. Use only synthetic data.
- Delete the stack as soon as you have your screenshots and CSV files.

## How to calculate cost per 1,000 requests

Use measured numbers, not guesses.

**Step A: get prices for your region.** Open the AWS pricing pages for Lambda, API Gateway (HTTP APIs), DynamoDB on-demand and CloudWatch Logs, or use the [AWS Pricing Calculator](https://calculator.aws/). Select your region, because prices differ by region. Write down: Lambda price per 1M requests, Lambda price per GB-second (x86 or Arm, whichever you deployed), API Gateway HTTP API price per 1M requests, DynamoDB price per 1M write request units (and read units if you use `GET /tickets/{id}`), and CloudWatch Logs price per GB ingested.

**Step B: get Billed Duration from CloudWatch.** Open the log group, find `REPORT` lines and read **Billed Duration** (not Duration). See the README section "Cold start vs warm". Average it over warm invocations for each memory setting. Billed Duration is rounded up to the next millisecond, so it can be larger than Duration.

**Step C: apply the formulas** (`experiments/cost_calculator.py` does this for you):

```
Lambda requests = 1000 / 1,000,000 x (price per 1M requests)
Lambda compute  = (memory_MB / 1024) x (billed_duration_ms / 1000) x 1000 requests x (price per GB-second)
API Gateway     = 1000 / 1,000,000 x (HTTP API price per 1M requests)
DynamoDB writes = 1000 x (write request units per request) / 1,000,000 x (price per 1M write units)
DynamoDB reads  = 1000 x (read request units per request) / 1,000,000 x (price per 1M read units)
CloudWatch logs = 1000 x (log bytes per request) / 1,000,000,000 x (price per GB ingested)
Total           = sum of the above
```

A `POST /tickets` with a small item (under 1 KB) uses 1 write request unit. An eventually consistent read of an item up to 4 KB uses 0.5 read request units. `GET /health` uses none.

**Step D: be honest about what is included.** The estimate applies no Free Tier. Storage and data transfer are tiny and listed separately. Cold starts are rare, so report both the warm-only cost and the cost including cold starts (from their larger Billed Duration).

**Step E: compare with reality.** After a day, open **Billing -> Bills** and **Cost Explorer**, filter by service, and compare actual spending with your estimate. Cost data can take up to about a day to appear.

### Spreadsheet-ready format

`experiments/cost_input.csv` (you fill with real values):

```csv
memory_mb,billed_duration_ms
128,<measured average>
256,<measured average>
512,<measured average>
```

`experiments/cost_calculator.py` writes `experiments/cost_results.csv` with these columns, ready for Excel or Google Sheets:

```csv
memory_mb,billed_duration_ms,lambda_requests_usd,lambda_compute_usd,api_gateway_usd,dynamodb_write_usd,dynamodb_read_usd,cloudwatch_logs_usd,cost_per_1000_requests_usd
```

Higher memory does **not** always mean lower cost. More memory gives more CPU and may shorten the duration, but the price per millisecond rises with memory, so the result depends on your measurements.

## Step 4: cleanup and verification

1. Run: `AWS_REGION=<region> ./scripts/delete_stack.sh` and type `DELETE`.
2. Verify in the console, in the same region:
   - **CloudFormation**: your stack no longer exists.
   - **Lambda -> Functions**: no function named `freshworks-serverless-poc-api`.
   - **DynamoDB -> Tables**: no `freshworks-serverless-poc-SupportTickets`.
   - **API Gateway**: no HTTP API from this project.
   - **CloudWatch -> Log groups**: no `/aws/lambda/freshworks-serverless-poc-api`.
3. **SAM's S3 bucket stays behind.** In the same region, open CloudFormation, find the stack `aws-sam-cli-managed-default`, empty its S3 bucket (S3 console -> the bucket starting `aws-sam-cli-managed-default-samclisourcebucket` -> **Empty**), then delete that stack. It is shared by any other SAM project in that region, so delete it only if you have no other SAM projects there.
4. Use the **Resource Explorer** or **Tag Editor** if you want a second check, and look at **Billing -> Bills** the next day to confirm charges have stopped.

The CLI commands for the verification checks are printed at the end of `scripts/delete_stack.sh`.

## Security basics

- Never commit AWS keys. `.gitignore` excludes common credential files.
- Use an IAM user or role with MFA instead of the root account for daily work.
- The API has **no authentication** (not required for the course demo), so anyone who finds the URL can call it. Throttling limits damage, but delete the stack when you are done and do not share the URL publicly.
- The code logs no ticket text. Keep it that way.
