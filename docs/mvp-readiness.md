# MVP Readiness

This page is a public-safe readiness snapshot for teammates, judges, and contributors.

3D-RAMS is ready for no-AWS teammate testing. It is not a certified RAMS product, live planning portal product, emergency tool, or production deployment.

## Current Status

| Area | Status | Evidence |
| --- | --- | --- |
| Local app startup | Ready for teammate testing | Codespaces/start script documented in [team-test-guide.md](team-test-guide.md). |
| AgentCore invocation API | Verified | `/ping`, `/invocations`, request normalization, and output envelope are covered by AgentCore tests. See [api-contract.md](api-contract.md). |
| Agent workflow | Verified in deterministic mode | `scripts/evaluate-demo.py` checks nine scenarios. |
| Frontend build | Verified | `scripts/check-demo.sh` and CI run the production build. |
| HTTP runtime smoke | Verified | One-command checks start AgentCore and frontend preview, then verify `/ping`, `/invocations`, and the frontend shell. |
| Public fixture pack | Ready for demo use | `public-lambeth-thames` cached fixture uses public-safe source metadata and no live runtime calls. |
| Architecture visualizer | Ready for demo use | UI and [architecture.md](architecture.md) show tool sequence, boundaries, trace, and AWS path. |
| Safety gate | Verified for demo boundary | Unsafe certified RAMS/work-approval requests are blocked in tests and evaluation. |
| CI | Active | GitHub Actions runs the local verification stack on push and pull request. |
| Live Bedrock | Optional local path | Available only when explicitly configured; deterministic fallback remains default. |

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

These checks compile code, run AgentCore tests, run deterministic evaluation, build the frontend, and start a no-AWS AgentCore/frontend HTTP smoke test. They do not require AWS credentials, Google keys, Cesium ion tokens, live planning portals, hosted infrastructure, real site data, or private documents.

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
| Planning data | Cached fixture only; no live planning portal scraping in MVP. |
| Public source freshness | Source metadata is visible, but the app does not refresh sources at runtime. |
| 3D map data | Token-free local Cesium view and fixture overlay; no Google Earth/3D Tiles. |
| Bedrock | Optional local model-assisted briefing only; no hosted public endpoint. |
| DynamoDB report store | Optional `caseId` report persistence when configured; local no-AWS demos skip it. |
| AWS production path | Architecture path only for S3, CloudWatch, Guardrails, and deeper AgentCore deployment hardening. |
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
| AWS budget/payment guardrail | AWS account owner | Pending before heavy live AWS use. |
| Hosted public endpoint | Project team | Deferred unless Codespaces fails for teammates or submission needs it. |
