# Plan: Fine-tune tool calling consistency

## Context

Tool invocation is inconsistent because:
1. `stages_completed` only tracks `"prep"` and `"insurance"` — `symptom_timeline` and `specialist_navigator` leave no trace, so the LLM has no reliable signal that they've already run.
2. The system prompt `TOOL USE` section gives vague mandatory rules with no concrete trigger examples or negative examples for the gray zone.
3. LLMs are probabilistic — declarative rules alone produce drift. Concrete patterns + stage state together give the LLM two independent signals to agree on.

## Changes

### 1. `agent.py` — stage tracking for timeline and navigator

**Where:** `make_symptom_timeline_tool()` (line 497) and the `specialist_navigator` registration (lines 225–233).

**What:**

In `make_symptom_timeline_tool`, after `session_state.timeline_result = result`, append `"recognition"` to `stages_completed` if not already present:
```python
if "recognition" not in session_state.stages_completed:
    session_state.stages_completed.append("recognition")
```

For `specialist_navigator`, wrap the existing `run_specialist_navigator` call in a closure (same pattern as `make_symptom_timeline_tool`) so we can append `"navigation"` after it runs:
```python
def make_specialist_navigator_tool(session_state: SessionState) -> StructuredTool:
    async def _run(symptom_summary: str, ...) -> dict:
        result = await run_specialist_navigator(...)
        if "navigation" not in session_state.stages_completed:
            session_state.stages_completed.append("navigation")
        return result
    return StructuredTool.from_function(...)
```

Replace the inline `make_tool(run_specialist_navigator, ...)` call in `__init__` with `make_specialist_navigator_tool(session_state)`.

### 2. `prompts/system.py` — rewrite the TOOL USE section

Replace lines 39–45 with a structured rule block:

```
TOOL USE — DECISION RULES:

When to call each tool:
- symptom_timeline: patient asks about their history, records, symptoms over time, or what's documented.
  Skip if: "recognition" in session_state.stages_completed AND patient is not asking to refresh/re-check.
- specialist_navigator: patient asks what kind of doctor they need, what specialist to see, or where to start.
  Skip if: "navigation" in session_state.stages_completed AND no new symptom info has been added.
- appointment_brief_generator: patient asks for a brief, prep sheet, appointment summary, or to prepare for a visit.
  Skip if: "prep" in session_state.stages_completed AND patient has not indicated they want an update.
- insurance_coverage_check: patient asks about insurance, coverage, referrals, or prior authorization.
  Skip if: "insurance" in session_state.stages_completed.
- provider_finder: patient asks to find a doctor, provider, or clinic near them.
- symptom_writer: patient mentions a new symptom not yet in their records — write it.
- save_symptom_note: patient describes their symptoms in their own words — save it for the brief.
- get_symptom_notes: you are about to generate a brief and need the patient's own words.

Do NOT call a tool for:
- Pure greetings ("hello", "thanks", "got it")
- Clarifying questions about your previous response ("what does that mean?", "can you explain that?")
- Acknowledgments or small talk with no health content

When in doubt: call the tool. Never answer a health question from memory.
```

## Files

- `advocate/agent.py` — add `make_specialist_navigator_tool()`, update `make_symptom_timeline_tool()`, update `__init__` registration
- `advocate/prompts/system.py` — rewrite TOOL USE section (lines 39–45)

## Verification

1. Run existing tests: `cd advocate && python -m pytest tests/ -x --tb=short`
2. Manual smoke test: start a session, ask "what's in my records?" → confirm `symptom_timeline` fires and `stages_completed` contains `"recognition"` after the response
3. Ask a follow-up like "can you explain that condition?" → confirm tool is NOT re-called
4. Ask "what specialist do I need?" → confirm `specialist_navigator` fires and `stages_completed` contains `"navigation"`
5. Ask again → confirm it does not re-fire
