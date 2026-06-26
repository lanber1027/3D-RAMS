# Team Test Guide

Use this guide to test the Demo1 flow before judging or submission. The app is intentionally local-first: it should run with the public fixtures only, without AWS credentials, Google Maps keys, Cesium ion tokens, live planning portals, client data, or real site data.

## What To Test

3D-RAMS turns a coordinate into an inspectable 3D pre-visit briefing pack:

1. coordinate input;
2. location fixture lookup;
3. mocked geospatial features;
4. Cesium scene configuration;
5. synthetic planning fixture;
6. candidate hazard extraction;
7. 3D annotations;
8. RAMS-style briefing;
9. safety gate;
10. evidence register, trace, and architecture visualizer.

This is not certified RAMS, emergency guidance, work approval, or a competent-person replacement. Treat all output as a demo briefing for human review.

## Codespaces Setup

1. Open the GitHub repository in Codespaces.
2. Wait for the devcontainer setup to finish. It installs backend and frontend dependencies.
3. Open a terminal and start both backend and frontend:

```bash
bash scripts/start-dev.sh
```

4. In the Codespaces Ports tab, open the forwarded frontend port, usually `5173`.
5. Confirm the backend health check if the UI cannot run:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status":"ok","service":"3d-rams-demo1"}
```

If the one-command startup fails in Codespaces, use this two-terminal fallback.

Terminal 1:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Terminal 2:

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

## Local Fallback Setup

Run this if Codespaces is unavailable or slow.

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

## Scenario Checklist

Use demo fixture data only. Do not enter real client sites, confidential project locations, private planning documents, secrets, or API keys.

| Scenario | Steps | Expected Result | Pass/Fail Notes |
| --- | --- | --- | --- |
| Happy path | Leave default options on and click `Run`. | 3D scene, annotations, briefing, evidence register, and trace are returned. | |
| Missing planning fixture | Turn off `Planning fixture`, then click `Run`. | Briefing still returns and states that planning evidence was unavailable or document-derived hazards may be missing. | |
| Map fallback | Turn on `Map fallback`, then click `Run`. | Trace shows `load_geospatial_features` with `fallback` status and the UI still produces a briefing. | |
| Safety refusal | Click `Safety test`. | Safety gate blocks certified RAMS, work approval, or emergency guidance behavior. | |
| Low-confidence annotation | Run the default scenario and inspect scene annotations or briefing limitations. | At least one inferred imagery/geospatial item is labelled low confidence. | |
| Architecture visualizer | Run any successful scenario and inspect `Architecture + Workflow`. | UI shows tool sequence, current trace status, real-vs-mocked boundaries, and AWS production path as future architecture. | |

## What Judges Or Teammates Should Inspect

- The 3D scene and annotations after a run.
- The RAMS-style briefing and its limitations.
- Evidence register entries and source labels.
- Trace rows with tool names and statuses.
- `Architecture + Workflow` for the agent sequence, real-vs-mocked boundary, and AWS path.
- `docs/architecture.md` for the written architecture diagrams and trace shape.

## Troubleshooting

| Symptom | Likely Cause | What To Try |
| --- | --- | --- |
| Frontend opens but run fails | Backend is not running or port `8000` is not forwarded. | Start the backend, check `/health`, and reload the frontend. |
| Codespaces frontend cannot reach backend | Startup script did not start the backend or proxy is not active. | Stop the script, run `bash scripts/start-dev.sh` again, check `/health`, and confirm ports `8000` and `5173` are forwarded. |
| `npm` command fails in PowerShell | Local execution policy blocks `npm.ps1`. | Use `npm.cmd run dev` or `npm.cmd run build`. |
| Cesium scene looks blank or slow | Browser/GPU/network constraints in the test environment. | Reload once, try another browser, and still capture whether briefing/evidence/trace worked. |
| Planning-related hazards are missing | `Planning fixture` is disabled. | Re-enable `Planning fixture` for the happy path. |
| Output sounds too authoritative | Demo copy or narration may be overstating the boundary. | Flag it in feedback; the intended boundary is human-review briefing only. |

## Feedback Instructions

Create a GitHub issue with the teammate feedback template after testing. Include:

- environment: Codespaces or local, browser, operating system if local;
- whether setup worked on the first try;
- pass/fail for each scenario in the checklist;
- screenshots or screen recording links if useful;
- bugs, confusing parts, slow steps, or visual problems;
- any wording that sounds like certified RAMS, work approval, emergency guidance, or real-data use.

Screenshots are optional. Do not attach secrets, private documents, real client material, or real site data.
