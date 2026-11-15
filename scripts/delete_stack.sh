#!/usr/bin/env bash
# =============================================================================
# MANUAL CLEANUP SCRIPT - deletes the whole CloudFormation stack you deployed.
#
# Deleting the stack removes the API, Lambda function, DynamoDB table (and its
# data) and the log group. It does NOT remove the S3 bucket that SAM created for
# code packages (stack "aws-sam-cli-managed-default"). See the end of this
# script's output and docs/cost-and-safety.md for how to remove that too.
#
# Usage:
#   AWS_REGION=ap-south-1 ./scripts/delete_stack.sh
# =============================================================================
set -euo pipefail

STACK_NAME="${STACK_NAME:-freshworks-serverless-poc}"
REGION="${AWS_REGION:-}"

if [[ -z "$REGION" ]]; then
  echo "ERROR: AWS_REGION is not set. Example:  AWS_REGION=ap-south-1 ./scripts/delete_stack.sh"
  exit 1
fi

if ! command -v aws >/dev/null 2>&1; then
  echo "ERROR: 'aws' CLI is not installed or not on your PATH."
  exit 1
fi

echo "About to DELETE stack '$STACK_NAME' in region '$REGION'."
echo "All tickets stored in the DynamoDB table will be lost."
aws sts get-caller-identity --output table
read -r -p "Type  DELETE  to continue: " typed
if [[ "$typed" != "DELETE" ]]; then
  echo "Cancelled. Nothing was deleted."
  exit 1
fi

aws cloudformation delete-stack --stack-name "$STACK_NAME" --region "$REGION"
echo "Waiting for deletion to finish (this can take a few minutes)..."
aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME" --region "$REGION"
echo "Stack deletion reported complete."

echo
echo "--- Verification (run these yourself and read the output) ---"
echo "1. The stack should no longer be listed (an error 'does not exist' is the GOOD result):"
echo "   aws cloudformation describe-stacks --stack-name $STACK_NAME --region $REGION"
echo "2. No DynamoDB table with the stack's name should remain:"
echo "   aws dynamodb list-tables --region $REGION"
echo "3. No Lambda function from this project should remain:"
echo "   aws lambda list-functions --region $REGION --query \"Functions[?starts_with(FunctionName, '$STACK_NAME')].FunctionName\""
echo "4. No log group should remain:"
echo "   aws logs describe-log-groups --region $REGION --log-group-name-prefix /aws/lambda/$STACK_NAME"
echo "5. No HTTP API should remain:"
echo "   aws apigatewayv2 get-apis --region $REGION"
echo
echo "--- Leftover from 'sam deploy --resolve-s3' ---"
echo "SAM keeps a bucket for uploaded code in the stack 'aws-sam-cli-managed-default'."
echo "It holds only a few KB, but if you want a completely clean account, empty and delete it"
echo "(S3 console -> bucket name starting 'aws-sam-cli-managed-default-samclisourcebucket' -> Empty -> Delete,"
echo "then delete the CloudFormation stack 'aws-sam-cli-managed-default' in $REGION)."
echo "Also check the Billing console the next day to confirm charges have stopped."
