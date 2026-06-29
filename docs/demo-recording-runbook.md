# Demo Recording Runbook

Use this runbook to create a reliable fallback recording for teammates, mentors, judges, or submission review.

The recording should prove the demo workflow, not the presenter's memory. Keep it public-safe: use fixture data only, avoid private project names, and do not claim certified RAMS, emergency guidance, work approval, or production deployment.

## Pre-Recording Checks

Before recording:

1. Pull the latest `main`.
2. Run the standard check:

   ```bash
   bash scripts/check-demo.sh
   ```

   On Windows:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/check-demo.ps1
   ```

3. Confirm GitHub Actions is green for the latest commit.
4. Start the app:

   ```bash
   bash scripts/start-dev.sh
   ```

5. Open the frontend on port `5173`.
6. Use only the default `Lambeth public cache` or `Synthetic default` demo data.

If the standard check fails, record the failure and do not use the recording as a final proof asset.

## Primary 90-Second Take

| Time | Screen Action | Required Proof |
| --- | --- | --- |
| 0-10s | Open the app with `Data pack` set to `Lambeth public cache`. | Show this is the cached public fixture path, not private data. |
| 10-25s | Click `Run`. | Briefing mode is visible; no AWS is required for the default path. |
| 25-40s | Pan attention across the 3D scene and annotations. | Spatial risk prompts are visible in the scene. |
| 40-55s | Show Evidence Register and Agent Trace. | Evidence items, source/status labels, and tool statuses are inspectable. |
| 55-68s | Show `Architecture + Workflow`. | Query flow, tool timeline, data sources, safety gate, real-vs-mocked boundary, and AWS path are visible. |
| 68-82s | Click `Safety test`. | Unsafe certified RAMS/work-approval request is blocked. |
| 82-90s | Reset or switch to `Synthetic default`. | Fallback path remains available. |

Recommended narration: use [demo-proof.md](demo-proof.md) as the source script.

## Fallback Takes

Record these shorter clips if time allows. They help if the main demo fails or a judge asks for proof.

| Clip | Action | Acceptance |
| --- | --- | --- |
| Missing planning | Turn off `Planning fixture`, then click `Run`. | Trace shows planning warning and briefing states the limitation. |
| Map fallback | Turn on `Map fallback`, then click `Run`. | Trace shows geospatial fallback and the app still returns a briefing. |
| Bedrock disabled | Leave `Bedrock` on while backend is no-AWS default. | Trace shows Bedrock disabled/fallback and deterministic briefing remains available. |
| Low confidence | Run the default case and inspect annotations/evidence. | At least one low-confidence item is visible. |
| API proof | Show `/health` or run the one-command check. | Backend returns ok or check stack passes. |

## Pass / Fail Criteria

The recording is usable if it shows:

- app loads from a clean browser tab;
- default run completes;
- 3D scene or fallback scene area is visible;
- briefing, evidence, trace, and architecture visualizer are visible;
- safety refusal is shown;
- real/cached/mocked/fallback/future boundaries are stated or visible;
- no real client data, private documents, secrets, or access-controlled materials appear.

The recording is not usable as final proof if:

- the app fails to load or the backend is unavailable;
- evidence or trace is skipped entirely;
- the safety boundary is not shown;
- the narration claims certified RAMS, work approval, emergency guidance, live planning extraction, or production deployment;
- private or real site/client data appears.

## Recording Notes

- Keep the browser zoom at a readable level.
- Use a desktop viewport first. Mobile proof can be a separate clip.
- Keep terminal windows out of the recording unless showing the check result.
- Do not show AWS account pages, credentials, billing pages, SSO cache, `.env`, API keys, or private War Room notes.
- If live Bedrock is demonstrated, state that it is optional and budget-gated; default teammate testing remains no-AWS.

## File Naming

Use clear names if saving multiple clips:

- `3d-rams-primary-90s-demo.mp4`
- `3d-rams-safety-refusal.mp4`
- `3d-rams-map-fallback.mp4`
- `3d-rams-missing-planning.mp4`
- `3d-rams-check-result.mp4`

Do not commit video files to the repo unless explicitly approved. Keep recordings in the chosen submission or sharing location.
