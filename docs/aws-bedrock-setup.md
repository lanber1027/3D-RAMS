# Optional AWS Bedrock Setup

This guide is for maintainers who want to test the optional live Bedrock LLM-first path. It is not required for normal teammate testing, Codespaces testing, CI, or the deterministic demo.

Default 3D-RAMS behavior remains local and no-AWS:

- `ENABLE_BEDROCK=false`;
- cached public and synthetic fixtures only;
- no hosted public endpoint;
- no live planning portal, Google Maps, or Cesium ion dependency;
- deterministic briefing fallback available for every run.

## Use This Only After Cost Guardrails

Before repeated live Bedrock testing:

1. Confirm the AWS account and region.
2. Confirm payment preferences are understood.
3. Create a small budget alert, such as `25 USD/month`.
4. Keep usage low: no more than 4 Bedrock model calls per maintainer run.
5. Never use real client data, private site records, secrets, or access-controlled documents in prompts.

For one-off local smoke testing, use short fixture prompts only and stop if the response is slow, repeatedly failing, or unexpectedly costly.

## Current Local Settings

The current maintained local profile and model are:

```bash
AWS_PROFILE=3d-rams-dev
AWS_REGION=eu-west-2
BEDROCK_MODEL_ID=anthropic.claude-3-7-sonnet-20250219-v1:0
BEDROCK_MAX_TOKENS=1200
BEDROCK_TEMPERATURE=0.2
BEDROCK_MAX_MODEL_CALLS=4
```

Bedrock remains disabled unless explicitly enabled:

```bash
ENABLE_BEDROCK=true
```

Do not commit `.env`, AWS credentials, SSO cache files, API keys, or local shell history.

## Smoke Test

Install backend dependencies first if needed:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cd ..
```

Then run:

```bash
python scripts/bedrock-smoke.py
```

Expected result:

- the script exits with code `0`;
- `plannerStepStatus` and `synthesisStepStatus` are `ok`;
- `runtime.briefingMode` shows `real` for a live Bedrock call, or `mocked` only when the explicit mock switch is enabled;
- the frontend `LLM-First Runtime` panel shows model plan/synthesis details when those fields are returned, or degrades gracefully to trace-derived explanation when they are not;
- `safety` remains inside the human-review briefing boundary.

If the script exits non-zero, the app can still run in deterministic mode.

## How The App Uses Bedrock

3D-RAMS uses Bedrock only for one optional LLM-first planning/synthesis path:

1. The runtime prepares structured hazards, annotations, evidence, and limitations.
2. The Bedrock adapter can plan/synthesize from that structured evidence.
3. Only allowlisted tool calls are allowed back into the runtime.
4. The response is parsed and validated.
5. The local safety gate still blocks certified RAMS, emergency guidance, work approval, and competent-person replacement claims.
6. If Bedrock fails, returns invalid output, or is disabled, deterministic briefing fallback is used.

Bedrock is not the source of truth for evidence extraction in the current MVP. The evidence register and trace remain inspectable.

## Troubleshooting

| Symptom | Likely Cause | What To Try |
| --- | --- | --- |
| `AccessDeniedException` | Model access, profile, or permission issue. | Confirm the selected model is enabled in the target region and the active SSO profile can invoke it. |
| `Unable to locate credentials` | SSO session is not active or profile name is wrong. | Re-authenticate with AWS SSO for the selected profile, then rerun the smoke test. |
| `boto3 is not installed` | Backend dependencies are missing. | Install `backend/requirements.txt` in the active Python environment. |
| Smoke test falls back | Bedrock is disabled, simulated failure is set, or the model call failed. | Check environment variables and rerun once; keep deterministic mode if failures continue. |
| Output sounds too authoritative | Model wording crossed the demo safety boundary. | Treat as a bug; local safety scan should block unsafe claims, and the deterministic fallback remains available. |

## What Not To Do

- Do not make Bedrock mandatory for teammate testing.
- Do not add AWS credentials to GitHub, Codespaces secrets, issues, screenshots, or chat.
- Do not send real client or private site data to the model.
- Do not claim certified RAMS, emergency response guidance, work approval, or production deployment.
- Do not imply Bedrock is public-user enabled; current live testing remains maintainer-only.
- Do not add DynamoDB, S3, CloudWatch, Guardrails, or AgentCore until the core Bedrock path and demo proof are stable.

## Production Path Later

After the local Bedrock path is stable and cost-guarded, the next AWS stages can be evaluated separately:

- CloudWatch-style traces for model latency, status, fallback reason, and safety decision;
- S3 evidence-pack exports if shareable site packs become part of the demo;
- DynamoDB session/version records if approval, revise, or rollback becomes a real workflow;
- Bedrock Guardrails as an additional safety layer, not a replacement for local checks;
- AgentCore Runtime or Observability only if it reduces operational complexity or a bounty rewards it.
