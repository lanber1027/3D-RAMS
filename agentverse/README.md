# AgentVerse Hosted Adapter

This folder contains the hosted adapter used by the AgentVerse `@3d-rams` entry agent to invoke an AWS Bedrock AgentCore runtime.

It was imported from the separate `onboardAgentCore` proof of concept, but all real runtime ARNs, account IDs, access keys, and seed phrases must remain outside this public repository.

## Required Hosted Environment Variables

```bash
AWS_REGION=eu-west-2
AGENTCORE_RUNTIME_ARN=arn:aws:bedrock-agentcore:<region>:<account-id>:runtime/<runtime-id>
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
# Optional for temporary credentials:
AWS_SESSION_TOKEN=...
```

The IAM principal should be limited to the runtime it invokes. Because this adapter sends both
`x-amzn-bedrock-agentcore-runtime-session-id` and `x-amzn-bedrock-agentcore-runtime-user-id`, AWS may
authorize both runtime invocation and user-scoped runtime invocation. The resource list should include
both the runtime ARN and the default runtime endpoint ARN:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "Invoke3DRamsEntryRuntime",
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:InvokeAgentRuntime",
        "bedrock-agentcore:InvokeAgentRuntimeForUser"
      ],
      "Resource": [
        "arn:aws:bedrock-agentcore:<region>:<account-id>:runtime/<runtime-id>",
        "arn:aws:bedrock-agentcore:<region>:<account-id>:runtime/<runtime-id>/runtime-endpoint/DEFAULT"
      ]
    }
  ]
}
```

If the hosted adapter returns `The request signature we calculated does not match`, check that the
SigV4 canonical URI signs the already-encoded runtime path with `quote(path, safe="/~")`. The current
`hosted_adapter.py` includes that fix.

## Dependencies

The hosted adapter environment needs:

```text
requests
uagents
uagents-core
```

AgentVerse hosted agents may not allow arbitrary dependencies. This adapter intentionally uses
`requests` plus standard-library SigV4 signing instead of `boto3`.

## Hosted Agent Entry File

Avoid registering the chat protocol twice. In AgentVerse, either put the full contents of
`hosted_adapter.py` in the single runnable file, or use a tiny `agent.py` wrapper:

```python
from hosted_adapter import agent

if __name__ == "__main__":
    agent.run()
```

Do not keep the default OpenAI rephrase template in the same hosted agent.

## Boundary

This adapter is still only the AgentVerse-to-AgentCore bridge. Deeper 3D-RAMS report orchestration belongs in the AgentCore supervisor runtime, not in this hosted adapter.
