---
name: shea-symphony-issue-forge
description: Use when creating, shaping, or validating 3D-RAMS GitHub issues from rough operator intent through a conversation-first, quality-gated issue drafting flow.
---

# Shea Symphony Issue Forge

Create 3D-RAMS issues through a conversation-first workflow. Do not jump
straight to issue creation from rough intent unless the user explicitly provides
a complete issue body.

## Repository

Default repository: `Capitano00/3D-RAMS`

Default local checkout: the current 3D-RAMS repo root.

Default assignee: ask the operator, or leave unassigned if unclear.

## CLI Constraint

Prefer a suite-owned CLI for issue validation and creation when one exists. In
3D-RAMS it temporarily cannot be used: there is no Shea Symphony `forge`
command or canonical workflow file. Do not run legacy `forge validate`,
`forge create`, `forge promote`, or `forge rework` commands. Approximate the
workflow with discussion, local repo checks, a complete issue body, explicit
confirmation, and `gh issue create` only after confirmation. Record skipped CLI
steps as `CLI unavailable in 3D-RAMS`.

## Discuss Flow

- Ask only questions that affect execution.
- Offer recommended assumptions when the user implied a direction.
- Stop asking when the user says to draft, create, proceed, or skip.
- If the user skips, record assumptions in the draft.
- Split work when one issue would produce unrelated PRs.
- Keep safety, public/private boundary, and real-vs-mocked disclosure visible.

Resolve before creation:

- goal and why now;
- target area: backend, frontend, docs, fixtures, deploy, tests, or skills;
- scope and out-of-scope;
- dependencies, credentials, or data needs;
- accepted real/mocked/fallback behavior;
- non-negotiable safety guardrails;
- verification command, usually `bash scripts/check-demo.sh`;
- UAT expectations when user-facing behavior changes.

## Investigation

Before drafting migrations, external integrations, AWS/Bedrock behavior,
protocol changes, or safety-sensitive wording, do a short scan:

- read current code/docs;
- check official docs or local `--help` only when the external fact may have
  changed;
- do not expose private repo contents to external services without approval;
- prefer conservative issue slices over one large issue.

## Issue Body Shape

```md
## Issue Setup

- UAT Required: Yes / No
- Assignee: TBD
- Dependencies: None / ...
- Related Parent Issue or Context: ...

## Issue Goal

...

## Issue Context

...

### Why Now

...

### Target Repository / Package

- Capitano00/3D-RAMS

## Non-Negotiable Guardrails

- Preserve the public repo boundary.
- Preserve the 3D-RAMS safety boundary: no certified RAMS, emergency guidance,
  or approval-to-work claims.
- Keep Demo1 runnable without cloud credentials or live map keys.

## Scope

### In Scope

- ...

### Out of Scope

- ...

## Canonical References

### Relevant Knowledge Sources

- `docs/...`

### Relevant Code Paths

- `backend/...`
- `frontend/...`

## Current State

...

## Deliverable Shape

...

## Risks or Constraints

- ...

## Expected Outcome

- [ ] ...

## Verification

### Completion Criteria

- [ ] ...

### Functional Verification

- [ ] `bash scripts/check-demo.sh`

### UAT

- [ ] ...

### Context Verification

- [ ] Confirm the issue still matches latest `main`, relevant open PRs, and
      recently completed work before dispatch.
```

## Creation Workflow

After the user confirms the draft:

1. Write the issue body to a temporary file outside the repo.
2. Create with GitHub CLI:

```bash
gh issue create --repo Capitano00/3D-RAMS --title "<title>" --body-file /tmp/<slug>.md
```

3. Read back the created issue and report URL, number, assumptions, and any
   follow-up.

## Safety

- Never create issues without explicit confirmation unless the user directly
  says to create it.
- Do not mutate code while using this skill.
- Do not add secrets, private notes, client data, or confidential context to an
  issue body.
