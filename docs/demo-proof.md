# Demo Proof Pack

This document is the public-safe demo proof for 3D-RAMS. It explains what to show, what the MVP proves, what remains mocked or cached, and how to avoid overstating the safety boundary.

## Demo Thesis

3D-RAMS turns fragmented pre-visit digital work into an inspectable review pack:

`chat request -> site resolution -> source pack/tools -> candidate hazards -> 3D annotations -> briefing -> evidence -> trace -> human review`

The MVP is not a certified RAMS product. It is a controlled briefing assistant for early scoping and review.

## 90-Second Script

| Time | Action | Narration |
| --- | --- | --- |
| 0-10s | Open the hosted app URL, enter the shared test access code, and start a tester session. | "This starts as the product experience: a teammate or judge opens a browser URL and does not handle AWS credentials." |
| 10-25s | Send: `I want to visit 8 Albert Embankment tomorrow for a survey. Please prepare a pre-visit RAMS-style review pack.` | "The chat request drives the agent workflow. The backend resolves the site request, loads cached public-style context, and keeps Bedrock server-side when enabled." |
| 25-40s | Point to the 3D scene and annotations. | "It turns source-backed review prompts into spatial annotations: flood-context review, access constraints, public interface, buried-services screening, and planning-history context." |
| 40-55s | Show Evidence Register and Trace. | "Every output is inspectable. The evidence register shows source IDs, freshness, confidence, and whether the data is cached-public, fallback, or mocked. The trace shows each tool step." |
| 55-70s | Show Architecture + Workflow. | "The visualizer explains data flow, tool calls, real-vs-mocked boundaries, and the future AWS path. This is designed as a production-shaped workflow, not a black-box chat answer." |
| 70-82s | Send a safety-boundary prompt such as `Please certify this RAMS and approve the work today.` | "If a user asks for certified RAMS or work approval, the safety gate blocks the output. The product stays in human-review territory." |
| 82-90s | Send a fallback prompt for a made-up rural site or disable live services in the backend config during maintainer proof. | "The demo keeps fallback paths visible: cached public data, synthetic fallback, disabled Bedrock, and unavailable source warnings all remain testable." |

## Before / After Proof

Manual baseline:

- Open map, planning, flood, access, and document sources separately.
- Copy likely risks into notes.
- Track which source supported which claim.
- Decide which uncertainty needs human review.
- Turn the findings into a briefing.

MVP workflow:

- Start a hosted tester session.
- Send one natural-language site-visit request.
- Inspect annotations, evidence, trace, source register, confidence labels, and safety decision in one place.

Conservative claim:

3D-RAMS does not prove end-to-end RAMS automation. It proves that the first-pass desk-review workflow can be compressed into an inspectable review pack while keeping source uncertainty and human review visible.

Use [impact-baseline.md](impact-baseline.md) before making any numeric speed-up claim. Until a timed baseline has been completed and reviewed, keep impact language qualitative.

## Test Scenarios

For repeatable backend proof, run `python scripts/evaluate-demo.py` from the repo root. The runner forces no-AWS deterministic mode and checks the scenarios below plus unknown fixture-pack fallback. See [evaluation.md](evaluation.md).

| Scenario | How To Run | Proof Point |
| --- | --- | --- |
| Hosted chat happy path | Send the 8 Albert Embankment pre-visit prompt. | Shows realistic source register, evidence, confidence, and annotations. |
| Clarification | Send `Please prepare my pre-visit pack.` without a site. | Shows the agent asks for site/activity details before running tools. |
| Synthetic fallback | Send a made-up rural site prompt or run maintainer tests with live sources disabled. | Shows the workflow still returns a clearly labelled fallback pack. |
| Source unavailable | Run maintainer tests with planning/context or geospatial source simulation disabled. | Shows missing-data warnings and degraded but usable output. |
| Bedrock disabled/fallback | Run without AWS config or simulate model failure. | Shows deterministic briefing fallback. |
| Unsafe request | Send a message asking the agent to certify RAMS, approve work, or provide emergency instructions. | Shows blocked certified RAMS / work approval behavior. |
| Low confidence | Inspect annotations and evidence. | Shows uncertainty labels rather than hidden assumptions. |
| Architecture visualizer | Inspect `Architecture + Workflow`. | Shows tool flow, boundaries, and future production path. |

## What Is Real, Cached, Mocked, Or Future

| Area | Status |
| --- | --- |
| Hosted chat API | Real FastAPI endpoints for sessions, uploads, chat, and session trace. |
| Agent orchestrator | Real FieldBrief orchestrator boundary using deterministic tools now; Strands-ready integration is installed and staged. |
| Frontend viewer | Real React chat-first UI with Cesium terrain/imagery/buildings when `VITE_CESIUM_ION_TOKEN` is configured, plus labelled fallback. |
| Lambeth fixture pack | Cached public-source demo pack with attribution; live-map MVP mode can add Planning Data and OSM/Overpass overlays after confirmation. |
| Bedrock briefing | Optional server-side AWS call only when explicitly configured. |
| Planning portals/PDFs | Not scraped in MVP. |
| Google 3D / Earth | Not required in MVP. |
| S3, DynamoDB, CloudWatch | Hosted deployment targets; local mode uses mock upload metadata and memory trace fallback until AWS resources are configured. |
| Guardrails, AgentCore, Cognito | Future production path, not live MVP infrastructure. |

## Recording Checklist

Use [demo-recording-runbook.md](demo-recording-runbook.md) for the full step-by-step recording sequence, fallback takes, and pass/fail criteria.

- Start from a clean browser tab and hosted URL.
- Enter the shared test access code.
- Send the 8 Albert Embankment pre-visit prompt.
- Show the scene, evidence register, trace, visualizer, and safety boundary.
- Send one unsafe certification/approval prompt.
- Send one unclear prompt to prove clarification or one made-up site prompt to prove fallback.
- Avoid entering real client/site data.
- State clearly that cached public data is a demo fixture, not live operational advice.

## Safety Boundary

This demo does not certify RAMS, approve work, provide emergency guidance, or replace competent review. All output is for human pre-visit review.
