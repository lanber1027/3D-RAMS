# AgentVerse To AgentCore Adapter Contract

This contract fixes the boundary between the AgentVerse entry agent and the AgentCore supervisor runtime. It is local-first and contains no AWS credentials, API keys, private user data, or live site records.

The adapter is not the workflow backend. It validates launch readiness, maps payloads, and later owns IAM/signing for AgentCore invocation.

Implementation note: the separate ASI:ONE proof of concept has been imported into this repository as `app/MyAgent` and `agentverse/hosted_adapter.py`. See [agentverse-asi-one-runtime.md](agentverse-asi-one-runtime.md). Real runtime ARNs and AgentVerse secrets stay outside this public repo.

## Entry Agent To Adapter

The entry agent sends a confirmed intake payload only after the user has approved the launch.

```json
{
  "conversationId": "agentverse-session-id",
  "entryAgentId": "rams-entry-agent",
  "confirmedByUser": true,
  "intake": {
    "locationText": "near 8 Albert Embankment, Lambeth",
    "locationCandidate": {
      "label": "Lambeth Thames public fixture",
      "lat": 51.4908,
      "lng": -0.1216,
      "confidence": 0.82
    },
    "areaScope": {
      "type": "radius",
      "meters": 800
    },
    "userGoal": "pre-visit site risk and planning context",
    "userNotes": "Focus on flood context, access, and public interface constraints.",
    "materials": [
      {
        "type": "note",
        "label": "User note",
        "summary": "Client is considering an early feasibility walkover."
      }
    ]
  },
  "runtimeOptions": {
    "fixturePack": "public-lambeth-thames",
    "useBedrock": false,
    "includePlanningFixture": true,
    "simulateMapFailure": false
  }
}
```

Required launch fields:

| Field | Requirement |
| --- | --- |
| `confirmedByUser` | Must be `true`. |
| `intake.locationText` or `intake.locationCandidate` | At least one location clue is required. |
| `intake.areaScope` | Required so the supervisor can plan the review area. |
| `intake.userGoal` | Required so the supervisor can align evidence to the report purpose. |

## Adapter To AgentCore

The adapter maps the confirmed intake into the AgentCore invocation envelope.

```json
{
  "input": {
    "siteName": "Lambeth Thames public fixture",
    "latitude": 51.4908,
    "longitude": -0.1216,
    "goal": "pre-visit site risk and planning context",
    "fixturePack": "public-lambeth-thames",
    "useBedrock": false,
    "includePlanningFixture": true,
    "simulateMapFailure": false,
    "additionalRequest": "Focus on flood context, access, and public interface constraints.",
    "upstream": {
      "source": "AGENTVERSE",
      "adapterVersion": "agentverse-agentcore-adapter-v0",
      "conversationId": "agentverse-session-id",
      "entryAgentId": "rams-entry-agent",
      "confirmedByUser": true,
      "areaScope": {
        "type": "radius",
        "meters": 800
      },
      "locationConfidence": 0.82,
      "materialCount": 1
    }
  }
}
```

The local AgentCore runtime currently preserves this metadata as request context and returns the existing visualization run under `output.run`.

## AgentCore To Adapter

AgentCore returns the standard runtime envelope:

```json
{
  "output": {
    "reportStatus": "review_required",
    "workflowMode": "cached_public_fixture",
    "run": {}
  }
}
```

`review_required` means the current demo safety boundary still requires human review. A future `review_passed` status should only be used after the independent review-agent loop from ADR 0002 is implemented and has passed.

## Adapter To Entry Agent

The adapter returns a delivery payload suitable for ASI:ONE/AgentVerse:

```json
{
  "conversationId": "agentverse-session-id",
  "status": "review_required",
  "workflowMode": "cached_public_fixture",
  "customerSummary": {
    "title": "Lambeth Thames public fixture",
    "headline": "Cached public-source review pack for early site scoping.",
    "summary": [],
    "priorityChecks": [],
    "safetyMessage": "Allowed as a non-certified pre-visit briefing that requires human review."
  },
  "deepReport": {
    "kind": "agentcore_run_payload",
    "runId": "demo1-local-run",
    "evidenceCount": 0,
    "traceCount": 0,
    "visualizationReady": true
  },
  "agentcoreOutput": {}
}
```

The entry agent can present the summary conversationally and link the user to the frontend visualization. It should not generate new unsupported risk claims outside the AgentCore-reviewed result.

## Local Mock Behavior

For local development:

- no AWS credentials are required;
- adapter functions run in-process;
- AgentCore can be invoked through `agentcore dev`;
- runtime output remains fixture-backed unless live integrations are explicitly enabled.

For cloud deployment:

- adapter transport must add IAM/signing;
- secrets must stay outside the public repo;
- errors must return to the entry agent as recoverable delivery or clarification states;
- long-running supervisor work may need async status and report retrieval rather than a single blocking request.
