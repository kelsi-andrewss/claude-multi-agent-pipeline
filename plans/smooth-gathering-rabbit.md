# Plan: Real validation_eval Classifier + Visual Differentiation

## Context

`validation_eval` currently fires on every gated turn as a turn counter — it's not a real
signal. The listening gate and patient dismissal detection are conflated into one event that
means neither thing clearly.

The correct architecture (mirroring how `somatic_eval` works):

| Event | Meaning | Trigger |
|-------|---------|---------|
| `somatic_eval` | Patient can't articulate — shift to body-based prompting | `SomaticClassifierMiddleware` |
| `validation_eval` | Patient signals they feel dismissed *by the agent* | New `ValidationClassifierMiddleware` |
| `listening_gate` | Navigation blocked — discovery/somatic/feels_seen gate active | Listening gate (renamed from validation_eval) |

---

## Changes

### 1. New file: `prompts/validation.py`

`ValidationClassifierMiddleware` — mirrors `SomaticClassifierMiddleware` structure.

Detects patient language signaling they feel dismissed or unheard *by the agent*:
- Explicit: "you're not listening", "I already said that", "that's not what I meant"
- Deflation after sharing something significant: very short follow-ups ("yeah", "idk", "ok") after an emotionally loaded message
- Frustrated restatement: repeating the same thing with changed emphasis or trailing off
- Withdrawal signals: "never mind", "forget it", "doesn't matter"

```python
VALIDATION_CLASSIFIER_PROMPT = """You are a patient experience classifier for a health navigation agent.
Analyze the patient's message for signals that they feel dismissed, unheard, or invalidated
by the agent they are speaking with.

Signals to detect:
- Explicit dismissal language: "you're not listening", "I already told you", "that's not what I said",
  "you're not hearing me", "never mind", "forget it", "doesn't matter"
- Frustrated restatement: repeating the same concern with increased emphasis or resignation
- Deflated withdrawal: very short responses after sharing something emotionally significant
  ("yeah", "idk", "whatever", "ok fine") that suggest the patient has stopped engaging
- Correcting the agent: "no, what I meant was...", "that's not it", "you misunderstood"

Do NOT trigger on:
- Normal short responses ("yeah", "ok", "thanks") in neutral context
- First-turn short messages — there's no prior exchange to signal withdrawal from
- Messages that are vague because the patient can't find words (that's somatic, not dismissal)

Respond with JSON only.
Format: {"validation_trigger": true, "reason": "brief reason"} or
        {"validation_trigger": false, "reason": "brief reason"}"""
```

Fields on `SessionState` to add:
- `validation_trigger_count: int = 0` — tracks how many times dismissal was detected this session

### 2. New model: `ValidationClassifierOutput` in `models.py`

```python
class ValidationClassifierOutput(BaseModel):
    validation_trigger: bool
    reason: str
```

### 3. `agent.py`

**Import and initialize** `ValidationClassifierMiddleware` alongside `SomaticClassifierMiddleware`
in `AdvocateAgent.__init__`.

**Run classifier every turn** (after somatic, before gate check):
```python
try:
    validation_result = await self.validation_classifier.process_turn(message)
    if validation_result.validation_trigger and self._event_queue is not None:
        event = json.dumps({
            "tool_name": "validation_eval",
            "status": "done",
            "output": validation_result.reason,
            "timestamp": datetime.utcnow().isoformat(),
        })
        self._event_queue.put_nowait(event)
except Exception as exc:
    print(f"[agent] WARNING: validation classifier failed: {exc}", file=sys.stderr)
```

**Rename gate event** from `validation_eval` → `listening_gate`:
```python
# In the listening gate block:
event = json.dumps({
    "tool_name": "listening_gate",
    "status": "done",
    "output": gate_reason,   # specific: "Turn 2/3 — discovery phase" etc.
    "timestamp": datetime.utcnow().isoformat(),
})
```

**Gate reason** should be specific:
```python
if session_state.discovery_turns <= _DISCOVERY_MODE_TURNS:
    gate_reason = f"Turn {session_state.discovery_turns}/{_DISCOVERY_MODE_TURNS} — discovery phase active"
elif session_state.somatic_mode_active:
    gate_reason = "Somatic mode active — navigation paused"
else:
    gate_reason = "Patient not yet feels_seen — gate held"
```

### 4. `flutter/lib/features/agent_state/agent_state_panel.dart`

**Add new icons** to `_toolIcon()`:
```dart
'somatic_eval'    => Icons.hearing_outlined,
'listening_gate'  => Icons.do_not_disturb_outlined,
```

**Three-tier hard-stop classification:**
```dart
// validation_eval: amber/tertiary warning (patient feels dismissed)
// somatic_eval: secondary/blue (language signal)
// listening_gate: neutral gate (navigation blocked, informational)

const _kValidationEvalName = 'validation_eval';
const _kSomaticEvalName = 'somatic_eval';
const _kGateEventNames = {'listening_gate'};
const _kHardStopToolNames = {_kValidationEvalName, _kSomaticEvalName};
```

**Render logic changes:**
- `validation_eval`: tertiary container bg, `Icons.warning_amber_rounded`, "eval" badge (amber)
- `somatic_eval`: secondary container bg, `Icons.hearing_outlined`, "eval" badge (secondary color)
- `listening_gate`: no special background, `Icons.do_not_disturb_outlined`, "gate" badge (neutral)
- All other tools: current behavior unchanged

---

## Files to Change

| File | Change |
|------|--------|
| `prompts/validation.py` | New file — `ValidationClassifierMiddleware` |
| `models.py` | Add `ValidationClassifierOutput`; add `validation_trigger_count: int = 0` to `SessionState` |
| `agent.py` | Import + init classifier; emit `validation_eval` from classifier; rename gate event to `listening_gate` with specific reason string |
| `flutter/lib/features/agent_state/agent_state_panel.dart` | Three-tier event rendering: validation (amber), somatic (blue/secondary), gate (neutral) |

---

## Verification

Manual flow:
1. "idk i just feel overwhelmed" → `somatic_eval` (blue, hearing icon) + `listening_gate` (neutral, gate icon, "Turn 1/3 — discovery phase")
2. "you're not listening to me" → `validation_eval` fires (amber, warning icon) with reason from classifier
3. "never mind" after the agent misses something → `validation_eval` fires
4. Normal turn after discovery → only `listening_gate` fires, no `validation_eval`

Run tests:
```
PYTHONPATH=/Users/kelsiandrews/gauntlet/advocate .venv/bin/pytest tests/test_listening_gate.py -q --tb=short
```
Update `test_listening_gate.py`: `validation_eval` event assertions → `listening_gate`.
Add new tests in `tests/test_validation_classifier.py`.
