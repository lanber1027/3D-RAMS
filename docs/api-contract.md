# API Contract

3D-RAMS exposes a hosted-product API for the chat-first pre-visit agent, plus the older `/api/run` compatibility route used by regression tests.

The frontend never calls Bedrock directly. Hosted model calls, uploads, session tracing, and safety checks happen server-side.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Confirms the backend is reachable. |
| `POST` | `/api/session/start` | Validates the shared access code and starts a tester session. |
| `POST` | `/api/upload-url` | Registers PDF/image evidence and returns an S3 presigned upload URL when hosted storage is configured. |
| `POST` | `/api/conversation/message` | Primary frontend route. Applies bounded session memory and guarded routing, then either answers from context or starts a durable run. |
| `POST` | `/api/chat` | Compatibility chat route retained for hosted smoke/regression checks. |
| `POST` | `/api/runs` | V3.2 branch: creates a durable run and returns run status/checkpoints. |
| `GET` | `/api/runs/{runId}` | V3.2 branch: returns latest durable run status, partial/final UI state, location-resolution state, and trace. |
| `POST` | `/api/runs/{runId}/confirm-location` | V3.2 branch: confirms a source-labelled location candidate and continues the review workflow. |
| `POST` | `/api/runs/{runId}/cancel` | V3.2 branch: requests cancellation for a queued/running durable run. |
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

## Conversation Message

`POST /api/conversation/message`

This is the primary frontend route for the AgentCore-ready rebuild slice. It keeps Bedrock and tools server-side, applies deterministic guards first, uses bounded session memory for follow-up/status messages, and starts the durable run workflow only when the message is a new site task.

| Field | Type | Notes |
| --- | --- | --- |
| `sessionId` | string | Required tester session id. |
| `message` | string | Natural-language user message. Follow-ups such as `What do you mean?` should be resolved against the current session instead of becoming a fake site name. |
| `uploadedFileIds` | string array | Optional ids returned by `/api/upload-url`. |
| `useBedrock` | boolean | Requests server-side Bedrock where enabled by environment. |

Important response fields:

| Field | Meaning |
| --- | --- |
| `action` | `started_run` or `answered_from_memory`. |
| `route` | Router decision, such as `new_or_guarded_run`, `follow_up`, or `status`. |
| `assistantMessage` | Natural-language response. |
| `run` | Durable run status object when a new run was created; absent when the message was answered from memory. |
| `runtime` | AgentCore-ready runtime contract, adapter status, guard policy, memory mode, and Bedrock/AWS metadata. |

The current implementation stores bounded recent turns and structured working memory in the session record. It must not store raw access codes, credentials, uploaded file contents, or private client material.

## Compatibility Chat Request

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
| `needsLocationConfirmation` | Whether a named-site prompt has candidate locations that must be confirmed before review tools run. |
| `locationCandidates` | Source-labelled candidate locations when the fixture-first resolver finds them. |
| `confirmedLocation` | Confirmed candidate location, otherwise `null`. |
| `nextStage` | `confirm_location`, `provide_location_detail`, or the next workflow stage. |
| `clarifyingQuestions` | Questions for the user when needed. |
| `uiState` | Map, annotations, hazards, evidence, sources, briefing, safety, trace, architecture data, and `reviewMode` for the frontend panels. |
| `runtime` | Hosted mode, Bedrock/fallback mode, latency, and session trace mode. |
| `trace` | Ordered visible tool timeline. |
| `modelCalls` | Server-side model call metadata when Bedrock is actually used. |
| `safety` | Safety gate result. |

## Durable Run Request

`POST /api/runs`

The V3.2 branch uses this endpoint instead of a long synchronous chat request. It creates a `runId`, stores a checkpointed run record, and lets the frontend poll with `GET /api/runs/{runId}`. A structured intent parser extracts site name, coordinate/postcode clues, nearest-town clues, site/activity type, visit date, and unsafe certification/approval intent before review tools start.

Named-site, postcode, and coordinate prompts run a location-resolution stage before any site-specific map/evidence/risk/briefing tools start, except for the known cached Lambeth fixture path. If no source-labelled candidate is available, the API may return `uiState.reviewMode = "provisional checklist pending location"` and hazards with `dataMode = "provisional-from-user-description"`. These are non-site-specific prompts for human review, not evidence-backed findings.

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
| `status` | `queued`, `running`, `waiting_for_clarification`, `waiting_for_location_confirmation`, `waiting_for_approval`, `completed`, `failed`, or `cancelled`. |
| `currentStep` | Latest lifecycle step. |
| `modelCallsUsed` / `maxModelCalls` | Model-call budget accounting. |
| `tokenBudget` | Planner, reasoner, and compiler output-token caps. |
| `steps` | Checkpointed lifecycle/model/tool steps. |
| `toolResults` | Sanitized allowlisted tool outputs. |
| `partialUiState` | Latest UI panels available during execution. |
| `locationResolution` | Site name, candidate list, resolver mode, confirmation state, and next stage when the run is waiting for location confirmation. |
| `finalUiState` | Final UI panels when complete. |
| `safetyResult` | Final safety gate result when available. |
| `fallbackReason` | Reason the deterministic/default path was used. |
| `errorSummary` | Safe error summary for failed runs. |

Hazard and location objects may include `dataMode` values such as `cached-public-fixture`, `synthetic-fixture`, `source-labelled-location`, `source-labelled-coordinate`, or `provisional-from-user-description`. The UI should display these labels so testers can distinguish source evidence from prompt-derived risk prompts.

The current branch implementation uses a local memory run store. Future AWS deployment should use a separate DynamoDB run table plus SQS worker Lambda after review.

## Location Confirmation

`POST /api/runs/{runId}/confirm-location`

Use this only when a run is in `waiting_for_location_confirmation` and returned one or more `locationCandidates`.

Request:

```json
{
  "candidateId": "candidate-greenacre-solar-demo"
}
```

Response:

- returns the updated run record;
- moves the run into the review workflow;
- no review pack, risk cards, or evidence are produced before this confirmation;
- invalid candidate ids return a safe `400` error.

The current MVP resolver is fixture-first plus server-side postcode/outcode lookup through Postcodes.io and user-supplied latitude/longitude candidates. It may return a clearly labelled synthetic candidate for demo paths, a source-labelled postcode/outcode candidate, or a user-supplied coordinate candidate with deterministic distance/bearing context. It must not fabricate real-world coordinates from the LLM. Geoapify code exists behind `ENABLE_GEOAPIFY_GEOCODING`, but the live provider spike was rejected for current teammate testing because candidate relevance was weak, so the default hosted product keeps Geoapify disabled. All provider or coordinate candidates still require user confirmation before review tools run. If no reliable cached/public/postcode/coordinate candidate exists, the run asks the user for postcode, coordinate, OS grid reference, nearest road/town, local authority, or public evidence.

Candidate objects may include `locationContext`:

| Field | Meaning |
| --- | --- |
| `submittedLocation` | Original postcode, outcode, or latitude/longitude supplied by the user. |
| `coordinate` | Candidate WGS84 latitude/longitude. |
| `nearestTown`, `ward`, `parish`, `district`, `county`, `region` | Source-labelled administrative context where available. |
| `nearestAnchor` / `relativeLocation` | Deterministic distance and bearing from a known UK city, for example `about 50 km west of Manchester`. |

Public Nominatim-style broad geocoding is deliberately deferred because the MVP is not a generic geocoding service and would need compliant caching, attribution, rate limiting, and usage controls before use.

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
