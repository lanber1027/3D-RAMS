# AgentCore Invocation Contract

3D-RAMS exposes the local demo runtime through the AgentCore dev server. The frontend calls the Vite proxy path `/agentcore/invocations`, which forwards to AgentCore Runtime `/invocations`.

The runtime is local-first. It does not require AWS credentials, Google keys, live planning portals, hosted infrastructure, real site data, or private documents.

AgentVerse and ASI:ONE should not call AgentCore directly in the current architecture. The intended cross-platform path is documented in [agentverse-agentcore-adapter-contract.md](agentverse-agentcore-adapter-contract.md): AgentVerse entry agent confirms intake, the adapter validates and signs/invokes AgentCore, then delivery returns to the entry agent.

When `RAMS_REPORT_STORE_TABLE` is set in the supervisor runtime environment, the runtime writes a DynamoDB report-store item keyed by `caseId`. When it is unset, persistence is skipped and the no-AWS local demo behavior is unchanged.

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
| `caseId` | string | Optional entry-agent generated correlation id. Echoed in output, run, and structured report when provided. |
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
| `upstream` | object | Optional upstream metadata from AgentVerse, ASI:ONE, or another entry agent. |

## Invocation Response

The response keeps the AgentCore output envelope:

```json
{
  "output": {
    "caseId": "case_demo_fixture_001",
    "reportStatus": "review_required",
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
| `status` | `blocked`, `review_required`, or future `review_passed`. |
| `intake` | Confirmed user intake and optional upstream AgentVerse metadata. |
| `site` | Resolved site label, coordinate, authority, confidence, and source ids. |
| `executiveSummary` | User-facing headline, summary, priority checks, site-visit checks, limitations, and safety message. |
| `sections` | Stable report sections with reference ids for sources, evidence, and trace steps. |
| `findings` | Candidate hazards/findings with confidence, notes, evidence ids, source ids, and annotation linkage. |
| `visualization` | Frontend-ready scene config and map/3D annotations. |
| `evidenceRegister` | Source register and evidence register used by findings and sections. |
| `reasoning` | Inspectable supervisor evidence-use decisions, report-fit status, gaps, conflicts, and review questions. |
| `reviewGate` | Current safety/review state. It is `pending_independent_review` until the independent review agent exists. |
| `dataQuality` | Completeness flags, warnings, and gaps surfaced by fixture fallback, disabled data, or limitations. |
| `externalSignals` | Placeholder for future Tavily/open-web signals. Current prototype marks this as `not_configured`. |
| `trace` | Ordered tool timeline for debugging and evidence inspection. |

Important `output.persistence` fields:

| Field | Meaning |
| --- | --- |
| `mode` | `disabled` when no table is configured, or `dynamodb` when the report store path was attempted. |
| `status` | `skipped`, `stored`, or `error`. Store errors are surfaced here without hiding the report payload. |
| `tableName` | DynamoDB table name when configured. |
| `caseId` | Partition key used for the stored item. |

The DynamoDB item uses `caseId` as the partition key and stores report metadata plus the structured report payload. It is still a human-review demo report; persistence does not imply certified RAMS, legal approval, work approval, or independent review completion.

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
