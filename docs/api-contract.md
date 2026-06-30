# API Contract

3D-RAMS exposes a hosted-product API for the chat-first pre-visit agent, plus the older `/api/run` compatibility route used by regression tests.

The frontend never calls Bedrock directly. Hosted model calls, uploads, session tracing, and safety checks happen server-side.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Confirms the backend is reachable. |
| `POST` | `/api/session/start` | Validates the shared access code and starts a tester session. |
| `POST` | `/api/upload-url` | Registers PDF/image evidence and returns an S3 presigned upload URL when hosted storage is configured. |
| `POST` | `/api/chat` | Runs the chat-first hosted agent workflow. |
| `POST` | `/api/runs` | V2 branch: creates a durable run and returns run status/checkpoints. |
| `GET` | `/api/runs/{runId}` | V2 branch: returns latest durable run status, partial/final UI state, and trace. |
| `POST` | `/api/runs/{runId}/cancel` | V2 branch: requests cancellation for a queued/running durable run. |
| `GET` | `/api/session/{sessionId}` | Returns session metadata and run summaries for refresh/debug. |
| `POST` | `/api/run` | Compatibility route for the older coordinate-to-briefing workflow. |
| `GET` | `/openapi.json` | Returns the generated OpenAPI schema from FastAPI. |

## Health Response

```json
{
  "status": "ok",
  "service": "3d-rams-demo1"
}
```

## Session Start

`POST /api/session/start`

| Field | Type | Notes |
| --- | --- | --- |
| `accessCode` | string or null | Shared tester code. If `APP_ACCESS_TOKEN_HASH` is configured, invalid or missing codes return `401`. |
| `testerAlias` | string or null | Optional tester alias for evaluation tracing. Do not put private data here. |

Response:

| Field | Meaning |
| --- | --- |
| `sessionId` | Opaque session id used by chat/upload calls. |
| `testerAlias` | Optional alias echoed back. |
| `accessLabel` | Backend-side access-code label, not the code itself. |
| `runtime` | Access and trace mode metadata. |

## Upload URL

`POST /api/upload-url`

| Field | Type | Notes |
| --- | --- | --- |
| `sessionId` | string | Session id from `/api/session/start`. |
| `filename` | string | Original filename for metadata only. |
| `contentType` | string | `application/pdf`, `image/png`, or `image/jpeg`. |
| `sizeBytes` | number or null | Must be no more than 10 MB when supplied. |

If `S3_UPLOAD_BUCKET` is configured, the response includes a short-lived presigned `uploadUrl`. In local mode it returns `local-mock://...` so the UI and tests can exercise the flow without S3.

## Chat Request

`POST /api/chat`

| Field | Type | Notes |
| --- | --- | --- |
| `sessionId` | string | Required tester session id. |
| `message` | string | Natural-language user request, for example a site visit briefing prompt. |
| `uploadedFileIds` | string array | Optional ids returned by `/api/upload-url`. |
| `useBedrock` | boolean | Requests server-side Bedrock. Environment config still controls whether Bedrock is used. |

Important response fields:

| Field | Meaning |
| --- | --- |
| `assistantMessage` | Natural-language agent response. |
| `needsClarification` | Whether the agent needs more site/activity information before running tools. |
| `clarifyingQuestions` | Questions for the user when needed. |
| `uiState` | Map, annotations, hazards, evidence, sources, briefing, safety, trace, and architecture data for the frontend panels. |
| `runtime` | Hosted mode, Bedrock/fallback mode, latency, and session trace mode. |
| `trace` | Ordered visible tool timeline. |
| `modelCalls` | Server-side model call metadata when Bedrock is actually used. |
| `safety` | Safety gate result. |

## Durable Run Request

`POST /api/runs`

The v2 branch uses this endpoint instead of a long synchronous chat request. It creates a `runId`, stores a checkpointed run record, and lets the frontend poll with `GET /api/runs/{runId}`.

| Field | Type | Notes |
| --- | --- | --- |
| `sessionId` | string | Required tester session id. |
| `message` | string | Natural-language user request. |
| `uploadedFileIds` | string array | Optional ids returned by `/api/upload-url`. |
| `useBedrock` | boolean | Requests server-side Bedrock where enabled by environment. |
| `autoStart` | boolean | Defaults to `true`. Set `false` to keep the run queued for cancellation/restart testing. |

Important run-status fields:

