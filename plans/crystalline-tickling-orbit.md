# Plan: Fix Agent Conversation Quality + Force Tool Calls

## Context

Two UX problems observed in the chat:

1. **Vague, clinical follow-up question** — After the patient says "I feel like I have ADHD" and "for awhile", the agent asks "What symptoms have you been experiencing?" This is intake-form language — clinical, closed, chore-like. The system prompt says to use plain language and body-based prompting, but the agent is drifting.

2. **Missing tool call / passive note-taking** — After "just so overwhelmed", the agent replied "I've made a note of that. Can you tell me more about what 'overwhelmed' feels like for you?" — no `symptom_timeline` call. The system prompt mandates "ANY question about symptoms... MUST trigger the appropriate tool call" but there's no enforcement; the LLM ignores it.

## Fix

### Fix 1 — Rewrite CONVERSATION STYLE in system prompt

**File: `prompts/system.py`**

Add explicit prohibition on clinical intake phrasing. Add instruction to mirror patient language and respond with curiosity, not form questions.

Replace the CONVERSATION STYLE block:
```
CONVERSATION STYLE:
- Ask intake questions 1–2 at a time, conversationally. Do not dump all questions at once.
- Use plain language. The patient is not a clinician. NEVER use clinical intake phrasing like "What symptoms have you been experiencing?" or "Can you describe your complaint?" — these feel like forms, not conversations.
- Mirror the patient's own words. If they say "I feel like I have ADHD", respond to that experience with curiosity: ask about the hardest part, what it feels like day-to-day, not what "symptoms" they have.
- Treat the patient's own words as primary data, not noise to filter against records.
- When a patient struggles to describe something, switch to body-based prompting: "Where in your body do you feel it?", "What does it feel like physically?"
```

### Fix 2 — Rewrite TOOL USE to trigger early, not just on explicit questions

**File: `prompts/system.py`**

The current rule says "call when patient asks about their symptom history." The LLM interprets this narrowly (only explicit questions). Change it to trigger on first mention of any health concern.

Replace the symptom_timeline line:
```
- symptom_timeline: call at the FIRST sign of a health concern in the conversation — do not wait for an explicit question about records. When a patient mentions any symptom, condition, feeling, or health experience ("I feel like I have ADHD", "I've been exhausted", "something is off"), call symptom_timeline immediately to retrieve their record context before formulating your response. Do NOT say "I've made a note of that" or acknowledge symptoms without first calling this tool.
```

### Fix 3 — Add note-taking guard in agent.py

**File: `agent.py`**

After the executor result is received (~line 381), add a lightweight check: if the output contains passive note-taking phrases AND no tool was called (empty `intermediate_steps`), re-invoke with an explicit system reminder forcing the tool call.

Add helper near the top of the module (with other helpers):
```python
_NOTE_TAKING_PHRASES = [
    "i've made a note",
    "i'll make a note",
    "i've noted that",
    "i'll note that",
    "noted that",
    "i'll remember that",
]

def _output_skipped_tool(output: str, intermediate_steps: list) -> bool:
    lowered = output.lower()
    if not any(phrase in lowered for phrase in _NOTE_TAKING_PHRASES):
        return False
    return len(intermediate_steps) == 0
```

After line 381 (`output = result.get("output", "")`):
```python
intermediate_steps = result.get("intermediate_steps", [])
if _output_skipped_tool(output, intermediate_steps):
    forced = (
        f"[SYSTEM: You skipped a required tool call. You MUST call symptom_timeline "
        f"before responding to any health-related message. Do not note-take without "
        f"retrieving records first.]\n\nPatient: {augmented_message}"
    )
    result = await self.executor.ainvoke(
        {"input": forced},
        config={"callbacks": callbacks} if callbacks else {},
    )
    output = result.get("output", output)
```

### Fix 4 — Rename symptom_timeline → read_medical_history everywhere

The tool reads FHIR chart records (Encounter, Condition, Observation, MedicationRequest). It does not include patient-reported language and does not write anything. `symptom_timeline` is misleading — it implies patient-described symptoms and suggests a UI output rather than a data-fetching action.

Rename to `read_medical_history` in:
- `agent.py`: tool name in `StructuredTool.from_function()` (`name="read_medical_history"`)
- `prompts/system.py`: all references in TOOL USE rules
- `models.py`: `SymptomTimelineInput` / `SymptomTimelineOutput` class names → `MedicalHistoryInput` / `MedicalHistoryOutput`, field `somatic_trigger_recommended` stays as-is
- `tools/symptom_timeline.py`: rename file to `tools/medical_history.py`, rename `run_symptom_timeline` → `run_medical_history`
- `agent.py`: update import from `tools/symptom_timeline` → `tools/medical_history`
- `verification/confidence.py`: no reference to tool name, no change needed
- Flutter `advocate_api.dart` / `session_data_provider.dart`: the Eval Suite panel displays `tool_name` from the SSE event — the label will automatically update once the backend emits `read_medical_history`

## Files to Change

| File | Change |
|------|--------|
| `prompts/system.py` | CONVERSATION STYLE: prohibit clinical intake phrasing, add mirror-language instruction. TOOL USE: rename to `read_medical_history`, trigger on first health mention not just explicit questions. |
| `agent.py` | Rename tool, add `_output_skipped_tool()` + re-invoke guard after executor result, update import |
| `tools/symptom_timeline.py` | Rename file to `tools/medical_history.py`, rename `run_symptom_timeline` → `run_medical_history` |
| `models.py` | Rename `SymptomTimelineInput` → `MedicalHistoryInput`, `SymptomTimelineOutput` → `MedicalHistoryOutput` |

## Verification

1. Start a new chat, send "I feel like I have ADHD"
   - Eval Suite panel should show `read_medical_history` tool call immediately (not `symptom_timeline`)
   - Response should mirror ADHD experience with curiosity, not ask "What symptoms have you been experiencing?"
2. Send "just so overwhelmed"
   - Agent should call `read_medical_history` (or use cached) — no "I've made a note of that" without a tool call
3. Send a pure greeting like "hi" — no tool call should fire (ensure guard doesn't over-trigger)
