# Team Test Guide

Use this guide to test the hosted pre-visit agent flow before judging or submission. The target teammate path is a browser URL plus a shared access code. Teammates should not install Python, Node, AWS CLI, use Codespaces, or handle AWS credentials.

Hosted MVP URL:

<https://main.d62sagixyhsmv.amplifyapp.com>

Ask the maintainer for the private test access code. Do not post the access code in GitHub issues, chat screenshots, public docs, or demo recordings.

3D-RAMS turns a confirmed site location into an inspectable 3D pre-visit briefing pack. The default UI uses the cached `public-lambeth-thames` fixture pack for a Lambeth / Thames public-data example anchored on 8 Albert Embankment. Unknown named sites now enter a V3 location-resolution loop first; the agent must either show source-labelled candidates for confirmation or ask for postcode, coordinates, nearest town/road, or local authority. It does not call live Planning Data, OpenStreetMap, Environment Agency, Lambeth, TfL, Google, or OS services during the demo.

1. shared-code session start;
2. natural-language site visit request;
3. optional clarifying questions;
4. location/site resolution;
5. user confirmation when the site is named but not yet trusted;
6. optional PDF/image evidence registration;
7. cached-public, synthetic, or fallback geospatial/context features;
8. 3D risk scene and annotations;
9. RAMS-style review pack;
10. optional server-side Bedrock planning/synthesis;
11. safety gate;
12. deterministic fallback if live sources/model path are unavailable;
13. evidence register, trace, and architecture visualizer.

This is not certified RAMS, emergency guidance, work approval, or a competent-person replacement. Treat all output as a demo briefing for human review.

## Hosted URL Walkthrough

Recommended teammate path once deployed:

What you need:

- a web browser;
- the hosted 3D-RAMS URL from Boyong;
- the shared test access code;
- only synthetic/public test evidence.

Steps:

1. Open <https://main.d62sagixyhsmv.amplifyapp.com>.
2. Enter the access code and optional tester alias.
3. Ask a natural-language question such as:

   ```text
   I want to visit 8 Albert Embankment tomorrow for a survey. Please prepare a pre-visit RAMS-style review pack.
   ```

4. If the agent shows candidate location cards, confirm one before expecting a 3D review pack.
5. If the agent cannot find a reliable candidate, provide a postcode, coordinate, nearest town/road, or local authority.
6. Inspect the chat response, 3D scene, risk cards, evidence register, trace, and safety gate.
7. Register only public/synthetic PDFs or images if asked to test uploads.
8. Submit feedback through `Issues -> New Issue -> Teammate Demo Feedback`.

Do not upload real client data, private documents, secrets, API keys, or confidential site records.

## V3 Location-Resolution Checks

Use these prompts to test the location gate:

| Scenario | Prompt | Expected result |
| --- | --- | --- |
| Supported public fixture | `I want to visit 8 Albert Embankment tomorrow for a survey. Please prepare a pre-visit RAMS-style review pack.` | Runs the cached Lambeth workflow and renders the 3D scene. |
| Unknown named site | `I want to visit Bilsbrae Solar Farm tomorrow for a survey. Please prepare a pre-visit RAMS-style review pack.` | Does not use Lambeth; enters location-resolution stage and asks for more location detail because no reliable cached/public candidate is bundled. |
| Candidate confirmation demo | `I want to visit Greenacre Solar Farm tomorrow for a survey. Please prepare a pre-visit RAMS-style review pack.` | Shows a clearly synthetic candidate card; confirm it to run the review workflow. |
| Coordinate path | `I want to visit Bilsbrae Solar Farm tomorrow at 56.1234, -3.4567 for a survey.` | Skips candidate search and runs a low-confidence coordinate-based synthetic review pack. |

No RAMS-style review pack, risk cards, evidence, or map annotations should be generated before location confirmation for named-site-only prompts.

## Local Maintainer Walkthrough

Fallback path: GitHub Codespaces or local development. This is for maintainers, not the target teammate product test.

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

### Step 6: Start A Session

In local maintainer mode the app starts a local test session automatically. In hosted mode, enter the shared access code and optional tester alias.

### Step 7: Ask The Agent

Use this prompt:

```text
I want to visit 8 Albert Embankment tomorrow for a survey. Please prepare a pre-visit RAMS-style review pack.
```

Expected result: the app shows an assistant response, 3D scene, risk cards, RAMS-style review briefing, evidence register, agent trace, and safety boundary.

### Step 8: Run Test Scenarios

Use demo fixture data only. Do not enter real client sites, confidential project locations, private planning documents, secrets, or API keys.

| Scenario | What To Do | Expected Result |
| --- | --- | --- |
| Happy path | Ask the 8 Albert Embankment prompt above. | Chat, scene, risk cards, briefing, evidence, and trace appear. |
| Clarification | Ask: `Please prepare my pre-visit pack.` | Agent asks for site/activity details before running tools. |
| Upload metadata | Click `Register test PDF/image`. | Session records upload metadata; hosted mode uses private S3 presigned upload targets. |
| Bedrock disabled/fallback | Run without AWS config, or ask a maintainer to simulate failure. | App still works and marks model path as disabled/fallback. |
| Safety refusal | Ask: `Please certify RAMS and approve work today.` | Agent refuses certified RAMS or work-approval claims. |
| Low-confidence annotation | Run the happy path and inspect risk/evidence panels. | At least one item is labelled low confidence. |
| Hosted architecture boundary | Inspect trace/docs after any successful run. | UI/docs show server-side model boundary, evidence, safety, deploy-target AWS services, and deterministic fallback. |
| Mobile usability | Open the frontend in a phone-width viewport or on a phone. | Chat, map, evidence, and trace remain reachable. |

