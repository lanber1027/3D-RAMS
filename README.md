# 3D-RAMS

![CI](https://github.com/Capitano00/3D-RAMS/actions/workflows/ci.yml/badge.svg)

3D-RAMS is a hosted pre-visit agent product that turns a natural-language site visit request with a confirmed location into an inspectable 3D review pack.

The current V3 rebuild makes chat the primary interface: a tester asks for a site visit briefing, the backend resolves or confirms the site first, then runs server-side tools and updates the UI with a 3D risk scene, evidence register, trace, confidence/fallback notes, safety gate, and RAMS-style review pack for human review. Bedrock access stays server-side.

## Two Ways To Use 3D-RAMS

### Hosted demo / judge version

Use the hosted 3D-RAMS URL with a private access code from the maintainer:

<https://main.d62sagixyhsmv.amplifyapp.com>

This path is for judges and teammates. You only need a browser and the access code. You do not need AWS, Python, Node, Codespaces, local setup, or cloud credentials.

### Deploy your own LLM version

If you clone or fork this repo and want the live Bedrock-backed agent, you need to deploy your own AWS stack and configure your own server-side environment variables. The frontend must never call Bedrock directly and no AWS credentials should be committed to GitHub.

Use [docs/deploy-your-own.md](docs/deploy-your-own.md) for the deployment checklist, required AWS resources, environment variables, access-code hash pattern, cost controls, and teardown reminder.

## Problem Statement

Site teams preparing for unfamiliar rural, development, or infrastructure visits have to combine maps, terrain, access routes, planning records, document evidence, and risk notes before they can form a useful briefing. 3D-RAMS explores whether an agent can turn that fragmented digital work into an inspectable 3D pre-visit pack with evidence, annotations, trace, confidence labels, and a visible safety boundary.

Read the full problem statement in [docs/problem-statement.md](docs/problem-statement.md).

## Architecture At A Glance

![3D-RAMS query-to-brief architecture flow](docs/assets/architecture/query-to-brief-flow.svg)

This rendered diagram is the README-scale view of the hosted durable-run workflow in [docs/architecture.md](docs/architecture.md). The detailed architecture document remains the source of truth for the full Mermaid diagrams, trust boundaries, real-vs-mocked register, safety gate, AgentCore-ready conversation boundary, and AWS path.
The current implementation adds bounded conversation memory and guarded routing in front of that durable run path; managed AgentCore Runtime/Memory activation remains a later reviewed AWS gate.

## Demo Workflow

1. User starts a test session with a shared access code.
2. User asks for a site visit review pack in natural language.
3. Agent extracts structured site intent: clean site name, coordinate/postcode clues, site type, activity, date, and unsafe certification/approval intent.
4. Named-site-only prompts enter a location-resolution stage before review generation.
5. If candidates exist, the UI asks the user to confirm a candidate location; if not, it asks for postcode, coordinate, nearest town/road, or local authority and may show a clearly provisional checklist.
6. Only after a confirmed location does the agent register uploaded evidence metadata and run allowlisted location, context, map, risk, briefing, and safety tools.
7. Backend optionally calls Amazon Bedrock server-side when enabled.
8. UI updates chat, 3D scene, risk cards, evidence, trace, and safety boundary.
9. Session/run metadata is shaped for DynamoDB evaluation tracing.

## Real vs Mocked

| Component | Demo1 Status | Notes |
| --- | --- | --- |
| Agent workflow | Real Python code | Chat session, tool sequence, evidence, trace, safety gate, deterministic fallback, and response shape are implemented. |
| Conversation memory/router | Active AgentCore-ready rebuild slice | The hosted Lambda adapter now keeps bounded recent turns and structured working memory so follow-up/status questions do not silently start fake site runs. Managed AgentCore Runtime/Memory activation remains a gated AWS step. |
| Intent and safety parser | Real V3.1 control flow | Extracts clean site labels, coordinates/postcodes, nearest-town clues, site/activity type, and unsafe certification/approval intent before tool execution. |
| Location-resolution loop | Real V3.1 control flow with fixture-first and postcode-source resolver | Recognizable named-site prompts do not silently map to Lambeth. Candidate locations require user confirmation before the review workflow starts. Postcode/outcode clues can create source-labelled Postcodes.io candidates server-side; name-only prompts ask for stronger location evidence. |
| Provisional risk profiles | Real rule layer, not site evidence | Coordinate-backed arbitrary sites get site/activity-specific provisional prompts, such as solar/PV, quarry, drainage/slope, roof, substation/BESS, delivery, and access-track checks. These are labelled provisional, not evidence-backed site findings. |
| Public data pack | Cached public fixture plus live-map option | `fixtures/public-lambeth-thames` remains the deterministic fallback. When `ENABLE_LIVE_MAP_FEATURES=true`, the backend can fetch live Planning Data and OSM/Overpass features after location confirmation. |
| Bedrock planner + briefing | Live hosted MVP path | Server-side Bedrock planner/synthesis is enabled in the hosted MVP, capped at 2 model calls per run; deterministic fallback remains available. |
| 3D viewer | Real React/Vite + CesiumJS UI | Real terrain/imagery/buildings require `VITE_CESIUM_ION_TOKEN`; no-token mode remains a labelled synthetic fallback. |
| Geospatial features | Live public, cached-public, or mocked fixture | Live MVP mode queries Planning Data and OSM/Overpass server-side; cached and synthetic fixtures remain fallback paths. |
| Planning/context notes | Cached-public or synthetic fixture | Default pack uses cached public-safe notes and source metadata; synthetic fallback uses `fixtures/planning_report.txt`. |
| AWS hosted MVP | Live maintainer deployment | Amplify frontend, API Gateway HTTP API, Lambda/FastAPI backend, Bedrock Claude 3.7 Sonnet, DynamoDB session trace, S3 upload presign, and CloudWatch logs are deployed for access-code teammate testing. |
| Google Maps / Earth / 3D Tiles | Not used | Kept out of Demo1 to avoid key, cost, licensing, and freshness risk. |

## Hosted Teammate Testing

Target teammate path is a hosted browser URL plus a shared access code. Teammates should not run Python, Node, Codespaces, AWS CLI, or AWS credentials.

Hosted MVP URL: <https://main.d62sagixyhsmv.amplifyapp.com>

Ask the maintainer for the private test access code. Do not commit, paste into public issues, or share the code outside the test group.

The hosted product path is documented in [docs/hosted-aws-product.md](docs/hosted-aws-product.md). Use [docs/team-test-guide.md](docs/team-test-guide.md) for the current scenario checklist and feedback rules.

Runtime V3 work is isolated on `feature/durable-runs-tool-loop`. It adds durable run APIs, checkpointed tool execution, polling/reconnect UX, a 3-phase model-budget design, and a location-resolution/confirmation loop before review generation. See [docs/durable-runtime-v2.md](docs/durable-runtime-v2.md).

For real 3D MVP testing, set `VITE_CESIUM_ION_TOKEN` before building/running the frontend. For live public feature overlays, set `ENABLE_LIVE_MAP_FEATURES=true` on the backend. No Google Maps key is required.

The chat UI uses the public-safe Lambeth fixture only when the prompt references the supported Lambeth / 8 Albert Embankment context or a maintainer explicitly selects that fixture in compatibility paths. Unknown named sites should not use Lambeth without confirmation.

Arbitrary named sites are not geocoded by broad web search. For a site-specific pack, provide coordinates, a full UK postcode, or enough source evidence for a source-labelled candidate. Name-only prompts can show provisional risk prompts, but they are not map/evidence-backed site findings.

For the 90-second walkthrough, before/after proof, and recording checklist, use [docs/demo-proof.md](docs/demo-proof.md).

For measured impact without overclaiming speed-up, use [docs/impact-baseline.md](docs/impact-baseline.md).

For a step-by-step fallback recording sequence and pass/fail criteria, use [docs/demo-recording-runbook.md](docs/demo-recording-runbook.md).

For repeatable local proof of the backend workflow, run:

```bash
python scripts/evaluate-demo.py
```

The evaluation runner covers nine deterministic scenarios, including cached-public happy path, missing planning evidence, map fallback, Bedrock-disabled fallback, unsafe request blocking, low-confidence output, architecture payload shape, and unknown pack fallback. See [docs/evaluation.md](docs/evaluation.md).

GitHub Actions also runs the backend tests, deterministic evaluation, frontend build, and HTTP runtime smoke on pushes and pull requests. See [docs/mvp-readiness.md](docs/mvp-readiness.md) for the current readiness snapshot, verified scenarios, and remaining gates.

For contribution expectations, safety boundaries, and handoff checklist, see [CONTRIBUTING.md](CONTRIBUTING.md).

For backend request/response shape and validation behavior, including `/api/session/start`, `/api/upload-url`, `/api/conversation/message`, `/api/chat`, and durable run routes, see [docs/api-contract.md](docs/api-contract.md).

To run the full local verification stack before sharing changes in Codespaces/Linux/macOS:

```bash
bash scripts/check-demo.sh
```

On a fresh Codespace or local clone, install dependencies as part of the check:

```bash
bash scripts/check-demo.sh --install
```

On Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check-demo.ps1
```

On a fresh Windows clone:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check-demo.ps1 -Install
```

The check runs backend compile/tests, deterministic evaluation, frontend production build, and a no-AWS HTTP runtime smoke against the backend and frontend preview.

## Bedrock Mode

The app defaults to deterministic fallback unless the backend is started with Bedrock enabled. In the current milestone, the intended public explanation is:

- `Hosted Bedrock enabled`: server-side LLM planner/synthesis path, with allowlisted tool calls, evidence trace, safety gate, and deterministic fallback.
- `No AWS / Bedrock disabled`: deterministic agent path only.
- `Future AWS path`: Cognito, Guardrails, AgentCore Observability, CloudWatch dashboards, API throttling/WAF, and richer live data adapters remain later production-shaped stages.

Use the full optional setup guide in [docs/aws-bedrock-setup.md](docs/aws-bedrock-setup.md). Confirm cost guardrails before repeated live testing; the hosted MVP is capped to 2 Bedrock model calls per run, `BEDROCK_MAX_TOKENS=1200`, and `BEDROCK_TEMPERATURE=0.2`.

Recommended local settings:

```bash
ENABLE_BEDROCK=true
AWS_PROFILE=your-local-aws-profile
AWS_REGION=eu-west-2
BEDROCK_MODEL_ID=anthropic.claude-3-7-sonnet-20250219-v1:0
BEDROCK_MAX_TOKENS=1200
BEDROCK_TEMPERATURE=0.2
BEDROCK_MAX_MODEL_CALLS=2
```

Run a low-volume smoke test:

```bash
python scripts/bedrock-smoke.py
```

Do not commit `.env`, AWS credentials, SSO cache files, API keys, or real client/site data. The UI shows whether a run used LLM-first runtime, deterministic mode, or fallback. Hosted Bedrock remains server-side and access-code gated for teammate testing.

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

### Real 3D Map Setup

The default UI can run without a token, but real Cesium terrain, imagery, and OSM Buildings require a Cesium ion token.

1. Create or sign in to a Cesium ion account.
2. Create an access token in Cesium ion.
3. Restrict the token to the URLs you will use, such as `http://localhost:5173` and the hosted Amplify URL.
4. Create a local frontend env file:

```powershell
cd frontend
New-Item -ItemType File -Force .env.local
```

5. Add the token to `frontend/.env.local`:

```env
VITE_CESIUM_ION_TOKEN=replace-with-your-cesium-ion-token
```

6. Restart the frontend:

```powershell
npm.cmd run dev
```

For live public feature overlays, also start the backend with:

```powershell
$env:ENABLE_LIVE_MAP_FEATURES="true"
$env:LIVE_MAP_REQUIRED="false"
uvicorn app.main:app --reload --port 8000
```

Do not commit `.env.local` or paste real tokens into README, docs, issues, or commits. The Cesium token is browser-visible public configuration, so use URL restrictions rather than treating it as a private backend secret.

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

OpenAPI schema:

```bash
curl http://localhost:8000/openapi.json
```

## Demo Scenarios

| Scenario | How to Run | Expected Result |
| --- | --- | --- |
| Happy path | Ask: `I want to visit 8 Albert Embankment tomorrow for a survey. Please prepare a pre-visit RAMS-style review pack.` | Chat, scene, risk cards, briefing, evidence, and trace are returned. |
| Clarification | Ask for a pack without giving a site. | Agent asks targeted questions before running tools. |
| Random named site | Ask: `I want to visit Foxglove Farm Solar Site near Hexham tomorrow for a PV module inspection.` | Agent asks for stronger location evidence and may show a provisional, non-site-specific checklist. |
| Coordinate arbitrary site | Ask with a site name and coordinates. | Agent returns a synthetic coordinate-based pack with site/activity-specific provisional risk prompts and explicit limitations. |
| Postcode candidate | Ask with a site name and UK postcode. | Backend creates a source-labelled postcode candidate and asks for confirmation before review tools run. |
| Upload metadata | Register a test PDF/image. | Upload evidence metadata is attached to the session; hosted mode uses private S3 presigned upload targets. |
| Bedrock fallback | Run without backend Bedrock config, or set `BEDROCK_SIMULATE_FAILURE=true`. | Runtime marks model path as disabled/fallback; deterministic briefing remains available. |
| Unsafe request | Ask the agent to certify RAMS or approve work. | Safety gate blocks certified RAMS/work approval behavior. |
| Low confidence | Run the Lambeth prompt and inspect risk/evidence panels. | Low-confidence items remain visible for human review. |
| Architecture visualizer | Inspect architecture docs/trace after a run. | UI/docs show server-side Bedrock boundary, evidence flow, safety gate, and deploy-target AWS services. |

## AWS Production Path

Demo1 trace and response objects are shaped to map naturally to an AWS implementation:

- Amazon Bedrock for the hosted server-side LLM planner and synthesis path.
- DynamoDB for versioned project state, approvals, and rollback records.
- S3 for evidence packs, exported briefings, screenshots, and source documents.
- CloudWatch for trace, latency, cost, and failure visibility.
- Bedrock Guardrails for unsafe claim and policy filtering as a future layer after the local safety gate.
- AgentCore Runtime and Observability as a stretch layer after the hosted MVP is stable.

See [docs/architecture.md](docs/architecture.md) for the workflow and AWS diagrams.

## Safety Boundary

This project does not produce certified RAMS, emergency response instructions, work approval, or competent-person replacement. It produces an inspectable pre-visit review pack for human review.
