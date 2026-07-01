# AgentCore Rebuild Plan

This document tracks the selected AgentCore path for 3D-RAMS.

The current hosted teammate MVP remains:

```text
Amplify frontend -> API Gateway -> Lambda/FastAPI -> Bedrock + tools + DynamoDB/S3/CloudWatch
```

The selected next runtime path is:

```text
Amplify frontend -> API Gateway/Lambda guard adapter -> AgentCore Runtime sidecar -> Bedrock + tools + trace
```

Managed AgentCore is not yet the live public runtime. The first implementation slice added an AgentCore-ready conversation boundary: bounded session memory, guarded routing, and an app-level memory contract.

## Why Not Direct Cutover Yet

The AgentCore path should be proven in parallel before any traffic switch. A direct cutover would risk breaking the working teammate MVP, so the safer route is a sidecar runtime proof with explicit smoke tests and review gates.

## Decision Gates

| Gate | Required proof |
| --- | --- |
| 1. CLI/tooling | `agentcore --version` works locally and the project can run in `agentcore dev`. |
| 2. Runtime proof | A parallel AgentCore Runtime endpoint can answer a simple non-Bedrock request. |
| 3. Guard proof | Unsafe requests are blocked before model/tool execution. |
| 4. Memory proof | Follow-up/status questions use session context without broad long-term memory. |
| 5. Tool-loop proof | Location confirmation remains required before map/evidence/risk tools run. |
| 6. Observability proof | AgentCore/CloudWatch trace shows router, model, tool, evaluator, and safety phases. |
| 7. Quality review | Public docs, runtime claims, security, safety, cost, and rollback are reviewed before traffic switch. |

## First Prototype Scope

Use `agentcore-prototype/` as the sidecar source.

Default settings:

- CodeZip build;
- Bedrock model provider;
- memory `none`;
- app-layer bounded memory only;
- no teammate traffic;
- no public production claim;
- no certified RAMS, emergency guidance, or approval-to-work claims.

## Deferred

- AgentCore Memory;
- AgentCore Gateway;
- AgentCore Browser;
- Cognito;
- public traffic switch;
- broad live geocoding/search.
