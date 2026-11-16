# Freshworks-Inspired Serverless Support Ticket API

IT457 Cloud Computing group project. This project is a small Freshdesk-inspired support-ticket API built with AWS serverless services. It demonstrates how an API can receive requests, run Python code without managing a server, and store ticket data in a managed database.

This is a student project inspired by Freshworks; it is not the actual Freshworks product.

## Project overview

The API supports three endpoints:

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Checks that the API is running. Does not access DynamoDB. |
| `POST` | `/tickets` | Validates and creates a support ticket in DynamoDB. |
| `GET` | `/tickets/{ticketId}` | Retrieves a ticket using its ID. |

A ticket contains a generated ID, subject, description, optional customer email, status, creation time, and expiry time. Tickets are configured to expire after 7 days using DynamoDB TTL.

## Architecture

```text
Client
  |
  v
Amazon API Gateway (HTTP API)
  |
  v
AWS Lambda (Python 3.12) ------> Amazon CloudWatch Logs
  |
  v
Amazon DynamoDB (SupportTickets table)
```

- **API Gateway** provides the public HTTPS API endpoint.
- **AWS Lambda** runs the Python application in `src/app.py`.
- **DynamoDB** stores support tickets using on-demand capacity.
- **CloudWatch** stores Lambda execution logs and report lines used to inspect duration and cold starts.
- **AWS SAM / CloudFormation** defines and deploys the AWS resources in `template.yaml`.

The deployed API uses 128 MB Lambda memory, a 10-second timeout, a DynamoDB on-demand table, and 7-day CloudWatch log retention. API Gateway throttling is configured at 5 requests per second with a burst limit of 10.

## Live deployment

The project was deployed in AWS Region `ap-south-1` (Mumbai).

**Live API base URL:**

```text
https://cauva9p5ei.execute-api.ap-south-1.amazonaws.com
```

Example health check in PowerShell:

```powershell
Invoke-RestMethod -Method GET -Uri "https://cauva9p5ei.execute-api.ap-south-1.amazonaws.com/health"
```

Example: create a ticket:

```powershell
$body = @{
    subject = "Demo support ticket"
    description = "Testing the Freshworks serverless ticket API."
    customerEmail = "demo@example.com"
} | ConvertTo-Json

$response = Invoke-RestMethod `
    -Method POST `
    -Uri "https://cauva9p5ei.execute-api.ap-south-1.amazonaws.com/tickets" `
    -ContentType "application/json" `
    -Body $body

$response
```

Retrieve the created ticket (use the `ticketId` returned by the POST request):

```powershell
Invoke-RestMethod -Method GET -Uri "https://cauva9p5ei.execute-api.ap-south-1.amazonaws.com/tickets/YOUR_TICKET_ID"
```

The API currently has no authentication. Anyone with the URL can send requests, so it is intended only for this controlled student demonstration.

## Technologies used

- Python 3.12
- AWS Lambda
- Amazon API Gateway HTTP API
- Amazon DynamoDB
- Amazon CloudWatch
- AWS SAM and AWS CloudFormation
- Python `unittest` for application tests
- Matplotlib for latency graphs

## Repository structure

```text
freshworks-serverless-poc/
├── template.yaml
├── requirements-dev.txt
├── src/
│   ├── app.py
│   └── requirements.txt
├── events/
│   ├── create_ticket.json
│   ├── health.json
│   └── local-env.json
├── experiments/
│   ├── latency_test.py
│   ├── analysis.py
│   ├── cost_calculator.py
│   ├── aws_latency_100.csv
│   ├── results.csv
│   ├── cost_comparison.csv
│   ├── cost_input.csv
│   ├── post_cost_input.csv
│   ├── post_cost_results.csv
│   ├── get_cost_input.csv
│   ├── get_cost_results.csv
│   └── health_cost_results.csv
├── docs/
│   ├── architecture.md
│   └── cost-and-safety.md
├── scripts/
│   ├── deploy.sh
│   ├── delete_stack.sh
│   └── invoke_api.sh
└── tests/
    └── test_app.py
```

## Run the unit tests

From the project root, create and activate a virtual environment, then install the development dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

Run the tests:

