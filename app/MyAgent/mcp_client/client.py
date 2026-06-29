import logging
import os

from mcp.client.streamable_http import streamablehttp_client
from strands.tools.mcp.mcp_client import MCPClient


logger = logging.getLogger(__name__)

EXA_MCP_ENDPOINT = "https://mcp.exa.ai/mcp"


def get_streamable_http_mcp_client() -> MCPClient | None:
    """Return an optional Strands-compatible MCP client for entry-agent live web tooling."""
    if os.getenv("ENTRY_AGENT_ENABLE_EXA_MCP", "false").lower() != "true":
        return None
    return MCPClient(lambda: streamablehttp_client(os.getenv("ENTRY_AGENT_MCP_ENDPOINT", EXA_MCP_ENDPOINT)))
