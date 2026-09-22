#!/usr/bin/env bash
set -euo pipefail

REGION="${AWS_REGION:-us-gov-east-1}"
STACK_NAME="${CBOM_STACK_NAME:-cbom-workbench-dev}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

status="$(aws cloudformation describe-stacks \
  --region "$REGION" \
  --stack-name "$STACK_NAME" \
  --query 'Stacks[0].StackStatus' \
  --output text)"

if [[ "$status" == "UPDATE_IN_PROGRESS" ]]; then
  echo "Canceling the stuck $STACK_NAME update so CloudFormation can restore the last stable service state..."
  aws cloudformation cancel-update-stack \
    --region "$REGION" \
    --stack-name "$STACK_NAME"
fi

for attempt in {1..180}; do
  status="$(aws cloudformation describe-stacks \
    --region "$REGION" \
    --stack-name "$STACK_NAME" \
    --query 'Stacks[0].StackStatus' \
    --output text)"

  case "$status" in
    UPDATE_ROLLBACK_COMPLETE|UPDATE_COMPLETE|CREATE_COMPLETE)
      echo "Stack is ready for a clean deployment: $status"
      exec "$SCRIPT_DIR/deploy-latest.sh"
      ;;
    *_FAILED|ROLLBACK_COMPLETE|ROLLBACK_FAILED|UPDATE_ROLLBACK_FAILED)
      echo "Stack reached $status; inspect CloudFormation events before retrying." >&2
      exit 1
      ;;
    *)
      echo "Waiting for rollback to finish: $status (attempt $attempt/180)"
      sleep 10
      ;;
  esac
done

echo "Timed out waiting for $STACK_NAME to become deployable." >&2
exit 1
