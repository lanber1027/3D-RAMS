# 3D-RAMS Agent Instructions

## Public Repo Boundary

This repository is public hackathon demo code. Do not commit:

- API keys, AWS credentials, Google Maps keys, or Cesium ion tokens;
- private planning notes, career strategy, private messages, or confidential documents;
- client data or real project documents unless explicitly cleared and anonymised.

Keep strategic notes and private decisions in the local war-room workspace, not here.

## Build Posture

- Keep Demo1 runnable without cloud credentials or live map keys.
- Prefer deterministic fixtures until a live integration is clearly valuable.
- Clearly label real, mocked, fallback, and future AWS components.
- Preserve the safety boundary: no certified RAMS, emergency guidance, or approval-to-work claims.
- Keep trace and evidence objects inspectable in the UI and easy to map to CloudWatch later.

## Verification

Before pushing changes, run the narrowest relevant checks:

```bash
python -m compileall backend/app backend/tests
python -m unittest discover -s backend/tests -q
cd frontend && npm run build
```

If a check cannot be run, record the blocker clearly.

