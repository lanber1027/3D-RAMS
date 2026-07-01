---
name: shea-symphony-manual-merge
description: Use when manually handling 3D-RAMS merge-lane work: checking approved PR readiness, repairing mechanical merge blockers when safe, preserving evidence, and landing only after approval is clear.
---

# Shea Symphony Manual Merging Agent

Use this skill for 3D-RAMS merge-lane work. The merge lane owns approved PR
readiness and landing. It does not own fresh implementation.

## Repository

Default repository: `Capitano00/3D-RAMS`

Default local checkout: the current 3D-RAMS repo root.

## CLI Constraint

Prefer a suite-owned CLI for merge selection, claim locks, state changes, and
merge evidence when one exists. In 3D-RAMS it temporarily cannot be used: there
is no Shea Symphony Cargo CLI or merge-loop workflow file. Do not run legacy
`merge loop`, `project issue`, or `project set-state` commands. Approximate the
workflow with `gh pr view`, local git, focused verification, explicit approval
evidence, and conservative routing. Record skipped CLI steps as
`CLI unavailable in 3D-RAMS`.

## Preflight

```bash
git status --short --branch
gh pr view <pr> --repo Capitano00/3D-RAMS --json number,title,state,url,isDraft,baseRefName,headRefName,mergeStateStatus,reviewDecision,statusCheckRollup,commits,closingIssuesReferences
gh issue view <issue> --repo Capitano00/3D-RAMS --comments
```

Check:

- PR is open, non-draft, and targets the intended base;
- approval and required checks are present;
- issue/PR linkage is clear;
- review and human acceptance evidence exists when required;
- local worktree is clean before any repair.

## Merge-Lane Recovery

Repair only mechanical merge-lane issues:

- stale branch refresh;
- straightforward conflict caused by base drift;
- CI failure caused by merge-only drift with an obvious fix.

Do not change product scope. If conflicts are semantic, broad, or verification
fails, stop and recommend rework or human input.

## Merging

Before merge:

1. Confirm approval evidence.
2. Confirm checks are green or intentionally waived by the repository owner.
3. Run focused verification when branch repair happened.
4. Merge using the repository's accepted GitHub method.
5. Report merge evidence and follow-up cleanup.

## Hard Boundaries

- Never merge without approval evidence.
- Never claim fresh implementation work.
- Never create a replacement branch unless the operator explicitly agrees.
- Never hide unknown mergeability, missing PR linkage, or failing checks.
- Never delete local branches/worktrees unless the operator asks.
- Never mark safety-sensitive acceptance that was not actually reviewed.
