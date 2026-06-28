# 3D-RAMS Problem Statement

Site teams often need to understand unfamiliar rural, development, or infrastructure sites before they arrive. Useful context is spread across maps, terrain views, access routes, planning records, document extracts, local constraints, and risk notes. The painful work is not simply finding one source. It is comparing fragmented evidence, spotting likely hazards, judging confidence, and turning that into a briefing a human can review.

Existing tools usually help with only one part of that workflow. Mapping tools show location context. Planning portals expose documents. Search tools retrieve records. But these tools rarely connect spatial context, planning evidence, hazard notes, confidence labels, and review boundaries into one inspectable pre-visit pack.

3D-RAMS explores whether an agent can close that gap. The user starts with a coordinate or site location. The agent resolves the site context, loads geospatial features, builds a 3D scene, reads planning-style evidence, extracts candidate hazards, creates map annotations, generates a RAMS-style briefing, and shows the trace behind each step.

The agent is valuable because it operates in the digital decision layer where the painful work already happens: maps, documents, forms, evidence registers, and review notes. It does not need to physically inspect the site to be useful. It can prepare an evidence-backed briefing that helps a person decide what to verify next.

The core problem is:

**How can an agent help a site visitor quickly understand an unfamiliar site by combining spatial context, document evidence, hazard extraction, confidence labels, and safety controls into an inspectable 3D briefing pack?**

## What The Agent Should Improve

- Reduce the time needed to turn a coordinate into a useful pre-visit context pack.
- Make scattered evidence easier to inspect by linking hazards to sources, annotations, and trace steps.
- Show what is real, mocked, unavailable, or low confidence instead of hiding uncertainty.
- Surface missing-data and tool-failure cases early so the user knows what still needs manual checking.
- Keep high-risk claims behind a visible safety gate and human review boundary.

## Why This Is More Than A 3D Map

The 3D scene is the presentation surface, not the whole product. The agent value is the workflow around it:

- resolving the user request into a site context;
- combining spatial features and planning-style evidence;
- extracting candidate hazards and limitations;
- creating annotations that can be inspected visually;
- generating a briefing with evidence references;
- logging tool calls, fallbacks, and confidence;
- blocking certified RAMS, work approval, and emergency guidance claims.

## Safety Boundary

3D-RAMS does not produce certified RAMS, emergency response instructions, approval to work, or a competent-person replacement. It produces an inspectable pre-visit review pack for human review.

Demo1 uses public-safe synthetic fixtures and local deterministic logic. Live planning portals, Google 3D data, AWS model calls, weather feeds, infrastructure sources, and news feeds are future integrations that must keep the same evidence, confidence, fallback, and safety-boundary pattern.
