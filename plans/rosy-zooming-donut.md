# Plan: Move MCP Server to Global Claude Directory

## Context

The Gemini MCP server lives at `advocate/mcp_server/` but the user wants it globally available at `~/.claude/mcp-servers/gemini/`. The config in `~/.claude/settings.json` already references it globally — now the code itself should live there too. `PROJECT_ROOT` will use `os.getcwd()` so it adapts to whichever project Claude Code is running in.

## Files

- **Copy** `mcp_server/server.py` → `~/.claude/mcp-servers/gemini/server.py`
- **Copy** `mcp_server/test_server.py` → `~/.claude/mcp-servers/gemini/test_server.py`
- **Copy** `mcp_server/requirements.txt` → `~/.claude/mcp-servers/gemini/requirements.txt`
- **Modify** `~/.claude/settings.json` — update mcpServers paths
- **Create** new venv at `~/.claude/mcp-servers/gemini/.venv/`

## Changes

### 1. Create directory and venv

```
mkdir -p ~/.claude/mcp-servers/gemini
cp mcp_server/server.py ~/.claude/mcp-servers/gemini/
cp mcp_server/test_server.py ~/.claude/mcp-servers/gemini/
cp mcp_server/requirements.txt ~/.claude/mcp-servers/gemini/
python3.11 -m venv ~/.claude/mcp-servers/gemini/.venv
~/.claude/mcp-servers/gemini/.venv/bin/pip install -r ~/.claude/mcp-servers/gemini/requirements.txt
```

### 2. Update `PROJECT_ROOT` in server.py

Change from:
```python
PROJECT_ROOT = Path(__file__).resolve().parent.parent
```
To:
```python
PROJECT_ROOT = Path.cwd()
```

This makes the server work with whatever project Claude Code is running in.

### 3. Update `~/.claude/settings.json`

Update mcpServers to point to new location:
```json
"mcpServers": {
  "gemini": {
    "command": "/Users/kelsiandrews/.claude/mcp-servers/gemini/.venv/bin/python3",
    "args": [
      "/Users/kelsiandrews/.claude/mcp-servers/gemini/server.py"
    ]
  }
}
```

## Verification

1. `cd ~/.claude/mcp-servers/gemini && .venv/bin/python3 -m pytest test_server.py -v`
2. Restart Claude Code, confirm tools appear via `/mcp`
