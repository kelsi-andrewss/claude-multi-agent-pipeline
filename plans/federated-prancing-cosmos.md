# Listening Gate Overhaul

## Context

The listening gate is meant to ensure the agent listens empathetically before jumping to navigation tools (`specialist_navigator`, `appointment_brief_generator`). It's currently broken in several ways:

1. **Hard exit bypasses LLM**: `_SOMATIC_NUDGE` returns a canned string and skips the LLM entirely when a brief is requested without somatic details (`agent.py:519-526`)
2. **Streaming bug**: `chat_stream()` uses `astream_events` directly and never sets `symptoms_captured = True` — only the `SessionQueueCallback` in `main.py:109-110` does, but it's not used by the streaming path
3. **Dead code**: `_is_listening()` (line 77), `_DISCOVERY_PIVOT_CONTEXT` (line 83), `_DISCOVERY_BLOCKED_TOOLS` (line 74), `_DISCOVERY_MODE_TURNS` (line 73) are defined but never called
4. **UI/state mismatch**: The `listening_gate` event is informational-only and can desync from actual LLM behavior

**Goal**: A unified gate that works identically in both `chat()` and `chat_stream()`, blocks tools only when appropriate, respects explicit user requests, and uses LLM-driven assessment instead of arbitrary turn counts.

## Design Decisions (from user)

- **Gate behavior**: Block gated tools only when behavioral checks haven't cleared AND the user is NOT directly asking for that tool
- **Somatic nudge**: Keep but soften — inject as prompt context, not hard return
- **feels_seen**: LLM-driven classifier, on-demand only (runs only when gate would block a tool)
- **Intent detection**: Hybrid — keywords first, LLM fallback when ambiguous
- **Parallel tool calls**: Enable (already supported by LangGraph v2 default; confirm it works)

## Implementation

### Step 1: Add `post_model_hook` to `create_react_agent`

**File**: `agent.py`

The `post_model_hook` runs after the LLM decides which tools to call but before tools execute. It works identically for `ainvoke` and `astream_events`, solving the streaming bug. Available in `langgraph-prebuilt==1.0.8` (confirmed in installed source).

Create `_make_listening_gate_hook(session_state, llm)` that returns an async closure:

```
LLM produces AIMessage with tool_calls
  → post_model_hook inspects tool_calls
  → If no gated tools (specialist_navigator, appointment_brief_generator): pass through
  → If gate is open (feels_seen=True AND symptoms_captured=True): pass through
  → If gate is closed but user explicitly requested the tool (keyword/insistence match): pass through
  → If gate is closed and no explicit request:
    1. Run on-demand feels_seen classifier (LLM call)
    2. If classifier says feels_seen=True, update state, re-check gate
    3. If still blocked: strip ONLY gated tool_calls, keep non-gated ones intact
       - Uses RemoveMessage to remove original AIMessage + adds new AIMessage with allowed calls only
       - Example: LLM calls [observed_symptom, specialist_navigator] → hook strips navigator,
         keeps observed_symptom → symptom gets saved, navigation is deferred (no data loss)
    4. If ALL calls were gated and stripped, the new AIMessage has content only (no tool_calls),
       routing to END — the LLM's natural text response becomes the output
```

Update `__init__` to pass the hook:
```python
self.graph = create_react_agent(
    model=self.llm,
    tools=registered_tools,
    prompt=self.system_prompt,
    post_model_hook=_make_listening_gate_hook(session_state, self.llm),
)
```

### Step 2: Fix `symptoms_captured` in streaming path

**File**: `agent.py` — `chat_stream()` method, lines 697-707

Add state update in the existing `on_tool_end` handler within `chat_stream`:
```python
elif ev_name == "on_tool_end":
    tool_name = event.get("name", "unknown")
    if tool_name in _SYMPTOM_CAPTURE_TOOLS:
        session_state.symptoms_captured = True  # <-- ADD THIS
    ...
```

Move `_SYMPTOM_CAPTURE_TOOLS` from `main.py:84` into `agent.py` (or define it in both — the hook also needs it).

### Step 3: Hybrid intent detection

**File**: `agent.py`

New function `_detect_explicit_tool_request(user_message, gated_tool_names) -> bool`:

Keyword-based first pass with two tiers — polite requests and insistent overrides:

```python
_TOOL_REQUEST_KEYWORDS = {
    "specialist_navigator": ["what specialist", "what kind of doctor", "which doctor",
        "find me a specialist", "who should i see", "recommend a specialist", "do i need a referral"],
    "appointment_brief_generator": ["brief", "prep sheet", "appointment summary",
        "generate brief", "create brief", "make my brief"],
}

# Insistence patterns — user is overriding the gate explicitly, applies to ANY gated tool
_INSISTENCE_PATTERNS = [
    "i don't care",  "i dont care", "just give me", "just do it", "skip",
    "skip the questions", "stop asking", "i already told you", "just tell me",
    "can you just", "please just", "i said",
]
```

Detection logic:
1. Check `_INSISTENCE_PATTERNS` first — these override the gate for any gated tool
2. Check `_TOOL_REQUEST_KEYWORDS` for tool-specific explicit requests
3. If neither matches but the LLM still chose a gated tool, fall back to a lightweight LLM classifier call (short prompt, same model, structured JSON output)

### Step 4: On-demand `feels_seen` classifier

**File**: `agent.py`

New async function `_classify_feels_seen(messages, llm) -> bool`:

- Only called from the `post_model_hook` when: gate is closed, `feels_seen=False`, and the LLM tried to call a gated tool
- Extracts last ~5 turns of conversation
- Asks the LLM: "Has the patient been acknowledged and heard? JSON: {feels_seen: bool, reason: str}"
- Returns `False` on error (fail-closed)

