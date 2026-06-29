---
name: Teammate Demo Feedback
about: Report setup results, scenario checks, bugs, and confusing parts from testing Demo1
title: "[Team Test]: "
labels: team-test, feedback
assignees: ""
---

## Environment

- Test mode: Codespaces / local
- Browser:
- Operating system, if local:
- Did Codespaces work? Yes / No / Not tested
- Did setup work on the first try? Yes / No
- Frontend opened on port `5173`? Yes / No / Not tested
- Backend `/health` returned ok? Yes / No / Not tested

## Self-Check Result

Optional but useful if you are comfortable using the terminal.

- Did `bash scripts/check-demo.sh` pass? Yes / No / Not tested
- If testing on Windows, did `powershell -ExecutionPolicy Bypass -File scripts/check-demo.ps1` pass? Yes / No / Not tested
- If it failed, paste the last 10-20 lines of output here. Do not include secrets, keys, private documents, or real site data.

## Scenario Results

| Scenario | Pass / Fail / Not Tested | Notes |
| --- | --- | --- |
| Happy path | | |
| Cached public pack | | |
| Synthetic fallback pack | | |
| Missing planning fixture | | |
| Map fallback | | |
| Bedrock disabled/fallback | | |
| Safety refusal | | |
| Low-confidence annotation | | |
| Architecture visualizer | | |
| Mobile usability | | |

## Bugs Or Failures

Describe any broken behavior, console errors, backend errors, blank views, slow steps, or confusing results.

## Confusing Parts

What was unclear in setup, UI wording, scenario flow, evidence, trace, safety boundary, or architecture visualizer?

## Screenshots Or Recording

Optional links or attachments. Do not include secrets, private documents, client material, real site data, or API keys.

## Safety And Data Boundary Check

Did anything appear to claim certified RAMS, emergency guidance, work approval, or use of real client/site data?

- Yes / No
- Notes:

Did you enter only demo fixture data?

- Yes / No
- Notes:

## Suggested Improvement

What is the highest-impact change before the demo or submission?
