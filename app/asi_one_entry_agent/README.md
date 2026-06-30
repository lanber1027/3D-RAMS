# 3D-RAMS AgentVerse Entry Runtime

This runtime was imported from the `onboardAgentCore/app/MyAgent` proof of concept and renamed for its actual role. It is the AgentCore-side runtime that the AgentVerse hosted adapter can invoke for the public `@3d-rams` entry agent.

It is separate from `app/rams_supervisor_runtime`, which remains the 3D-RAMS supervisor/report runtime.

`supervisor_adapter.py` is the entry-side contract adapter for the supervisor runtime. It validates confirmed AgentVerse intake payloads, maps them to the supervisor `/invocations` envelope, and normalizes supervisor output into entry-agent delivery payloads.

## Runtime Role

- Accept chat-style prompts or Bedrock-style message payloads from the AgentVerse hosted adapter.
- Accept structured frontend/proxy payloads with confirmed intake and launch the supervisor runtime.
- Use a fast Bedrock model through Strands for entry-agent conversation.
- Preserve AgentCore session/user identity so memory can be used when configured.
- Stay thin: intake and delivery UX live here, while deeper site-review orchestration belongs in `rams_supervisor_runtime`.

## Cloud Supervisor Handoff

Set the supervisor runtime ARN in the deployed entry runtime environment:

```bash
RAMS_SUPERVISOR_RUNTIME_ARN=arn:aws:bedrock-agentcore:<region>:<account-id>:runtime/<runtime-id>
```

The entry runtime maps confirmed intake with `supervisor_adapter.py`, invokes the supervisor runtime, and returns the supervisor run plus entry delivery payload. Do not commit the real ARN.

## Local Development

The deployed/runtime entry agent uses AWS/Bedrock and Strands for meaningful model responses:

```bash
agentcore dev --runtime asi_one_entry_agent --skip-deploy --no-browser --no-traces --logs --port 8082
```

For explicit no-AWS local testing, `local_entry_flow.py` still provides a deterministic local ASI:ONE substitute. It is no longer the default frontend path; set `VITE_USE_LOCAL_ASIONE=true` only when local testing is intended.

Optional Exa MCP tooling is disabled by default. Enable it only when live outbound network use is intended:

```bash
ENTRY_AGENT_ENABLE_EXA_MCP=true
```

## Public Repo Boundary

Do not commit AWS credentials, AgentVerse keys, seed phrases, runtime ARNs, account IDs, or private user/session content. Use environment variables in the deployment environment.
