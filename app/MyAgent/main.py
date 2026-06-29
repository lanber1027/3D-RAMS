from __future__ import annotations

from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from model.load import load_model
from mcp_client.client import get_streamable_http_mcp_client
from memory.session import get_memory_session_manager
from strands import Agent, tool
from strands.agent.conversation_manager.null_conversation_manager import NullConversationManager


app = BedrockAgentCoreApp()
log = app.logger

DEFAULT_SYSTEM_PROMPT = """
You are the 3D-RAMS AgentVerse entry agent.

Provide a fast conversational intake experience for ASI:ONE users. Help the user clarify location,
area scope, goal, and supporting notes before a deeper 3D-RAMS supervisor run is launched.

Do not claim certified RAMS, emergency guidance, legal approval, work approval, or competent-person
replacement. If a deep site-review report is needed, explain that the AgentCore supervisor workflow
must produce the reviewed report data.

Do not reveal internal reasoning, chain-of-thought, scratchpad text, or <thinking> tags. Answer
directly and concisely. If the user is only testing connectivity, confirm that the AgentVerse to
AgentCore integration is working.
"""


tools = []
_INLINE_FUNCTION_NAMES = set()


@tool
def add_numbers(a: int, b: int) -> int:
    """Return the sum of two numbers."""
    return a + b


tools.append(add_numbers)

entry_mcp_client = get_streamable_http_mcp_client()
if entry_mcp_client:
    tools.append(entry_mcp_client)


def _make_conversation_manager() -> NullConversationManager:
    return NullConversationManager()


def agent_factory():
    cache: dict[str, Agent] = {}

    def get_or_create_agent(session_id: str, user_id: str) -> Agent:
        actor_id = user_id
        key = f"{session_id}/{actor_id}"
        if key not in cache:
            cache[key] = Agent(
                model=load_model(),
                session_manager=get_memory_session_manager(session_id, actor_id),
                conversation_manager=_make_conversation_manager(),
                system_prompt=DEFAULT_SYSTEM_PROMPT,
                tools=tools,
                hooks=[],
            )
        return cache[key]

    return get_or_create_agent


get_or_create_agent = agent_factory()


def _extract_prompt(payload: dict[str, Any]):
    """Accept harness-style messages[], tool_results[], or plain prompt string payloads."""
    if "messages" in payload:
        return payload["messages"]
    if "tool_results" in payload:
        return [
            {
                "role": "user",
                "content": [
                    {
                        "toolResult": {
                            "toolUseId": tool_result["toolUseId"],
                            "status": tool_result.get("status", "success"),
                            "content": tool_result.get("content", []),
                        }
                    }
                    for tool_result in payload["tool_results"]
                ],
            }
        ]
    return payload.get("prompt", "")


@app.entrypoint
async def invoke(payload: dict[str, Any], context: Any):
    log.info("Invoking 3D-RAMS AgentVerse entry runtime.")

    session_id = getattr(context, "session_id", "default-session")
    user_id = getattr(context, "user_id", "default-user")
    agent = get_or_create_agent(session_id, user_id)
    prompt = _extract_prompt(payload)

    async for event in agent.stream_async(prompt):
        if not isinstance(event, dict) or "event" not in event:
            continue
        content_block_start = event["event"].get("contentBlockStart")
        if content_block_start is not None and not content_block_start.get("start"):
            continue
        yield event


if __name__ == "__main__":
    app.run()
