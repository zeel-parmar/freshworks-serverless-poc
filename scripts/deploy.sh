#!/usr/bin/env bash
# =============================================================================
# MANUAL DEPLOYMENT SCRIPT - nothing runs until YOU run it and confirm.
#
# This script creates REAL AWS resources that can cost REAL money:
#   API Gateway HTTP API, Lambda, DynamoDB table, CloudWatch log group,
#   plus an S3 bucket that SAM uses to store the code package.
#
# Read docs/cost-and-safety.md first. AWS Budgets are alerts, NOT spending caps.
#
# Usage:
#   AWS_REGION=ap-south-1 ./scripts/deploy.sh
#   AWS_REGION=ap-south-1 MEMORY_MB=256 ./scripts/deploy.sh      # optional memory experiment
#
# Optional variables:
#   STACK_NAME   (default: freshworks-serverless-poc)
#   MEMORY_MB    (default: 128; allowed: 128, 256, 512)
# =============================================================================
set -euo pipefail

STACK_NAME="${STACK_NAME:-freshworks-serverless-poc}"
MEMORY_MB="${MEMORY_MB:-128}"
REGION="${AWS_REGION:-}"

cd "$(dirname "$0")/.."

if [[ -z "$REGION" ]]; then
  echo "ERROR: AWS_REGION is not set."
  echo "Choose the region deliberately, for example:  AWS_REGION=ap-south-1 ./scripts/deploy.sh"
  exit 1
fi

for tool in aws sam; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "ERROR: '$tool' is not installed or not on your PATH. See the README, section 'Local setup'."
    exit 1
  fi
done

echo "============================================================"
echo " About to deploy to REAL AWS"
echo "   Stack name : $STACK_NAME"
echo "   Region     : $REGION"
echo "   Memory     : ${MEMORY_MB} MB"
echo "============================================================"
echo
echo "Which AWS account will be charged (read-only check):"
aws sts get-caller-identity --output table
echo

cat <<'CHECKLIST'
Before continuing, confirm that you have personally checked:
  [ ] AWS Billing console -> Bills: no unexpected charges
  [ ] AWS Billing console -> Credits: whether credits exist and when they expire
  [ ] Free Tier page: what is (and is not) included for THIS account
  [ ] A budget alert exists (remember: it only warns you, it does not stop spending)
  [ ] The region above is the one you intend to use
  [ ] You will run scripts/delete_stack.sh when you finish testing
CHECKLIST
echo

read -r -p "Type the region name ($REGION) to confirm the region: " typed_region
if [[ "$typed_region" != "$REGION" ]]; then
  echo "Region did not match. Nothing was deployed."
  exit 1
fi

read -r -p "Type  I HAVE CHECKED BILLING  to continue: " typed_confirm
if [[ "$typed_confirm" != "I HAVE CHECKED BILLING" ]]; then
  echo "Confirmation text did not match. Nothing was deployed."
  exit 1
fi

echo
echo "Step 1/2: sam build (packages the code locally, no AWS charges)"
sam build

echo
echo "Step 2/2: sam deploy (creates AWS resources). SAM will show a change set and ask you to approve it."
sam deploy \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --resolve-s3 \
  --capabilities CAPABILITY_IAM \
  --confirm-changeset \
  --no-fail-on-empty-changeset \
  --parameter-overrides "LambdaMemoryMb=${MEMORY_MB}"

echo
echo "Deployment finished. Your API URL:"
aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" \
  --output text
echo
echo "Next: ./scripts/invoke_api.sh <API_URL>   (sends only 2 requests)"
echo "When finished: AWS_REGION=$REGION ./scripts/delete_stack.sh"
