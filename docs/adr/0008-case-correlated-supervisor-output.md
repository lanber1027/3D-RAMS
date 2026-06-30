# ADR 0008: Case-Correlated Supervisor Output

## Status

Accepted for implementation.

## Context

ADR 0005 made the entry agent responsible for launching a confirmed workflow with a stable `caseId`. That identifier is needed to connect chat turns, AgentCore supervisor input, trace rows, structured report data, and frontend visualization output.

The current implementation could invoke the supervisor through the AgentVerse entry path, but the `caseId` was not consistently generated, forwarded, or echoed. Without that correlation field, a cloud demo can still render one response, but it is harder to map chat delivery, report payloads, evidence, and future CloudWatch records to the same user-confirmed case.

This repository is still public hackathon demo code. A `caseId` must remain a non-secret correlation value. Persistence must not imply certified RAMS output, work approval, emergency advice, legal advice, or a production audit record.

## Decision

Use `caseId` as the stable cross-runtime correlation id for confirmed entry-agent launches.

The AgentVerse entry adapter should generate a `case_<id>` value when a confirmed payload does not already provide one. The adapter must pass that id into:

- AgentCore supervisor `input.caseId`;
- supervisor upstream metadata as `input.upstream.caseId`;
- entry-agent delivery payloads;
- the top-level AgentCore output envelope.

The supervisor runtime must echo the same id in:

- `output.caseId`;
- `output.run.caseId`;
- `output.run.request.caseId`;
- `output.structuredReport.caseId`;
- `output.structuredReport.intake.caseId`.

When `RAMS_REPORT_STORE_TABLE` is set, the supervisor runtime must also write a DynamoDB report-store item keyed by `caseId`. When the variable is unset, the runtime must skip persistence and keep the no-AWS local demo path runnable.

## Boundaries

The `caseId` is the DynamoDB partition key only when report-store persistence is configured. It is not:

- an authorization token;
- an AWS resource identifier;
- a claim that the report has passed independent review;
- a claim that the output is certified RAMS or approval to work.

The stored item should contain public-safe report metadata and the structured report payload. It must not store AWS credentials, AgentVerse secrets, private notes, client data, or confidential planning content.

## Consequences

Positive:

- Chat summary, supervisor run, structured report, evidence, and trace can be matched without relying on transient runtime ids.
- The frontend can render or link to a case path later using the same key.
- CloudWatch and DynamoDB report records can use the same correlation field.

Tradeoffs:

- Tests must assert one more contract field across entry and supervisor paths.
- The id format must stay public-safe and non-secret because it can appear in UI payloads and docs.
- DynamoDB retention, item shape, and IAM grants must remain explicit infrastructure choices.

## Acceptance Criteria

- Confirmed entry payloads without `caseId` receive a generated `case_<id>` value.
- Existing payloads with `caseId` preserve that value.
- Supervisor output echoes the id through output, run, request, and structured report objects.
- Local deterministic ASI:ONE fallback and cloud handoff paths expose the same field.
- When `RAMS_REPORT_STORE_TABLE` is unset, output includes skipped persistence status and no AWS write is attempted.
- When `RAMS_REPORT_STORE_TABLE` is set, supervisor output writes a DynamoDB item keyed by `caseId` and returns stored/error status.
- Public docs describe DynamoDB persistence without implying certified RAMS output, approval to work, or independent review completion.

## Next Review Trigger

Revisit this ADR when `/case/{caseId}` routing, report retrieval APIs, retention policy, or CloudWatch search dashboards are implemented.
