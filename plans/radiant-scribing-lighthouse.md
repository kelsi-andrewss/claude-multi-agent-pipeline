## Context

story-231: Update the README.md to accurately reflect the current state of the Claude Code configuration repository at `/Users/kelsiandrews/.claude`. The repo contains scripts, skills, agents, hooks, and MCP servers. Key discrepancies to fix: skills and epics.db now live inside `.claude/`, tracking uses SQLite (epics.db) not JSON, and some referenced files have been deleted or restructured.

Affected file: `README.md`

## What changes

- Explore and document the full directory structure: `.claude/scripts/`, `.claude/skills/`, `agents/`, `hooks/`, `mcp-servers/`, `skills/`
- Update the "What's in this repo" file tree to match reality (skills under `.claude/` subdirectory, epics.db instead of epics.json)
- Replace all references to `epics.json` with `epics.db` in Overview, Hierarchy, and Recovery sections
- Update Agent Roster table to match agents defined in `agents/` directory
- Update Script Reference table: verify all listed scripts exist in `.claude/scripts/` and descriptions are accurate
- Add/update sections for MCP servers (gemini), hooks, and any new skills
- Ensure Model Selection guidance is current

## Verification

- All file paths mentioned in README exist on disk
- No references to `epics.json` remain (use grep to confirm)
- Script table matches files in `.claude/scripts/`
- Agent list matches files in `agents/`
