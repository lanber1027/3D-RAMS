---
name: shea-symphony-human-review
description: Use when briefing a 3D-RAMS operator for Human Review after review evidence, guiding UAT, recording a structured decision note, and routing only after explicit operator confirmation.
---

# Shea Symphony Human Review

Use this skill when the operator wants help accepting or rejecting a 3D-RAMS
issue or PR after independent review evidence.

Human Review is operator-owned final acceptance before merge-lane work. It is
not implementation, independent review, or merge execution.

## Repository

Default repository: `Capitano00/3D-RAMS`

Default local checkout: the current 3D-RAMS repo root.

## CLI Constraint

Prefer a suite-owned CLI for Project reads, timeline notes, and state routing
when one exists. In 3D-RAMS it temporarily cannot be used: there is no Shea
Symphony Cargo CLI, `project timeline-comment`, or `project set-state`
workflow. Do not run legacy workflow commands. Approximate the workflow with
`gh` issue/PR reads, local verification, a decision note in the conversation or
PR/issue comment after confirmation, and conservative routing. Record skipped
CLI steps as `CLI unavailable in 3D-RAMS`.

## Conversation Language

- Match the operator-facing language in the live session.
- Durable notes intended for GitHub should be in English unless the operator
  requests otherwise.
- Preserve canonical decision labels: `Approve for Merging`, `Request Rework`,
  `Need Human Input`, and `Defer`.

## Core Boundary

- Do not modify implementation code except for a narrow mechanical PR freshness
  repair explicitly accepted by the operator.
- Do not act as the independent Review Agent.
- Do not merge PRs.
- Do not approve certified RAMS, emergency guidance, or approval-to-work claims.
- Never mutate GitHub state until the operator explicitly confirms the decision.

## Required Reads

```bash
gh issue view <issue> --repo Capitano00/3D-RAMS --comments
gh pr view <pr> --repo Capitano00/3D-RAMS --json number,title,state,url,isDraft,baseRefName,headRefName,mergeStateStatus,reviewDecision,statusCheckRollup
git status --short --branch
```

Inspect:

- issue goal, scope, guardrails, and dependencies;
- expected outcome, verification, UAT, and context evidence;
- review pass evidence and any missing items;
- linked PR identity, readiness, base branch, checks, and review state;
- safety-boundary or public/private risks.

## Brief The Operator

Start with a concise brief:

```text
## Human Review Brief

Issue: #<issue> <title>
PR: #<pr> <title or URL>
State: <current state>

What this is about: <one sentence>
What changed: <2-4 bullets>
Review evidence: <short summary>
Human-owned part: <UAT or acceptance decision still needed>
Risks / things to watch: <none / concise list>
Available decisions: Approve for Merging / Request Rework / Need Human Input / Defer
```

Do not bury the operator in raw JSON.

## PR Freshness Gate

Before PR-specific UAT, check freshness from the PR branch/worktree:

```bash
git fetch origin
git merge-base --is-ancestor origin/main HEAD
```

If stale, ask before attempting repair unless the operator already authorized
mechanical freshness repair. If repair is safe and accepted:

```bash
git merge --no-edit origin/main
bash scripts/check-demo.sh
```

If conflicts are broad, semantic, or verification fails, stop and recommend
`Request Rework`.

## Guide UAT

- Give exactly one next action at a time.
- Tell the operator which directory to run it from.
- Ask for `pass`, `fail`, or `deferred` plus the observation.
- Treat fixture-only checks as acceptable UAT only when the issue or operator
  accepts that boundary.
- Keep a running decision-note draft in the conversation.

Recommended step:

```text
Next action: <one command or inspection>
Why: <one sentence tied to the issue purpose>
Please reply with: pass/fail/deferred plus the observation or key output lines.
```

## Decision Note

After UAT, prepare:

```md
## Human Review Decision Note

- Issue: #<issue>
- PR: #<pr>
- Repository: Capitano00/3D-RAMS
- Decision: Approve for Merging / Request Rework / Need Human Input / Defer
- CLI status: CLI unavailable in 3D-RAMS; workflow approximated with gh/local checks.
- Operator confirmation phrase: `<exact phrase>`

### Evidence Reviewed

- ...

### UAT Result

- ...

### Risks / Missing Evidence

- ...

### Routing

- ...
```

Ask for explicit confirmation before posting a GitHub comment or changing
labels/state:

- `confirm approve to Merging`
- `confirm request Rework`
- `confirm Need Human Input`
- `defer, do not change state`

## Decision Mapping

- Approve for merge-lane work -> Merging / ready to merge.
- Implementation change needed -> Rework.
- Missing human decision, credential, external context, or destructive approval
  -> Need Human Input.
- Evidence incomplete but no routing decision -> Defer / no state change.
