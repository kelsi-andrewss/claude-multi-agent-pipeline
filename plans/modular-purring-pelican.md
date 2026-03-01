# Fix: agent_scratchpad str/list TypeError

## Context
`create_react_agent` in LangChain 0.2.x formats `agent_scratchpad` as a plain string via `format_log_to_str()`. The current prompt uses `MessagesPlaceholder(variable_name="agent_scratchpad")` which validates that its value is a `list[BaseMessage]` — causing `ValueError: variable agent_scratchpad should be a list of base messages, got str` on every chat request. The CORS error is a side effect: the backend crashes before sending response headers.

## Fix

**File**: `advocate/agent.py`
**Change**: 1 line — replace `MessagesPlaceholder` for `agent_scratchpad` with an AI message template string

```python
# BEFORE (line ~184)
MessagesPlaceholder(variable_name="agent_scratchpad"),

# AFTER
("ai", "{agent_scratchpad}"),
```

`("ai", "{agent_scratchpad}")` creates an `AIMessagePromptTemplate` that accepts a string — exactly what `create_react_agent` provides. On first call (no tool steps) it's `""`, which is valid.

## What stays unchanged
- `MessagesPlaceholder(variable_name="chat_history", optional=True)` — untouched
- `SessionAwareMemory`, `load_memory_variables`, `_invoke_with_memory` — untouched
- All tool files, models.py, fhir_client.py — untouched

## Verification
1. Restart backend: `uvicorn advocate.main:app --host 0.0.0.0 --port 8000 --reload`
2. Send a chat message from the Flutter app
3. Backend log should show ReAct Thought/Action/Final Answer, no ValueError
4. Response appears in chat UI
