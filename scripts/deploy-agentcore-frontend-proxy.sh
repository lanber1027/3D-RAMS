#!/usr/bin/env bash
set -euo pipefail

FUNCTION_NAME="${AGENTCORE_PROXY_FUNCTION_NAME:-3d-rams-agentcore-frontend-proxy}"
ROLE_NAME="${AGENTCORE_PROXY_ROLE_NAME:-3d-rams-agentcore-frontend-proxy-role}"
ENTRY_RUNTIME_NAME="${AGENTCORE_ENTRY_RUNTIME_NAME:-RamsAgent_asi_one_entry_agent}"
AWS_REGION_VALUE="${AWS_REGION:-${AWS_DEFAULT_REGION:-eu-west-2}}"
ALLOWED_ORIGIN="${AGENTCORE_PROXY_ALLOWED_ORIGIN:-*}"
TIMEOUT_SECONDS="${AGENTCORE_PROXY_TIMEOUT:-120}"

usage() {
  cat <<'EOF'
Usage:
  AWS_PROFILE=3d-rams-deployer \
  AGENTCORE_PROXY_ALLOWED_ORIGIN=https://<amplify-domain> \
  bash scripts/deploy-agentcore-frontend-proxy.sh

Optional:
  AGENTCORE_RUNTIME_ARN           Use a known entry runtime ARN instead of discovery.
  AGENTCORE_ENTRY_RUNTIME_NAME    Default: RamsAgent_asi_one_entry_agent
  AGENTCORE_PROXY_FUNCTION_NAME   Default: 3d-rams-agentcore-frontend-proxy
  AGENTCORE_PROXY_ROLE_NAME       Default: 3d-rams-agentcore-frontend-proxy-role
  AGENTCORE_PROXY_ALLOWED_ORIGIN  Default: *
  AGENTCORE_PROXY_TIMEOUT         Default: 120
  AWS_PROFILE                     Optional AWS CLI profile.
  AWS_REGION                      Default: eu-west-2
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ -n "${AWS_PROFILE:-}" ]]; then
  AWS_ARGS=(--profile "$AWS_PROFILE" --region "$AWS_REGION_VALUE" --no-cli-pager)
  IAM_ARGS=(--profile "$AWS_PROFILE" --no-cli-pager)
else
  AWS_ARGS=(--region "$AWS_REGION_VALUE" --no-cli-pager)
  IAM_ARGS=(--no-cli-pager)
fi

aws_region_cmd() {
  aws "${AWS_ARGS[@]}" "$@"
}

aws_iam_cmd() {
  aws "${IAM_ARGS[@]}" "$@"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_command aws
require_command python3
require_command zip

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/rams-agentcore-proxy.XXXXXX")"
chmod 700 "$TMP_DIR"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

RUNTIME_ARN="${AGENTCORE_RUNTIME_ARN:-}"
if [[ -z "$RUNTIME_ARN" ]]; then
  RUNTIMES_JSON="$TMP_DIR/agent-runtimes.json"
  aws_region_cmd bedrock-agentcore-control list-agent-runtimes --output json > "$RUNTIMES_JSON"
  RUNTIME_ARN="$(ENTRY_RUNTIME_NAME_VALUE="$ENTRY_RUNTIME_NAME" python3 - "$RUNTIMES_JSON" <<'PY'
import json
import os
import sys

runtime_name = os.environ["ENTRY_RUNTIME_NAME_VALUE"]
with open(sys.argv[1], "r", encoding="utf-8") as handle:
    payload = json.load(handle)

candidates = [
    runtime
    for runtime in payload.get("agentRuntimes", [])
    if runtime.get("agentRuntimeName") == runtime_name and runtime.get("status") == "READY"
]
if not candidates:
    raise SystemExit(0)

candidates.sort(key=lambda runtime: runtime.get("lastUpdatedAt", ""), reverse=True)
print(candidates[0].get("agentRuntimeArn", ""))
PY
)"
  if [[ -z "$RUNTIME_ARN" || "$RUNTIME_ARN" == "None" ]]; then
    echo "Could not discover READY AgentCore runtime named $ENTRY_RUNTIME_NAME." >&2
    echo "Set AGENTCORE_RUNTIME_ARN explicitly." >&2
    exit 1
  fi
fi

ENDPOINT_ARN="${RUNTIME_ARN}/runtime-endpoint/DEFAULT"
ACCOUNT_ID="$(aws_region_cmd sts get-caller-identity --query Account --output text)"
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

cat > "$TMP_DIR/trust-policy.json" <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"Service": "lambda.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }
  ]
}
JSON

cat > "$TMP_DIR/invoke-policy.json" <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AgentCoreInvoke",
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:InvokeAgentRuntime",
        "bedrock-agentcore:InvokeAgentRuntimeForUser"
      ],
      "Resource": [
        "${RUNTIME_ARN}",
        "${ENDPOINT_ARN}"
      ]
    },
    {
      "Sid": "LambdaLogs",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:${AWS_REGION_VALUE}:${ACCOUNT_ID}:*"
    }
  ]
}
JSON

