"""Gemini MCP Server — exposes Gemini generation as MCP tools for Claude Code."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("gemini")

# Register all tool modules against this mcp instance
from tools_gemini import register as _r_gemini
tool_refs = _r_gemini(mcp)

from tools_test import register as _r_test
_r_test(mcp)

from tools_analysis import register as _r_analysis
analysis_refs = _r_analysis(mcp)

from tools_argue import register as _r_argue
_r_argue(mcp, seed_tools={
    "find_bug": analysis_refs["find_bug"],
    "plan": tool_refs["plan"],
    "audit": analysis_refs["audit"],
})

from tools_pm_read import register as _r_pm_read
_r_pm_read(mcp)

from tools_pm_plan import register as _r_pm_plan
_r_pm_plan(mcp)

from tools_pm_write import register as _r_pm_write
_r_pm_write(mcp)

from tools_pm_organize import register as _r_pm_organize
_r_pm_organize(mcp)

from tools_pm_analytics import register as _r_pm_analytics
_r_pm_analytics(mcp)

from tools_pm_ship import register as _r_pm_ship
_r_pm_ship(mcp)

from tools_knowledge import register as _r_knowledge
_r_knowledge(mcp)


if __name__ == "__main__":
    import sys

    if "--migrate-pitfalls" in sys.argv:
        from tools_pm_helpers import _get_db
        from tools_knowledge import _migrate_pitfalls
        conn = _get_db()
        try:
            counts = _migrate_pitfalls(conn)
            total = sum(counts.values())
            print(f"Migrated {total} patterns:")
            for cat, n in sorted(counts.items()):
                print(f"  {cat}: {n}")
        finally:
            conn.close()
    elif "--http" in sys.argv:
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
