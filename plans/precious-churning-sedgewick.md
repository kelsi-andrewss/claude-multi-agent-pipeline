# Plan: Emotional Validation Gate — "Felt Heard" Before Navigation

## Context

The screenshot shows Advocate jumping to specialist recommendations and PCP referral scripts
after just two turns: "i feel like i have adhd" → "idk i just feel overwhelmed". The patient
shared vulnerability and the agent responded with a navigation checklist and a `specialist_navigator`
call visible in the eval panel. This is the dismissal pattern Advocate is supposed to prevent.

Root causes:
1. **Discovery pivot is post-executor** — the executor still runs and calls `specialist_navigator`,
   then the output is overwritten. The tool still fires and shows in the eval panel.
2. **Somatic trigger doesn't block the executor** — sets `somatic_mode_active=True` but the
   executor runs anyway.
3. **`patient_lens` tool doesn't exist** — when a patient says "I feel like I have ADHD",
   the agent should look up what that condition *feels like* experientially, not route to a specialist.
4. **Symptom tool names are confusing** — `symptom_writer` and `save_symptom_note` don't signal
   what data they hold or who provided it.

---

## Decisions

- New tool: **`patient_lens`** — experiential condition lookup ("what does it feel like to live with X")
- New evaluator event: **`validation_eval`** — fires every time the pre-executor gate blocks navigation
- Gate extension flag: **`feels_seen: bool = False`** on `SessionState` — gate stays active until set
- Symptom tracking rename:
  - `symptom_writer` → **`fhir_symptom_record`** (writes a structured clinical FHIR Observation)
  - `save_symptom_note` → **`patient_voice_note`** (saves the patient's own words verbatim to Firestore)
  - New: **`observed_symptom`** — middle layer, what the agent observes from patient language
    (structured but not FHIR-grade; lives in Firestore, feeds the brief's "patient's own words" section)

---

## Files to Change

| File | Change |
|---|---|
| `agent.py` | Pre-executor listening gate; remove post-executor discovery pivot; `validation_eval` emit; `patient_lens` event emit; rename tool references |
| `models.py` | Add `feels_seen: bool = False` and `heard_turns: int = 0` to `SessionState` |
| `tools/patient_lens.py` | New file — experiential condition lookup (direct LLM, no FHIR) |
| `tools/observed_symptom.py` | New file — agent-observed symptom (structured, Firestore, not FHIR) |
| `tools/symptom_writer.py` | Rename to `fhir_symptom_record.py`; rename function and tool name |
| `tools/symptom_notes.py` | Rename tool name from `save_symptom_note` → `patient_voice_note`; rename `get_symptom_notes` → `get_patient_voice_notes` |
| `prompts/system.py` | Add `patient_lens` and `observed_symptom` to TOOL USE; update `fhir_symptom_record` and `patient_voice_note` names |
| `flutter/lib/features/agent_state/agent_state_panel.dart` | Add icons for `patient_lens`, `observed_symptom`, `validation_eval` hard-stop; update renamed tool names |
| `tests/test_listening_gate.py` | New test file |

---

## 1. Pre-Executor Listening Gate (`agent.py`)

Replace the current **post-executor** discovery pivot with a **pre-executor** gate.

**Gate condition:**
```python
_is_listening = (
    session_state.discovery_turns <= _DISCOVERY_MODE_TURNS
    or session_state.somatic_mode_active
    or not session_state.feels_seen
)
```

**Gate logic (new step in `chat()`, before `executor.ainvoke()`):**
```python
if _is_listening:
    pivot_messages = [
        ("system", SYSTEM_PROMPT),
        ("human", _DISCOVERY_PIVOT_CONTEXT.format(patient_message=augmented_message)),
    ]
    pivot_response = await self.llm.ainvoke(pivot_messages)
    output = getattr(pivot_response, "content", "")
    session_state.heard_turns += 1
    # Emit validation_eval event
    if self._event_queue is not None:
        event = json.dumps({
            "tool_name": "validation_eval",
            "status": "done",
            "output": f"Listening turn {session_state.heard_turns} — navigation paused",
            "timestamp": datetime.utcnow().isoformat(),
        })
        self._event_queue.put_nowait(event)
    return output  # ← executor never runs
```

**Remove** the existing post-executor discovery pivot block (currently lines ~488–498).

**`feels_seen` is set to `True`** when: `discovery_turns > _DISCOVERY_MODE_TURNS` AND
`somatic_mode_active=False`. The agent does not set it automatically — the LLM signals readiness
via an explicit message pattern or when the patient says something like "ok let's look for a doctor."
For now: `feels_seen` defaults to False and is set to True when `discovery_turns > _DISCOVERY_MODE_TURNS
and not somatic_mode_active` — i.e., it flips at the same time the natural gate would have released.
This makes `feels_seen` immediately useful as a manual override: any code can set it True earlier
(future: LLM-driven) or keep it False longer (future: distress continuation).

---

## 2. `models.py`

```python
feels_seen: bool = False
heard_turns: int = 0
```

---

## 3. `tools/patient_lens.py` (new)

```python
async def run_patient_lens(condition_name: str, patient_statement: str, llm) -> dict:
    """
    Return an experiential summary of what living with a named condition feels like.
    Not diagnostic. Not navigational. Frames around patient-reported experience.
    Returns: { "condition": str, "experiential_summary": str, "common_patient_phrases": list[str] }
    """
```

Registered as a `StructuredTool` with `args_schema=PatientLensInput`. Direct LLM call, no FHIR.
Called **by the executor** when `feels_seen=True` (normal navigation mode) — but also safe to
call via the direct LLM path since it never navigates.

The LLM will naturally call it instead of `specialist_navigator` during listening phase once
it's in the tool registry and the system prompt instructs it to.

---

## 4. `tools/observed_symptom.py` (new)

Middle-layer symptom record: what the agent observes from patient language — more structured
than a voice note but not FHIR-grade. Stored in Firestore as `observed_symptoms/{patient_id}`.

```python
async def run_save_observed_symptom(
    symptom_description: str,   # agent's structured interpretation
    patient_phrase: str,         # verbatim patient language that triggered this
    confidence: str,             # "low" | "medium" | "high"
    patient_id: str,
) -> dict:
```

Feeds into the brief's "Patient's Own Words" section alongside `patient_voice_note`.

---

## 5. Symptom Tool Renames

### `tools/symptom_writer.py` → `tools/fhir_symptom_record.py`
- Function: `run_symptom_writer` → `run_fhir_symptom_record`
- Tool name: `"symptom_writer"` → `"fhir_symptom_record"`
- Input schema: `SymptomWriterInput` → `FhirSymptomRecordInput` (same fields, renamed)

### `tools/symptom_notes.py`
- `run_save_symptom_note` → `run_save_patient_voice_note`, tool name `"patient_voice_note"`
- `run_get_symptom_notes` → `run_get_patient_voice_notes`, tool name `"get_patient_voice_notes"`
- Input schemas: `SaveSymptomNoteInput` → `SavePatientVoiceNoteInput`; `GetSymptomNotesInput` → `GetPatientVoiceNotesInput`

Update all references in `agent.py`, `models.py`, `prompts/system.py`.

---

## 6. `prompts/system.py` TOOL USE section additions

```
- patient_lens: call when the patient names a condition they think they have (e.g., "I feel like
  I have ADHD", "I wonder if it's fibromyalgia"). Returns an experiential summary of what that
  condition typically feels like from a patient perspective. Use this INSTEAD of specialist_navigator
  during the listening phase — it helps the patient feel understood without routing them prematurely.
- observed_symptom: call when the patient describes a symptom that should be captured for the
  brief. Use this for agent-observed patterns from patient language — more structured than a
  voice note but not yet a clinical FHIR record. Use patient_voice_note for verbatim quotes.
- fhir_symptom_record: call to write a structured symptom to the patient's FHIR record as an
  Observation. Use only when a symptom is clearly defined with onset date and severity.
- patient_voice_note: save the patient's own words verbatim. Use when they describe something
  in a way that should be preserved exactly as said for the appointment brief.
- get_patient_voice_notes: retrieve previously saved patient voice notes.
```

---

## 7. Flutter (`agent_state_panel.dart`)

Add to `_toolIcon()`:
```dart
'patient_lens' => Icons.psychology_outlined,
'observed_symptom' => Icons.sticky_note_2_outlined,
'fhir_symptom_record' => Icons.medical_information_outlined,
'patient_voice_note' => Icons.record_voice_over_outlined,
'get_patient_voice_notes' => Icons.notes_outlined,
```

Add `'validation_eval'` alongside `'somatic_eval'` as a hard-stop evaluator event
(renders with warning icon, "eval" badge, tertiary container background).

```dart
const _kHardStopToolNames = {'somatic_eval', 'validation_eval'};
```

---

## Verification

```bash
PYTHONPATH=/Users/kelsiandrews/gauntlet/advocate .venv/bin/pytest tests/test_listening_gate.py -x --tb=short
PYTHONPATH=/Users/kelsiandrews/gauntlet/advocate .venv/bin/pytest tests/test_distress_response.py tests/test_human_first.py -x --tb=short
```

Manual flow:
1. "hi" → warm greeting, no tools, `validation_eval` in panel
2. "i feel like i have adhd" → `patient_lens` in eval panel (not `specialist_navigator`), experiential response
3. "idk i just feel overwhelmed" → `somatic_eval` + `validation_eval` in panel, empathetic response, no navigation
4. Turn 4, after `feels_seen=True` → `specialist_navigator` now allowed if patient asks