```powershell
python -m unittest discover -s tests -v
```

The project test suite was run successfully: **20 tests passed**. The tests use a mocked DynamoDB resource and do not require a live AWS database.

## Latency experiment

The benchmark sent **100 consecutive `GET /health` requests** to the deployed API in `ap-south-1`, with a 250 ms delay between requests. All 100 requests succeeded.

| Metric | Measured result |
|---|---:|
| Requests sent | 100 |
| Successful requests | 100 |
| Failed requests | 0 |
| Average client-observed latency | 265.7 ms |
| Median latency | 249.6 ms |
| 95th percentile (p95) | 319.3 ms |
| 99th percentile (p99) | 403.8 ms |
| Minimum latency | 202.1 ms |
| Maximum latency | 1385.5 ms |
| First request latency | 1385.5 ms |
| 100th request latency | 246.6 ms |

The benchmark CSV is saved at `experiments/aws_latency_100.csv`. The graphs are generated in `experiments/graphs/` from the benchmark results.

**Latency note:** These are client-observed times. They include the client's network, DNS/TLS, API Gateway, and Lambda overhead. They are not the same as Lambda execution duration. The first request in the benchmark is not automatically a confirmed cold start.

### Confirmed cold-start evidence

A separate first Lambda invocation had an `Init Duration` of **471.85 ms** in its CloudWatch `REPORT` line. This is the evidence used to identify a confirmed cold start. That invocation had a Lambda `Duration` of 1.98 ms and a `Billed Duration` of 474 ms.

A subsequent warm health invocation had a Lambda `Duration` of 25.05 ms and a `Billed Duration` of 26 ms.

## Estimated cost

The following estimates are for **1,000 requests**, not requests actually sent during testing. They use the recorded billed duration for one representative invocation of each endpoint and the pricing assumptions entered in the cost calculator. They are estimates, not a copy of the AWS bill.

| Operation | Billed duration used | Estimated cost per 1,000 requests (USD) |
|---|---:|---:|
| `GET /health` | 26 ms | $0.00125417 |
| `POST /tickets` | 348 ms | $0.00263500 |
| `GET /tickets/{ticketId}` | 98 ms | $0.00147542 |
| One POST plus one ticket GET | — | $0.00411042 |

The POST estimate assumes one DynamoDB write request unit per ticket. The ticket GET estimate assumes an eventually consistent read of an item up to 4 KB (0.5 read request units). These estimates exclude CloudWatch log ingestion/storage, DynamoDB storage, data transfer, and any other account-level charges. They do not apply Free Tier or credits. Actual charges depend on AWS pricing, usage, and account eligibility.

The inputs and outputs are saved in `experiments/` as CSV files and can be opened in Excel.

## Deploy and remove the AWS stack

The AWS stack is already deployed for the project demonstration. The SAM template is `template.yaml`. If redeploying from a Windows PowerShell terminal, use the AWS CLI/SAM CLI with an authenticated AWS profile and the intended region:

```powershell
$env:AWS_PROFILE = "YOUR_AWS_PROFILE"
$env:AWS_DEFAULT_REGION = "ap-south-1"
sam build
sam deploy --stack-name freshworks-serverless-poc --region ap-south-1 --capabilities CAPABILITY_IAM --resolve-s3
```

After deployment, retrieve the API URL from the CloudFormation stack outputs or SAM deployment output. The URL can change if the stack is recreated.

To remove the deployed stack after the demonstration:

```powershell
sam delete --stack-name freshworks-serverless-poc --region ap-south-1
```

**Important:** Deleting the stack removes the API, Lambda function, DynamoDB table and its ticket data, and the CloudWatch log group managed by the stack. The SAM-managed S3 deployment bucket may remain and should be checked separately. Check AWS Billing after cleanup. AWS credits and budgets do not guarantee that usage will cost nothing; AWS Budgets are alerts, not spending limits.

## Limitations

- The API has no authentication and is for demonstration use only.
- The latency benchmark contains one 100-request run from one client/network.
- The cost figures are estimates based on representative invocations and stated assumptions, not measured charges for 1,000 real requests.
- DynamoDB TTL deletion is asynchronous; an item may remain visible for some time after its expiry timestamp.
