# Plan: Scope pm_plan to Relevant Files Only

## Context

`pm_plan` defaults to `PROJECT_ROOT` when `paths` is not provided, causing Gemini to read
the entire codebase (~200KB budget). For story-mode planning (the common case), this is
wasteful — the story's `write_files` already identifies which files are relevant.

The fix: when `story_id` is given and the story already has `write_files` set, automatically
use those as the file-reading scope inside `pm_plan` — no caller changes needed.

## Change

**File:** `/Users/kelsiandrews/.claude/mcp-servers/gemini/server.py`

### Current code (lines ~1636–1645)

```python
# Load shared context (codebase + project docs)
audit_context = _load_audit_context()
files = _discover_files(paths)
code_content, _ = _read_files_within_budget(files, MAX_CODE_BYTES)

# ---------------------------------------------------------------
# Story mode
# ---------------------------------------------------------------
if story_id:
    story = conn.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()
    ...
    sd = _story_to_dict(story)
```

### Proposed change

Move `_discover_files` + `_read_files_within_budget` calls **into each branch** so story mode
can scope to `write_files` before loading files:

```python
audit_context = _load_audit_context()

# ---------------------------------------------------------------
# Story mode
# ---------------------------------------------------------------
if story_id:
    story = conn.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()
    ...
    sd = _story_to_dict(story)

    # Scope to relevant files: caller-supplied > story write_files > full codebase
    effective_paths = paths or (sd.get("write_files") or None)
    files = _discover_files(effective_paths)
    code_content, _ = _read_files_within_budget(files, MAX_CODE_BYTES)
    ...
```

Epic and bulk mode branches get their own `files = _discover_files(paths)` call, preserving
existing behavior (full codebase unless caller overrides).

## Critical file

- `/Users/kelsiandrews/.claude/mcp-servers/gemini/server.py` — `pm_plan`, lines ~1636–1671

## Verification

1. Re-read the modified function to confirm story mode uses `effective_paths`
2. Confirm epic/bulk modes still call `_discover_files(paths)` unchanged
3. Run `/find-bug <symptom>` on a project — verify `pm_plan` only loads the files listed in
   the story's `write_files` rather than the full codebase
