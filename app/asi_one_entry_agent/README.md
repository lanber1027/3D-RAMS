# 3D-RAMS AgentVerse Entry Runtime

This runtime was imported from the `onboardAgentCore/app/MyAgent` proof of concept and renamed for its actual role. It is the AgentCore-side runtime that the AgentVerse hosted adapter can invoke for the public `@3d-rams` entry agent.

It is separate from `app/rams_supervisor_runtime`, which remains the 3D-RAMS supervisor/report runtime.

`supervisor_adapter.py` is the entry-side contract adapter for the supervisor runtime. It validates confirmed AgentVerse intake payloads, maps them to the supervisor `/invocations` envelope, and normalizes supervisor output into entry-agent delivery payloads.

## Runtime Role

- Accept chat-style prompts or Bedrock-style message payloads from the AgentVerse hosted adapter.
- Use a fast Bedrock model through Strands for entry-agent conversation.
- Preserve AgentCore session/user identity so memory can be used when configured.
- Stay thin: intake and delivery UX live here, while deeper site-review orchestration belongs in `rams_supervisor_runtime`.

## Local Development

The deployed/runtime entry agent uses AWS/Bedrock and Strands for meaningful model responses:

```bash
agentcore dev --runtime asi_one_entry_agent --skip-deploy --no-browser --no-traces --logs --port 8082
```

For the no-AWS Demo1 path, `local_entry_flow.py` provides a deterministic local ASI:ONE substitute. The frontend sends a `localAsiOne` envelope to the local supervisor runtime, which routes through the entry adapter contract before invoking the supervisor directly. This keeps the local demo runnable without Bedrock, AgentVerse keys, or a second AgentCore runtime process.

Optional Exa MCP tooling is disabled by default. Enable it only when live outbound network use is intended:

```bash
ENTRY_AGENT_ENABLE_EXA_MCP=true
```

## Public Repo Boundary

Do not commit AWS credentials, AgentVerse keys, seed phrases, runtime ARNs, account IDs, or private user/session content. Use environment variables in the deployment environment.
