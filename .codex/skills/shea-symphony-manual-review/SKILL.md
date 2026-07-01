---
name: shea-symphony-manual-review
description: Use when manually reviewing a 3D-RAMS issue or pull request as an independent Review Agent, focusing on bugs, regressions, missing tests, evidence, safety boundaries, and handoff quality.
---

# Shea Symphony Manual Review

Use this skill for an independent review pass on 3D-RAMS work. Manual review is
evidence, not implementation and not merge approval.

## Repository

Default repository: `Capitano00/3D-RAMS`

Default local checkout: the current 3D-RAMS repo root.

## CLI Constraint

Prefer a suite-owned CLI for review claims, checklist updates, and state routing
when one exists. In 3D-RAMS it temporarily cannot be used: there is no Shea
Symphony Cargo CLI or Project workflow file. Do not run legacy `review claim`,
`review pass`, or `review reject` commands. Approximate the workflow with `gh`
readbacks, local diff inspection, focused checks, and a written review outcome.
Record skipped CLI steps as `CLI unavailable in 3D-RAMS`.

## Required Reads

```bash
git status --short --branch
gh issue view <issue> --repo Capitano00/3D-RAMS --comments
gh pr view <pr> --repo Capitano00/3D-RAMS --json number,title,state,url,isDraft,baseRefName,headRefName,mergeStateStatus,reviewDecision,statusCheckRollup,files,commits
```

Inspect:

- issue goal, scope, guardrails, dependencies, and acceptance criteria;
- PR diff and changed files;
- verification evidence;
- real vs mocked/fallback/AWS behavior disclosure;
- safety boundary language;
- public/private boundary.

## Review Workflow

1. Confirm the PR clearly maps to the issue or user request.
2. Review for bugs, behavioral regressions, missing tests, and unsafe claims.
3. Evaluate docs and demo behavior only where touched.
4. Run the smallest useful check when local verification is needed; prefer:

```bash
bash scripts/check-demo.sh
```

5. Classify the result:
   - `ManualPass`
   - `ManualRework`
   - `ManualInconclusive`
   - `ManualInfrastructureBlocked`
6. Write findings first, ordered by severity, with file and line references.

## Evidence Template

```md
## Manual Agent Review Evidence

- Issue: #<issue or none>
- PR: #<pr or none>
- Repository: Capitano00/3D-RAMS
- Result: ManualPass / ManualRework / ManualInconclusive / ManualInfrastructureBlocked
- CLI status: CLI unavailable in 3D-RAMS; workflow approximated with gh/local checks.
- Review workspace: <path or current checkout>

### Findings

- ...

### Verification

- ...

### Boundary Check

- Public/private boundary:
- Safety claims:
- Real vs mocked/fallback/AWS disclosure:

### Recommended Next Action

...
```

## Safety

- Do not merge PRs.
- Do not edit implementation code during review unless the user explicitly
  switches to implementation.
- Do not force-push.
- Do not approve unsafe RAMS, emergency, or approval-to-work claims.
- Do not add or expose secrets, live access codes, client data, or private notes.
