# Optional AWS Bedrock Setup

This guide is for maintainers who want to test the optional live Bedrock briefing path. It is not required for normal teammate testing, Codespaces testing, CI, or the deterministic demo.

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
4. Keep usage low: one Bedrock call per agent run.
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
MATERIAL_EXTRACTION_MODEL_ID=amazon.nova-lite-v1:0
MATERIAL_EXTRACTION_MAX_TOKENS=900
```

Bedrock remains disabled unless explicitly enabled:

```bash
ENABLE_BEDROCK=true
```

Do not commit `.env`, AWS credentials, SSO cache files, API keys, or local shell history.

## Smoke Test

Install the AgentCore Python package first if needed:

```bash
python -m pip install -e app/rams_supervisor_runtime
```

Then run:

```bash
python scripts/bedrock-smoke.py
```

Expected result:

- the script exits with code `0`;
- `bedrockStepStatus` is `ok`;
- `runtime.briefingMode` shows `real` for a live Bedrock call, or `mocked` only when the explicit mock switch is enabled;
- `safety` remains inside the human-review briefing boundary.

If the script exits non-zero, the app can still run in deterministic mode.

## How The App Uses Bedrock

3D-RAMS uses Bedrock for optional bounded model steps when explicitly enabled:

1. The material adapter can extract bounded observations from already-authorized retrieved PDF/text material using `MATERIAL_EXTRACTION_MODEL_ID`, defaulting to Nova Lite.
2. The briefing adapter can draft a briefing from structured evidence using `BEDROCK_MODEL_ID`.
3. Responses are parsed, bounded, and validated before report use.
4. The local safety gate still blocks certified RAMS, emergency guidance, work approval, and competent-person replacement claims.
5. If Bedrock fails, returns invalid output, or is disabled, deterministic briefing fallback remains available and material extraction returns explicit skipped/failure statuses.

Raw document text or binary content is not persisted in traces, reports, fixtures, or report-store payloads. The evidence register and trace remain inspectable with bounded observations, citations, limitations, and model metadata.

## Troubleshooting

| Symptom | Likely Cause | What To Try |
| --- | --- | --- |
| `AccessDeniedException` | Model access, profile, or permission issue. | Confirm the selected model is enabled in the target region and the active AWS profile can invoke it. |
| `Unable to locate credentials` | AWS credentials are not active or the profile name is wrong. | Configure or refresh the selected AWS profile, then rerun the smoke test. |
| `boto3 is not installed` | AgentCore package dependencies are missing. | Install `app/rams_supervisor_runtime` in the active Python environment. |
| Smoke test falls back | Bedrock is disabled, simulated failure is set, or the model call failed. | Check environment variables and rerun once; keep deterministic mode if failures continue. |
| Output sounds too authoritative | Model wording crossed the demo safety boundary. | Treat as a bug; local safety scan should block unsafe claims, and the deterministic fallback remains available. |

## What Not To Do

- Do not make Bedrock mandatory for teammate testing.
- Do not add AWS credentials to GitHub, Codespaces secrets, issues, screenshots, or chat.
- Do not send real client or private site data to the model.
- Do not claim certified RAMS, emergency response guidance, work approval, or production deployment.
- Do not add DynamoDB, S3, CloudWatch, or Guardrails until the core Bedrock path and demo proof are stable.

## Production Path Later

After the local Bedrock path is stable and cost-guarded, the next AWS stages can be evaluated separately:

- CloudWatch-style traces for model latency, status, fallback reason, and safety decision;
- S3 evidence-pack exports if shareable site packs become part of the demo;
- DynamoDB session/version records if approval, revise, or rollback becomes a real workflow;
- Bedrock Guardrails as an additional safety layer, not a replacement for local checks;
- AgentCore Runtime or Observability only if it reduces operational complexity or a bounty rewards it.
