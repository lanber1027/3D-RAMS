# API Contract

3D-RAMS exposes a small local API for the demo frontend, runtime smoke tests, and teammate inspection.

The API is intentionally local-first. It does not require AWS credentials, Google keys, live planning portals, hosted infrastructure, real site data, or private documents.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Confirms the backend is reachable. |
| `POST` | `/api/run` | Runs the coordinate-to-briefing agent workflow. |
| `GET` | `/openapi.json` | Returns the generated OpenAPI schema from FastAPI. |

## Health Response

```json
{
  "status": "ok",
  "service": "3d-rams-demo1"
}
```

## Run Request

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
