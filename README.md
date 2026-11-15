# Freshworks-inspired Serverless Support-Ticket API

IT457 Cloud Computing group project. Company case study: **Freshworks** (a SaaS company built and scaled on the cloud from India for global markets).

> **Cost warning.** Deploying this project creates real AWS resources that can cost real money. Nothing here deploys automatically. AWS Budgets are alerts, **not** spending caps. Read `docs/cost-and-safety.md` before running `scripts/deploy.sh`, and delete the stack when you finish.

## 1. What this project is

A very small support-ticket API in the spirit of Freshdesk. It is **not** the Freshworks platform. Freshworks runs its Marketplace apps as AWS Lambda functions (reported by AWS and Sedai), so we rebuild that serverless pattern at tiny scale and measure it.

It demonstrates serverless computing with API Gateway, Lambda and DynamoDB, a live API URL, first-versus-100th-request latency, and cost per 1,000 requests.

| Endpoint | What it does |
|---|---|
| `GET /health` | Returns `{"status": "ok"}`. Never touches DynamoDB |
| `POST /tickets` | Validates JSON (`subject` and `description` required, `customerEmail` optional), stores a ticket, returns `201` with `ticketId` and `status` |
| `GET /tickets/{ticketId}` | Optional: reads one ticket back |

## 2. Architecture

```
Client (browser / curl / Python script)
        |
        v
Amazon API Gateway (HTTP API)
        |
        v
AWS Lambda (Python 3.12)  ---->  Amazon CloudWatch (logs, metrics)
        |
        v
Amazon DynamoDB (SupportTickets, on-demand)
```

Details and a Mermaid diagram are in `docs/architecture.md`.

## 3. Technologies

Python 3.12 and boto3 (Lambda), AWS SAM / CloudFormation (infrastructure as code), API Gateway HTTP API, DynamoDB on-demand with TTL, CloudWatch, `unittest` with mocks (tests), k6 (optional load test), matplotlib (graphs).

## 4. Project directory

```
freshworks-serverless-poc/
├── README.md                 <- this file
├── template.yaml             <- describes ALL AWS resources (SAM / CloudFormation)
├── requirements-dev.txt      <- Python packages for your own computer
├── src/
│   ├── app.py                <- the Lambda function (the whole application)
│   └── requirements.txt      <- intentionally empty (boto3 is built into Lambda)
├── tests/
│   └── test_app.py           <- unit tests, DynamoDB mocked, no AWS needed
├── events/
│   ├── create_ticket.json    <- sample POST event for `sam local invoke`
│   ├── health.json           <- sample GET /health event (small extra)
│   └── local-env.json        <- settings for local testing against DynamoDB Local (small extra)
├── scripts/
│   ├── deploy.sh             <- MANUAL deployment with confirmations
│   ├── delete_stack.sh       <- MANUAL cleanup
│   └── invoke_api.sh         <- sends 2 requests to the live API
├── experiments/
│   ├── latency_test.py       <- 100 consecutive requests, saves results.csv
│   ├── load_test.js          <- optional low-volume k6 test
│   ├── results.csv           <- starts empty; filled by YOUR real measurements
│   ├── analysis.py           <- statistics and graphs from the CSV
│   ├── cost_calculator.py    <- cost per 1,000 requests (small extra)
│   └── cost_input.csv        <- starts empty; you fill it from CloudWatch (small extra)
└── docs/
    ├── architecture.md
    └── cost-and-safety.md
```

The structure follows the requested layout. The only additions are `events/health.json`, `events/local-env.json`, `experiments/cost_calculator.py`, `experiments/cost_input.csv`, `requirements-dev.txt` and `src/requirements.txt`, which make local testing and the cost step easier.

## 5. Local setup

Everything in this section is free and does not touch AWS.

1. **Install Python 3.12 or newer** from python.org. Check with `python3 --version`.
2. **Create a virtual environment** (an isolated space for packages):
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   ```
3. **Install the packages:**
   ```bash
   pip install -r requirements-dev.txt
   ```
4. **Install the AWS SAM CLI** (needed for `sam build` and `sam local`). Follow the official guide: https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html . Check with `sam --version`.
5. **Install the AWS CLI** (used by the deploy and cleanup scripts): https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html
6. **Install Docker Desktop** only if you want to use `sam local` (it runs your function in a container that mimics Lambda).
7. **Optional:** install k6 (https://grafana.com/docs/k6/latest/set-up/install-k6/) for the load test.

## 6. Unit testing

```bash
python -m unittest discover -s tests -v
```

- `unittest` is Python's built-in test runner. `discover -s tests` finds test files in the `tests` folder. `-v` prints each test name.
- The tests replace DynamoDB with a fake, so no AWS account or credentials are needed.
- They cover: successful creation, missing subject, missing description, malformed JSON, the health endpoint and a DynamoDB failure, plus extra checks (invalid email, base64 bodies, 404s, no ticket text in logs).

All tests should print `OK`.

## 7. Local API testing

### 7a. Run the function once with a sample event (no database needed for `/health`)

```bash
sam build
sam local invoke TicketFunction -e events/health.json
```

- `sam build` packages `src/` into a `.aws-sam/` folder.
- `sam local invoke` runs the function once in a Docker container with the event from the JSON file.
- You should see a response with `"statusCode": 200`.

### 7b. Local API on your computer

```bash
sam local start-api
```

In another terminal:
```bash
curl http://127.0.0.1:3000/health
```
Stop it with Ctrl+C. `POST /tickets` needs a database, so use 7c for that.

### 7c. Test `POST /tickets` safely with a local DynamoDB (optional)

This uses a database running in Docker on your computer, so it **cannot** touch your AWS account or bill you.

```bash
# 1. Start a local DynamoDB (leave this terminal running)
docker run --rm -p 8000:8000 amazon/dynamodb-local

