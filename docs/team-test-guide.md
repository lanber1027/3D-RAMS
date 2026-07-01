# Team Test Guide

Use this guide to test the Demo1 flow before judging or submission. The primary dogfood path is ASI/ASI:ONE or the hosted FieldBrief entry simulation when access exists. The local no-AWS path remains the baseline fallback: it should run with public fixtures only, without Google Maps keys, Cesium ion tokens, live planning portals, client data, or real site data. Bedrock mode is available only when the AgentCore runtime has AWS credentials and `ENABLE_BEDROCK=true`; deterministic fallback remains available.

3D-RAMS turns a site request into an inspectable 3D pre-visit briefing pack. The current dogfood flow is:

`ASI/ASI:ONE or hosted FieldBrief entry -> signed proxy -> asi_one_entry_agent -> rams_supervisor_runtime -> Harness subagents/shared tools -> run + structuredReport + delivery -> caseId report lookup -> frontend visualization/report lookup`.

The default fixture path uses the cached `public-lambeth-thames` pack for a Lambeth / Thames public-data example anchored on 8 Albert Embankment. It does not call live Planning Data, OpenStreetMap, Environment Agency, Lambeth, TfL, Google, or OS services during the demo.

1. coordinate input;
2. selected fixture-pack lookup;
3. cached-public, synthetic, or fallback geospatial features;
4. Cesium scene configuration;
5. cached-public or synthetic planning/context notes;
6. candidate hazard extraction;
7. 3D annotations;
8. RAMS-style briefing;
9. optional Bedrock briefing generation;
10. safety gate;
11. evidence register, trace, and architecture visualizer.

This is not certified RAMS, emergency guidance, work approval, or a competent-person replacement. Treat all output as a demo briefing for human review.

## Hosted ASI/AgentCore Dogfood

Use this path first when a maintainer has provided hosted access.

What you need:

- the hosted 3D-RAMS frontend URL or ASI/ASI:ONE entry access;
- access to the signed entry proxy already configured by the project team;
- demo-only public fixture input, not private site or client material.

### Step 1: Open The Hosted Entry

Open the hosted frontend or ASI/ASI:ONE entry supplied by the project team. The hosted frontend should be configured with `VITE_CLOUD_ENTRY_PROXY_URL` and should call the signed proxy, not local `/agentcore/invocations`.

### Step 2: Start A Demo Request

Use the default public Lambeth example or a safe demo request such as:

```text
Review 8 Albert Embankment for a survey pre-visit briefing.
```

Expected behavior: the entry agent confirms or clarifies the site, area scope, and goal before supervisor launch.

### Step 3: Confirm And Review Output

After confirmation, expected output includes a concise delivery summary, `caseId`, report link or case page, 3D visualization payload, evidence register, trace, safety boundary, and structured report data.

### Step 4: Check Report Lookup

Open the case/report link if available. The lookup should use the signed entry proxy and `caseId` report access context. `caseId` is a correlation id, not a bearer secret; production access is ASI/ASI:ONE identity-bound.

### Step 5: Optional Hosted Smoke

Maintainers can run the hosted parity smoke when cloud resources are configured:

```bash
RAMS_HOSTED_FRONTEND_URL=https://<amplify-app-url> \
RAMS_HOSTED_ENTRY_URL=https://<signed-proxy-domain>/invoke \
python3 scripts/hosted-agentcore-asio-smoke.py
```

This smoke covers entry clarification, confirmed supervisor launch, report-store write, identity-bound lookup behavior, authorized/denied material references, runtime mode assertions, and public-safe output.

## Local Fallback Codespaces Walkthrough

Use this when hosted ASI/ASI:ONE access is unavailable, slow, or out of scope. You do not need to install Python, Node, AWS tools, Google tools, or map keys locally if Codespaces works for your GitHub account.

What you need:

- a GitHub account with Codespaces access available for your account or plan;
- a web browser;
- repo URL: <https://github.com/Capitano00/3D-RAMS>.

### Step 1: Open The Repo

Open:

<https://github.com/Capitano00/3D-RAMS>

You should see folders such as `.devcontainer`, `app`, `frontend`, `docs`, `fixtures`, and `scripts`.

### Step 2: Create A Codespace

On the GitHub repo page, click:

`Code -> Codespaces -> Create codespace on <branch being tested>`

GitHub will open a browser-based VS Code-like workspace. It may look technical, but you only need the terminal once.

### Step 3: Wait For Setup

Wait until Codespaces finishes preparing the workspace. The devcontainer setup runs:

```bash
bash scripts/start-dev.sh --install-only
```

That pre-installs AgentCore and frontend dependencies.

### Step 4: Open The Terminal

Inside Codespaces, use the terminal at the bottom of the screen. If it is not visible, open:

`Terminal -> New Terminal`

Paste:

```bash
bash scripts/start-dev.sh
```

This starts the AgentCore runtime on port `8080` and the Vite frontend on port `5173`.

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
The `Data pack` control should show `Lambeth public cache` by default.

### Step 7: Run Test Scenarios

Use demo fixture data only. Do not enter real client sites, confidential project locations, private planning documents, secrets, or API keys.

