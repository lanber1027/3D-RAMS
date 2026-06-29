# 3D-RAMS Supervisor Runtime

This directory started from an AgentCore CLI scaffold and now contains the deployable 3D-RAMS runtime package.

# Layout

The generated application code lives at the agent root directory. At the root, there is a `.gitignore` file, an
`agentcore/` folder which represents the configurations and state associated with this project. Other `agentcore`
commands like `deploy`, `dev`, and `invoke` rely on the configuration stored here.

## Agent Root

The main entrypoint is `main.py`. It uses the AgentCore SDK `@app.entrypoint` decorator and delegates invocation handling to `supervisor_core.agentcore_adapter`.

The current migration preserves the existing deterministic 3D-RAMS workflow under `supervisor_core/` ("supervisor-core" in architecture notes). Bedrock remains optional and environment-controlled.

Reusable tools live in the shared `app/rams_agent_tools` package and are grouped by capability so future Harness subagents can expose only the functions they need. The supervisor runtime imports those tools; it does not own them.

The local `rams_agent_tools` and `fixtures` entries in this runtime directory are packaging links to the shared package. They keep AgentCore CodeZip self-contained while preserving `app/rams_agent_tools` as the source of truth.

Runtime-required fixture data is packaged under `fixtures/` so local mock and cached-public modes are available to AgentCore packaging.

## Environment Variables

| Variable | Required | Description |
| --- | --- | --- |
| `LOCAL_DEV` | No | Set to `1` to use `.env.local` instead of AgentCore Identity. |
| `ENABLE_BEDROCK` | No | Set to `true` only when AWS credentials and model access are ready. Defaults to deterministic fallback. |
| `RUNTIME_DATA_MODE` | No | Use `fixture_first` for Demo1 and no-AWS validation. |
| `RAMS_SUBAGENT_EXECUTION_MODE` | No | Defaults to `direct`, which runs the shared Python tool functions locally. Set to `agentcore_harness` only after Harness ARNs and IAM are configured. |
| `RAMS_HARNESS_ARNS` | For `agentcore_harness` mode | JSON object mapping Harness names to deployed Harness ARNs. Individual variables such as `RAMS_GEOSPATIAL_HARNESS_ARN` can be used instead. |
| `RAMS_HARNESS_QUALIFIER` | No | Harness endpoint qualifier. Defaults to `DEFAULT`. |

The supervisor always dispatches through `supervisor_core.subagent_invoker`. In local demo mode this adapter uses deterministic direct execution. In `agentcore_harness` mode it calls `bedrock-agentcore.invoke_harness`, handles inline function tool-use events, executes the shared Python tool functions, and returns JSON results to the supervisor.

# Developing locally

If installation was successful, a virtual environment is already created with dependencies installed.

Run `source .venv/bin/activate` before developing.

From the repository root, start the local runtime server on port 8080 with:

`agentcore dev --runtime rams_supervisor_runtime --skip-deploy --no-browser --no-traces --logs --port 8080`

In a new terminal, you can invoke that server with:

`agentcore invoke --dev '{"input":{"fixturePack":"public-lambeth-thames","useBedrock":false}}'`

The demo UI targets AgentCore by default through the Vite proxy at `/agentcore/invocations`. Start the frontend with `npm run dev` from `frontend/` after AgentCore is listening on port 8080.

For the AgentVerse/ASI:ONE entry-agent payload shape, see `docs/agentverse-agentcore-adapter-contract.md`.

# Deployment

After providing credentials and passing the repo verification stack, `agentcore deploy` can deploy the project into Amazon Bedrock AgentCore.

Use `agentcore invoke` to invoke your deployed runtime. To test deployed Harness subagent execution through the supervisor, set `RAMS_SUBAGENT_EXECUTION_MODE=agentcore_harness` and provide the deployed Harness ARNs through `RAMS_HARNESS_ARNS` or the individual `RAMS_*_HARNESS_ARN` variables.
