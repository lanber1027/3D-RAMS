# Demo Proof Pack

This document is the public-safe demo proof for 3D-RAMS. It explains what to show, what the MVP proves, what remains mocked or cached, and how to avoid overstating the safety boundary.

## Demo Thesis

3D-RAMS turns fragmented pre-visit digital work into an inspectable review pack:

`site or coordinate -> cached source pack -> candidate hazards -> 3D annotations -> briefing -> evidence -> trace -> human review`

The MVP is not a certified RAMS product. It is a controlled briefing assistant for early scoping and review.

## 90-Second Script

| Time | Action | Narration |
| --- | --- | --- |
| 0-10s | Open the app with `Data pack` set to `Lambeth public cache`. | "This starts from a real public-data style problem: a site team has to inspect maps, planning context, flood indicators, access constraints, and source uncertainty before a visit." |
| 10-25s | Click `Run`. | "The agent loads a cached public-source pack for 8 Albert Embankment. It does not scrape live portals or use private data during the demo." |
| 25-40s | Point to the 3D scene and annotations. | "It turns source-backed review prompts into spatial annotations: flood-context review, access constraints, public interface, buried-services screening, and planning-history context." |
| 40-55s | Show Evidence Register and Trace. | "Every output is inspectable. The evidence register shows source IDs, freshness, confidence, and whether the data is cached-public, fallback, or mocked. The trace shows each tool step." |
| 55-70s | Show Architecture + Workflow. | "The visualizer explains data flow, tool calls, real-vs-mocked boundaries, and the future AWS path. This is designed as a production-shaped workflow, not a black-box chat answer." |
| 70-82s | Click `Safety test`. | "If a user asks for certified RAMS or work approval, the safety gate blocks the output. The product stays in human-review territory." |
| 82-90s | Reset or switch to synthetic fallback. | "The demo keeps fallback paths visible: cached public data, synthetic fallback, disabled Bedrock, and map fallback all remain testable." |

## Before / After Proof

Manual baseline:

- Open map, planning, flood, access, and document sources separately.
- Copy likely risks into notes.
- Track which source supported which claim.
- Decide which uncertainty needs human review.
- Turn the findings into a briefing.

MVP workflow:

- Select a known fixture pack or coordinate.
- Run one agent workflow.
- Inspect annotations, evidence, trace, source register, confidence labels, and safety decision in one place.

Conservative claim:

3D-RAMS does not prove end-to-end RAMS automation. It proves that the first-pass desk-review workflow can be compressed into an inspectable review pack while keeping source uncertainty and human review visible.

## Test Scenarios

For repeatable backend proof, run `python scripts/evaluate-demo.py` from the repo root. The runner forces no-AWS deterministic mode and checks the scenarios below plus unknown fixture-pack fallback. See [evaluation.md](evaluation.md).

| Scenario | How To Run | Proof Point |
| --- | --- | --- |
| Cached public pack | Leave `Data pack` as `Lambeth public cache`, click `Run`. | Shows realistic source register, evidence, confidence, and annotations. |
| Synthetic fallback | Change `Data pack` to `Synthetic default`, click `Run`. | Shows the workflow still runs without public fixture pack dependency. |
| Missing planning | Turn off `Planning fixture`, click `Run`. | Shows missing-data warning and degraded but usable output. |
| Map fallback | Turn on `Map fallback`, click `Run`. | Shows tool failure/fallback trace. |
| Bedrock disabled/fallback | Run without AWS config or simulate failure. | Shows deterministic briefing fallback. |
| Unsafe request | Click `Safety test`. | Shows blocked certified RAMS / work approval behavior. |
| Low confidence | Inspect annotations and evidence. | Shows uncertainty labels rather than hidden assumptions. |
| Architecture visualizer | Inspect `Architecture + Workflow`. | Shows tool flow, boundaries, and future production path. |

## What Is Real, Cached, Mocked, Or Future

| Area | Status |
| --- | --- |
| Backend agent loop | Real local Python workflow. |
| Frontend viewer | Real React/Cesium UI with token-free local overlay. |
| Lambeth fixture pack | Cached public-source demo pack with attribution and no live runtime calls. |
| Bedrock briefing | Optional live AWS call only when explicitly configured. |
| Planning portals/PDFs | Not scraped in MVP. |
| Google 3D / Earth | Not required in MVP. |
| CloudWatch, DynamoDB, S3, Guardrails, AgentCore | Future production path, not live MVP infrastructure. |

## Recording Checklist

- Start from a clean browser tab.
- Confirm `Data pack` is `Lambeth public cache`.
- Run the default scenario.
- Show the scene, evidence register, trace, visualizer, and safety boundary.
- Run `Safety test`.
- Switch to `Synthetic default` once to prove fallback.
- Avoid entering real client/site data.
- State clearly that cached public data is a demo fixture, not live operational advice.

## Safety Boundary

This demo does not certify RAMS, approve work, provide emergency guidance, or replace competent review. All output is for human pre-visit review.
