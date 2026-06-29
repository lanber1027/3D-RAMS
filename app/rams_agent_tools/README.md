# 3D-RAMS Agent Tools

This package contains reusable tool functions and deterministic fixture resources shared by the supervisor runtime and future Harness subagents.

The package is intentionally outside `app/rams_supervisor_runtime` so tools are not owned by one runtime. Runtime and subagent packages should import from `rams_agent_tools` and expose only the tool groups they need.

Current groups are defined in `rams_agent_tools.tools.registry`.

Input contracts for AgentCore Harness inline function declarations live under `tool_schemas/`. These schemas mirror the shared Python tool boundaries and are registered on the specialist Harness configs with `agentcore add tool`.
