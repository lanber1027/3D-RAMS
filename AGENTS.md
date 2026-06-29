# 3D-RAMS Agent Instructions

## Public Repo Boundary

This repository is public hackathon demo code. Do not commit:

- API keys, AWS credentials, Google Maps keys, or Cesium ion tokens;
- private planning notes, career strategy, private messages, or confidential documents;
- client data or real project documents unless explicitly cleared and anonymised.

Keep strategic notes and private decisions in the local war-room workspace, not here.

## Contributor Workflow

This repo is worked through bounded tasks. For each task, keep the change focused and hand it back with:

- task summary;
- files or areas changed;
- verification run;
- real vs mocked components affected;
- risks or blockers;
- recommended next action.

Large tasks should be split before implementation. Parallel changes are acceptable only when file ownership is non-overlapping.

## Review Expectations

Before merge, push, teammate share, or demo/submission use, changes should have a clear quality handoff:

- acceptance criteria covered;
- changed files match the assigned scope;
- relevant checks run, with skipped checks recorded;
- real vs mocked behavior still disclosed;
- no secrets, private notes, client data, or confidential planning content added;
- no certified RAMS, emergency, legal, financial, medical, or approval-to-work claims added;
- known risks, blockers, and recommended next action stated.

Small docs-only changes can use a lightweight review, but the public/private boundary still applies.

## Build Posture

- Keep Demo1 runnable without cloud credentials or live map keys.
- Prefer deterministic fixtures until a live integration is clearly valuable.
- Clearly label real, mocked, fallback, and future AWS components.
- Preserve the safety boundary: no certified RAMS, emergency guidance, or approval-to-work claims.
- Keep trace and evidence objects inspectable in the UI and easy to map to CloudWatch later.
- Keep public docs team-safe: no private strategy, career framing, private messages, client data, or local war-room coordination.

## Verification

Before pushing changes, run the standard local verification stack when practical:

The stack covers backend compile/tests, deterministic evaluation, frontend production build, and a no-AWS backend/frontend HTTP runtime smoke test.

```bash
bash scripts/check-demo.sh
```

On Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check-demo.ps1
```

If a check cannot be run, record the blocker clearly.
