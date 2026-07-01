# AgentVerse / ASI:ONE Runtime Integration

This document captures the current integration status after importing the separate `onboardAgentCore/app/MyAgent` proof of concept into this repository.

## Current Status

The team has a working ASI:ONE / AgentVerse entry agent:

- AgentVerse handle: `@3d-rams`;
- proof-of-concept AWS runtime name: `onboardAgentCore_MyAgent`;
- imported local runtime source: `app/asi_one_entry_agent`;
- hosted AgentVerse adapter source: `agentverse/hosted_adapter.py`.

This public repo does not store the deployed runtime ARN, AWS account ID, access keys, AgentVerse key, or AgentVerse seed phrase.

## Unified AgentCore Project Shape

The repository now has two AgentCore runtimes:

| Runtime | Path | Role |
| --- | --- | --- |
| `rams_supervisor_runtime` | `app/rams_supervisor_runtime/` | 3D-RAMS supervisor/report runtime; owns site-review orchestration and visualization payloads. |
| `asi_one_entry_agent` | `app/asi_one_entry_agent/` | AgentVerse entry runtime imported from the ASI:ONE proof of concept; owns fast conversational intake/delivery behavior. |

The repository now has one supervisor Harness config plus specialist Harness subagents:

| Harness | Path | Role |
| --- | --- | --- |
| `rams_supervisor_harness` | `app/rams_supervisor_harness/` | Target Harness for supervisor orchestration and review workflow. |
| `rams_geospatial_harness` | `app/rams_geospatial_harness/` | Geospatial specialist for location resolution, geospatial context, and scene configuration. |
| `rams_planning_harness` | `app/rams_planning_harness/` | Planning/document context specialist. |
| `rams_material_harness` | `app/rams_material_harness/` | ASI-owned material reference validation and bounded evidence extraction specialist. |
| `rams_hazard_harness` | `app/rams_hazard_harness/` | Hazard and RAMS-scoping evidence specialist. |
| `rams_annotation_harness` | `app/rams_annotation_harness/` | 3D annotation payload specialist. |
| `rams_briefing_harness` | `app/rams_briefing_harness/` | Evidence-backed briefing specialist. |
| `rams_review_harness` | `app/rams_review_harness/` | Independent review-gate Harness. |

The supervisor Harness owns the dispatch plan in `app/rams_supervisor_harness/subagents.json`. The supervisor runtime dispatches through `supervisor_core.subagent_invoker`: local Demo1 defaults to deterministic direct execution, while deployed Harness execution can be enabled with `RAMS_SUBAGENT_EXECUTION_MODE=agentcore_harness` and the deployed Harness ARN mappings.

The imported entry runtime also declares `asi_one_entry_agent_memory` in `agentcore/agentcore.json`, matching the environment variable expected by `app/asi_one_entry_agent/memory/session.py`.

## AgentVerse Hosted Adapter

`agentverse/hosted_adapter.py` is designed for an AgentVerse hosted environment. It receives AgentVerse chat messages, signs an AWS AgentCore invocation request, streams text deltas from AgentCore, and replies to AgentVerse.

Required hosted environment variables:

```bash
AWS_REGION=eu-west-2
AGENTCORE_RUNTIME_ARN=arn:aws:bedrock-agentcore:<region>:<account-id>:runtime/<runtime-id>
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
# Optional for temporary credentials:
AWS_SESSION_TOKEN=...
```

