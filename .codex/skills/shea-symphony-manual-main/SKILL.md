---
name: shea-symphony-manual-main
description: Use when manually running a Codex Main Agent implementation or rework session for 3D-RAMS, including issue intake, scoped changes, verification, PR preparation, and handoff to review.
---

# Shea Symphony Manual Main Agent

Use this skill for implementation work in 3D-RAMS. The Main Agent owns scoped
code/docs changes and stops at review; it does not own approval or merging.

## Repository

Default repository: `Capitano00/3D-RAMS`

Default local checkout: the current 3D-RAMS repo root.

Project anchors:

- `AGENTS.md`
- `CONTRIBUTING.md`
- `README.md`
- `backend/`
- `frontend/`
- `docs/`
- `fixtures/`
- `scripts/check-demo.sh`

## CLI Constraint

Prefer a suite-owned CLI for issue claims, state transitions, worktree
selection, and handoff when one exists. In 3D-RAMS it temporarily cannot be
used: there is no Shea Symphony Cargo CLI or canonical workflow file. Do not
run legacy `cargo run -- project ...`, `forge validate`, or `main loop`
commands. Approximate the workflow with GitHub issue/PR reads, local git
branches/worktrees, explicit user confirmation for writes, and clear handoff
notes. Record skipped CLI steps as `CLI unavailable in 3D-RAMS`.

## Preflight

Before implementation:

```bash
git status --short --branch
gh issue view <issue> --repo Capitano00/3D-RAMS --comments
gh pr list --repo Capitano00/3D-RAMS --state open
```

Read the issue, relevant docs, touched code, fixtures, and tests. If no issue
exists, use the user's prompt as the temporary contract and keep the change
small.

## Selection

Work only when all are true:

- scope is clear enough to implement without inventing product decisions;
- dependencies and external credentials are not blocking;
- the change preserves public repo boundaries and 3D-RAMS safety claims;
- no unrelated dirty worktree changes need to be overwritten;
- verification can be run or a blocker can be stated.

Route back to clarification when the task needs live credentials, private data,
client documents, destructive approval, or a product decision.

## Implementation Loop

1. Identify the smallest accepted scope.
2. Read every caller or surface affected by the change.
3. Implement the shortest root-cause fix that matches local patterns.
4. Update docs only when the behavior or operator workflow changed.
5. Run focused checks first, then the standard stack when practical:

```bash
bash scripts/check-demo.sh
```

6. Prepare or update the PR with a concise summary, verification, real vs
   mocked behavior, risks, and next action.
7. Hand off to review; do not merge.

## Evidence

Leave the handoff with:

- task summary;
- files or areas changed;
- verification run or skipped blocker;
- real, mocked, fallback, and future AWS components affected;
- public/private boundary check;
- risks or blockers;
- recommended next action.

## Hard Boundaries

- Do not merge PRs.
- Do not claim certified RAMS, emergency guidance, or approval-to-work behavior.
- Do not add cloud secrets, API keys, local access codes, client data, or
  private planning notes.
- Do not require AWS credentials or live map keys for Demo1.