# 2. In a new terminal, set DUMMY credentials so nothing can reach real AWS
export AWS_ACCESS_KEY_ID=local AWS_SECRET_ACCESS_KEY=local AWS_DEFAULT_REGION=ap-south-1

# 3. Create the local table
aws dynamodb create-table --table-name local-SupportTickets \
  --attribute-definitions AttributeName=ticketId,AttributeType=S \
  --key-schema AttributeName=ticketId,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST --endpoint-url http://localhost:8000

# 4. Start the local API pointing at it
sam local start-api --env-vars events/local-env.json

# 5. Send a ticket
curl -X POST http://127.0.0.1:3000/tickets -H "Content-Type: application/json" \
  -d '{"subject":"Order delayed","description":"My order has not arrived yet."}'
```

The `--endpoint-url http://localhost:8000` in step 3 sends the command to the local container instead of AWS. If `host.docker.internal` does not work on your Linux machine, change the address in `events/local-env.json` to your computer's IP address.

## 8. AWS billing safety checklist

Complete this **before** deploying. Details are in `docs/cost-and-safety.md`.

- [ ] I opened Billing -> **Bills** and saw no unexpected charges.
- [ ] I opened Billing -> **Credits** and know whether credits exist and when they expire.
- [ ] I opened Billing -> **Free Tier** and know what my account is eligible for. I am **not** assuming anything is free.
- [ ] I created a **Budget** alert and understand it is only a warning, not a cap.
- [ ] I chose one region (preferred: `ap-south-1`, Mumbai) and will confirm it in the script.
- [ ] I know how to delete everything (`scripts/delete_stack.sh`) and will do it when finished.
- [ ] I am using only synthetic data and no real AWS keys are in this folder.

## 9. Deployment instructions

Configure your AWS CLI first (`aws configure`, using an IAM user or role, not the root account). Then:

```bash
chmod +x scripts/*.sh
AWS_REGION=ap-south-1 ./scripts/deploy.sh
```

What the script does, in order: refuses to run without `AWS_REGION`, shows which AWS account you are logged in to, prints the checklist, asks you to type the region and then `I HAVE CHECKED BILLING`, runs `sam build`, then `sam deploy` (which shows a change set and asks for your approval before creating anything), and finally prints your **API URL**.

Optional memory setting for the memory experiment (allowed: 128, 256, 512):
```bash
AWS_REGION=ap-south-1 MEMORY_MB=256 ./scripts/deploy.sh
```

## 10. Live API testing

```bash
./scripts/invoke_api.sh https://<api-id>.execute-api.ap-south-1.amazonaws.com
```

This sends exactly two requests (`GET /health` and one `POST /tickets` with synthetic data). Take **screenshots** for the TA: the API URL working in the browser or terminal, the CloudFormation stack resources, the Lambda function with its API Gateway trigger, and the DynamoDB table with an item.

## 11. Latency experiment (first request vs 100th request)

```bash
python experiments/latency_test.py --url https://<api-id>.execute-api.ap-south-1.amazonaws.com --memory-mb 128
```

- Sends 100 consecutive requests to `GET /health`, records request number, timestamp, status code, client-observed latency in ms and success, and appends them to `experiments/results.csv`.
- Prints request 1, request 100, average, median, p95 and p99.
- Useful options: `--method POST --path /tickets` (writes synthetic items), `--runs 3 --pause-between-runs 600` (repeat after idle gaps), `--delay-ms`, `--note "after 10 min idle"`.
- Safety limits: at most 200 requests per run and 5 runs, with a confirmation question unless you pass `--yes`.

**Client-observed latency is not Lambda duration.** It includes your network, DNS and TLS, API Gateway, Lambda and DynamoDB. Lambda's own `Duration` in CloudWatch is smaller.

### Cold start vs warm

Three different things, which must not be confused:

