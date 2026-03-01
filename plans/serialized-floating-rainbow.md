# Plan: Fix MCP server E2BIG risk + add test coverage

## Context

Gemini's audit flagged issues with `mcp_server/server.py`. The user wants to keep the `gemini` CLI (uses their Google Ultra subscription, no paid API key needed), so the fix is scoped to hardening the subprocess approach.

| Claim | Verdict | Action |
|---|---|---|
| **E2BIG arg limit crash** | **Overstated today** (docs ~24KB, ARG_MAX 1MB) but **fragile** — grows with doc size | **Fix: pipe via stdin** |
| **Cloud Run undeployable** | True but irrelevant — local dev tool only | No action |
| **gemini_chat string concat** | CLI limitation, not a server.py bug | No action (CLI has no multi-turn API) |
| **Zero test coverage** | True | **Fix: add tests** |

## Files Modified

- `mcp_server/server.py` — change `_gemini()` to pipe prompt via stdin instead of `-p` arg
- `mcp_server/test_server.py` — new test file (pytest, no external calls)
- `mcp_server/requirements.txt` — add `pytest` dev dependency

## Change

The `gemini` CLI docs say: `-p, --prompt "Appended to input on stdin (if any)."` So we can pipe the prompt body via stdin and use `-p ""` (or omit `-p`) to trigger headless mode.

### Current code (line 58-74):

```python
async def _gemini(prompt: str, *, model: str | None = DEFAULT_MODEL) -> str:
    cmd: list[str] = ["gemini", "-p", prompt]
    if model:
        cmd.extend(["-m", model])
    cmd.extend(["-o", "json"])
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
```

### New code:

```python
async def _gemini(prompt: str, *, model: str | None = DEFAULT_MODEL) -> str:
    cmd: list[str] = ["gemini"]
    if model:
        cmd.extend(["-m", model])
    cmd.extend(["-o", "json"])
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(input=prompt.encode())
```

Key changes:
1. Remove `-p prompt` from the command args — prompt no longer on the command line
2. Add `stdin=asyncio.subprocess.PIPE` to capture stdin
3. Pass `input=prompt.encode()` to `communicate()` — pipes the prompt via stdin
4. The gemini CLI reads stdin and runs in headless mode when it receives piped input

This eliminates the E2BIG risk entirely — stdin has no OS size limit.

## Tests — `mcp_server/test_server.py`

All tests mock `asyncio.create_subprocess_exec` — no real CLI calls, no network, fast.

### What to test

1. **`_gemini()` pipes via stdin** — assert `create_subprocess_exec` is called WITHOUT `-p` in args, WITH `stdin=PIPE`, and `communicate()` receives `input=prompt.encode()`
2. **`_gemini()` includes model flag** — when `model="gemini-2.0-flash"`, assert `-m gemini-2.0-flash` is in the command
3. **`_gemini()` omits model flag when None** — assert `-m` not in command
4. **`_gemini()` handles CLI error** — mock returncode=1, assert error message returned
5. **`_gemini()` parses JSON response** — mock stdout with `{"response": "hello"}`, assert returns `"hello"`
6. **`_gemini()` handles empty response** — mock stdout with `{}`, assert returns `"(empty response)"`
7. **`gemini_generate` prepends system instruction** — when `system_instruction` is set, assert `[System: ...]` is prepended to the prompt passed to `_gemini`
8. **`gemini_generate` without system instruction** — prompt passes through unchanged
9. **`gemini_chat` formats messages** — assert messages are formatted as `"Role: content"` lines
10. **`fetch_doc("list")` returns table** — assert all DOCUMENTS keys appear in the output
11. **`fetch_doc("claude")` returns file content** — mock/use real CLAUDE.md, assert content returned
12. **`fetch_doc("nonexistent")` returns error** — assert error message with valid keys
13. **`plan` reads default docs** — mock `_read_doc`, assert called with `["claude", "requirements", "architecture"]`
14. **`plan` includes system instruction** — assert `[System: ...]` prefix in prompt
15. **`analyze` reads claude doc** — mock `_read_doc`, assert called with `"claude"`
16. **`analyze` includes context when provided** — assert `"Additional Context"` section in prompt

### Test setup

```python
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

@pytest.fixture
def mock_subprocess():
    """Mock create_subprocess_exec returning a successful gemini response."""
    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(
        b'{"response": "test response"}',
        b'',
    ))
    with patch("server.asyncio.create_subprocess_exec", return_value=proc) as mock:
        yield mock, proc
```

## Verification

1. `cd mcp_server && source .venv/bin/activate && pip install pytest`
2. `cd mcp_server && python -m pytest test_server.py -x --tb=short` — all tests pass
3. `python3 -c "import asyncio; from server import mcp; asyncio.run(mcp.list_tools())"` — confirm all 5 tools still register
4. Quick smoke test: `echo "say hello" | gemini -o json` — confirm CLI reads from stdin
