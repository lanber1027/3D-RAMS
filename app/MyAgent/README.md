# 3D-RAMS AgentVerse Entry Runtime

This runtime was imported from the `onboardAgentCore/app/MyAgent` proof of concept. It is the AgentCore-side runtime that the AgentVerse hosted adapter can invoke for the public `@3d-rams` entry agent.

It is separate from `app/rams_agentcore`, which remains the 3D-RAMS supervisor/report runtime.

## Runtime Role

- Accept chat-style prompts or Bedrock-style message payloads from the AgentVerse hosted adapter.
- Use a fast Bedrock model through Strands for entry-agent conversation.
- Preserve AgentCore session/user identity so memory can be used when configured.
- Stay thin: intake and delivery UX live here, while deeper site-review orchestration belongs in `rams_agentcore`.

## Local Development

This runtime requires AWS/Bedrock access for meaningful model responses. It is not part of the no-AWS Demo1 path.

```bash
agentcore dev --runtime MyAgent --skip-deploy --no-browser --no-traces --logs --port 8082
```

Optional Exa MCP tooling is disabled by default. Enable it only when live outbound network use is intended:

```bash
ENTRY_AGENT_ENABLE_EXA_MCP=true
```

## Public Repo Boundary

Do not commit AWS credentials, AgentVerse keys, seed phrases, runtime ARNs, account IDs, or private user/session content. Use environment variables in the deployment environment.