| Field | Meaning |
| --- | --- |
| `runId` | Opaque run id used for polling/reconnect. |
| `status` | `queued`, `running`, `waiting_for_clarification`, `waiting_for_approval`, `completed`, `failed`, or `cancelled`. |
| `currentStep` | Latest lifecycle step. |
| `modelCallsUsed` / `maxModelCalls` | Model-call budget accounting. |
| `tokenBudget` | Planner, reasoner, and compiler output-token caps. |
| `steps` | Checkpointed lifecycle/model/tool steps. |
| `toolResults` | Sanitized allowlisted tool outputs. |
| `partialUiState` | Latest UI panels available during execution. |
| `finalUiState` | Final UI panels when complete. |
| `safetyResult` | Final safety gate result when available. |
| `fallbackReason` | Reason the deterministic/default path was used. |
| `errorSummary` | Safe error summary for failed runs. |

The current branch implementation uses a local memory run store. Future AWS deployment should use a separate DynamoDB run table plus SQS worker Lambda after review.

## Compatibility Run Request

All fields are optional. Unknown fields are ignored so teammate test payloads can stay forgiving, but known fields are validated.

| Field | Type | Notes |
| --- | --- | --- |
| `siteName` | string | Optional site label for briefing and visualizer output. |
| `latitude` | number | Decimal degrees, `-90` to `90`. Defaults to fixture coordinate when omitted. |
| `longitude` | number | Decimal degrees, `-180` to `180`. Defaults to fixture coordinate when omitted. |
| `goal` | string | User goal for the pre-visit briefing. |
| `fixturePack` | string or null | Optional cached fixture pack id, for example `public-lambeth-thames`. |
| `fixture_pack` | string or null | Backward-compatible alias for `fixturePack`. |
| `includePlanningFixture` | boolean | Defaults to `true`. Set `false` to test missing planning/context behavior. |
| `simulateMapFailure` | boolean | Defaults to `false`. Set `true` to force the geospatial fallback path. |
| `useBedrock` | boolean | Defaults to `true`. Bedrock is still used only when backend environment settings enable it. |
| `agentMode` | string or null | Optional execution mode: `llm-planner`, `deterministic`, or `bedrock-briefing`. When omitted, `useBedrock=true` selects `llm-planner`; `useBedrock=false` selects `deterministic`. |
| `agent_mode` | string or null | Backward-compatible alias for `agentMode`. |
| `additionalRequest` | string | Optional user instruction. Unsafe RAMS/work-approval claims are blocked. |

Example no-AWS request:

```json
{
  "fixturePack": "public-lambeth-thames",
  "includePlanningFixture": true,
  "simulateMapFailure": false,
  "useBedrock": false
}
```

Invalid coordinates return a `422` validation response before the agent runs.

## Run Response

The response is an inspectable review pack. Important top-level fields include:

| Field | Meaning |
| --- | --- |
| `request` | Normalized request summary used by the agent. |
| `runtime` | Fixture mode, Bedrock mode, fallback reason, and live-call status. |
| `llmPlan` | Planner status, rationale, requested tool calls, allowlist, and fallback reason when `llm-planner` is used or requested. |
| `llmToolCalls` | Allowlisted local tool-call records accepted from the planner. Empty for deterministic or legacy briefing-only runs. |
| `modelCalls` | Model invocation records with phase, status, model id, region, latency, and call-budget metadata when a model call actually occurred. |
| `tokenUsage` | Aggregate token usage when the provider response exposes it; otherwise `null`. |
| `fallback` | Deterministic fallback status, trigger, and reason. |
| `location` | Resolved site label and coordinate. |
| `scene` | 3D scene configuration for the frontend viewer. |
| `hazards` | Candidate hazards extracted from cached/synthetic evidence. |
| `annotations` | 3D annotation data with confidence labels. |
| `briefing` | Human-review RAMS-style briefing summary, checks, and limitations. |
| `evidence` | Evidence register with source/status/context. |
| `trace` | Ordered tool timeline with statuses, source ids, evidence ids, and fallback reasons. |
| `safety` | Safety gate result and triggered rules. |
| `architecture` | Data for the in-app Architecture + Workflow visualizer. |

## Safety And Data Boundary

The API returns a pre-visit review pack for human review only. It does not produce certified RAMS, emergency guidance, work approval, legal advice, or a competent-person replacement.

Do not send real client data, private site records, access-controlled planning documents, secrets, API keys, or AWS credentials to the API or issue tracker.
