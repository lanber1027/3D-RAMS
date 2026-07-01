---
name: shea-symphony-issue-forge-reflect
description: Use when reflecting over recent 3D-RAMS conversations, issues, PRs, docs, or work records to extract backlog candidates or promote rough backlog ideas into executable issues.
---

# Shea Symphony Issue Forge Reflect

Turn loose recent 3D-RAMS context into manageable Backlog candidates, then help
promote selected candidates into executable issues.

Reflection is a skill behavior, not a CLI subcommand. Do not expect
`shea-symphony forge reflect`.

## Repository

Default repository: `Capitano00/3D-RAMS`

Default local checkout: the current 3D-RAMS repo root.

## CLI Constraint

Prefer a suite-owned CLI for backlog creation, promotion, and Project state
when one exists. In 3D-RAMS it temporarily cannot be used: there is no Shea
Symphony `forge reflect` or Project workflow CLI. Do not run legacy
`forge create`, `forge promote`, or raw Project mutation commands. Approximate
the workflow with local scans, `gh` issue/PR reads, draft issues, and explicit
confirmation before any GitHub write. Record skipped CLI steps as
`CLI unavailable in 3D-RAMS`.

## Backlog Semantics

Backlog candidates are parking-lot memory, not executable work. A candidate
means useful work may exist, but shape, priority, dependencies, UAT, or
dispatchability still needs discussion.

When listing candidates, explain:

- why it was parked;
- evidence anchor;
- duplicate coverage checked;
- question promotion must answer.

## Reflect Mode

Gather only relevant sources:

```bash
git status --short --branch
gh issue list --repo Capitano00/3D-RAMS --state open
gh pr list --repo Capitano00/3D-RAMS --state open
```

Also scan local docs and code paths only where they relate to the theme.

Keep candidates if they show repeated demo pain, safety-boundary drift, missing
verification, unclear real-vs-mocked disclosure, public/private risk, fixture
gaps, or docs/operator workflow gaps. Drop duplicates and one-off complaints.

Use this seed body:

```md
## Issue Setup

- UAT Required: TBD
- Assignee: TBD
- Dependencies: TBD
- Related Parent Issue or Context: Reflective backlog seed from recent 3D-RAMS work.

## Issue Goal

[One concrete sentence.]

## Issue Context

[Why this surfaced.]

## Current Seed Scope

- ...

## Open Questions for Issue Forge

- ...

## Expected Promotion Path

Discuss through Issue Forge, resolve scope / dependencies / verification / UAT,
then promote to an executable issue if still worth doing.
```

## Promote Mode

Read the candidate first. If it is already solved, stale, or covered by an open
PR, recommend closing or leaving it parked instead of creating make-work.

Discuss like Issue Forge:

- ask 1-3 focused questions per turn;
- resolve goal, why now, scope, guardrails, dependencies, verification, and UAT;
- compare against current `main`, open PRs, and recently completed work;
- promote only after explicit confirmation.

Default promotion path:

1. Rewrite the candidate into the full Issue Forge execution contract.
2. Rename the title into an executable imperative title.
3. Create/update the GitHub issue with `gh` only after confirmation.
4. Read back and report.

## Boundaries

- Do not treat backlog candidates as executable work.
- Do not mutate code while reflecting unless the user explicitly switches tasks.
- Do not add private planning notes or confidential context to public issues.
