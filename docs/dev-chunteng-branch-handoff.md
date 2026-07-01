# dev-chunteng Branch Handoff

This document is the merge handoff for the AgentCore architecture branch. It is intended to be read before merging product-prototype work into this branch or before asking another Codex session to reconcile this branch with another line of work.

## Branch Purpose

`dev-chunteng` is the AgentCore-centered architecture branch for 3D-RAMS.

Its purpose is to move the product demo away from a standalone FastAPI backend and into the accepted ASI/ASI:ONE + AgentCore topology:

```text
ASI / AgentVerse entry
  -> asi_one_entry_agent
  -> rams_supervisor_runtime
  -> Harness subagents / shared tool packages
  -> run + structuredReport + delivery
  -> caseId-correlated report persistence
  -> frontend visualization and report lookup
```

Evan can continue product prototype work independently. This branch should absorb stable product capabilities into the AgentCore structure, but it should not preserve prototype-only backend route shapes as canonical contracts.

## What This Branch Has Done

- Replaced the old standalone FastAPI backend direction with an AgentCore-centered project structure.
- Added `app/asi_one_entry_agent` as the ASI/AgentVerse-style entry runtime.
- Added `app/rams_supervisor_runtime` as the supervisor runtime for orchestration, structured report assembly, evidence/trace output, review boundaries, and persistence.
- Split reusable tool logic into AgentCore-oriented packages and Harness/subagent runtime boundaries.
- Added Harness/subagent structure for geospatial, planning, hazard, annotation, briefing, and review roles.
- Added a supervisor planning layer. The planner may be deterministic/mock-backed, but it should not be optional or bypassed.
- Added report payloads shaped around `run`, `structuredReport`, `delivery`, and `caseId`.
- Added case-correlated report lookup through the entry/proxy path.
- Added AgentVerse/ASI-facing adapter and signed proxy code under `agentverse/`.
- Added cloud frontend wiring through `VITE_CLOUD_ENTRY_PROXY_URL`.
- Added a frontend Bedrock toggle; the explicit debug FieldBrief path now defaults to `useBedrock: true`, with the toggle still available for no-Bedrock smoke runs.
- Added AgentCore/ASI architecture ADRs through ADR 0016.
- Fixed the hosted proxy CORS issue caused by duplicate CORS headers between Lambda Function URL config and Lambda response headers.
- Verified a hosted no-Bedrock path can reach the entry runtime, launch the supervisor runtime, invoke Harness subagents, store a report, and render a case page.

## Important Current Status

The current cloud demo is suitable for proving workflow shape, not final report quality.

Known current behavior:

- The frontend FieldBrief ASI simulation is a development/debug substitute for ASI/ASI:ONE entry, not the production user entry.
- The default hosted demo path should keep `Use Bedrock` off unless explicitly testing Bedrock behavior.
- The supervisor can run in `agentcore-harness` mode and return a visualization-ready payload.
- Fixture-backed and fallback-normalized data is still acceptable for smoke tests.
- Some Harness outputs are not yet normalized into ideal first-class report fields.
- The Risk Review panel currently reads `run.hazards`. If a Harness run returns usable risk information only through `structuredReport.findings`, evidence, annotations, or normalized briefing output, the UI can show the empty risk-card fallback even though the workflow ran. This should be treated as a mapping/normalization gap, not proof that orchestration failed.

## What Is Not Done Yet

- Full LLM-first entry-agent conversation quality is not complete.
- AgentVerse normal chat should become more polished and should not expose raw JSON in ordinary user-facing replies.
- ASI/ASI:ONE identity-bound report access now has an initial `reportAccess` contract, hashed store binding, and denied/expired/wrong-user lookup coverage. Real ASI-issued identity artifacts still need integration.
- Material ingestion is still mostly metadata/reference oriented. Real authorized material retrieval and extraction still need implementation.
- Report persistence works for report lookup and stores report-access binding metadata. Evidence summaries, material citations, and longer-term authorization records still need to be expanded.
- Harness subagent outputs need stricter schemas so the supervisor does not need fallback normalization for common fields.
- Risk Review UI needs a robust mapping from `run.hazards`, `structuredReport.findings`, annotations, and evidence-backed candidate findings.
- Bedrock-enabled paths still need hardening. The stable demo path should remain no-Bedrock until Bedrock smoke is reliable.
- Hosted smoke should be formalized as a script that validates the AgentCore + ASI topology rather than old FastAPI route names.
- Tavily/open-web subagent integration remains a planned extension, not a completed default path.

