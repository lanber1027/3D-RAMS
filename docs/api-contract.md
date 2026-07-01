# AgentCore Invocation Contract

3D-RAMS exposes the local demo runtime through the AgentCore dev server. The frontend calls the Vite proxy path `/agentcore/invocations`, which forwards to AgentCore Runtime `/invocations`.

The runtime is local-first. It does not require AWS credentials, Google keys, live planning portals, hosted infrastructure, real site data, or private documents.

## Scope And Product Boundary

This contract describes the AgentCore invocation surface, not a standalone product backend. `/ping` and `/invocations` are valid for local AgentCore development, tests, smoke checks, and runtime-to-runtime invocation.

Hosted product entry should go through ASI/ASI:ONE or the development/debug FieldBrief entry simulation, then through the signed entry proxy configured by `VITE_CLOUD_ENTRY_PROXY_URL`. The proxy is transport-level: it signs and forwards entry-turn or report-lookup payloads to `asi_one_entry_agent`; it must not implement product orchestration, intake semantics, report generation, uploads, sessions, or old FastAPI-compatible product routes.

The codebase intentionally does not expose `/api/chat`, `/api/run`, `/api/session/start`, or `/api/upload-url` as canonical contracts.

AgentVerse and ASI:ONE should not call AgentCore directly in the current architecture. The intended cross-platform path is documented in [agentverse-agentcore-adapter-contract.md](agentverse-agentcore-adapter-contract.md): AgentVerse entry agent confirms intake, the adapter validates and signs/invokes AgentCore, then delivery returns to the entry agent.

When `RAMS_REPORT_STORE_TABLE` is set in the supervisor runtime environment, the runtime writes a DynamoDB report-store item keyed by `caseId`. When it is unset, persistence is skipped and the no-AWS local demo behavior is unchanged. The stored item is a case-correlated report/evidence record, not a web session record.

`caseId` is a workflow correlation id, not a bearer secret. Stored report lookup requires an ASI/ASI:ONE identity or authorized session context. The local FieldBrief path may send an explicit `dev_local` access context for no-AWS debugging; that bypass is not production authorization.

