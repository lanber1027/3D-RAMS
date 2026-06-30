#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${AMPLIFY_APP_NAME:-3d-rams-dev-chunteng}"
BRANCH_NAME="${AMPLIFY_BRANCH:-dev-chunteng}"
REPOSITORY="${AMPLIFY_REPOSITORY:-https://github.com/Capitano00/3D-RAMS}"
AWS_REGION_VALUE="${AWS_REGION:-${AWS_DEFAULT_REGION:-eu-west-2}}"
FRAMEWORK="${AMPLIFY_FRAMEWORK:-React}"
STAGE="${AMPLIFY_STAGE:-DEVELOPMENT}"
WAIT_FOR_JOB="${AMPLIFY_WAIT:-true}"
SKIP_GITHUB_PREFLIGHT="${AMPLIFY_SKIP_GITHUB_PREFLIGHT:-false}"

usage() {
  cat <<'EOF'
Usage:
  AMPLIFY_GITHUB_TOKEN_FILE=/private/tmp/3d-rams-gh-token \
  VITE_CLOUD_ENTRY_PROXY_URL=https://<signed-proxy-domain>/invoke \
  AWS_PROFILE=3d-rams-deployer \
  bash scripts/deploy-amplify-source.sh

Required:
  AMPLIFY_GITHUB_TOKEN or AMPLIFY_GITHUB_TOKEN_FILE

Optional:
  AMPLIFY_APP_ID                 Reuse a known Amplify app id.
  AMPLIFY_APP_NAME               Default: 3d-rams-dev-chunteng
  AMPLIFY_BRANCH                 Default: dev-chunteng
  AMPLIFY_REPOSITORY             Default: https://github.com/Capitano00/3D-RAMS
  VITE_CLOUD_ENTRY_PROXY_URL     Public browser endpoint for the signed AgentCore proxy.
  VITE_USE_LOCAL_ASIONE          Default: false
  VITE_CESIUM_ION_TOKEN          Default: empty
  AWS_PROFILE                    Optional AWS CLI profile.
  AWS_REGION                     Default: eu-west-2
  AMPLIFY_WAIT                   Default: true
  AMPLIFY_SKIP_GITHUB_PREFLIGHT  Default: false
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ -n "${AWS_PROFILE:-}" ]]; then
  AWS_ARGS=(--profile "$AWS_PROFILE" --region "$AWS_REGION_VALUE" --no-cli-pager)
else
  AWS_ARGS=(--region "$AWS_REGION_VALUE" --no-cli-pager)
fi

aws_cmd() {
  aws "${AWS_ARGS[@]}" "$@"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_command aws
require_command python3

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/rams-amplify-source.XXXXXX")"
chmod 700 "$TMP_DIR"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

TOKEN_FILE="$TMP_DIR/github-token"
if [[ -n "${AMPLIFY_GITHUB_TOKEN:-}" ]]; then
  printf '%s' "$AMPLIFY_GITHUB_TOKEN" > "$TOKEN_FILE"
elif [[ -n "${AMPLIFY_GITHUB_TOKEN_FILE:-}" && -r "${AMPLIFY_GITHUB_TOKEN_FILE:-}" ]]; then
  tr -d '\r\n' < "$AMPLIFY_GITHUB_TOKEN_FILE" > "$TOKEN_FILE"
else
  echo "Missing GitHub token. Set AMPLIFY_GITHUB_TOKEN or AMPLIFY_GITHUB_TOKEN_FILE." >&2
  echo "The token needs GitHub repo access and webhook creation permissions for $REPOSITORY." >&2
  exit 1
fi
chmod 600 "$TOKEN_FILE"

if [[ ! -s "$TOKEN_FILE" ]]; then
  echo "GitHub token is empty." >&2
  exit 1
fi

if [[ -z "${VITE_CLOUD_ENTRY_PROXY_URL:-}" ]]; then
  echo "Warning: VITE_CLOUD_ENTRY_PROXY_URL is empty; hosted UI can load, but cloud workflow calls will fail until it is set." >&2
fi

if [[ "$SKIP_GITHUB_PREFLIGHT" != "true" ]]; then
  REPOSITORY_VALUE="$REPOSITORY" python3 - "$TOKEN_FILE" <<'PY'
import json
import os
import re
import sys
import urllib.error
import urllib.request

token_file = sys.argv[1]
repository = os.environ["REPOSITORY_VALUE"]
match = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+)(?:\.git)?$", repository)
if not match:
    raise SystemExit(f"Cannot parse GitHub repository URL: {repository}")

