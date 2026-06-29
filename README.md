# 3D-RAMS

3D-RAMS is a hackathon Demo1 agent that turns a site coordinate into a 3D pre-visit briefing pack.

The first slice is intentionally local-first: it can run without Google Maps keys, Cesium ion keys, live planning-portal scraping, or hosted infrastructure. The production-shaped path can also make one Amazon Bedrock call per run for briefing generation when AWS credentials are configured, while preserving deterministic fallback.

## Problem Statement

Site teams preparing for unfamiliar rural, development, or infrastructure visits have to combine maps, terrain, access routes, planning records, document evidence, and risk notes before they can form a useful briefing. 3D-RAMS explores whether an agent can turn that fragmented digital work into an inspectable 3D pre-visit pack with evidence, annotations, trace, confidence labels, and a visible safety boundary.

Read the full problem statement in [docs/problem-statement.md](docs/problem-statement.md).

## Architecture At A Glance

![3D-RAMS query-to-brief architecture flow](docs/assets/architecture/query-to-brief-flow.svg)

This rendered diagram is the README-scale view of the workflow in [docs/architecture.md](docs/architecture.md). The detailed architecture document remains the source of truth for the full Mermaid diagrams, trust boundaries, real-vs-mocked register, safety gate, and future AWS path.

## Demo Workflow

1. User enters a coordinate.
2. The backend resolves the location fixture.
3. The agent loads mock geospatial features.
4. The agent builds a Cesium scene configuration.
5. The agent loads a synthetic planning-document fixture.
6. The agent extracts candidate hazard notes.
7. The agent creates 3D annotations.
8. The agent generates a RAMS-style briefing.
9. A safety gate blocks certified RAMS, work approval, and emergency guidance claims.
10. The UI shows the 3D scene, briefing, evidence register, trace, and architecture visualizer.

## Real vs Mocked

| Component | Demo1 Status | Notes |
| --- | --- | --- |
| Agent workflow | Real Python code | Tool sequence, evidence, trace, safety gate, deterministic fallback, and response shape are implemented. |
| Bedrock briefing | Optional live AWS path | Uses one `InvokeModel` call per run when `ENABLE_BEDROCK=true`; deterministic briefing remains the fallback. |
| 3D viewer | Real React/Vite + CesiumJS UI | Uses a token-free Cesium canvas plus local scene overlay and annotations. |
| Geospatial features | Mocked fixture | `fixtures/geospatial_features.json` is public-safe synthetic data. |
| Planning documents | Mocked fixture | `fixtures/planning_report.txt` is synthetic and not a real LPA document. |
| AWS | Partially live when configured | Bedrock briefing can be live; DynamoDB, S3, CloudWatch, Guardrails, and AgentCore remain production-path stages. |
| Google Maps / Earth / 3D Tiles | Not used | Kept out of Demo1 to avoid key, cost, licensing, and freshness risk. |

## Quickstart

## Teammate Testing

The easiest teammate test path is GitHub Codespaces. Open the repo in Codespaces, then run:

```bash
bash scripts/start-dev.sh
```

Codespaces should forward the frontend on port `5173` and backend on port `8000`. Use [docs/team-test-guide.md](docs/team-test-guide.md) for the scenario checklist and feedback template.

No AWS, Google Maps, Cesium ion token, or real site data is required.

## Bedrock Mode

The app defaults to deterministic fallback unless the backend is started with Bedrock enabled.

Recommended local settings:

```bash
ENABLE_BEDROCK=true
AWS_PROFILE=3d-rams-dev
AWS_REGION=eu-west-2
BEDROCK_MODEL_ID=anthropic.claude-3-7-sonnet-20250219-v1:0
BEDROCK_MAX_TOKENS=1200
BEDROCK_TEMPERATURE=0.2
```

Run a low-volume smoke test:

```bash
python scripts/bedrock-smoke.py
```

Do not commit `.env`, AWS credentials, SSO cache files, API keys, or real client/site data. The UI shows whether a run used Bedrock, deterministic mode, or fallback.

## Local Quickstart

Backend:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

Health check:

```bash
curl http://localhost:8000/health
```

Agent run:

```bash
curl -X POST http://localhost:8000/api/run ^
  -H "Content-Type: application/json" ^
  -d "{\"latitude\":52.2053,\"longitude\":-1.6022}"
```

## Demo Scenarios

| Scenario | How to Run | Expected Result |
| --- | --- | --- |
| Happy path | Click `Run` | Scene, annotations, briefing, evidence, and trace are returned. |
| Missing data | Disable `Planning fixture`, click `Run` | Briefing continues with a planning-evidence limitation. |
| Tool failure | Enable `Map fallback`, click `Run` | Trace marks geospatial loading as `fallback`. |
| Bedrock fallback | Enable Bedrock in UI while backend has no AWS config, or set `BEDROCK_SIMULATE_FAILURE=true` | Trace marks Bedrock step as `disabled` or `fallback`; deterministic briefing remains available. |
| Unsafe request | Click `Safety test` | Safety gate blocks certified RAMS/work approval behavior. |
| Low confidence | Normal run | Imagery-derived bridge indicator is labelled low confidence. |
| Architecture visualizer | Normal run | UI shows tool sequence, boundaries, AWS path, and real-vs-mocked status. |

## AWS Production Path

Demo1 trace and response objects are shaped to map naturally to an AWS implementation:

- Amazon Bedrock for the live model-assisted briefing step.
- DynamoDB for versioned project state, approvals, and rollback records.
- S3 for evidence packs, exported briefings, screenshots, and source documents.
- CloudWatch for trace, latency, cost, and failure visibility.
- Guardrails for unsafe claim and policy filtering.
- AgentCore Runtime and Observability as a stretch layer after the plain Bedrock-backed loop works.

See [docs/architecture.md](docs/architecture.md) for the workflow and AWS diagrams.

## Safety Boundary

This project does not produce certified RAMS, emergency response instructions, work approval, or competent-person replacement. It produces an inspectable pre-visit review pack for human review.
