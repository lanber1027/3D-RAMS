# MVP Readiness

This page is a public-safe readiness snapshot for teammates, judges, and contributors.

3D-RAMS is ready for hosted access-code teammate testing. It is not a certified RAMS product, live planning portal product, emergency tool, or production deployment.

Hosted V3.2 plus the Slice B Agent State UI are isolated on `feature/durable-runs-tool-loop` and currently power the access-code teammate test path after review-gated deployment.

## Current Status

Current evidence snapshot:

- GitHub Actions runs on `main` and pull requests; use the README badge or Actions tab for the latest public CI status.
- Full local no-AWS verification has passed with backend/API tests, deterministic evaluation, frontend build, and HTTP runtime smoke.
- Exact commit/run evidence is tracked privately by the project team so this public page does not need to change after every docs-only commit.

| Area | Status | Evidence |
| --- | --- | --- |
| Local app startup | Ready for teammate testing | Codespaces/start script documented in [team-test-guide.md](team-test-guide.md). |
| Backend API | Verified | `/health`, `/api/run`, request validation, and OpenAPI schema are covered by API contract tests. See [api-contract.md](api-contract.md). |
| Agent workflow | Verified in deterministic mode | `scripts/evaluate-demo.py` checks nine scenarios. |
| Frontend build | Verified | `scripts/check-demo.sh` and CI run the production build. |
| HTTP runtime smoke | Verified | One-command checks start backend and frontend preview, then verify `/health`, `/api/run`, and the frontend shell. |
| Public fixture pack | Ready for demo use | `public-lambeth-thames` cached fixture uses public-safe source metadata; live runtime calls occur only when live-map MVP flags are enabled. |
| Architecture visualizer | Ready for demo use | UI and [architecture.md](architecture.md) show tool sequence, boundaries, trace, and AWS path. |
| Safety gate | Verified for demo boundary | Unsafe certified RAMS/work-approval requests are blocked in tests and evaluation. |
| CI | Active | GitHub Actions runs the local verification stack on push and pull request. |
| Hosted Bedrock | Live in hosted MVP | Server-side Lambda calls Bedrock after access-code validation; deterministic fallback remains available. |
| Location confirmation | Verified in V3.2 tests | Named-site, postcode, and coordinate prompts enter a location-resolution stage and do not generate a site-specific review pack before confirmation or stronger location detail. |
| Arbitrary-site usefulness | Verified in V3.2 tests | Random name-only prompts ask for source evidence and may show a labelled provisional checklist; coordinate/postcode prompts use clean labels and site/activity-specific risk profiles. |
| Agent state UI | Live in hosted MVP | Shows latest route, pending user action, active run, storage mode, recent bounded session memory, and evaluator/quality-loop state. |

## One-Command Checks

Codespaces/Linux/macOS:

```bash
bash scripts/check-demo.sh
```

Fresh Codespace or local clone:

```bash
bash scripts/check-demo.sh --install
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check-demo.ps1
```

Fresh Windows clone:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check-demo.ps1 -Install
```

These checks compile code, run backend/API tests, run deterministic evaluation, build the frontend, and start a no-AWS backend/frontend HTTP smoke test. The deterministic checks do not require AWS credentials, Google keys, Cesium ion tokens, live planning portals, hosted infrastructure, real site data, or private documents. Live 3D MVP testing additionally requires a restricted `VITE_CESIUM_ION_TOKEN` and `ENABLE_LIVE_MAP_FEATURES=true`.

## Verified Scenarios

The deterministic evaluation runner covers:

- cached public happy path;
- synthetic fallback path;
- missing planning/context evidence;
- map/geospatial fallback;
- Bedrock requested while disabled;
- unsafe certified RAMS/work-approval request;
- low-confidence output visibility;
- architecture visualizer response contract;
- unknown fixture-pack fallback.

## What Is Still Demo-Scoped

| Area | Current Boundary |
| --- | --- |
| Planning data | Cached fixture by default; live Planning Data point-constraint lookup available in live-map MVP mode. |
| Public source freshness | Source metadata is visible, but the app does not refresh sources at runtime. |
| 3D map data | Real Cesium terrain/imagery/buildings with `VITE_CESIUM_ION_TOKEN`; labelled synthetic fallback without token. |
| Bedrock | Hosted server-side model-assisted planner/synthesis behind access-code validation; deterministic fallback remains available. |
| AWS hosted path | Amplify, API Gateway, Lambda, Bedrock, DynamoDB, S3 presign, and CloudWatch structured logs are live for MVP testing. |
| Agent memory | Bounded session memory and working state are implemented for the hosted MVP; long-term personal memory remains deferred. |
| AWS future path | Cognito, Guardrails, managed AgentCore Runtime/Memory, CloudWatch dashboards, API throttling/WAF, and richer live adapters remain deferred. |
| Safety/RAMS | Human-review briefing only; not certified RAMS, work approval, or emergency guidance. |
| Impact metrics | [impact-baseline.md](impact-baseline.md) is ready; numeric speed-up claims still need a completed and reviewed timed run. |

## Before Public Demo Or Submission

- Run `bash scripts/check-demo.sh` or the PowerShell equivalent.
- Confirm the latest GitHub Actions run is green.
- Use [demo-proof.md](demo-proof.md) for the 90-second script and recording checklist.
- Use [impact-baseline.md](impact-baseline.md) before making numeric speed-up claims.
- Use [demo-recording-runbook.md](demo-recording-runbook.md) for fallback recording acceptance criteria.
- Keep the demo on fixture data unless a new public-safe source adapter has been reviewed.
- State clearly what is real, cached, mocked, fallback, and future.
- Do not claim certified RAMS, emergency guidance, work approval, or production deployment.

## Remaining Gates

| Gate | Responsible Party | Status |
| --- | --- | --- |
| Teammate feedback | Project team | Ready to collect through GitHub issue template. |
| Stopwatch baseline | Demo reviewer | Worksheet ready; measured run pending before numeric speed-up claims. |
| Fallback recording | Demo reviewer | Runbook ready; actual recording pending before final demo package. |
| AWS budget/payment guardrail | AWS account owner | Complete for hosted MVP; monitor usage during teammate testing. |
| Hosted public endpoint | Project team | Live behind access-code gate; browser visual QA passed for the Agent State panel, and teammate confirmation is still needed for real user feedback. |
