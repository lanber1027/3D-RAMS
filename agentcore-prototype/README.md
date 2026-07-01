# 3D-RAMS AgentCore Prototype

This folder is the sidecar prototype for moving the hosted 3D-RAMS agent toward Amazon Bedrock AgentCore Runtime without breaking the current Lambda/API Gateway teammate MVP.

Current status:

- The prototype is shaped for a future AgentCore Runtime proof in `eu-west-2`.
- No managed AgentCore runtime is live for the public demo yet.
- The hosted MVP still uses Lambda/FastAPI as the active adapter.
- The prototype keeps memory disabled at the AgentCore service layer until retention and privacy are reviewed; bounded session memory remains in the app layer.
- The local sidecar harness processes runs inline by default so smoke tests return a terminal guard, clarification, confirmation, or review-pack state rather than a transient background-worker state.

## Intended AgentCore Path

1. Install the AgentCore CLI separately:

   ```powershell
   npm.cmd install -g @aws/agentcore
   agentcore --version
   ```

2. Use this folder as the implementation reference for a CodeZip project.
3. Keep `memory none` for the first AgentCore Runtime proof.
4. Deploy a parallel runtime endpoint.
5. Smoke-test it without switching the hosted frontend.
6. Add Observability before considering AgentCore Memory.
7. Switch traffic only after quality review.

## Files

| Path | Purpose |
| --- | --- |
| `app/fieldbrief_agent/main.py` | Minimal AgentCore-side entrypoint wrapper around the existing 3D-RAMS conversation contract. |
| `app/fieldbrief_agent/pyproject.toml` | Dependency declaration for a CodeZip-style Python prototype. |
| `agentcore/agentcore.template.json` | Public-safe project config template. |
| `agentcore/aws-targets.template.json` | Public-safe AWS target template. |

## Safety Boundary

The prototype must preserve the current MVP controls:

- access control remains outside the model path;
- no tools before confirmed location;
- no certified RAMS, emergency guidance, or approval-to-work claims;
- no frontend AWS credentials;
- no raw access codes, secrets, uploaded file contents, or private client data in memory/logs.
