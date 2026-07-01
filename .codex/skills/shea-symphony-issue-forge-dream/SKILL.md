---
name: shea-symphony-issue-forge-dream
description: Use when slowly mining broader 3D-RAMS history, docs, issues, PRs, demo evidence, and local notes for evidence-backed backlog seeds and bounded Dream Logs.
---

# Shea Symphony Issue Forge Dream

Run slow, broad backlog mining for 3D-RAMS. Dream is broader than Reflect and
should be evidence-heavy.

Dream is a skill behavior, not a CLI subcommand. Do not expect
`shea-symphony forge dream`.

## Repository

Default repository: `Capitano00/3D-RAMS`

Default local checkout: the current 3D-RAMS repo root.

## CLI Constraint

Prefer a suite-owned CLI for Project reads and backlog seed creation when one
exists. In 3D-RAMS it temporarily cannot be used: there is no Shea Symphony
Dream/Forge CLI or workflow file. Do not run legacy `project state`,
`inspect`, `doctor`, or `forge create` commands. Approximate the workflow with
bounded local reads, `gh` reads, Dream Logs under `docs/dream-log/`, and GitHub
issue creation only after explicit confirmation. Record skipped CLI steps as
`CLI unavailable in 3D-RAMS`.

## Operating Rules

- Prefer report-only mode unless the operator explicitly asks to create issues.
- Never create executable issues directly from Dream without later Issue Forge
  discussion.
- Dream Logs are advisory context, not execution authority.
- Every seed needs a concrete evidence anchor.
- Summarize conversations and sessions; do not paste raw long dumps.
- Do not change external-facing product surfaces while dreaming.
- Do not edit skills while dreaming unless the operator explicitly asks.

## Source Window

Gather a bounded source set:

```bash
gh issue list --repo Capitano00/3D-RAMS --state open
gh pr list --repo Capitano00/3D-RAMS --state open
git log --oneline -20
```

Sample relevant local sources:

- `README.md`, `CONTRIBUTING.md`, `AGENTS.md`;
- `docs/architecture.md`, `docs/evaluation.md`, `docs/mvp-readiness.md`,
  `docs/demo-proof.md`, and current runbooks;
- recent touched code in `backend/`, `frontend/`, `scripts/`, and `fixtures/`;
- existing `docs/dream-log/INDEX.md` and recent Dream runs, if present;
- open issues/PRs and recent merged work.

Do not reread unlimited history by default.

## Candidate Triage

Keep candidates when they show:

- repeated demo or teammate-testing pain;
- safety-boundary drift;
- stale docs or skill contracts;
- unclear real/mocked/fallback/AWS disclosure;
- missing evidence or trace surfaces;
- public/private boundary risk;
- verification gaps.

Drop or watchlist candidates that are one-off, duplicated, too broad, already
solved, or memory-only speculation.

For each kept candidate, record evidence anchors, existing coverage checked,
likely owner, promotion path, and confidence.

## Dream Log Layout

Write Dream Logs under:

```text
docs/dream-log/YYYY-MM-DD-<run-count>-<slug>/
```

Each run directory may include:

- `RUN.md`: source inventory, round summary, candidate mapping, and next theme;
- `topic-*.md`: bounded topic logs with evidence and triage;
- `created-backlog.md`: optional mapping when issues were created.

Update `docs/dream-log/INDEX.md` when writing Dream Logs.

## Backlog Seed Shape

```md
## Issue Setup

- UAT Required: TBD
- Assignee: TBD
- Dependencies: TBD
- Related Parent Issue or Context: Dream seed from `docs/dream-log/.../RUN.md`.

## Issue Goal

[One concrete sentence.]

## Dream Evidence Anchors

- `path/or/issue`: [short evidence summary]

## Existing Coverage Checked

- ...

## Current Seed Scope

- ...

## Non-Goals / Guardrails

- ...

## Promotion Path

Discuss through Issue Forge, resolve scope / dependencies / verification / UAT,
then create executable work only if still worth doing.

## Dream Confidence

Medium - [short reason]
```

## Report

End each Dream round with:

- slept enough: yes/no;
- Dream Logs written;
- would-create or created seeds;
- watchlist candidates;
- duplicate risk;
- recommended next Dream theme.
