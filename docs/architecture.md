# 3D-RAMS Architecture

This document is the public, living architecture reference for Demo1. It explains what the agent does today, what is mocked, what is real, and how the same run shape can map to AWS later.

3D-RAMS creates a pre-visit briefing pack for human review. It does not create certified RAMS, emergency guidance, approval to work, or a competent-person replacement.

## Query-To-Brief Flow

```mermaid
flowchart LR
    User["User enters coordinate and test options"] --> UI["React/Vite UI"]
    UI --> API["AgentCore POST /invocations"]
    API --> Agent["Deterministic Demo1 agent loop"]
    Agent --> Locate["Resolve location or cached fixture pack"]
    Agent --> Geo["Load synthetic, cached-public, or fallback features"]
    Agent --> Scene["Build 3D scene config"]
    Agent --> Planning["Load cached-public or synthetic planning context"]
    Agent --> Hazards["Extract candidate hazard notes"]
    Agent --> Annotations["Create 3D annotations"]
    Agent --> Brief["Generate deterministic briefing"]
    Agent --> BedrockBrief["Optional Bedrock briefing"]
    Agent --> Safety["Safety gate"]
    Safety --> Output["Scene, briefing, evidence, trace, visualizer"]
    Output --> UI
```

## AgentVerse Entry And AgentCore Supervisor Boundary

```mermaid
flowchart LR
    User["ASI:ONE user"] --> Entry["AgentVerse entry agent"]
    Entry --> Intake["Clarify, collect materials, confirm launch"]
    Intake --> Adapter["AgentVerse-to-AgentCore adapter"]
    Adapter --> Runtime["AgentCore supervisor runtime"]
    Runtime --> Tools["Specialist subagents and project tools"]
    Runtime --> Review["Review-agent gate"]
    Review --> Report["Structured report JSON"]
    Report --> Adapter
    Adapter --> Entry
    Entry --> User
    Report --> UI["Frontend visualization"]
```

The adapter exists only at the AgentVerse-to-AgentCore boundary. It handles launch-readiness validation, request mapping, and future IAM/signing. Supervisor planning, specialist subagents, tool calls, reasoning, report assembly, and review loops belong inside AgentCore.

## Data Flow And Trust Boundaries

```mermaid
flowchart TB
    subgraph Browser["Browser boundary"]
        Form["Coordinate, options, safety-test request"]
        Viewer["3D scene and workflow visualizer"]
    end

    subgraph RuntimeBoundary["AgentCore runtime boundary"]
        Runtime["Agent runtime"]
        Trace["Trace builder"]
        Safety["Safety policy"]
    end

    subgraph Fixtures["Public-safe fixture boundary"]
        GeoFixture["Mock geospatial features"]
        PublicPack["Cached Lambeth public fixture pack"]
        PlanningFixture["Synthetic or cached planning text"]
    end

    subgraph FutureSources["Future live-source boundary"]
        LPA["Planning portals or APIs"]
        MapData["Geospatial and terrain APIs"]
    end

    Form --> Runtime
    Runtime --> GeoFixture
    Runtime --> PublicPack
    Runtime --> PlanningFixture
    Runtime -. "future" .-> LPA
    Runtime -. "future" .-> MapData
    Runtime --> Trace
    Runtime --> Safety
    Trace --> Viewer
    Safety --> Viewer
```

## Current Tool-Calling Sequence

```mermaid
sequenceDiagram
    participant U as User
    participant UI as Frontend
    participant API as AgentCore Runtime
    participant A as Agent Loop
    participant F as Fixtures

    U->>UI: Submit coordinate and options
    UI->>API: POST /invocations
    API->>A: run_site_briefing
    A->>A: resolve_location
    A->>F: load_geospatial_features
    A->>A: build_scene_config
    A->>F: load_planning_context
    A->>A: extract_hazard_notes
    A->>A: create_annotations
    A->>A: generate_site_brief
    A->>A: generate_bedrock_briefing if enabled
    A->>A: safety_gate
    A-->>API: JSON run object
    API-->>UI: scene, briefing, evidence, sources, trace, architecture
    UI-->>U: 3D briefing and workflow visualizer
```

## Bedrock Briefing Path

```mermaid
sequenceDiagram
    participant A as Agent Runtime
    participant Adapter as Model Adapter
    participant Bedrock as Amazon Bedrock
    participant Safety as Guardrails and Human Review
    participant Obs as CloudWatch

    A->>Adapter: Create structured briefing task
    Adapter->>Bedrock: Invoke model with structured evidence prompt
    Bedrock-->>Adapter: Draft extraction or briefing
    Adapter->>Safety: Check unsafe claims and review requirement
    Safety-->>A: allow, block, or require approval
    A->>Obs: Emit trace, latency, status, and evidence ids
```

Demo1 can run without Bedrock, but it now has a live Bedrock briefing path when `ENABLE_BEDROCK=true`. The deterministic briefing remains the fallback, and the Bedrock step is limited to one model call per agent run. The default UI uses the cached `public-lambeth-thames` pack anchored on 8 Albert Embankment. Runtime does not call live Planning Data, OpenStreetMap, Environment Agency, Lambeth, TfL, Google, or OS services.

## Evidence, Trace, And Observability Flow

```mermaid
flowchart LR
    Tool["Tool call"] --> Span["Trace row"]
    Source["Source register"] --> Span
    Span --> Evidence["Evidence id"]
    Evidence --> Annotation["3D annotation"]
    Evidence --> Briefing["Briefing statement"]
    Span --> Visualizer["Architecture + Workflow UI"]

    Span -. "future" .-> CloudWatch["CloudWatch trace span"]
    Evidence -. "future" .-> S3["S3 evidence pack"]
    Visualizer -. "optional when configured" .-> DDB["DynamoDB report store by caseId"]
```