| Scenario | What To Do | Expected Result |
| --- | --- | --- |
| Happy path | Leave defaults and click `Run`. | Scene, annotations, briefing, evidence, trace, and visualizer appear. |
| Cached public pack | Leave `Data pack` as `Lambeth public cache`, then click `Run`. | Evidence includes cached Planning Data / flood context and OSM-style access context with source and freshness labels. |
| Synthetic fallback pack | Change `Data pack` to `Synthetic default`, then click `Run`. | App still works using the original synthetic fixture path. |
| Missing planning fixture | Turn off `Planning fixture`, then click `Run`. | App still works and explains planning evidence limitations. |
| Map fallback | Turn on `Map fallback`, then click `Run`. | Trace shows geospatial loading using fallback. |
| Bedrock disabled/fallback | Leave `Bedrock` on, but run without AWS config, or ask a project maintainer to simulate failure. | App still works; trace shows Bedrock as disabled or fallback and keeps deterministic briefing. |
| Safety refusal | Click `Safety test`. | Agent refuses certified RAMS or work-approval claims. |
| Low-confidence annotation | Run the default case and inspect limitations/annotations. | At least one item is labelled low confidence. |
| Architecture visualizer | Run any successful scenario and inspect `Architecture + Workflow`. | UI shows query flow, tools, sources, evidence, safety, real-vs-mocked boundaries, and future AWS path. |
| Mobile usability | Open the frontend in a phone-width viewport or on a phone. | Run controls remain reachable, proof surfaces are readable, and no primary action is blocked. |

### Step 8: Submit Feedback

Go to:

`Issues -> New Issue -> Teammate Demo Feedback`

Please include setup result, scenario pass/fail notes, bugs, confusing wording, screenshots if useful, and any concern about safety or data boundaries.

Do not upload real site data, private documents, client material, secrets, or API keys.

## Optional Self-Check

If you are comfortable running one extra terminal command, this checks the AgentCore tests, invocation contract, deterministic evaluation, frontend build, and a no-AWS AgentCore/frontend HTTP runtime smoke test.

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

This check starts local AgentCore and frontend preview servers, then shuts them down. It does not use AWS, Google Maps, live planning portals, hosted infrastructure, real site data, or secrets. It verifies the fallback/baseline path, not hosted ASI/ASI:ONE access.

## Plain-English Repo Map

| Part | Meaning |
| --- | --- |
| `frontend` | The website you click on. |
| `app/rams_supervisor_runtime` | The AgentCore runtime that receives the coordinate and returns briefing data. |
| `fixtures` | Public-safe cached and synthetic demo data, not client data. |
| `fixtures/public-lambeth-thames` | Cached public-source fixture pack and attribution files for the Lambeth / Thames example. Runtime makes no live public-data calls. |
| `scripts/start-dev.sh` | One-command startup script for Codespaces. |
| `scripts/check-demo.sh` / `scripts/check-demo.ps1` | One-command local verification scripts for tests, evaluation, frontend build, and runtime smoke. |
| `scripts/smoke-runtime.py` | No-AWS HTTP smoke test for AgentCore health, invocation, and frontend preview shell. |
| `scripts/hosted-agentcore-asio-smoke.py` | Hosted ASI/AgentCore parity smoke when signed proxy and cloud resources are configured. |
| `docs/team-test-guide.md` | This testing checklist. |
| `.github/ISSUE_TEMPLATE` | Feedback form for teammate testing. |
| `.devcontainer` | Codespaces setup recipe. |

The AgentCore runtime exposes `/ping` and `/invocations`. The default agent workflow is:

`coordinate or data-pack input -> fixture-pack lookup -> cached-public/synthetic features -> scene config -> cached-public/synthetic planning context -> hazard extraction -> annotations -> briefing -> safety gate -> evidence/trace/architecture visualizer`

For the AgentCore invocation fields and validation behavior, see [api-contract.md](api-contract.md).

## Local Setup

Run this only if hosted access and Codespaces are unavailable or slow.

AgentCore runtime:

```bash
agentcore dev --runtime rams_supervisor_runtime --skip-deploy --no-browser --no-traces --logs --port 8080
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

AgentCore runtime environment:

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

If the UI cannot run, confirm the AgentCore runtime health check:

```bash
curl http://localhost:8080/ping
```

Expected response includes:

```json
{"status":"Healthy"}
```

## What Judges Or Teammates Should Inspect

- The 3D scene and annotations after a run.
- The RAMS-style briefing and its limitations.
- Evidence register entries and source labels.
- Trace rows with tool names and statuses.
- Briefing mode pill: deterministic disabled, Bedrock real, or fallback.
- `Architecture + Workflow` for query flow, tools, sources, evidence, safety, real-vs-mocked boundaries, and future AWS path.
- `docs/architecture.md` for written architecture diagrams and trace shape.
- `docs/impact-baseline.md` if you are helping measure manual-vs-agent timing.
- `docs/demo-recording-runbook.md` for the exact fallback recording sequence if you are helping prepare a demo clip.

## Troubleshooting

| Symptom | Likely Cause | What To Try |
| --- | --- | --- |
| Frontend opens but run fails | AgentCore runtime is not running or port `8080` is not forwarded. | Start the runtime, check `/ping`, and reload the frontend. |
| Codespaces frontend cannot reach AgentCore | Startup script did not start AgentCore or the Vite proxy is not active. | Stop the script, run `bash scripts/start-dev.sh` again, check `/ping`, and confirm ports `8080` and `5173` are forwarded. |
| `npm` command fails in PowerShell | Local execution policy blocks `npm.ps1`. | Use `npm.cmd run dev` or `npm.cmd run build`. |
| Cesium scene looks blank or slow | Browser/GPU/network constraints in the test environment. | Reload once, try another browser, and still capture whether briefing/evidence/trace worked. |
| Planning-related hazards are missing | `Planning fixture` is disabled. | Re-enable `Planning fixture` for the happy path. |
| Output sounds too authoritative | Demo copy or narration may be overstating the boundary. | Flag it in feedback; the intended boundary is human-review briefing only. |