Keep the existing `heard_turns >= 2` auto-flip as a fast path that avoids the LLM call entirely when conditions are simple.

### Step 5: Soften the somatic nudge

**File**: `agent.py`

Replace the hard return at lines 519-526 (`chat()`) and 607-617 (`chat_stream()`):

**Before**: `return _SOMATIC_NUDGE` (skips LLM entirely)

**After**: Inject somatic context into the augmented message before `_graph_ainvoke`:
```python
if (
    _message_is_brief_request(message)
    and not session_state.somatic_collected
    and not session_state.patient_language_buffer
    and not session_state.somatic_nudge_issued
):
    session_state.somatic_nudge_issued = True
    augmented_message = f"[SOMATIC NUDGE: The patient wants a brief but hasn't shared physical details yet. " \
        f"Before generating the brief, gently ask about their physical experience — where in their body, " \
        f"what it feels like. If they say 'skip', proceed immediately.]\n\n{augmented_message}"
```

The LLM handles the nudge naturally in its own voice. The `post_model_hook` still gates `appointment_brief_generator` if behavioral checks aren't met.

### Step 6: Update system prompt

**File**: `prompts/system.py`

Soften DISCOVERY MODE from hard prohibitions to preferences:
- Remove: "Do NOT call specialist_navigator or appointment_brief_generator until..."
- Replace with: "Prefer listening and symptom capture before navigation. The system manages tool availability."
- Remove turn-count language from TOOL USE section ("NOT in the first 3 turns unless...")
- Keep all behavioral guidance (empathy, narrative recognition, follow-up questions)

### Step 7: Clean up dead code

**File**: `agent.py`

Remove:
- `_DISCOVERY_MODE_TURNS` (line 73) — unused
- `_DISCOVERY_BLOCKED_TOOLS` (line 74) — replace with `_GATED_TOOLS` used by the hook
- `_is_listening()` (lines 77-82) — unused, replaced by hook logic
- `_DISCOVERY_PIVOT_CONTEXT` (lines 83-95) — unused, replaced by somatic nudge context injection

Keep `_SOMATIC_NUDGE` text available as fallback nudge content (renamed to `_SOMATIC_NUDGE_CONTEXT`).

### Step 8: Update listening gate event emission

**File**: `agent.py`

Move gate event emission into the `post_model_hook` so it accurately reflects what actually happened:
- Emit `listening_gate` event when the hook blocks a tool call (with reason)
- Emit `gate_override` event when user explicitly requested a gated tool and it was allowed through
- Remove the existing informational-only gate events from `chat()` (lines 540-556) and `chat_stream()` (lines 647-663)

### Step 9: Update tests

**File**: `tests/test_listening_gate.py`
- Update import: `_DISCOVERY_BLOCKED_TOOLS` → `_GATED_TOOLS`
- `TestDiscoveryBlockedTools` → `TestGatedTools` (same assertions, new name)
- `TestFeelsSeenAutoFlip`: keep existing tests (auto-flip is still a fast path), add tests for LLM classifier
- `TestListeningGateEvent`: update to test hook-emitted events
- Add new test class `TestPostModelHook`:
  - Gate blocks gated tools when `feels_seen=False` and `symptoms_captured=False`
  - Gate allows gated tools when both flags are `True`
  - Gate allows gated tools when user explicitly requests them (keyword match)
  - Gate allows gated tools when user insists ("I don't care, just give me the specialist")
  - Gate allows non-gated tools regardless of state
  - **Partial gating**: when LLM calls [observed_symptom, specialist_navigator] in one turn, hook strips only specialist_navigator — observed_symptom still executes and `symptoms_captured` flips
  - `symptoms_captured` updates when symptom capture tools fire

**File**: `tests/test_agent/test_triggers.py`
- `test_somatic_nudge_fires_on_brief_request`: update — no longer returns `_SOMATIC_NUDGE` string, now the LLM is invoked with nudge context
- `test_somatic_nudge_only_fires_once`: update — second request should invoke `_graph_ainvoke`
- `test_no_nudge_when_somatic_collected` and `test_no_nudge_when_buffer_has_data`: minimal changes (these already expect `_graph_ainvoke` to run)

## Files Modified

| File | Changes |
|------|---------|
| `agent.py` | Hook, intent detection, feels_seen classifier, somatic softening, dead code removal, streaming fix |
| `prompts/system.py` | Soften DISCOVERY MODE, remove turn-count prohibitions |
| `main.py` | Move `_SYMPTOM_CAPTURE_TOOLS` to `agent.py`, keep callback for event emission only |
| `tests/test_listening_gate.py` | Update imports, add hook tests |
| `tests/test_agent/test_triggers.py` | Update somatic nudge assertions |

## Verification

1. **Unit tests**: `python -m pytest tests/test_listening_gate.py tests/test_agent/test_triggers.py -x --tb=short`
2. **Full test suite**: `python -m pytest tests/ -x --tb=short`
3. **Manual smoke test**: Start the agent, verify:
   - Early turns: agent listens, doesn't call specialist_navigator
   - Explicit request "find me a specialist" on turn 1: tool fires despite gate
   - Brief request without somatic data: LLM asks about physical experience (not canned response)
   - Streaming path: `symptoms_captured` flips after `observed_symptom` tool fires
   - Parallel tool calls: agent can call multiple tools in a single response
4. **Parallel tool calls**: Verify by prompting a scenario that naturally triggers multiple tools (e.g., "tell me about my history and find a specialist") after the gate is open
