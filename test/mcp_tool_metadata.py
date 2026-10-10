#!/usr/bin/env python3
"""Keep the published MCP tool descriptions useful and discoverable."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from faultdebug.mcp_server import make_server


def main() -> int:
    tools = make_server(Path("/tmp/faultdebug-mcp-metadata"))._tool_manager._tools
    assert len(tools) == 25, f"unexpected MCP tool count: {len(tools)}"
    missing = {
        name: (tool.description or "").strip()
        for name, tool in tools.items()
        if len((tool.description or "").strip()) < 30
    }
    assert not missing, f"MCP tools need useful descriptions: {missing}"
    for name in ("get_fault_flow", "get_call_relations", "get_source_evidence"):
        assert name in tools, f"missing core report tool: {name}"
    print(f"PASS: {len(tools)} MCP tools have substantive descriptions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
