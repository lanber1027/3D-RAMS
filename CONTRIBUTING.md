# Contributing

3D-RAMS is a public hackathon demo. Keep contributions narrow, reviewable, and safe for teammates and judges to inspect.

## Public Boundary

Do not commit:

- API keys, AWS credentials, SSO cache files, Google Maps keys, Cesium ion tokens, or `.env` files;
- real client data, private site records, private planning documents, screenshots from confidential projects, or access-controlled material;
- private strategy notes, career/application framing, private messages, or local war-room coordination files.

Use only the included demo fixtures unless a public-safe source has been reviewed and attributed.

## Safety Boundary

3D-RAMS produces a human-review pre-visit briefing pack. It does not produce certified RAMS, emergency response guidance, work approval, legal advice, or a competent-person replacement.

Changes must preserve that boundary in code, docs, UI text, test data, and generated outputs.

## Before Changing Code

Check the current state:

```bash
git status --short
```

Keep changes scoped to one purpose. If a change touches backend, frontend, docs, fixtures, and workflow at once, split it unless the parts are tightly coupled.

## Verification

The standard check compiles backend/scripts, runs backend and API tests, runs deterministic evaluation, builds the frontend, and starts a no-AWS backend/frontend HTTP smoke test.

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

If a check cannot be run, state exactly what was skipped and why.

## Pull Request Or Handoff Checklist

Include:

- what changed;
- files or areas touched;
- real, mocked, fallback, or future components affected;
- checks run and results;
- checks skipped and why;
- safety/data-boundary risks;
- known blockers or follow-up work.

## Issue Feedback

Use the `Teammate Demo Feedback` issue template for testing feedback. Do not paste secrets, private documents, real site data, or API keys into issues.
