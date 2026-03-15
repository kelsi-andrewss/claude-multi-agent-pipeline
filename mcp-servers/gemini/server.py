"""Gemini MCP Server — exposes Gemini generation as MCP tools for Claude Code."""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from mcp.server.fastmcp import FastMCP

from constants import (
    AUDIT_PROMPT_PATH, DOCUMENTS, EPICS_DB, MAX_CODE_BYTES,
    MAX_CONTEXT_BYTES, NO_CODE_INSTRUCTION, PROJECT_ROOT,
    REDESIGN_SYSTEM_INSTRUCTION, STORY_STATES, VALID_STORY_TRANSITIONS,
)
from gemini_client import (
    _discover_files, _gemini, _load_audit_context, _load_audit_prompt,
    _read_doc, _read_files_within_budget,
)
from tools_pm_helpers import (
    _epic_to_dict, _get_db, _next_id, _story_to_dict, _validate_transition,
)
from tools_analysis import (
    _build_redesign_prompt, _collect_redesign_files, _detect_framework,
)

mcp = FastMCP("gemini")

# Register all tool modules against this mcp instance
from tools_gemini import register as _r_gemini
_r_gemini(mcp)

from tools_test import register as _r_test
_r_test(mcp)

from tools_analysis import register as _r_analysis
_r_analysis(mcp)

from tools_design import register as _r_design
_r_design(mcp)

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

from tools_pm_decisions import register as _r_pm_decisions
_r_pm_decisions(mcp)

from tools_knowledge import register as _r_knowledge
_r_knowledge(mcp)

from tools_search import register as _r_search
_r_search(mcp)


if __name__ == "__main__":
    import sys
    from tools_pm_helpers import startup_migrate
    startup_migrate()

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
