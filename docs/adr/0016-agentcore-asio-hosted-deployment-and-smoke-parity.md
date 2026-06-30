# ADR 0016: AgentCore And ASIO Hosted Deployment And Smoke Parity

## Status

Accepted direction from discussion.

## Context

`main` added a standalone hosted MVP deployment stack in `deploy/`:

- Lambda package build;
- Lambda/API Gateway deployment;
- S3 upload bucket;
- DynamoDB session table;
- CloudWatch log retention;
- Amplify zip deployment;
- hosted smoke test covering health, rejected access code, session start, upload registration, and chat.

That deployment stack validates Evan's standalone hosted web MVP. It does not validate the accepted ASI/ASI:ONE and AgentCore architecture:

- ADR 0012 makes ASI/ASI:ONE the real user entry and FieldBrief a development/debug-only simulation;
- ADR 0013 makes detailed report access ASI/ASI:ONE identity-bound;
- ADR 0014 makes materials ASI-owned while allowing AgentCore to retrieve authorized material content;
- ADR 0015 makes 3D-RAMS persistence case-correlated report/evidence storage, not web session storage.

`dev-chunteng` already uses a different cloud shape:

- AgentCore CDK app under `agentcore/`;
- `asi_one_entry_agent` and `rams_supervisor_runtime`;
- Harness subagents;
- `RAMS_REPORT_STORE_TABLE`;
- signed proxy for ASI/ASI-style frontend-to-AgentCore calls;
- source-connected Amplify deployment for the viewer/debug frontend;
- local `scripts/check-demo.sh` covering compile, tests, deterministic eval, frontend build, and local AgentCore/frontend smoke.

The remaining gap is not "port Evan's deploy scripts"; it is "prove the accepted AgentCore + ASIO topology works when hosted."

This ADR is parallel to ADR 0012, ADR 0013, ADR 0014, and ADR 0015. It decides deployment and smoke parity only.

## Decision

Do not keep Evan's `deploy/` PowerShell Lambda/API Gateway/S3/session-stack as an active deployment path.

Use the AgentCore CDK and ASI/ASI:ONE invocation path as the canonical hosted deployment model. Source-connected Amplify may host the report viewer and development/debug FieldBrief simulation, but production user entry remains ASI/ASI:ONE.

Add AgentCore + ASIO hosted smoke coverage. The smoke test should be capability-based and should not assert old FastAPI route names such as `/api/session/start`, `/api/upload-url`, or `/api/chat`.

The minimum hosted smoke should verify:

- ASI/ASI-style payload can invoke `asi_one_entry_agent`;
- entry agent can return clarification or confirmation;
- confirmed case can launch `rams_supervisor_runtime`;
- supervisor returns `caseId`, trace, evidence, safety, and structured report;
- authorized fixture or ASI-style material reference can be retrieved and ingested;
- denied, expired, or unauthorized material reference is rejected with a trace reason;
- report store writes a `caseId` report/evidence record;
- report lookup denies access without valid ASI/ASI:ONE identity context;
- report lookup returns the report with valid ASI/ASI:ONE identity/case binding;
- smoke output redacts ASI tokens, material access artifacts, signed URLs, raw private material content, AWS credentials, and account-sensitive details.

## Options Considered

1. Keep only `scripts/check-demo.sh`.
   - Pros: already validates local no-AWS orchestration.
   - Cons: does not prove hosted AgentCore wiring, ASI-style identity, material access, or report lookup.

2. Port Evan's PowerShell deployment and smoke scripts unchanged.
   - Pros: preserves exact standalone hosted MVP checks.
   - Cons: validates the wrong architecture and keeps the team split between two deployment models.

3. Add AgentCore + ASIO hosted smoke parity.
   - Pros: validates the chosen architecture and preserves Evan's product acceptance intent at the capability level.
   - Cons: requires hosted AgentCore resources and ASI-style identity/material test fixtures.

## Consequences

Positive:

- Demo readiness is measured against the actual AgentCore + ASIO topology.
- Evan's functional intent remains visible as capabilities, not obsolete route names.
- Local verification and hosted verification stay separate and explicit.
- The team avoids maintaining two active deployment systems.

Tradeoffs:

- Hosted smoke cannot run without configured AWS/AgentCore resources.
- ASI/ASI-style identity and material fixtures need a controlled test contract.
- Some of Evan's old deployment docs/scripts should be removed or clearly marked obsolete once replacement smoke exists.

## Acceptance Criteria

- `scripts/check-demo.sh` remains the standard no-AWS local verification stack.
- The active hosted deployment docs point to AgentCore CDK, ASI/ASI-style invocation, report viewer hosting, and hosted smoke.
- Evan's PowerShell `deploy/` stack is not documented as the active deployment path.
- Hosted smoke proves entry-agent to supervisor orchestration, not just static frontend deployment.
- Hosted smoke proves authorized material ingestion and denied material access.
- Hosted smoke proves identity-bound report lookup.
- Hosted smoke output redacts secrets, identity artifacts, signed URLs, raw material content, and private payloads.
- Public docs continue to disclose real, mocked, fallback, and future AWS components.

## Discussion Questions

- Should hosted smoke be one script with feature flags, or separate scripts for AgentCore invocation, material ingestion, and report lookup?
- What ASI/ASI-style test identity and material fixtures should be safe to include in public demo code?
- Once AgentCore + ASIO hosted smoke exists, should old `deploy/` files be deleted or moved to an archival note?
