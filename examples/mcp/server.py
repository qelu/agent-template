#!/usr/bin/env python3
"""Disabled read-only MCP example. Install the optional `mcp` dependency to run."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("agent-template-example")


@mcp.tool()
def get_status(component: str) -> dict[str, str]:
    """Return placeholder status for an explicitly named example component."""
    return {"component": component, "status": "example-only", "mutation": "none"}


if __name__ == "__main__":
    mcp.run()
