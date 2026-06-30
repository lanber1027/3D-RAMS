# Amplify Frontend Hosting

This document implements [ADR 0006](adr/0006-amplify-app-framework-hosting.md) for source-connected Amplify hosting.

Amplify hosts only the React/Vite frontend. AgentCore runtimes, Harnesses, the signed AgentCore proxy, AgentVerse hosted adapter secrets, IAM credentials, and runtime ARNs remain outside Amplify source control.

## Build Contract

The repository root contains `amplify.yml`. Amplify should connect to the Git branch and use the configured app root:

- app root: `frontend`
- install: `npm ci`
- build: `npm run build`
- artifact directory: `frontend/dist`

No AWS credentials, AgentCore runtime ARNs, AgentVerse keys, or private deployment summaries belong in this file or in frontend source.

## Branch Environment Variables

Set these in the Amplify app branch environment:

```bash
VITE_CLOUD_ENTRY_PROXY_URL=https://<signed-proxy-domain>/invoke
VITE_USE_LOCAL_ASIONE=false
VITE_CESIUM_ION_TOKEN=
```

`VITE_CLOUD_ENTRY_PROXY_URL` is public client configuration. The proxy behind that URL owns AWS signing and calls the cloud `asi_one_entry_agent` runtime. It is a transport bridge only; it must not recreate `/api/chat`, `/api/run`, `/api/session/start`, or `/api/upload-url`.

Do not set these local-only variables for hosted Amplify unless you are intentionally debugging a local tunnel:

```bash
VITE_AGENTCORE_URL=/agentcore/invocations
VITE_AGENTCORE_PROXY_TARGET=http://127.0.0.1:8080
```

## Source-Connected Setup

Use the repository script to create or update the Amplify app, connect the GitHub repository, configure the branch environment, and start a source build:

```bash
AMPLIFY_GITHUB_TOKEN_FILE=/private/tmp/3d-rams-gh-token \
VITE_CLOUD_ENTRY_PROXY_URL=https://<signed-proxy-domain>/invoke \
AWS_PROFILE=3d-rams-deployer \
AWS_REGION=eu-west-2 \
bash scripts/deploy-amplify-source.sh
```

The GitHub token must have repository access plus webhook creation permissions for `Capitano00/3D-RAMS`. In practice, use a token from a repo admin with classic `repo` + `admin:repo_hook` scopes, or a fine-grained token with repository Administration/Webhooks read-write access. Keep it in a local file or environment variable only. Do not commit it or paste it into public logs.

Useful overrides:

```bash
AMPLIFY_APP_ID=<existing-app-id>
AMPLIFY_APP_NAME=3d-rams-dev-chunteng
AMPLIFY_BRANCH=dev-chunteng
AMPLIFY_REPOSITORY=https://github.com/Capitano00/3D-RAMS
VITE_USE_LOCAL_ASIONE=false
VITE_CESIUM_ION_TOKEN=
```

The signed proxy must already be reachable from the browser before the hosted UI can complete the cloud workflow.

The deploy script performs a GitHub permission preflight before calling Amplify. If it reports missing repo admin/webhook permission, the same token will fail in Amplify with a GitHub hooks API `404`.

## Manual Console Setup

The script above is the preferred setup path. If the AWS Console is used for inspection or recovery, the equivalent settings are:

1. Create or open the Amplify app.
2. Connect the intended GitHub branch.
3. Confirm Amplify picks up `amplify.yml`.
4. Add the branch environment variables above.
5. Deploy the branch from source.

## Verification

After deployment:

- Open the hosted Amplify URL.
- Confirm the page loads static assets and the Cesium scene shell.
- Submit the default FieldBrief ASI simulation prompt.
- Confirm the browser request goes to `VITE_CLOUD_ENTRY_PROXY_URL`, not `/agentcore/invocations`.
- Confirm the response renders map annotations, briefing, evidence, trace, and safety data.
- Confirm no cloud-mode run contains `localAsiOneSubstitute: true`.

For full ADR 0016 hosted workflow parity, run the AgentCore + ASI smoke against the same signed proxy:

```bash
RAMS_HOSTED_FRONTEND_URL=https://<amplify-app-url> \
RAMS_HOSTED_ENTRY_URL=https://<signed-proxy-domain>/invoke \
python3 scripts/hosted-agentcore-asio-smoke.py
```

Add `--bedrock-fallback` to also verify the Bedrock-requested fallback behavior. This hosted smoke covers Amplify app-shell loading when `RAMS_HOSTED_FRONTEND_URL` is set, entry clarification, confirmed supervisor launch, report-store write, identity-bound lookup, authorized/denied material references, runtime mode assertions, and public-safe output. Amplify page-load verification alone is not enough to prove the hosted AgentCore + ASI topology.

## Legacy Manual ZIP Deploy

If a manual Amplify ZIP deployment script exists in another worktree or historical branch, keep it as a fallback/debug path only. Source-connected Amplify builds from `amplify.yml` are the preferred hosted frontend deployment path.
