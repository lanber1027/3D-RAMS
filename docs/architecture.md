# 3D-RAMS Architecture

## Current Demo1 Boundaries

```mermaid
flowchart LR
    User["User"] --> UI["React/Vite UI"]
    UI --> API["FastAPI /api/run"]
    API --> Agent["3D-RAMS agent loop"]
    Agent --> Geo["Mock geospatial fixture"]
    Agent --> Planning["Synthetic planning fixture"]
    Agent --> Scene["Scene config"]
    Agent --> Safety["Safety gate"]
    Agent --> Trace["Trace + evidence register"]
    Scene --> UI
    Safety --> UI
    Trace --> UI
```

## Agent Tool Sequence

```mermaid
sequenceDiagram
    participant U as User
    participant UI as Frontend
    participant API as FastAPI
    participant A as Agent Loop
    participant F as Fixtures

    U->>UI: Submit coordinate and options
    UI->>API: POST /api/run
    API->>A: Run site briefing
    A->>A: resolve_location
    A->>F: load_geospatial_features
    A->>A: build_scene_config
    A->>F: load_planning_context
    A->>A: extract_hazard_notes
    A->>A: create_annotations
    A->>A: generate_site_brief
    A->>A: safety_gate
    A-->>API: scene, annotations, evidence, trace
    API-->>UI: JSON response
    UI-->>U: 3D briefing and visualizer
```

## AWS Production Path

```mermaid
flowchart TB
    UI["React UI"] --> APIGW["API Gateway or App Runner endpoint"]
    APIGW --> Runtime["Agent runtime service"]
    Runtime --> Bedrock["Amazon Bedrock model/tool planning"]
    Runtime --> Guardrails["Bedrock Guardrails"]
    Runtime --> DDB["DynamoDB project state"]
    Runtime --> S3["S3 evidence packs"]
    Runtime --> CloudWatch["CloudWatch logs, metrics, traces"]
    Runtime --> Sources["Planning APIs / geospatial APIs"]
    CloudWatch --> Review["Human review dashboard"]
    DDB --> Review
    S3 --> Review
```

## Trace Shape

Each backend tool emits:

- `name`: stable tool name;
- `status`: `ok`, `warning`, `fallback`, or `blocked`;
- `summary`: human-readable action summary;
- `timestamp`: UTC ISO timestamp;
- `output`: compact structured output.

This is deliberately close to a CloudWatch/AgentCore observability model: each tool call can become a span, each status can become a metric dimension, and each run can attach evidence IDs for audit.

## Real vs Mocked Register

| Area | Current | Upgrade Path |
| --- | --- | --- |
| Agent loop | Real deterministic Python | Add Bedrock model adapter behind `ENABLE_BEDROCK=true`. |
| Location resolution | Fixture | Add postcode/address geocoder or official gazetteer source. |
| Geospatial features | Fixture | Add OS, OSM, satellite, or sponsor geospatial APIs. |
| 3D map | Local Cesium scene | Add live terrain/tiles if licensing, key management, and reliability fit. |
| Planning context | Synthetic text fixture | Add LPA search, document retrieval, OCR, parsing, and cited extraction. |
| Safety gate | Rule-based | Add Guardrails and policy tests. |
| State | In-memory per request | Add DynamoDB versioned runs and approvals. |
| Evidence packs | JSON response | Add S3 export and signed review links. |
| Observability | JSON trace in UI | Add CloudWatch logs, metrics, traces, and run dashboards. |

