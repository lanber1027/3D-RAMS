# MVP Readiness

This page is a public-safe readiness snapshot for teammates, judges, and contributors.

3D-RAMS is ready for ASI/ASI:ONE + AgentCore dogfood when hosted access is available, with a no-AWS local path kept as the baseline verification and fallback demo. It is not a certified RAMS product, live planning portal product, emergency tool, or production deployment.

## Current Status

| Area | Status | Evidence |
| --- | --- | --- |
| ASI/AgentCore dogfood path | Ready with access prerequisites | Hosted entry should follow `ASI/ASI:ONE or FieldBrief simulation -> signed proxy -> asi_one_entry_agent -> rams_supervisor_runtime -> Harness subagents/tools -> structuredReport/run/delivery -> caseId lookup`. See [api-contract.md](api-contract.md) and [amplify-hosting.md](amplify-hosting.md). |
| Entry and report lookup contract | Implemented for current dogfood | `caseId` correlation, entry-agent launch, report-store write/lookup, and identity-bound access placeholders are documented in [api-contract.md](api-contract.md). |
| Local app startup | Baseline fallback | Codespaces/start script documented in [team-test-guide.md](team-test-guide.md). |
| AgentCore local invocation API | Verified | `/ping`, `/invocations`, request normalization, and output envelope are covered by AgentCore tests. See [api-contract.md](api-contract.md). |
| Agent workflow | Verified in deterministic and smoke modes | `scripts/evaluate-demo.py` checks nine scenarios; hosted parity smoke is available once cloud resources and ASI/proxy access are configured. |
| Frontend build | Verified | `scripts/check-demo.sh` and CI run the production build. |
| HTTP runtime smoke | Verified | One-command checks start AgentCore and frontend preview, then verify `/ping`, `/invocations`, and the frontend shell. |
| Public fixture pack | Ready for demo use | `public-lambeth-thames` cached fixture uses public-safe source metadata and no live runtime calls. |
| Architecture visualizer | Ready for demo use | UI and [architecture.md](architecture.md) show tool sequence, boundaries, trace, and AWS path. |
| Safety gate | Verified for demo boundary | Unsafe certified RAMS/work-approval requests are blocked in tests and evaluation. |
| CI | Active | GitHub Actions runs the local verification stack on push and pull request. |
| Live Bedrock | Optional dogfood path | Available only when explicitly configured; deterministic fallback remains the safe baseline. |

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

These checks compile code, run AgentCore tests, run deterministic evaluation, build the frontend, and start a no-AWS AgentCore/frontend HTTP smoke test. They do not require AWS credentials, Google keys, Cesium ion tokens, live planning portals, hosted infrastructure, real site data, or private documents. They prove the repository baseline, not hosted ASI/ASI:ONE access.

## Hosted Dogfood Check

When ASI/ASI:ONE or hosted FieldBrief access exists, test the current product-shaped path through the signed entry proxy:

```bash
RAMS_HOSTED_FRONTEND_URL=https://<amplify-app-url> \
RAMS_HOSTED_ENTRY_URL=https://<signed-proxy-domain>/invoke \
python3 scripts/hosted-agentcore-asio-smoke.py
```

This check starts at `asi_one_entry_agent`, verifies supervisor launch, report-store write, identity-bound lookup behavior, authorized/denied material references, and public-safe output. It needs operator-provided hosted access and environment configuration, so it is not part of the default no-AWS baseline.

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
| Bedrock | Optional model-assisted briefing when configured; deterministic fallback remains valid. |
| DynamoDB report store | Optional `caseId` report persistence when configured; lookup requires ASI/ASI:ONE identity or authorized session context. Local no-AWS demos skip persistence and may use an explicit dev-local lookup context. |
| Hosted entry | ASI/ASI:ONE or hosted FieldBrief simulation through the signed proxy; direct `/api/chat`, `/api/run`, `/api/session/start`, and `/api/upload-url` are not canonical. |
| AWS production path | AgentCore runtimes, Harnesses, signed proxy, and optional report store are dogfood surfaces; S3, CloudWatch, Guardrails, and deeper deployment hardening remain future work. |
| Safety/RAMS | Human-review briefing only; not certified RAMS, work approval, or emergency guidance. |
| Impact metrics | [impact-baseline.md](impact-baseline.md) is ready; numeric speed-up claims still need a completed and reviewed timed run. |

## Before Public Demo Or Submission

- Prefer a hosted ASI/ASI:ONE dogfood run when access exists, then run `bash scripts/check-demo.sh` or the PowerShell equivalent as the repository baseline.
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
| ASI/ASI:ONE hosted access | Project team | Required for primary dogfood path; local no-AWS path remains fallback. |
| Live Harness output-contract smoke (#12) | Project team | Remaining gate before claiming full hosted Harness contract confidence. |
| Teammate feedback | Project team | Ready to collect through GitHub issue template after hosted or fallback run. |
| Stopwatch baseline | Demo reviewer | Worksheet ready; measured run pending before numeric speed-up claims. |
| Fallback recording | Demo reviewer | Runbook ready; actual recording pending before final demo package. |
| AWS budget/payment guardrail | AWS account owner | Pending before heavy live AWS use. |
| Hosted public endpoint | Project team | Dogfood path when configured; public submission status depends on access, budget, and smoke evidence. |