Each runtime tool emits a compact trace object:

- `id`, `name`, `type`, `status`, `summary`;
- `startedAt`, `endedAt`, `durationMs`;
- `sourceIds`, `evidenceIds`, `fallbackReason`;
- `awsMapping`;
- `output`.

## Safety And Human Review Gate

```mermaid
flowchart TB
    Request["User request"] --> Classify["Check for unsafe claims"]
    Classify -->|"certified RAMS, approve work, emergency route"| Block["Block response"]
    Classify -->|"normal pre-visit briefing"| Review["Allow as review-required output"]
    Block --> UIBlock["Show refusal and no annotations"]
    Review --> UIReview["Show briefing, limitations, and human-review boundary"]
    Review -. "future" .-> HITL["Human approval queue"]
    Classify -. "future" .-> Guardrails["Bedrock Guardrails"]
```

The safety gate is deliberately visible. Judges and teammates should be able to see where the agent refuses high-risk claims and where a human review point would sit in production.

## Real Vs Mocked Register

| Area | Current Source | Current Status | Visible In UI | Production AWS Mapping | Upgrade Risk |
| --- | --- | --- | --- | --- | --- |
| Agent loop | AgentCore Python runtime | Real deterministic code plus optional Bedrock briefing | Tool timeline and trace | Bedrock model/tool planning | Model variability and evaluation |
| Public fixture pack | `fixtures/public-lambeth-thames` | Cached public-source metadata and attribution files | Source register, evidence, trace, briefing | S3 source pack plus source registry | Source freshness, licence handling, and overclaiming |
| Request state | Browser form payload plus optional `caseId` report-store item | Real; DynamoDB write only when configured | Run overview | DynamoDB report metadata keyed by `caseId` | Data privacy and retention |
| 3D viewer | React/Vite + CesiumJS | Real token-free local scene plus overlay | 3D scene | Static frontend plus API runtime | Performance on low-power devices |
| Geospatial features | Synthetic fixture or cached public pack | Mocked, cached-public, or fallback | Sources and annotations | S3 source object plus live geospatial APIs | Licensing, freshness, key management |
| Planning context | Synthetic fixture or cached public pack | Synthetic, cached-public, or unavailable | Sources, evidence, briefing limits | S3 documents plus Bedrock extraction | Scraping reliability and citations |
| Bedrock briefing | Amazon Bedrock when configured | Optional live AWS call with deterministic fallback | Runtime mode, trace, and briefing | Evaluated Bedrock adapter with CloudWatch traces | Cost, model access, latency, and fallback quality |
| Safety gate | Python rules | Real Demo1 policy | Safety pill and visualizer | Guardrails plus human review queue | Overclaiming or hidden unsafe edge cases |
| Evidence register | API response | Real response object | Evidence cards | S3 evidence pack | Source traceability |
| Observability | JSON trace | Real response object | Trace and visualizer | CloudWatch logs, metrics, traces | Noise and cost control |

## Future Risk Intelligence Sources

These sources are not live in Demo1. They are future review-pack inputs that should use the same source-register, evidence, confidence, and fallback pattern before any live API is added.

| Source Group | Example Use | Demo1 Status | Main Risk |
| --- | --- | --- | --- |
| Infrastructure and grid context | Overhead lines, pylons, substations, route constraints, and other open infrastructure risks. | Future only | Licensing, coverage, critical-asset sensitivity, and false positives. |
| Weather and seasonal context | Combine slope, access, flood, wind, snow/ice, rain, quarry or ground-risk context into review flags. | Future only | Forecast uncertainty, stale data, and operational-advice overclaiming. |
| News and live incidents | Nearby transport crashes, road closures, industrial incidents, flood warnings, or major disruption. | Future only | Freshness, geocoding accuracy, misinformation, and emergency-guidance risk. |

Future reasoning should produce inspectable review flags, not unsupported instructions. Example shape: source combination, confidence, evidence ids, risk flag, and human review requirement.

## AWS Production Path

```mermaid
flowchart TB
    UI["React UI"] --> Edge["CloudFront or static hosting"]
    UI --> Runtime["AgentCore Runtime endpoint"]
    Runtime --> Bedrock["Amazon Bedrock briefing generation"]
    Runtime --> Guardrails["Bedrock Guardrails"]
    Runtime --> DDB["DynamoDB report store by caseId"]
    Runtime --> S3["S3 evidence packs and source documents"]
    Runtime --> CloudWatch["CloudWatch logs, metrics, traces"]
    Runtime --> Sources["Planning and geospatial APIs"]
    Guardrails --> Review["Human review dashboard"]
    CloudWatch --> Review
    DDB --> Review
    S3 --> Review
```

## Visualizer Contract

The `/invocations` response keeps the visualizer in `output.run`. There is no separate visualizer endpoint.

Core fields:

- `request`: submitted site name, coordinate, goal, toggles, and additional request;
- `sources`: real, mocked, fallback, unavailable, and future source register;
- `runtime`: deterministic, Bedrock, disabled, or fallback briefing mode;
- `trace`: ordered tool calls with source ids, evidence ids, fallback reason, model metadata, and AWS mapping;
- `evidence`: evidence register shown to the user;
- `safety`: allow/block decision, triggered rules, review requirement, and decision id;
- `architecture`: UI-ready run overview, current trace, source map, safety gate, real-vs-mocked register, and future AWS path.
