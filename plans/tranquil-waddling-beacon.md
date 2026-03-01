# Plan: Replace Listening Gate with Executor-Driven Discovery Phase

## Context

The current listening gate (`_is_listening()`) works by short-circuiting the AgentExecutor entirely — when active, it routes through a direct LLM call and returns early, so no tools can fire at all. This is causing two problems:

1. **`patient_lens` never fires during discovery.** The user wants Advocate to call `patient_lens` when someone says "I feel like I have ADHD" — but the gate blocks the executor completely, so the agent just offers warm validation with no tool call.
2. **The gate's turn-counting logic is blunt.** It auto-flips `feels_seen = True` after 3 turns regardless of actual symptom coverage or whether the patient feels understood.

The desired behavior:
- The **executor always runs**, so tools like `patient_lens`, `observed_symptom`, and `patient_voice_note` can fire naturally.
- Only `specialist_navigator` and `appointment_brief_generator` are blocked until the patient feels seen AND enough symptoms have been surfaced.
- The discovery phase ends when both conditions are true: patient feels validated **and** at least one symptom has been captured.
- The `listening_gate` event in the sidebar should still fire (now reflecting "navigation blocked — still in discovery") so the eval panel remains informative.

---

## Changes

### 1. `agent.py` — Remove the listening gate short-circuit

**Remove:**
- The `_is_listening()` function (lines 78–83)
- The `_DISCOVERY_PIVOT_CONTEXT` string (lines 84–96)
- The entire `if _is_listening(session_state):` block (lines 530–556) that calls the direct LLM and returns early

**Replace with:** A lighter pre-executor check that only emits a `listening_gate` event (for the sidebar) without bypassing the executor. The executor will handle discovery mode naturally because the system prompt already instructs the agent not to call navigator/brief tools in early turns.

```python
# Emit discovery state event for the eval panel (no blocking)
if self._event_queue is not None:
    in_discovery = (
        not session_state.feels_seen
        or not session_state.symptoms_captured
    )
    if in_discovery:
        if not session_state.feels_seen:
            gate_reason = "Patient not yet feels_seen — navigation paused"
        else:
            gate_reason = "No symptoms captured yet — navigation paused"
        event = json.dumps({
            "tool_name": "listening_gate",
            "status": "done",
            "output": gate_reason,
            "timestamp": datetime.utcnow().isoformat(),
        })
        self._event_queue.put_nowait(event)
```

Then fall through to the executor normally.

**Update `feels_seen` auto-flip logic:** Remove the hard turn-count auto-flip. Instead, flip `feels_seen = True` when `validation_trigger_count == 0` and `heard_turns >= 2` (patient has had at least 2 exchanges without a dismissal signal). Keep the somatic hold as-is.

**Update `_DISCOVERY_BLOCKED_TOOLS`:** Keep this set. It's used in the system prompt instructions — no code enforcement needed since the system prompt already tells the LLM not to call these tools in discovery. If you want belt-and-suspenders enforcement, add a tool-start callback check (optional, low priority).

### 2. `models.py` — Add `symptoms_captured` field to `SessionState`

```python
symptoms_captured: bool = False  # True once ≥1 observed_symptom or patient_voice_note has fired
```

### 3. `agent.py` — Set `symptoms_captured = True` when symptom tools fire

In the `SessionQueueCallback.on_tool_end()` (in `main.py`) or via a post-executor hook in `agent.py`, detect when `observed_symptom`, `patient_voice_note`, or `fhir_symptom_record` completes and flip `session_state.symptoms_captured = True`.

The cleanest place is `main.py`'s `SessionQueueCallback.on_tool_end()`:

```python
SYMPTOM_CAPTURE_TOOLS = {"observed_symptom", "patient_voice_note", "fhir_symptom_record"}

def on_tool_end(self, output, **kwargs):
    tool_name = kwargs.get("name", "unknown")
    if tool_name in SYMPTOM_CAPTURE_TOOLS:
        self.session_state.symptoms_captured = True
    # ... rest of existing event emission
```

### 4. `prompts/system.py` — Strengthen the TOOL USE instruction for `patient_lens`

The existing system prompt already says to call `patient_lens` when a patient names a condition (line 124). The gate was preventing it. Now that the executor runs freely, this instruction will take effect.

However, strengthen the instruction slightly so the LLM knows this is its **primary response** during discovery, not an optional add-on:

Change (line 124):
> "Use this INSTEAD of specialist_navigator during the listening phase — it helps the patient feel understood without routing them prematurely."

To:
> "During discovery (before navigation begins), calling patient_lens IS the correct response when a patient names a condition — it MUST be called before asking follow-up questions. Do not skip it."

### 5. `prompts/system.py` — Update DISCOVERY MODE section

Update the discovery mode bullet (line 22–41) to remove the turn-count framing and replace with symptom/validation-state framing:

```
DISCOVERY MODE (early listening phase):
- Your priority is listening and symptom capture, not navigation.
- Do NOT call specialist_navigator or appointment_brief_generator until:
  (a) the patient feels heard (no dismissal signals in the exchange), AND
  (b) at least one symptom has been captured via observed_symptom or patient_voice_note.
- When a patient names a condition (e.g. "I feel like I have ADHD"), call patient_lens immediately.
  Then ask a follow-up question about WHY they think they have that condition — what specific
  experiences led them there. Example: "What's been making you wonder about ADHD specifically?"
```

---

## Files to Modify

| File | Change |
|---|---|
| `advocate/agent.py` | Remove `_is_listening()`, `_DISCOVERY_PIVOT_CONTEXT`, gate block; add lightweight event emit; update `feels_seen` auto-flip logic |
| `advocate/models.py` | Add `symptoms_captured: bool = False` to `SessionState` |
| `advocate/main.py` | In `SessionQueueCallback.on_tool_end()`, set `session_state.symptoms_captured = True` for symptom tools |
| `advocate/prompts/system.py` | Strengthen `patient_lens` instruction; update DISCOVERY MODE section to drop turn-count framing |

---

## What Does NOT Change

- Somatic classifier, validation classifier — unchanged
- `patient_lens` tool itself — unchanged
- `observed_symptom`, `patient_voice_note` tools — unchanged
- SSE event pipeline — unchanged
- Flutter sidebar rendering — unchanged (it already handles `listening_gate` events)
- `_DISCOVERY_BLOCKED_TOOLS` set — kept for reference but enforcement is now prompt-only

---

## Verification

1. Start the backend: `cd advocate && uvicorn main:app --reload`
2. Send "i feel like i have adhd" in the chat
3. **Expected:** Sidebar shows `patient_lens` event firing. Agent responds with an experiential summary of ADHD from a patient perspective, then asks why they think they have it (specific experiences).
4. **Expected:** `listening_gate` sidebar event still fires showing "navigation paused — no symptoms captured yet"
5. Send a follow-up describing a symptom (e.g., "I can never finish tasks, I lose track mid-sentence")
6. **Expected:** `observed_symptom` fires, sidebar shows it. `symptoms_captured` flips to True.
7. After 2+ exchanges with no dismissal signals, `feels_seen` flips. Once both conditions met, specialist_navigator becomes available.
8. Run pytest: `cd advocate && python -m pytest tests/ -x --tb=short`
