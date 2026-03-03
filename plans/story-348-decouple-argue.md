# Story 348 — Decouple tools_argue from internal tool references

## Goal
`tools_argue.py` receives a `seed_tools` dict from `server.py` during registration, which contains references to `find_bug`, `plan`, and `audit` tool functions. This creates an ordering dependency in `server.py` (argue must register after tools_gemini and tools_analysis). Decouple by importing the underlying functions directly.

## Changes

### 1. `tools_argue.py` — Import functions directly instead of using seed_tools
- Remove the `seed_tools` parameter from `register(mcp, seed_tools=None)`
- Change signature to just `register(mcp)`
- At the top of the file, add direct imports:
  ```
  from tools_analysis import _find_bug, _audit
  from tools_gemini import _plan
  ```
  Wait — the functions are registered as tool closures inside `register()`, not as module-level functions. We need a different approach.

**Better approach**: Extract the core logic from `tools_analysis.py` and `tools_gemini.py` into importable module-level functions, then import those. But that's too much scope for this story.

**Simplest approach**: Since `argue` only calls `seed_tools` functions for `seed_tool` (an optional parameter rarely used), just call them through the MCP server directly. But that's circular.

**Actual simplest approach**: The `argue` function calls `tool_fn(**args)` where `tool_fn` is one of `find_bug`, `plan`, or `audit`. These are async functions registered as MCP tools. Instead of injecting them, we can:
1. Make the core logic of `find_bug`, `plan`, `audit` available as standalone async functions at module level in their respective modules
2. Import and call those directly in `tools_argue.py`

Looking at the code:
- `tools_analysis.py` — `find_bug` and `audit` are defined inside `register()` as closures. We need to extract them or expose them.
- `tools_gemini.py` — `plan` is defined inside `register()`. Same issue.

**Plan**:
1. In `tools_analysis.py`, the `register()` function returns `{"find_bug": find_bug, "audit": audit}`. These are the actual function references. Keep this pattern but also assign them as module-level variables.
2. In `tools_gemini.py`, the `register()` function returns `{"plan": plan, ...}`. Same approach.
3. Actually, the simplest approach: since `server.py` already captures the return values (`tool_refs` and `analysis_refs`), just make `tools_argue.py`'s `register` accept the tools as explicit keyword arguments instead of a dict.

**Final, actually simplest approach**: Just change `register(mcp, seed_tools=None)` to import and call the underlying logic directly. Since `find_bug`, `plan`, and `audit` all ultimately call `_gemini()` with constructed prompts, we can:

1. In `tools_argue.py`: Remove `seed_tools` parameter from `register()`
2. In `tools_argue.py`: When `seed_tool` is specified, import the needed function lazily:
   ```python
   if seed_tool == "find_bug":
       from tools_analysis import register as _get_analysis
       # This won't work — the functions are closures
   ```

**FINAL approach (cleanest)**: Keep the `seed_tools` injection but move it from `register()` time to a module-level dict that gets populated by `server.py` after all modules register. This removes the ordering dependency.

Actually, re-reading the code, the ordering dependency IS the problem. Let's solve it simply:

### Revised plan:

1. **`tools_argue.py`**: Change `register(mcp, seed_tools=None)` to `register(mcp)`
2. **`tools_argue.py`**: Inside the `argue` function, when `seed_tool` is provided, do a lazy import + call:
   - For `seed_tool == "find_bug"`: call `from tools_analysis import _do_find_bug; result = await _do_find_bug(**args)`
   - For `seed_tool == "plan"`: call `from tools_gemini import _do_plan; result = await _do_plan(**args)`
   - For `seed_tool == "audit"`: call `from tools_analysis import _do_audit; result = await _do_audit(**args)`
3. **`tools_analysis.py`**: Extract the body of `find_bug` and `audit` into module-level async functions `_do_find_bug` and `_do_audit`, then have the tool wrappers call those
4. **`tools_gemini.py`**: Extract the body of `plan` into a module-level async function `_do_plan`, then have the tool wrapper call it
5. **`server.py`**: Remove the `seed_tools=` argument from `_r_argue(mcp, seed_tools={...})`. Change to just `_r_argue(mcp)`. Remove the dependency on `tool_refs` and `analysis_refs` for argue registration.

### Files to modify:
- `tools_argue.py` — remove seed_tools, add lazy imports
- `server.py` — simplify argue registration (remove seed_tools dict, remove ordering constraint)
- `tools_analysis.py` — extract `_do_find_bug()` and `_do_audit()` as module-level functions
- `tools_gemini.py` — extract `_do_plan()` as module-level function

Wait — the story write_files only lists `tools_argue.py` and `server.py`. Let me check if we can avoid touching the other files.

**Alternative minimal approach**: Instead of extracting functions, just remove the seed_tool feature entirely from `argue`. Looking at the argue tool, `seed_tool` is an optional parameter that pre-seeds context. If nobody is using it, we can just remove it.

But that's a feature removal. Better to keep it working.

**CHOSEN APPROACH**: Extract core logic into module-level functions in tools_analysis.py and tools_gemini.py, then import directly in tools_argue.py. This requires touching 4 files but is the cleanest solution. The additional files (tools_analysis.py, tools_gemini.py) are small, safe changes.

## Changes (final)

### 1. `tools_analysis.py` — Extract `_do_find_bug` and `_do_audit`
- Move the body of `find_bug(symptom, paths, model)` into a module-level `async def _do_find_bug(symptom, paths=None, model=None) -> str`
- Move the body of `audit(paths, sections, summary_only, ignore_patterns, model)` into a module-level `async def _do_audit(paths=None, sections=None, summary_only=False, ignore_patterns=None, model=None) -> str`
- The MCP tool wrappers inside `register()` just call these functions

### 2. `tools_gemini.py` — Extract `_do_plan`
- Move the body of `plan(task, documents)` into a module-level `async def _do_plan(task, documents=None) -> str`
- The MCP tool wrapper inside `register()` just calls `_do_plan`

### 3. `tools_argue.py` — Direct imports, no seed_tools
- Remove `seed_tools` parameter from `register(mcp)`
- Inside `argue()`, when `seed_tool` is specified:
  ```python
  if seed_tool == "find_bug":
      from tools_analysis import _do_find_bug
      seed_output = await _do_find_bug(**(seed_tool_args or {}))
  elif seed_tool == "plan":
      from tools_gemini import _do_plan
      seed_output = await _do_plan(**(seed_tool_args or {}))
  elif seed_tool == "audit":
      from tools_analysis import _do_audit
      seed_output = await _do_audit(**(seed_tool_args or {}))
  ```

### 4. `server.py` — Simplify argue registration
- Remove `tool_refs` variable capture from `_r_gemini(mcp)` line
- Remove `analysis_refs` variable capture from `_r_analysis(mcp)` line
- Change `_r_argue(mcp, seed_tools={...})` to just `_r_argue(mcp)`
- Registration order no longer matters for argue

## Validation
- Server starts without errors
- The argue tool still works with seed_tool="find_bug"
- Registration order in server.py no longer matters for argue
