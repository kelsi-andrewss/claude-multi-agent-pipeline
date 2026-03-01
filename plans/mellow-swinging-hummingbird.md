# Plan: Fix "expected string or bytes-like object, got 'list'" in /chat

## Context

The `/chat` endpoint crashes with `expected string or bytes-like object, got 'list'` because `AIMessage.content` in LangChain/Gemini can be a **list of content blocks** (e.g. `[{"type": "text", "text": "..."}]`) instead of a plain string. This list flows from `_graph_ainvoke` into the verification pipeline (`run_citation_layer`, `_rewrite_unsourced_claims`, `run_hallucination_guard`, etc.) and into regex operations that require a string.

## Root Cause

**File:** `agent.py:340`

```python
output = getattr(msg, "content", "") or ""
```

When `msg.content` is a list, `output` becomes that list (truthy, so `or ""` doesn't trigger). Everything downstream that calls regex ops on `output` then fails.

## Fix

In `_graph_ainvoke`, normalize `content` to a string immediately after extraction. If it's a list, concatenate the `text` fields of any `{"type": "text", ...}` blocks:

```python
raw_content = getattr(msg, "content", "") or ""
if isinstance(raw_content, list):
    output = " ".join(
        block.get("text", "") for block in raw_content
        if isinstance(block, dict) and block.get("type") == "text"
    )
else:
    output = raw_content
```

## Critical File

- `advocate/agent.py` — lines 337–341 (`_graph_ainvoke` method)

## No Other Files Need Changing

The verification layers (`citation.py`, `hallucination.py`, `boundary.py`, `pipeline.py`) are fine — they only fail because they receive a list. Normalizing at the source fixes all downstream callers.

## Verification

1. Run the test suite: `cd advocate && python -m pytest tests/ -x --tb=short`
2. Send a test chat message via the `/chat` endpoint and confirm a string response is returned without errors.
3. Confirm `history.add_ai_message` receives a string (not a list) by checking no `TypeError` in history operations on subsequent turns.