ALLOWED_ORIGIN_VALUE="$ALLOWED_ORIGIN" python3 - "$TMP_DIR/cors.json" <<'PY'
import json
import os
import sys

origins = [origin.strip() for origin in os.environ["ALLOWED_ORIGIN_VALUE"].split(",") if origin.strip()]
payload = {
    "AllowOrigins": origins or ["*"],
    "AllowMethods": ["GET", "POST"],
    "AllowHeaders": ["content-type", "authorization"],
    "MaxAge": 300,
}
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
PY

if aws_iam_cmd iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  echo "Updating IAM role policy $ROLE_NAME..."
else
  echo "Creating IAM role $ROLE_NAME..."
  aws_iam_cmd iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "file://$TMP_DIR/trust-policy.json" \
    --query 'Role.Arn' \
    --output text
  sleep 10
fi

aws_iam_cmd iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name 3d-rams-agentcore-runtime-invoke \
  --policy-document "file://$TMP_DIR/invoke-policy.json" >/dev/null

cp agentverse/agentcore_client.py "$TMP_DIR/agentcore_client.py"
cp agentverse/frontend_proxy_lambda.py "$TMP_DIR/frontend_proxy_lambda.py"
(cd "$TMP_DIR" && zip -q proxy.zip agentcore_client.py frontend_proxy_lambda.py)

ENV_VARS="Variables={AGENTCORE_RUNTIME_ARN=${RUNTIME_ARN},AGENTCORE_PROXY_ALLOWED_ORIGIN=${ALLOWED_ORIGIN},AGENTCORE_PROXY_TIMEOUT=${TIMEOUT_SECONDS}}"

if aws_region_cmd lambda get-function --function-name "$FUNCTION_NAME" >/dev/null 2>&1; then
  echo "Updating Lambda function $FUNCTION_NAME..."
  aws_region_cmd lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$TMP_DIR/proxy.zip" \
    --query 'FunctionArn' \
    --output text
  aws_region_cmd lambda wait function-updated --function-name "$FUNCTION_NAME"
  aws_region_cmd lambda update-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --runtime python3.12 \
    --handler frontend_proxy_lambda.handler \
    --role "$ROLE_ARN" \
    --timeout "$TIMEOUT_SECONDS" \
    --environment "$ENV_VARS" \
    --query 'FunctionArn' \
    --output text
else
  echo "Creating Lambda function $FUNCTION_NAME..."
  aws_region_cmd lambda create-function \
    --function-name "$FUNCTION_NAME" \
    --runtime python3.12 \
    --handler frontend_proxy_lambda.handler \
    --role "$ROLE_ARN" \
    --timeout "$TIMEOUT_SECONDS" \
    --environment "$ENV_VARS" \
    --zip-file "fileb://$TMP_DIR/proxy.zip" \
    --query 'FunctionArn' \
    --output text
fi

aws_region_cmd lambda wait function-active --function-name "$FUNCTION_NAME"

if aws_region_cmd lambda get-function-url-config --function-name "$FUNCTION_NAME" >/dev/null 2>&1; then
  echo "Updating Lambda function URL CORS..."
  aws_region_cmd lambda update-function-url-config \
    --function-name "$FUNCTION_NAME" \
    --auth-type NONE \
    --cors "file://$TMP_DIR/cors.json" \
    >/dev/null
else
  echo "Creating Lambda function URL..."
  aws_region_cmd lambda create-function-url-config \
    --function-name "$FUNCTION_NAME" \
    --auth-type NONE \
    --cors "file://$TMP_DIR/cors.json" \
    >/dev/null
fi

if aws_region_cmd lambda get-policy --function-name "$FUNCTION_NAME" \
  --query "Policy" --output text 2>/dev/null | grep -q "AllowPublicFunctionUrlInvoke"; then
  echo "Lambda function URL public invoke permission already exists."
else
  echo "Adding Lambda function URL public invoke permission..."
  aws_region_cmd lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id AllowPublicFunctionUrlInvoke \
    --action lambda:InvokeFunctionUrl \
    --principal "*" \
    --function-url-auth-type NONE \
    >/dev/null
fi

if aws_region_cmd lambda get-policy --function-name "$FUNCTION_NAME" \
  --query "Policy" --output text 2>/dev/null | grep -q "AllowPublicFunctionInvokeViaUrl"; then
  echo "Lambda function invoke-via-url permission already exists."
else
  echo "Adding Lambda function invoke-via-url permission..."
  aws_region_cmd lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id AllowPublicFunctionInvokeViaUrl \
    --action lambda:InvokeFunction \
    --principal "*" \
    --invoked-via-function-url \
    >/dev/null
fi

FUNCTION_URL="$(aws_region_cmd lambda get-function-url-config \
  --function-name "$FUNCTION_NAME" \
  --query 'FunctionUrl' \
  --output text)"

echo "AgentCore entry runtime ARN: $RUNTIME_ARN"
echo "Frontend signed proxy URL: ${FUNCTION_URL}invoke"
echo "Set Amplify branch env:"
echo "VITE_CLOUD_ENTRY_PROXY_URL=${FUNCTION_URL}invoke"
