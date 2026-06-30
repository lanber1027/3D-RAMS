# ADR 0014: ASIO-Owned Material Ingestion

## Status

Accepted direction from discussion.

## Context

`main` added hosted evidence upload registration:

- allowed content types: PDF, PNG, JPEG;
- 10 MB size limit;
- local mock upload metadata when S3 is not configured;
- S3 presigned PUT URL when `S3_UPLOAD_BUCKET` is configured;
- upload metadata attached to the chat run.

That model assumes 3D-RAMS is a standalone hosted web app with its own upload surface and storage bucket.

The accepted product direction is different:

- ASI/ASI:ONE is the real user entry point;
- FieldBrief is only a development/debug simulation of that entry;
- report access is ASI/ASI:ONE identity-bound;
- lower-level orchestration uses AgentCore invocation contracts, not FastAPI product routes.

However, the agent must be able to read relevant user-provided materials. Metadata-only evidence is not enough for a detailed analysis or a useful generated report. The boundary should therefore be: ASI/ASI:ONE owns upload, storage, user identity, and material authorization; 3D-RAMS AgentCore receives authorized material references and retrieves/extracts content under the confirmed case context.

This ADR is parallel to ADR 0012, ADR 0013, ADR 0015, and ADR 0016. It decides material ingestion only. It does not decide report-view identity, session persistence, or deployment mechanics.

## Decision

Do not migrate Evan's `/api/upload-url` or `S3_UPLOAD_BUCKET` upload service as a 3D-RAMS product capability.

Use ASI/ASI:ONE-owned material storage and authorization. The ASI/ASI:ONE entry flow should pass material references into `asi_one_entry_agent` as part of the confirmed case context. Those references may point to ASI-managed files, documents, images, or extracted text sources, but they must not be public naked URLs.

3D-RAMS AgentCore may retrieve and extract material content only when the reference is authorized for the current ASI/ASI:ONE identity/session/case. The material retrieval path must be bounded, auditable, and explicit in trace output.

The entry-agent `materials` contract should support fields such as:

```json
{
  "materialId": "asio_material_123",
  "sourceSystem": "asio",
  "type": "application/pdf",
  "label": "Site access plan",
  "summary": "Uploaded by the ASI user for this case.",
  "caseId": "case_abc123",
  "access": {
    "mode": "asio_authorized_reference",
    "expiresAt": "2026-06-30T18:00:00Z"
  }
}
```

The supervisor should add a material ingestion phase before or alongside planning/briefing subagents. That phase should:

- validate that each material belongs to the current case or authorized ASI session;
- fetch only allowed content types and bounded file sizes;
- extract safe text or structured observations from supported material types;
- preserve source identifiers for citations and trace mapping;
- mark unsupported, expired, or denied materials as skipped with a reason;
- avoid storing raw private material content in public traces, public docs, or logs.

FieldBrief development/debug mode may use fixture materials or mock material references. It must not define the production upload or authorization model.

## Options Considered

1. Keep frontend-only mock material metadata.
   - Pros: simplest local flow.
   - Cons: not enough for detailed analysis or realistic report generation.

2. Restore Evan's 3D-RAMS-owned S3 presign upload service.
   - Pros: gives the demo direct upload capability.
   - Cons: makes 3D-RAMS a parallel hosted product with its own identity/storage boundary.

3. Use ASI/ASI:ONE-owned material references with AgentCore retrieval.
   - Pros: keeps upload and permissions with ASI while allowing the agent to analyze real material content.
   - Cons: requires a clear authorized retrieval contract and material extraction guardrails.

## Consequences

Positive:

- Reports can use real user-provided material content.
- Material permissions remain tied to ASI/ASI:ONE identity and case context.
- `caseId` continues to correlate entry, materials, trace, and report output.
- 3D-RAMS avoids owning a separate web upload product surface.

Tradeoffs:

- AgentCore needs a material retrieval/extraction capability, not just metadata rendering.
- ASI/ASI:ONE must provide an authorization artifact or retrieval API contract.
- Tests must cover denied, expired, unsupported, oversized, and successful material ingestion.
- Trace output must show enough evidence lineage without leaking raw private content.

## Acceptance Criteria

- The codebase does not reintroduce `/api/upload-url` or `S3_UPLOAD_BUCKET` as the production upload path.
- Confirmed entry payloads can carry ASI/ASI:ONE material references bound to the current case.
- Material content is retrieved only after validating the ASI/ASI:ONE identity/session/case authorization context.
- Supported materials produce extracted evidence with stable source ids that can feed planning, hazard, briefing, and report generation.
- Unsupported, denied, expired, or oversized materials are skipped with explicit trace reasons.
- FieldBrief development/debug mode uses only mock or fixture material references unless explicitly configured for local testing.
- Logs and public traces never include raw private material content, ASI tokens, signed URLs, or credentials.
- Public docs state that material-derived output is evidence support for human review, not certified RAMS or approval to work.

## Discussion Questions

- What exact ASI/ASI:ONE material access artifact will 3D-RAMS receive: signed URL, short-lived token, material API handle, or pre-extracted document text?
- Which material types are in scope first: PDF, image, text, CAD/site-plan metadata, or ASI-generated notes?
- Should material extraction run inside `asi_one_entry_agent`, inside a dedicated material subagent, or as an initial supervisor subagent before planning/hazard analysis?
- Should extracted material snippets be persisted in the report store, or should the report store keep only references, summaries, and citations?
