# Plan: Fix chatbot stuck-on-topic + redesign somatic mode as non-blocking

## Context

Two problems:
1. **Stuck-on-topic bug**: `somatic_mode_active` never resets. `SessionAwareMemory` prepends the full `session_state` JSON every turn, so the LLM sees `somatic_mode_active: true` forever and keeps treating every message as somatic intake.
2. **Somatic mode is too sticky**: It currently blocks topic-switching. The correct behavior is: somatic collection is opportunistic — if the patient skips it, the agent moves on; if they answer a somatic question later in passing, the agent captures it passively; if the brief is requested and no somatic data was collected, the agent asks once softly before generating.

---

## Intended behavior (from user decisions)

| Scenario | Behavior |
|---|---|
| Somatic fires, patient ignores it and asks a new topic | Answer the new topic immediately. Mark somatic as "pending, not blocking". |
| Patient later mentions body-based language in any message | Classifier appends to `patient_language_buffer`; if buffer has enough signal, run translation passively and set `clinical_descriptor`. Mark somatic as collected. |
| Patient asks for the brief and somatic data is missing | One soft nudge: "Before I generate your brief, it would help to know more about how you're feeling physically. Can you describe where or how you feel it? (Or say 'skip' to generate the brief now.)" |
| Patient says skip (or ignores the nudge a second time) | Generate brief without `patients_own_words` section. |

---

## Changes

### `models.py` — add two fields to `SessionState`

```python
somatic_collected: bool = False          # True once clinical_descriptor is set
clarification_turns_used: int = 0        # Persists clarification count across re-instantiation
```

### `prompts/somatic.py` — guard re-activation

In `process_turn()`: only set `somatic_mode_active = True` if somatic data hasn't been collected yet:

```python
async def process_turn(self, patient_message: str) -> SomaticClassifierOutput:
    result = await self.classify(patient_message)
    if result.somatic_trigger:
        self.session_state.patient_language_buffer.append(patient_message)
        if not self.session_state.somatic_collected:
            self.session_state.somatic_mode_active = True
    return result
```

This means:
- After collection resolves, new somatic-sounding messages still accumulate in the buffer (useful for the brief) but don't re-lock the agent.
- If the patient never answered and `somatic_collected` is still `False`, subsequent triggers can still activate the mode.

### `agent.py` — three changes

**1. Reset somatic mode after translation completes** (`chat()`, ~line 348):

```python
self.session_state.clinical_descriptor = translation.get("translated_text", "")
self.session_state.somatic_mode_active = False
self.session_state.somatic_collected = True
```

**2. Non-blocking topic switch**: Remove nothing — the `clarification_flow.should_clarify()` guard already lets the agent proceed. The key fix is that `somatic_mode_active` resets, so the LLM no longer sees it as active context. The agent will naturally answer the new topic.

**3. Soft nudge before brief generation**: Add a pre-brief check. When the agent is about to call `appointment_brief_generator` and `somatic_collected` is `False` and `patient_language_buffer` is empty, intercept with a single soft question. Track whether the nudge was already issued in a new `somatic_nudge_issued` field on `SessionState`.

Add to `SessionState` in `models.py`:
```python
somatic_nudge_issued: bool = False
```

In `agent.py`, add a check before the executor call. If the message is clearly a brief request (contains "brief", "prep", "appointment summary") and somatic data is missing and nudge hasn't been issued yet:

```python
_BRIEF_REQUEST_KEYWORDS = {"brief", "prep sheet", "appointment summary", "generate brief", "create brief"}

def _message_is_brief_request(message: str) -> bool:
    lower = message.lower()
    return any(kw in lower for kw in _BRIEF_REQUEST_KEYWORDS)

_SOMATIC_NUDGE = (
    "Before I generate your brief, it would help to know a bit more about how you're feeling physically. "
    "Can you describe where in your body you feel it, or what it feels like? "
    "(If you'd prefer to skip this, just say 'skip' and I'll generate the brief now.)"
)
```

In `chat()`, before the executor call:
```python
if (
    _message_is_brief_request(message)
    and not session_state.somatic_collected
    and not session_state.patient_language_buffer
    and not session_state.somatic_nudge_issued
):
    session_state.somatic_nudge_issued = True
    return _SOMATIC_NUDGE
```

If the patient says "skip" on the next turn, the executor proceeds normally (LLM sees no somatic context → generates brief without `patients_own_words`). If they provide somatic language, the somatic classifier picks it up passively on the next turn.

**4. Fix clarification turn persistence** — `ClarificationSubFlow` reads/writes `session_state.clarification_turns_used` instead of its own in-memory counter:

```python
def should_clarify(self) -> bool:
    return (
        self.session_state.confidence_tier == "LOW"
        and self.session_state.entry_point == "no_appointment"
        and self.session_state.clarification_turns_used < self.MAX_CLARIFICATION_TURNS
    )

def increment_turn(self) -> None:
    self.session_state.clarification_turns_used += 1

def is_exhausted(self) -> bool:
    return self.session_state.clarification_turns_used >= self.MAX_CLARIFICATION_TURNS
```

Remove `self.clarification_turn_count = 0` from `__init__`.

---

## Files changed

| File | Change |
|---|---|
| `models.py` | Add `somatic_collected`, `somatic_nudge_issued`, `clarification_turns_used` to `SessionState` |
| `prompts/somatic.py` | Guard `somatic_mode_active` assignment behind `not somatic_collected` |
| `agent.py` | Reset somatic state after translation; add brief-request nudge; fix clarification persistence |

---

## Tests to write

New file: `tests/test_eval_agent.py` — append to existing test sections (following existing `print("\n[EVAL: ...]")` convention).

### Somatic mode reset tests
```
test_somatic_resets_after_translation
  - session with somatic_mode_active=True, patient_language_buffer populated, clinical_descriptor=None
  - mock run_clinical_language_translator to return {"translated_text": "burning chest pain"}
  - call the translation block logic directly
  - assert somatic_mode_active is False, somatic_collected is True, clinical_descriptor is set

test_somatic_no_reactivation_after_collected
  - session with somatic_collected=True, clinical_descriptor="burning chest pain"
  - call SomaticClassifierMiddleware.process_turn() with mock LLM returning somatic_trigger=True
  - assert somatic_mode_active remains False (guard in process_turn)
  - assert patient_language_buffer appended (passive collection still works)

test_somatic_activates_when_not_collected
  - session with somatic_collected=False, somatic_mode_active=False
  - call process_turn() with mock LLM returning somatic_trigger=True
  - assert somatic_mode_active is True
```

### Brief nudge tests
```
test_brief_request_detected
  - _message_is_brief_request("can you generate my brief") → True
  - _message_is_brief_request("show me a prep sheet") → True  (note: "prep sheet" keyword)
  - _message_is_brief_request("what specialist do I need") → False

test_somatic_nudge_fires_on_brief_request
  - session: somatic_collected=False, patient_language_buffer=[], somatic_nudge_issued=False
  - call agent.chat("generate my brief") with mocked executor
  - assert returned string is _SOMATIC_NUDGE
  - assert session.somatic_nudge_issued is True
  - assert executor was NOT called

test_somatic_nudge_only_fires_once
  - session: somatic_nudge_issued=True (already issued)
  - call agent.chat("generate my brief")
  - assert executor IS called (nudge skipped, falls through to normal flow)

test_no_nudge_when_somatic_collected
  - session: somatic_collected=True
  - call agent.chat("generate my brief")
  - assert executor IS called (no nudge)

test_no_nudge_when_buffer_has_data
  - session: somatic_collected=False, patient_language_buffer=["burning pain in chest"]
  - call agent.chat("generate my brief")
  - assert executor IS called (buffer has data, nudge skipped)
```

### Clarification persistence tests
```
test_clarification_uses_session_state
  - create ClarificationSubFlow with session having clarification_turns_used=2
  - assert should_clarify() is True (2 < MAX=3)
  - increment_turn()
  - assert session.clarification_turns_used == 3
  - assert is_exhausted() is True

test_clarification_persists_across_reinstantiation
  - create session with clarification_turns_used=3
  - create new ClarificationSubFlow (simulates re-instantiation)
  - assert should_clarify() is False immediately (not reset to 0)
```

### conftest.py additions
Add fixtures needed by the new tests:
```python
@pytest.fixture
def session_somatic_pending():
    # somatic triggered but patient skipped it — no descriptor yet
    return SessionState(
        patient_id="test-patient-somatic",
        entry_point="appointment_scheduled",
        somatic_mode_active=False,
        somatic_collected=False,
        patient_language_buffer=[],
    )

@pytest.fixture
def session_somatic_collected():
    return SessionState(
        patient_id="test-patient-somatic2",
        entry_point="appointment_scheduled",
        somatic_collected=True,
        clinical_descriptor="burning pain in upper chest, worse on exertion",
    )
```

## Verification

1. Run `python -m pytest tests/test_eval_agent.py -x --tb=short` — all new tests pass
2. Run `python -m pytest tests/ -x --tb=short` — full suite passes
3. Manual: trigger somatic mode → ignore → ask new topic → confirm agent answers normally
4. Manual: ask for brief with no somatic data → confirm one soft nudge → say "skip" → brief generates