| Term | Meaning | How you know |
|---|---|---|
| **Initial request** | The first request of one experiment run | You know because you sent it first. It is **not** guaranteed to be a cold start, because a warm environment may already exist |
| **Confirmed cold start** | A request where Lambda created a new execution environment | Its CloudWatch `REPORT` line contains **Init Duration** |
| **Warm invocation** | A request served by a reused environment | Its `REPORT` line has **no** Init Duration |

A request after an idle period is also not guaranteed to be a cold start. Only label a request a cold start if its `REPORT` line shows Init Duration.

**Find Init Duration in CloudWatch:**

1. AWS Console -> CloudWatch -> Logs -> Log groups -> `/aws/lambda/freshworks-serverless-poc-api` -> open the newest log stream. Each request ends with a `REPORT` line showing Duration, Billed Duration, Memory Size, Max Memory Used and, on cold starts only, Init Duration.
2. Or run this in **Logs Insights** (select the log group and a time range):
   ```
   filter @type = "REPORT"
   | fields @timestamp, @requestId, @memorySize / 1000000 as memoryMB, @duration, @billedDuration, @initDuration
   | sort @timestamp asc
   ```
   Rows where `@initDuration` has a value are confirmed cold starts.
3. Match log timestamps to the timestamps in `results.csv` to see which of your requests were cold. Since 1 August 2025 AWS includes INIT time in Billed Duration for on-demand ZIP functions on managed runtimes (such as this one), so a cold start's Billed Duration can be larger than its Duration. Check this on your own `REPORT` lines.

### Memory experiment (optional, do it only after the basic test works)

1. Deploy with `MEMORY_MB=128`, run `latency_test.py ... --memory-mb 128`, and record from CloudWatch the **Duration**, **Billed Duration**, and any **Init Duration**.
2. Redeploy with `MEMORY_MB=256`, repeat, then do the same for `512`. Changing memory creates a new function configuration, so the first request after a redeploy may start a new environment (confirm using Init Duration).
3. For each setting, note: memory, execution duration, billed duration, cold-start information if present, client latency and estimated cost (next section).
4. Do not assume more memory is cheaper or faster. Compare your numbers.

### Optional k6 load test

Only after billing is checked and the API works:
```bash
k6 run -e BASE_URL=https://<api-id>.execute-api.ap-south-1.amazonaws.com experiments/load_test.js
```
Default: 1 user, 20 requests to `/health`, about 1 per second. The script caps itself at 3 users and 200 requests. **Stop at any time with Ctrl+C.** Each request can cost money.

### Graphs and statistics

```bash
python experiments/analysis.py
```

Reads `experiments/results.csv` and writes graphs to `experiments/graphs/`: request number vs latency, first vs 100th request, memory vs latency (if you used `--memory-mb`) and memory vs estimated cost (if `cost_results.csv` exists). If there is no data, it says so and creates nothing. It never invents results.

## 12. Cost calculation

The full method with formulas is in `docs/cost-and-safety.md`. In short:

1. Look up prices for **your region** (Lambda per request and per GB-second, HTTP API per request, DynamoDB write units, CloudWatch Logs per GB) on the AWS pricing pages or the AWS Pricing Calculator.
2. Put the measured average **Billed Duration** for each memory setting into `experiments/cost_input.csv` (columns `memory_mb,billed_duration_ms`).
3. Run, replacing the `<...>` placeholders with the prices you looked up:
   ```bash
   python experiments/cost_calculator.py \
     --lambda-request-price-per-million <USD> --lambda-gb-second-price <USD> \
     --apigw-price-per-million <USD> --ddb-write-price-per-million <USD> \
     --writes-per-request 1
   ```
   (For `GET /health` use `--writes-per-request 0`. For `GET /tickets/{id}` add `--reads-per-request 0.5 --ddb-read-price-per-million <USD>`.)
4. Open `experiments/cost_results.csv` in Excel or Google Sheets. It contains cost per 1,000 requests per memory setting, with no Free Tier applied.
5. Compare with **Billing -> Bills** after a day.

## 13. Cleanup

```bash
AWS_REGION=ap-south-1 ./scripts/delete_stack.sh
```

Type `DELETE` to confirm. The script deletes the CloudFormation stack, waits for completion, then prints commands to verify that the stack, Lambda function, DynamoDB table, log group and API are gone. **SAM's S3 bucket for code packages stays behind**: follow the instructions printed by the script and in `docs/cost-and-safety.md` to remove it. Check the Billing console the next day.

## Limitations

- No authentication, by design. Anyone with the URL can call the API, so delete the stack when finished.
- Client latency depends on your location and network. State where you ran the tests.
- Results from one machine at one time are a small sample. Repeat runs and report medians and percentiles.
- The unit tests mock DynamoDB, so they do not check real IAM permissions or table settings. Only the live deployment does.