owner = match.group("owner")
repo = match.group("repo")
with open(token_file, "r", encoding="utf-8") as handle:
    token = handle.read().strip()

def github_get(path: str) -> tuple[int, str]:
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "3d-rams-amplify-source-deploy",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, body

repo_status, repo_body = github_get(f"/repos/{owner}/{repo}")
if repo_status != 200:
    raise SystemExit(
        f"GitHub token cannot access {owner}/{repo}; GitHub API returned {repo_status}: {repo_body}"
    )

repo_payload = json.loads(repo_body)
permissions = repo_payload.get("permissions") or {}
if not permissions.get("admin"):
    raise SystemExit(
        "GitHub token can access the repository but does not have repo admin permission. "
        "Amplify source-connected hosting needs repo webhook access; use a token from a repo admin "
        "with classic scopes repo + admin:repo_hook, or a fine-grained token with repository "
        "Administration/Webhooks read-write access."
    )

hooks_status, hooks_body = github_get(f"/repos/{owner}/{repo}/hooks")
if hooks_status != 200:
    raise SystemExit(
        f"GitHub token cannot list repository webhooks; GitHub API returned {hooks_status}: {hooks_body}"
    )

print(f"GitHub token preflight passed for {owner}/{repo}.")
PY
fi

CUSTOM_RULES_JSON='[{"source":"</^[^.]+$|\\.(?!(css|gif|ico|jpg|js|png|txt|svg|woff|woff2|ttf|map|json)$)([^.]+$)/>","target":"/index.html","status":"200"}]'