## Core Boundaries

The canonical product architecture is:

- ASI/AgentVerse is the real user-facing entry.
- The frontend FieldBrief ASI simulation is a development/debug ASI entry surface.
- `asi_one_entry_agent` owns intake, clarification, user confirmation, supervisor launch, delivery summary, and report lookup coordination.
- `rams_supervisor_runtime` owns planning, orchestration, Harness/subagent dispatch, evidence/trace assembly, structured report generation, review/safety boundaries, and persistence.
- Harness subagents own role-specific analysis steps and should expose schema-stable outputs to the supervisor.
- Shared tools should live outside a single supervisor-only runtime when they are intended for multiple subagents or Harnesses.
- The signed proxy is transport-level only. It signs and forwards AgentCore runtime invocations; it must not become a product orchestration backend.

## Hard Rules

- Do not restore the old `backend/` FastAPI service as the product runtime.
- Do not make `/api/chat`, `/api/run`, `/api/session/start`, or `/api/upload-url` canonical contracts.
- Do not bypass `asi_one_entry_agent` for intake or `rams_supervisor_runtime` for report generation.
- Do not turn the frontend FieldBrief ASI simulation into a second production entry path.
- Do not treat `caseId` as a secret access token. It is a correlation id; report access must eventually be identity/case-bound.
- Do not let 3D-RAMS own raw product upload storage as the long-term material model. ASI/ASI:ONE should own materials; 3D-RAMS should receive authorized material references and retrieve/extract only within that authorization boundary.
- Do not commit AWS credentials, runtime ARNs, access keys, AgentVerse secrets, private client material, or private planning notes.
- Do not claim certified RAMS, emergency guidance, legal approval, or approval-to-work.
- Do not remove the no-AWS local verification path. Demo1 must remain runnable without cloud credentials.
- Do not make the planner optional. It may be deterministic/mock-backed during early smoke, but the supervisor path should still go through planning.

## Evan Prototype Coordination

Evan should keep moving quickly on product prototype, UX, feature validation, and demo polish. Prototype work does not need to wait for AgentCore migration.

When Evan adds or changes a product capability, the most useful handoff is:

- user action or workflow supported;
- intended request payload shape;
- intended response payload shape;
- frontend state and copy that should be preserved;
- data that should land in `run`, `structuredReport`, `delivery`, persistence, or evidence/material records;
- whether the feature is fixture-only, fallback, live, or cloud-required.

The AgentCore branch should migrate product intent and stable UX behavior, not necessarily Evan's temporary backend route shape.

Recommended collaboration loop:

1. Evan validates UX/capability quickly in the prototype line.
2. Evan documents intended payload, result, and state model.
3. Chunteng maps that behavior into the AgentCore entry/supervisor/report contracts.
4. Once the AgentCore equivalent exists, old prototype-only backend assumptions can be marked obsolete or removed.

## Merge Guidance

When merging from another branch into `dev-chunteng`:

- preserve AgentCore directory structure and ownership boundaries;
- migrate useful frontend/report UI improvements into the current frontend without reintroducing FastAPI dependency;
- map chat/session/upload concepts to ASI/AgentVerse entry contracts and material-reference contracts;
- keep route-level compatibility only when explicitly marked as a local/debug adapter;
- prefer capability-level smoke checks over old endpoint-name smoke checks;
- update ADRs or handoff docs when architecture decisions change.

## Verification Expectations

Before sharing, demoing, or merging:

- run `bash scripts/check-demo.sh` when practical;
- run focused tests for changed runtime packages;
- run frontend build when UI changes;
- smoke the hosted proxy and frontend when cloud wiring changes;
- disclose which components are real, mocked, fixture-backed, fallback-normalized, or future work;
- confirm no secrets or private material were added.