Recommended IAM scope:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "Invoke3DRamsEntryRuntime",
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:InvokeAgentRuntime",
        "bedrock-agentcore:InvokeAgentRuntimeForUser"
      ],
      "Resource": [
        "arn:aws:bedrock-agentcore:<region>:<account-id>:runtime/<runtime-id>",
        "arn:aws:bedrock-agentcore:<region>:<account-id>:runtime/<runtime-id>/runtime-endpoint/DEFAULT"
      ]
    }
  ]
}
```

The `InvokeAgentRuntimeForUser` action is required when the adapter sends
`x-amzn-bedrock-agentcore-runtime-user-id`. The `/runtime-endpoint/DEFAULT` resource was required by
the working proof of concept after AgentCore resolved the invocation to the default endpoint.

## Working Proof Notes

The proof-of-concept thread established these operational details:

- AgentVerse hosted agents did not have `boto3` available by default, so the adapter uses `requests` and standard-library SigV4 signing.
- SigV4 canonical URI must sign the already-encoded runtime path with `quote(path, safe="/~")`; otherwise AgentCore returns signature mismatch.
- IAM needs both `bedrock-agentcore:InvokeAgentRuntime` and `bedrock-agentcore:InvokeAgentRuntimeForUser` for the current headers.
- IAM resources need both the runtime ARN and the `runtime-endpoint/DEFAULT` ARN.
- AgentVerse should have only one chat protocol registration. If `agent.py` imports `hosted_adapter.agent`, it should not also define its own `ChatMessage` handlers.
- The first successful end-to-end path was `ASI:ONE -> AgentVerse hosted adapter -> AWS AgentCore asi_one_entry_agent -> Bedrock Nova Micro -> ASI:ONE`.

## Registration

Use `scripts/register_agentverse.py` only from a local environment with Python 3.10+ and `uagents-core` installed.

Required local environment variables:

```bash
AGENTVERSE_KEY=...
AGENT_SEED_PHRASE=...
AGENT_ENDPOINT_URL=https://<your-agentverse-hosted-adapter-endpoint>/chat
```

You may copy `.env.agentverse.example` to an untracked `.env.agentverse` locally. Do not commit the real file.

## Deployment Notes

The existing cloud runtime named like `onboardAgentCore_MyAgent` was created by the separate proof-of-concept AgentCore project. This repository can manage the same source code going forward, but the team still needs to choose one of these deployment strategies:

1. Import the existing deployed runtime into this AgentCore project if the CLI/account flow supports it cleanly.
2. Redeploy `asi_one_entry_agent` from this repository and update AgentVerse `AGENTCORE_RUNTIME_ARN`.
3. Keep the existing deployed runtime temporarily and use this repo as the source of truth for the next deployment.

Until one of those is completed, do not assume that `agentcore deploy` from this repo will automatically update the already-deployed `onboardAgentCore_MyAgent` resource.

## One-Time Cutover From The PoC Runtime

Recommended cutover path:

1. Deploy this repository's AgentCore project from a non-root AWS identity.
2. Read the newly deployed `asi_one_entry_agent` runtime ARN from `agentcore status --runtime asi_one_entry_agent --json`.
3. Update the AgentVerse hosted adapter secret `AGENTCORE_RUNTIME_ARN` to that new ARN.
4. Update the IAM policy attached to the AgentVerse invoker principal so it points at the new runtime ARN and its default endpoint ARN.
5. Test `@3d-rams` in ASI:ONE.
6. Keep the old `onboardAgentCore_MyAgent` runtime as fallback until the new path is verified, then retire it manually.

Deployment identity requirement:

- Do not deploy with AWS root credentials.
- AgentCore/CDK needs a non-root IAM/SSO identity that can use the CDK bootstrap deploy role.
- If `agentcore deploy --yes --json` fails with `Roles may not be assumed by root accounts`, switch to a non-root AWS profile and rerun deploy.

Useful commands:

```bash
aws sts get-caller-identity
agentcore package --runtime asi_one_entry_agent
agentcore deploy --dry-run --json
agentcore deploy --yes --json
agentcore status --runtime asi_one_entry_agent --json
```

## Hosted AgentCore + ASI Smoke

Use the ADR 0016 smoke script after the hosted entry runtime, supervisor runtime, signed proxy, Harnesses, and report store are configured:

```bash
RAMS_HOSTED_ENTRY_URL=https://<signed-proxy-domain>/invoke \
python3 scripts/hosted-agentcore-asio-smoke.py
```

The script invokes the signed proxy for `asi_one_entry_agent`; it does not call old FastAPI route names such as `/api/session/start`, `/api/upload-url`, or `/api/chat`.

The smoke verifies:

- entry clarification or confirmation without launching the supervisor;
- confirmed ASI-style intake launching `rams_supervisor_runtime`;
- returned `caseId`, trace, evidence, safety, and `structuredReport`;
- authorized and denied ASI-style material references;
- report-store write;
- denied report lookup without ASI access context;
- authorized report lookup with matching ASI access context;
- redacted public-safe output.

By default, the smoke requires report persistence status `stored`, so the supervisor runtime should have `RAMS_REPORT_STORE_TABLE` configured. Use `--allow-unstored` only for transport debugging; it is not ADR 0016 acceptance coverage.

The smoke uses public fixture identity/material references only. Do not paste real ASI tokens, signed URLs, AWS credentials, account ids, private documents, or client material into command lines, environment files, issue comments, or logs.

Template IAM policy for the AgentVerse invoker after the new runtime ARN is known:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "Invoke3DRamsEntryRuntime",
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:InvokeAgentRuntime",
        "bedrock-agentcore:InvokeAgentRuntimeForUser"
      ],
      "Resource": [
        "<NEW_ASI_ONE_ENTRY_AGENT_RUNTIME_ARN>",
        "<NEW_ASI_ONE_ENTRY_AGENT_RUNTIME_ARN>/runtime-endpoint/DEFAULT"
      ]
    }
  ]
}
```

## Boundary

`asi_one_entry_agent` should stay focused on entry-agent UX:

- fast conversation;
- location/goal/material clarification;
- user confirmation before deep analysis;
- delivery summary after AgentCore supervisor output exists.

`rams_supervisor_runtime` remains the place for professional site-review orchestration, tool calls, report JSON, review-agent loops, evidence, trace, and visualization payloads.