Hosted report lookup is ASI/ASI:ONE identity-bound. `caseId` is a correlation id, not a bearer secret. Stored report items launched with a `reportAccess` context require the same non-secret binding before `run` or `structuredReport` is returned.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/ping` | Confirms the AgentCore runtime is reachable. |
| `POST` | `/invocations` | Runs the coordinate-to-briefing agent workflow. |

## Ping Response

The AgentCore dev server returns a health object that includes:

```json
{
  "status": "Healthy"
}
```

## Invocation Request

The request body must use the AgentCore envelope:

```json
{
  "input": {
    "caseId": "case_demo_fixture_001",
    "fixturePack": "public-lambeth-thames",
    "includePlanningFixture": true,
    "simulateMapFailure": false,
    "useBedrock": false
  }
}
```

Known `input` fields:

| Field | Type | Notes |
| --- | --- | --- |
| `caseId` | string | Optional entry-agent generated correlation id. If omitted in direct local/debug calls, the supervisor creates a deterministic `case_<hash>` id from the normalized request. |
| `siteName` | string | Optional site label for briefing and visualizer output. |
| `latitude` | number | Decimal degrees, `-90` to `90`. Defaults to fixture coordinate when omitted. |
| `longitude` | number | Decimal degrees, `-180` to `180`. Defaults to fixture coordinate when omitted. |
| `goal` | string | User goal for the pre-visit briefing. |
| `fixturePack` | string or null | Optional cached fixture pack id, for example `public-lambeth-thames`. |
| `fixture_pack` | string or null | Backward-compatible alias for `fixturePack`. |
| `includePlanningFixture` | boolean | Defaults to `true`. Set `false` to test missing planning/context behavior. |
| `simulateMapFailure` | boolean | Defaults to `false`. Set `true` to force the geospatial fallback path. |
| `useBedrock` | boolean | Defaults to `true`. Bedrock is used only when runtime environment settings enable it. |
| `additionalRequest` | string | Optional user instruction. Unsafe RAMS/work-approval claims are blocked. |
| `materials` | array | Optional ASI/ASI:ONE-owned material references or explicit local fixture/mock references. Only bounded metadata is accepted: id, source system, type, label, summary, case id, size, source/evidence ids, and access mode/expiry/status/session plus a safe retrieval marker for URL or API-handle access. Raw files, raw material content, tokens, signed URLs, API handles, retrieval URLs, and credentials are not persisted or returned. |
| `upstream` | object | Optional upstream metadata from AgentVerse, ASI:ONE, or another entry agent. |
| `reportAccess` | object | Optional ASI/ASI:ONE identity/session binding metadata. `accessContext` is accepted as a compatibility alias, but `reportAccess` is the canonical field. Raw tokens must not be sent or stored. |

Material retrieval is bounded to 10 MiB and supported content types are PDF, JPEG, PNG, Markdown, and plain text. A short-lived `access.retrievalUrl` may be used directly. For `access.apiHandle`, configure `RAMS_ASI_MATERIAL_API_BASE_URL` and `RAMS_ASI_MATERIAL_API_BEARER_TOKEN`; the supervisor performs `GET {baseUrl}/{urlencoded apiHandle}` with `Authorization: Bearer ...` plus case/session headers. If those settings are absent, the material is skipped as `retrieval_not_configured`.

## Report Lookup Request

Stored reports can be loaded through the same AgentCore invocation path:

```json
{
  "input": {
    "operation": "getReport",
    "caseId": "case_demo_fixture_001",
    "reportAccess": {
      "schemaVersion": "3d-rams.report-access.v1",
      "mode": "asi_session",
      "caseId": "case_demo_fixture_001",
      "sessionId": "opaque-asi-session-reference",
      "authorizedCaseIds": ["case_demo_fixture_001"],
      "expiresAt": "<short-lived-iso-expiry>"
    },
    "upstream": {
      "source": "AGENTVERSE",
      "caseId": "case_demo_fixture_001",
      "conversationId": "agentverse-session-id",
      "entryAgentId": "@3d-rams"
    }
  }
}
```

Frontend cloud mode sends the same lookup through the entry proxy:

```json
{
  "frontendInvoke": true,
  "operation": "getReport",
  "caseId": "case_demo_fixture_001",
  "conversationId": "opaque-frontend-session-reference",
  "caller": "frontend",
  "reportAccess": {
    "schemaVersion": "3d-rams.report-access.v1",
    "mode": "asi_session",
    "caseId": "case_demo_fixture_001",
    "sessionId": "opaque-frontend-session-reference",
    "authorizedCaseIds": ["case_demo_fixture_001"]
  }
}
```

`reportAccess` is the current placeholder contract for the ASI/ASI:ONE-bound access assertion. Supported modes are `asi_identity`, `asi_session`, and explicit `dev_local` for local debugging. The runtime stores only hashed identity/session bindings in the report-store item, not raw ASI identity tokens, access assertions, signed URLs, or credentials.

The supervisor returns `output.run` and `output.structuredReport` only when DynamoDB contains the case and the access context matches the stored case binding. If authorization fails, the response sets `output.reportStatus` to `access_denied`, includes a machine-readable reason in `output.reportAccess.reason`, and omits `run` and `structuredReport`. If `RAMS_REPORT_STORE_TABLE` is unset or the item is missing after authorization, the response keeps the envelope shape but sets `output.reportStatus` to `not_found` and reports the reason in `output.persistence`.

The React frontend uses this contract for `/case/{caseId}` routes. A direct page load on that route performs a lookup instead of starting a fresh supervisor run.

In hosted mode, `/case/{caseId}` lookup still goes through the signed entry proxy and `asi_one_entry_agent`. `caseId` is a correlation id, not a bearer secret; production report access remains ASI/ASI:ONE identity-bound per ADR 0013.

## Invocation Response

The response keeps the AgentCore output envelope:

```json
{
  "output": {
    "caseId": "case_demo_fixture_001",
    "reportStatus": "passed_with_caveats",
    "workflowMode": "cached_public_fixture",
    "persistence": {
      "mode": "dynamodb",
      "status": "stored",
      "tableName": "rams-report-store",
      "caseId": "case_demo_fixture_001"
    },
    "structuredReport": {},
    "run": {}
  }
}
```

`output.structuredReport` is the stable supervisor report contract for AgentVerse delivery, review-agent validation, and frontend visualization. A JSON template is maintained at [structured-report-template.json](structured-report-template.json). The Python source of truth is the Pydantic `StructuredReport` schema in `app/rams_supervisor_runtime/supervisor_core/schemas.py`.

Important `output.structuredReport` fields:

| Field | Meaning |
| --- | --- |
| `schemaVersion` | Structural report schema version. |
| `caseId` | Entry-agent generated correlation id, when present. It becomes the DynamoDB partition key only when `RAMS_REPORT_STORE_TABLE` is configured. |
| `status` | `passed`, `passed_with_caveats`, `review_required`, or `blocked`. |
| `intake` | Confirmed user intake and optional upstream AgentVerse metadata. |
| `materialIngestion` | Safe material-ingestion status, accepted/skipped references, citations, and evidence/source ids. |
| `site` | Resolved site label, coordinate, authority, confidence, and source ids. |
| `executiveSummary` | User-facing headline, summary, priority checks, site-visit checks, limitations, and safety message. |
| `sections` | Stable report sections with reference ids for sources, evidence, and trace steps. |
| `findings` | Candidate hazards/findings with confidence, notes, evidence ids, source ids, and annotation linkage. |
| `visualization` | Frontend-ready scene config and map/3D annotations. |
| `evidenceRegister` | Source register and evidence register used by findings and sections. |
| `reasoning` | Inspectable supervisor evidence-use decisions, report-fit status, gaps, conflicts, and review questions. |
| `reviewGate` | Independent review output with decision, status, issues, caveats, and bounded revision count. |
| `dataQuality` | Completeness flags, warnings, and gaps surfaced by fixture fallback, disabled data, or limitations. |
| `externalSignals` | Placeholder for future Tavily/open-web signals. Current prototype marks this as `not_configured`. |
| `trace` | Ordered tool timeline for debugging and evidence inspection. |

The trace is case-correlated. Each supervisor trace step includes `caseId`, and the step `output` includes the same id where the output is an object. This is the field to map into future CloudWatch search and trace correlation.

Important `output.persistence` fields:

| Field | Meaning |
| --- | --- |
| `mode` | `disabled` when no table is configured, or `dynamodb` when the report store path was attempted. |
| `status` | `skipped`, `stored`, `loaded`, `access_denied`, `not_found`, or `error`. Store errors are surfaced here without hiding a newly generated report payload. |
| `tableName` | DynamoDB table name when configured. |
| `caseId` | Partition key used for the stored item. |

The DynamoDB item uses `caseId` as the partition key and stores:

- `schemaVersion: 3d-rams.report-store.v1`;
- report metadata and workflow status;
- `reportAccessBinding` with hashed subject/session references and optional expiry metadata;
- `authorizationBinding` with non-secret ASI/ASI:ONE session or pre-hashed subject/organization references for audit/debug summary;
- bounded `evidenceSummary`, `materialEvidenceSummary`, `citationMetadata`, and `traceSummary`;
- the generated `structuredReport` and `run` payloads for detailed lookup.

The record deliberately excludes raw ASI identity tokens, raw private material content, signed material URLs, shared access codes, AWS credentials, AgentCore secrets, and certified/approval-to-work claims. `caseId` is a correlation key, not a bearer token.

Retention is explicit metadata on the item. `RAMS_REPORT_STORE_TTL_DAYS` can be used to publish an intended TTL value in the record; DynamoDB TTL/index wiring remains an infrastructure decision. Until that infrastructure exists, stored records must be treated as human-review demo evidence/report records and not production audit records.

Important `output.run` fields:

| Field | Meaning |
| --- | --- |
| `caseId` | Entry-agent generated correlation id echoed from request/upstream metadata. |
| `upstream` | Optional entry-agent/session metadata passed through the adapter. |
| `request` | Normalized request summary used by the agent. |
| `runtime` | Fixture mode, Bedrock mode, fallback reason, and live-call status. |
| `location` | Resolved site label and coordinate. |
| `scene` | 3D scene configuration for the frontend viewer. |
| `hazards` | Candidate hazards extracted from cached/synthetic evidence. |
| `annotations` | 3D annotation data with confidence labels. |
| `briefing` | Human-review RAMS-style briefing summary, checks, and limitations. |
| `evidence` | Evidence register with source/status/context. |
| `reasoning` | Mandatory supervisor reasoning artifact created before structured report assembly. |
| `trace` | Ordered tool timeline with statuses, source ids, evidence ids, and fallback reasons. |
| `safety` | Safety gate result and triggered rules. |
| `architecture` | Data for the in-app Architecture + Workflow visualizer. |

## Safety And Data Boundary

The runtime returns a pre-visit review pack for human review only. It does not produce certified RAMS, emergency guidance, work approval, legal advice, or a competent-person replacement.

Do not send real client data, private site records, access-controlled planning documents, secrets, API keys, or AWS credentials to the runtime or issue tracker.
