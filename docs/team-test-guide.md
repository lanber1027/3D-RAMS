# Team Test Guide

Use this guide to test the Demo1 flow before judging or submission. The app is intentionally local-first: it should run with public fixtures only, without Google Maps keys, Cesium ion tokens, live planning portals, client data, or real site data. Bedrock mode is available only when the backend has AWS credentials and `ENABLE_BEDROCK=true`; deterministic fallback remains available.

3D-RAMS turns a coordinate into an inspectable 3D pre-visit briefing pack:

1. coordinate input;
2. location fixture lookup;
3. mocked geospatial features;
4. Cesium scene configuration;
5. synthetic planning fixture;
6. candidate hazard extraction;
7. 3D annotations;
8. RAMS-style briefing;
9. optional Bedrock briefing generation;
10. safety gate;
11. evidence register, trace, and architecture visualizer.

This is not certified RAMS, emergency guidance, work approval, or a competent-person replacement. Treat all output as a demo briefing for human review.

## No-Code Codespaces Walkthrough

Recommended path: GitHub Codespaces. You do not need to install Python, Node, AWS tools, Google tools, or map keys locally if Codespaces works for your GitHub account.

What you need:

- a GitHub account with Codespaces access available for your account or plan;
- a web browser;
- repo URL: <https://github.com/Capitano00/3D-RAMS>.

### Step 1: Open The Repo

Open:

<https://github.com/Capitano00/3D-RAMS>

You should see folders such as `.devcontainer`, `backend`, `frontend`, `docs`, `fixtures`, and `scripts`.

### Step 2: Create A Codespace

On the GitHub repo page, click:

`Code -> Codespaces -> Create codespace on main`

GitHub will open a browser-based VS Code-like workspace. It may look technical, but you only need the terminal once.

### Step 3: Wait For Setup

Wait until Codespaces finishes preparing the workspace. The devcontainer setup runs:

```bash
bash scripts/start-dev.sh --install-only
```

That pre-installs backend and frontend dependencies.

### Step 4: Open The Terminal

Inside Codespaces, use the terminal at the bottom of the screen. If it is not visible, open:

`Terminal -> New Terminal`

Paste:

```bash
bash scripts/start-dev.sh
```

This starts the FastAPI backend on port `8000` and the Vite frontend on port `5173`.

### Step 5: Open The Frontend

Codespaces should show a forwarded-port pop-up. Open port:

`5173`

If there is no pop-up, use the Codespaces `Ports` tab and open the forwarded address for port `5173`.

You should now see the 3D-RAMS web app.

### Step 6: Click Run

Leave the default coordinate and options unchanged, then click:

`Run`

Expected result: the app shows a 3D scene, annotations, RAMS-style briefing, evidence register, agent trace, and Architecture + Workflow visualizer.
The runtime pill should show `disabled`, `real`, or `fallback` for briefing mode.

### Step 7: Run Six Test Scenarios

Use demo fixture data only. Do not enter real client sites, confidential project locations, private planning documents, secrets, or API keys.

| Scenario | What To Do | Expected Result |
| --- | --- | --- |
| Happy path | Leave defaults and click `Run`. | Scene, annotations, briefing, evidence, trace, and visualizer appear. |
| Missing planning fixture | Turn off `Planning fixture`, then click `Run`. | App still works and explains planning evidence limitations. |
| Map fallback | Turn on `Map fallback`, then click `Run`. | Trace shows geospatial loading using fallback. |
| Bedrock disabled/fallback | Leave `Bedrock` on, but run without AWS config, or ask War Room to simulate failure. | App still works; trace shows Bedrock as disabled or fallback and keeps deterministic briefing. |
| Safety refusal | Click `Safety test`. | Agent refuses certified RAMS or work-approval claims. |
| Low-confidence annotation | Run the default case and inspect limitations/annotations. | At least one item is labelled low confidence. |
| Architecture visualizer | Run any successful scenario and inspect `Architecture + Workflow`. | UI shows query flow, tools, sources, evidence, safety, real-vs-mocked boundaries, and future AWS path. |

### Step 8: Submit Feedback

Go to:

`Issues -> New Issue -> Teammate Demo Feedback`

Please include setup result, scenario pass/fail notes, bugs, confusing wording, screenshots if useful, and any concern about safety or data boundaries.

Do not upload real site data, private documents, client material, secrets, or API keys.

## Plain-English Repo Map

| Part | Meaning |
| --- | --- |
| `frontend` | The website you click on. |
| `backend` | The local agent/API that receives the coordinate and returns briefing data. |
| `fixtures` | Fake/synthetic demo data, not real client data. |
| `scripts/start-dev.sh` | One-command startup script for Codespaces. |
| `docs/team-test-guide.md` | This testing checklist. |
| `.github/ISSUE_TEMPLATE` | Feedback form for teammate testing. |
| `.devcontainer` | Codespaces setup recipe. |

The backend exposes a health check endpoint and an `/api/run` endpoint. The agent workflow is:

`coordinate input -> fixture lookup -> mocked geospatial features -> scene config -> synthetic planning fixture -> hazard extraction -> annotations -> briefing -> safety gate -> evidence/trace/architecture visualizer`

## Local Fallback Setup

Run this only if Codespaces is unavailable or slow.

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

PowerShell note: if `npm run dev` is blocked by script execution policy, use `npm.cmd run dev`.

## Optional Bedrock Setup

Only use this if you are testing the live AWS path. Do not paste secrets into chat or commit `.env`.

Backend environment:

```bash
ENABLE_BEDROCK=true
AWS_PROFILE=3d-rams-dev
AWS_REGION=eu-west-2
BEDROCK_MODEL_ID=anthropic.claude-3-7-sonnet-20250219-v1:0
BEDROCK_MAX_TOKENS=1200
BEDROCK_TEMPERATURE=0.2
```

Low-volume smoke test:

```bash
python scripts/bedrock-smoke.py
```

Keep usage low: one Bedrock call per agent run, short fixture prompts only, and no real client/site data.

## Health Check

If the UI cannot run, confirm the backend health check:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status":"ok","service":"3d-rams-demo1"}
```

## What Judges Or Teammates Should Inspect

- The 3D scene and annotations after a run.
- The RAMS-style briefing and its limitations.
- Evidence register entries and source labels.
- Trace rows with tool names and statuses.
- Briefing mode pill: deterministic disabled, Bedrock real, or fallback.
- `Architecture + Workflow` for query flow, tools, sources, evidence, safety, real-vs-mocked boundaries, and future AWS path.
- `docs/architecture.md` for written architecture diagrams and trace shape.

## Troubleshooting

| Symptom | Likely Cause | What To Try |
| --- | --- | --- |
| Frontend opens but run fails | Backend is not running or port `8000` is not forwarded. | Start the backend, check `/health`, and reload the frontend. |
| Codespaces frontend cannot reach backend | Startup script did not start the backend or proxy is not active. | Stop the script, run `bash scripts/start-dev.sh` again, check `/health`, and confirm ports `8000` and `5173` are forwarded. |
| `npm` command fails in PowerShell | Local execution policy blocks `npm.ps1`. | Use `npm.cmd run dev` or `npm.cmd run build`. |
| Cesium scene looks blank or slow | Browser/GPU/network constraints in the test environment. | Reload once, try another browser, and still capture whether briefing/evidence/trace worked. |
| Planning-related hazards are missing | `Planning fixture` is disabled. | Re-enable `Planning fixture` for the happy path. |
| Output sounds too authoritative | Demo copy or narration may be overstating the boundary. | Flag it in feedback; the intended boundary is human-review briefing only. |