write_app_payload() {
  local mode="$1"
  local output_path="$2"
  local app_id="${3:-}"
  APP_ID_VALUE="$app_id" \
  APP_NAME_VALUE="$APP_NAME" \
  REPOSITORY_VALUE="$REPOSITORY" \
  CUSTOM_RULES_VALUE="$CUSTOM_RULES_JSON" \
  python3 - "$mode" "$output_path" "$TOKEN_FILE" <<'PY'
import json
import os
import sys

mode, output_path, token_file = sys.argv[1:4]
with open(token_file, "r", encoding="utf-8") as handle:
    token = handle.read().strip()

payload = {
    "repository": os.environ["REPOSITORY_VALUE"],
    "platform": "WEB",
    "accessToken": token,
    "enableBranchAutoBuild": True,
    "customRules": json.loads(os.environ["CUSTOM_RULES_VALUE"]),
}

if mode == "create":
    payload["name"] = os.environ["APP_NAME_VALUE"]
    payload["description"] = "3D-RAMS dev-chunteng source-connected Amplify frontend"
elif mode == "update":
    payload["appId"] = os.environ["APP_ID_VALUE"]
else:
    raise SystemExit(f"unknown mode: {mode}")

with open(output_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
PY
}

write_branch_payload() {
  local mode="$1"
  local output_path="$2"
  APP_ID_VALUE="$APP_ID" \
  BRANCH_NAME_VALUE="$BRANCH_NAME" \
  FRAMEWORK_VALUE="$FRAMEWORK" \
  STAGE_VALUE="$STAGE" \
  VITE_CLOUD_ENTRY_PROXY_URL_VALUE="${VITE_CLOUD_ENTRY_PROXY_URL:-}" \
  VITE_USE_LOCAL_ASIONE_VALUE="${VITE_USE_LOCAL_ASIONE:-false}" \
  VITE_CESIUM_ION_TOKEN_VALUE="${VITE_CESIUM_ION_TOKEN:-}" \
  python3 - "$mode" "$output_path" <<'PY'
import json
import os
import sys

mode, output_path = sys.argv[1:3]
payload = {
    "appId": os.environ["APP_ID_VALUE"],
    "branchName": os.environ["BRANCH_NAME_VALUE"],
    "framework": os.environ["FRAMEWORK_VALUE"],
    "stage": os.environ["STAGE_VALUE"],
    "enableAutoBuild": True,
    "environmentVariables": {
        "VITE_CLOUD_ENTRY_PROXY_URL": os.environ["VITE_CLOUD_ENTRY_PROXY_URL_VALUE"],
        "VITE_USE_LOCAL_ASIONE": os.environ["VITE_USE_LOCAL_ASIONE_VALUE"],
        "VITE_CESIUM_ION_TOKEN": os.environ["VITE_CESIUM_ION_TOKEN_VALUE"],
    },
}
if mode not in {"create", "update"}:
    raise SystemExit(f"unknown mode: {mode}")

with open(output_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
PY
}

APP_ID="${AMPLIFY_APP_ID:-}"
if [[ -z "$APP_ID" ]]; then
  APP_ID="$(aws_cmd amplify list-apps \
    --query "apps[?name=='${APP_NAME}'].appId | [0]" \
    --output text)"
  if [[ "$APP_ID" == "None" ]]; then
    APP_ID=""
  fi
fi

if [[ -n "$APP_ID" ]]; then
  echo "Updating Amplify app $APP_ID ($APP_NAME) with source repository..."
  APP_PAYLOAD="$TMP_DIR/update-app.json"
  write_app_payload update "$APP_PAYLOAD" "$APP_ID"
  aws_cmd amplify update-app \
    --cli-input-json "file://$APP_PAYLOAD" \
    --query 'app.{appId:appId,name:name,repository:repository,defaultDomain:defaultDomain}' \
    --output table
else
  echo "Creating source-connected Amplify app $APP_NAME..."
  APP_PAYLOAD="$TMP_DIR/create-app.json"
  write_app_payload create "$APP_PAYLOAD"
  APP_ID="$(aws_cmd amplify create-app \
    --cli-input-json "file://$APP_PAYLOAD" \
    --query 'app.appId' \
    --output text)"
  echo "Created Amplify app $APP_ID"
fi

if aws_cmd amplify get-branch --app-id "$APP_ID" --branch-name "$BRANCH_NAME" >/dev/null 2>&1; then
  echo "Updating Amplify branch $BRANCH_NAME..."
  BRANCH_PAYLOAD="$TMP_DIR/update-branch.json"
  write_branch_payload update "$BRANCH_PAYLOAD"
  aws_cmd amplify update-branch \
    --cli-input-json "file://$BRANCH_PAYLOAD" \
    --query 'branch.{branchName:branchName,stage:stage,enableAutoBuild:enableAutoBuild,environmentVariables:environmentVariables}' \
    --output table
else
  echo "Creating Amplify branch $BRANCH_NAME..."
  BRANCH_PAYLOAD="$TMP_DIR/create-branch.json"
  write_branch_payload create "$BRANCH_PAYLOAD"
  aws_cmd amplify create-branch \
    --cli-input-json "file://$BRANCH_PAYLOAD" \
    --query 'branch.{branchName:branchName,stage:stage,enableAutoBuild:enableAutoBuild,environmentVariables:environmentVariables}' \
    --output table
fi

echo "Starting source build for $BRANCH_NAME..."
JOB_ID="$(aws_cmd amplify start-job \
  --app-id "$APP_ID" \
  --branch-name "$BRANCH_NAME" \
  --job-type RELEASE \
  --query 'jobSummary.jobId' \
  --output text)"

echo "Amplify app id: $APP_ID"
echo "Amplify branch: $BRANCH_NAME"
echo "Amplify job id: $JOB_ID"
echo "Amplify URL: https://${BRANCH_NAME}.${APP_ID}.amplifyapp.com/"

if [[ "$WAIT_FOR_JOB" == "true" ]]; then
  echo "Waiting for Amplify job to finish..."
  while true; do
    STATUS="$(aws_cmd amplify get-job \
      --app-id "$APP_ID" \
      --branch-name "$BRANCH_NAME" \
      --job-id "$JOB_ID" \
      --query 'job.summary.status' \
      --output text)"
    echo "Amplify job status: $STATUS"
    case "$STATUS" in
      SUCCEED)
        echo "Amplify source deployment succeeded: https://${BRANCH_NAME}.${APP_ID}.amplifyapp.com/"
        break
        ;;
      FAILED|CANCELLED)
        echo "Amplify source deployment failed with status: $STATUS" >&2
        exit 1
        ;;
    esac
    sleep 10
  done
fi
