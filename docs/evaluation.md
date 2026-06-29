# Evaluation Proof

3D-RAMS includes a deterministic local evaluation runner for the Demo1 workflow.

The runner is designed for teammate testing, demo rehearsal, and sponsor/judge review. It proves that the backend agent can execute the core review workflow without live AWS, Google Maps, planning portal scraping, or private data.

## Run The Evaluation

From the repo root:

```bash
python scripts/evaluate-demo.py
```

Optional generated report:

```bash
python scripts/evaluate-demo.py --write docs/evaluation-results/latest.json
```

`latest.json` is intentionally ignored by Git because it is generated proof, not source documentation. Commit a curated snapshot only after manager and quality-review approval.

## Continuous Verification

GitHub Actions runs the same deterministic evaluation on pushes and pull requests, alongside backend compile checks, backend unit/API contract tests, the frontend production build, and a no-AWS HTTP runtime smoke test.

The CI workflow does not use AWS credentials, Google Maps keys, live planning portals, or hosted infrastructure.

Run the same local verification stack in Codespaces/Linux/macOS with:

```bash
bash scripts/check-demo.sh
```

Use `bash scripts/check-demo.sh --install` on a fresh Codespace or local clone.

On Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check-demo.ps1
```

On a fresh Windows clone:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check-demo.ps1 -Install
```

## Exit Codes

| Exit Code | Meaning |
| --- | --- |
| `0` | All scenario assertions passed. |
| `1` | Runner setup or execution error. |
| `2` | One or more scenario assertions failed. |

## Deterministic Mode

The runner forces:

- `ENABLE_BEDROCK=false`;
- no Bedrock mock response;
- no Bedrock unsafe mock response;
- no simulated Bedrock failure.

This keeps the evaluation stable and cheap. It also proves that the app remains useful when Bedrock is disabled or unavailable.

## Scenario Coverage

| Scenario | Proof |
| --- | --- |
| `cached_public_happy_path` | Default cached public Lambeth/Thames pack runs with evidence, annotations, trace, source links, and no live API calls. |
| `synthetic_happy_path` | The older synthetic fallback path still works without the public fixture pack. |
| `missing_planning_public_pack` | Disabling planning/context evidence produces a warning and usable degraded output. |
| `map_fallback_public_pack` | Simulated geospatial failure uses fallback data and exposes the fallback reason in the trace. |
| `bedrock_disabled_request_fallback` | A request for Bedrock in no-AWS mode returns deterministic briefing output and marks Bedrock as disabled. |
| `unsafe_request_blocked` | Certified RAMS/work-approval requests are blocked by the safety gate. |
| `low_confidence_visible` | Low-confidence evidence appears in annotations, evidence, and briefing limitations. |
| `architecture_visualizer_contract` | The architecture payload contains trace, sources, real-vs-mocked boundaries, safety gate, and future AWS path. |
| `unknown_fixture_pack_falls_back` | Unknown data-pack input safely falls back to synthetic defaults. |

## What This Proves

- The agent workflow is repeatable in local no-key mode.
- The backend and frontend preview can start over HTTP and serve the default no-AWS runtime path.
- Output remains inspectable through evidence, source IDs, trace steps, confidence labels, and safety decisions.
- The default demo uses cached public-safe fixture data and does not make live public-data calls.
- Bedrock is optional for the MVP and not required for teammate testing.
- The safety gate blocks certified RAMS, work approval, and emergency-style claims.

## What This Does Not Prove

- It does not prove production AWS deployment.
- It does not prove live planning portal extraction.
- It does not prove certified RAMS, emergency guidance, legal approval, or competent-person review.
- It does not prove full browser interaction or visual rendering by itself. Use the teammate guide and browser/mobile checks for UI proof.

## Public Safety Boundary

The evaluation uses demo fixtures and cached public-source metadata only. Do not add real client data, private site records, secrets, AWS credentials, API keys, or confidential planning documents to evaluation artifacts.
