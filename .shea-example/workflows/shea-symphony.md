---
tracker:
  kind: github_project_v2
  owner: Capitano00
  repo: 3D-RAMS
  project_owner: Capitano00
  project_owner_type: user
  project_number: 1
  status_field: Status
  state_map:
    backlog: Backlog
    todo: Todo
    need_to_clarify: Need to Clarify
    in_progress: In progress
    need_human_input: Need Human Input
    agent_review: In review
    human_review: Human Review
    rework: Rework
    merging: Merging
    done: Done
  active_states:
    - Todo
    - Rework
  terminal_states:
    - Done
    - Closed
    - Cancelled
    - Canceled
    - Duplicate
  assignee_filter:
    source: issue_assignees
    allow_unassigned: false
    assignees: []
  workpad:
    source: issue_comment
    marker: "<!-- shea-symphony-workpad -->"
git:
  base_branch: dev-chunteng
prompts:
  main_agent: ../prompts/3d-rams-main-agent.md
  review_agent: ../prompts/3d-rams-review-agent.md
  merge_agent: ../prompts/3d-rams-merge-agent.md
workpad_templates:
  agent_review_run: template/workpad/agent-review.md
  doctor_triage: template/workpad/doctor-triage.md
  human_review_repair: template/workpad/doctor-triage.md
  merge_run: template/workpad/merge-run.md
  merge_repair: template/workpad/merge-run.md
  forge_rework_run: template/workpad/rework-run.md
  forge_rework_blocked: template/workpad/rework-run.md
polling:
  interval_ms: 5000
artifacts:
  root: $SHEA_SYMPHONY_ARTIFACT_ROOT
  namespace: Capitano00/3D-RAMS
workspace:
  root: $SHEA_SYMPHONY_ARTIFACT_ROOT/Capitano00/3D-RAMS/default/worktrees
  base_branch: dev-chunteng
main_lane:
  backend: codex
  max_concurrent_agents: 3
  max_turns: 3
  max_retry_backoff_ms: 300000
tmux:
  command: tmux
  agent_command: codex
  review_agent_command: /Users/chuntengxiao/.local/bin/agy
  session_prefix: 3d-rams
codex:
  command: codex app-server -c 'service_tier="fast"'
  reasoning_effort: high
  approval_policy: never
  stall_timeout_ms: 300000
  session_stale_after_ms: 1800000
claude:
  command: claude
review_lane:
  backend: agy-cli
  agy_command: /Users/chuntengxiao/.local/bin/agy
  agy_model: gemini-3.1-pro-preview
  timeout_ms: 1200000
  max_concurrent_workers: 1
merge_lane:
  agent_backend: codex
  max_concurrent_workers: 1
verification:
  timeout_ms: 600000
  commands: []
observability:
  logs_root: $SHEA_SYMPHONY_ARTIFACT_ROOT/Capitano00/3D-RAMS/default/logs
---

# 3D-RAMS Shea Symphony Workflow

Tracker-backed workflow for `Capitano00/3D-RAMS` Project #1.