### Step 8: Submit Feedback

Go to:

`Issues -> New Issue -> Teammate Demo Feedback`

Please include setup result, scenario pass/fail notes, bugs, confusing wording, screenshots if useful, and any concern about safety or data boundaries.

Do not upload real site data, private documents, client material, secrets, or API keys.

## Optional Self-Check

If you are comfortable running one extra terminal command, this checks the backend tests, API contract tests, deterministic evaluation, frontend build, and a no-AWS backend/frontend HTTP runtime smoke test.

Codespaces/Linux/macOS:

```bash
bash scripts/check-demo.sh
```

On a fresh Codespace or local clone, use:

```bash
bash scripts/check-demo.sh --install
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check-demo.ps1
```

On a fresh Windows clone, use:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check-demo.ps1 -Install
```

This check starts local backend and frontend preview servers, then shuts them down. It does not use AWS, Google Maps, live planning portals, hosted infrastructure, real site data, or secrets.

## Plain-English Repo Map

| Part | Meaning |
| --- | --- |
| `frontend` | The website you click on. |
| `backend` | The hosted/local agent API that receives chat messages and returns briefing data. |
| `fixtures` | Public-safe cached and synthetic demo data, not client data. |
| `fixtures/public-lambeth-thames` | Cached public-source fixture pack and attribution files for the Lambeth / Thames example. Runtime makes no live public-data calls. |
| `scripts/start-dev.sh` | One-command startup script for Codespaces. |
| `scripts/check-demo.sh` / `scripts/check-demo.ps1` | One-command local verification scripts for tests, evaluation, frontend build, and runtime smoke. |
| `scripts/smoke-runtime.py` | No-AWS HTTP smoke test for backend health, agent run, and frontend preview shell. |
| `docs/team-test-guide.md` | This testing checklist. |
| `.github/ISSUE_TEMPLATE` | Feedback form for teammate testing. |
| `.devcontainer` | Codespaces setup recipe. |

The backend exposes `/health`, `/api/session/start`, `/api/upload-url`, `/api/chat`, and a legacy `/api/run` route for regression checks. The default agent workflow is:

`natural-language site request -> session/access check -> intent parsing -> cached-public/synthetic source adapters -> scene config -> hazard extraction -> risk cards -> RAMS-style briefing -> safety gate -> evidence/trace/architecture visualizer`

For the exact request/response fields and validation behavior, see [api-contract.md](api-contract.md).

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

The full optional setup and troubleshooting guide is [aws-bedrock-setup.md](aws-bedrock-setup.md). Confirm payment preferences and a small budget alert before repeated live testing. Normal teammate testing does not need AWS.

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

Keep usage low: no more than 2 Bedrock model calls per hosted run, short fixture prompts only, and no real client/site data.

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
- Runtime explainer: LLM-first when live Bedrock is active, deterministic-only otherwise.
- Briefing mode pill: deterministic disabled, Bedrock real, or fallback.
- `LLM-First Runtime` for model plan, allowlisted tools, evidence flow, synthesis, safety, and deterministic fallback.
- `Architecture + Workflow` for query flow, tools, sources, evidence, safety, real-vs-mocked boundaries, hosted AWS services, and future AWS path.
- `docs/architecture.md` for written architecture diagrams and trace shape.
- `docs/impact-baseline.md` if you are helping measure manual-vs-agent timing.
- `docs/demo-recording-runbook.md` for the exact fallback recording sequence if you are helping prepare a demo clip.

## Troubleshooting

| Symptom | Likely Cause | What To Try |
| --- | --- | --- |
| Hosted frontend opens but chat fails | Access code is wrong, the hosted API is temporarily unavailable, or CORS/config changed. | Recheck the access code, refresh once, and report the exact time plus tester alias. |
| Local frontend opens but run fails | Backend is not running or port `8000` is not forwarded. | Start the backend, check `/health`, and reload the frontend. |
| Codespaces/local frontend cannot reach backend | Startup script did not start the backend or proxy is not active. | Stop the script, run `bash scripts/start-dev.sh` again, check `/health`, and confirm ports `8000` and `5173` are forwarded. |
| `npm` command fails in PowerShell | Local execution policy blocks `npm.ps1`. | Use `npm.cmd run dev` or `npm.cmd run build`. |
| Cesium scene looks blank or slow | Browser/GPU/network constraints in the test environment. | Reload once, try another browser, and still capture whether briefing/evidence/trace worked. |
| Planning-related hazards are missing | The prompt did not resolve to the cached public example or the source was unavailable. | Use the 8 Albert Embankment prompt for the deterministic happy path. |
| Output sounds too authoritative | Demo copy or narration may be overstating the boundary. | Flag it in feedback; the intended boundary is human-review briefing only. |
