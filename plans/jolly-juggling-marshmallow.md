# Plan: Connect Tab Data to Real Sources

## Context

Four tabs (Timeline, Brief, Prep, Settings) show hardcoded Serena-persona content. Chat is already wired. The goal is to replace placeholders with real data:

- **Timeline** → `SymptomTimelineOutput.timeline` list from the agent
- **Brief** → `AppointmentBriefOutput` fields from the agent
- **Prep** → same `AppointmentBriefOutput` (`patient_prep_sheet`, `patients_own_words`)
- **Settings** → Firebase Auth `currentUser` (displayName, email)

The backend `SessionState` currently does NOT store brief or timeline results. The SSE `output` field is truncated to 500 chars, which is not enough for full structured data.

**Approach**: Add two fields to `SessionState`, populate them inside the tool wrappers in `agent.py`, and expose a `GET /session/{session_id}/data` endpoint. Flutter fetches this once after each chat turn completes.

---

## Backend Changes

### 1. `advocate/models.py` — extend `SessionState`

Add two optional fields:

```python
class SessionState(BaseModel):
    ...  # existing fields unchanged
    timeline_result: SymptomTimelineOutput | None = None     # new
    brief_result: AppointmentBriefOutput | None = None       # new
```

### 2. `advocate/agent.py` — save tool results to session state

The `AdvocateAgent` tools are registered via `StructuredTool.from_function()`. Each tool already receives `session_state` as a kwarg. After `symptom_timeline` runs, save the result:

```python
# In symptom_timeline wrapper:
result = await run_symptom_timeline(...)
session_state.timeline_result = result
return result
```

Same pattern for `appointment_brief_generator`.

### 3. `advocate/main.py` — add `/session/{session_id}/data` endpoint

```python
@app.get("/session/{session_id}/data")
async def get_session_data(
    session_id: str,
    patient_id: str = Depends(get_patient_id),
):
    key = f"{patient_id}:{session_id}"
    entry = _sessions.get(key)
    if not entry:
        raise HTTPException(status_code=404, detail="Session not found")
    _, session_state, _ = entry
    return {
        "timeline": session_state.timeline_result.model_dump() if session_state.timeline_result else None,
        "brief": session_state.brief_result.model_dump() if session_state.brief_result else None,
        "confidence_tier": session_state.confidence_tier,
        "escalation_flags": session_state.escalation_flags,
    }
```

`_sessions` stores tuples `(agent, session_state, queue)` — confirmed from `main.py:102`.

---

## Flutter Changes

### 4. `flutter/lib/services/advocate_api.dart` — add `fetchSessionData()`

```dart
Future<Map<String, dynamic>?> fetchSessionData(String sessionId) async {
  // GET /session/{sessionId}/data with Bearer token
  // Returns null on 404 (session not yet on server)
}
```

### 5. New: `flutter/lib/shared/models/timeline_event.dart`

```dart
class TimelineEventModel {
  final String date;
  final String resourceType;
  final String display;
  final String sourceId;
  final bool patientReported;
}
```

### 6. New: `flutter/lib/features/session/session_data_provider.dart`

`SessionDataNotifier extends StateNotifier<SessionDataState>`:
- Watches `sessionIdProvider` — when it changes, reset data
- Watches `chatProvider` — when the last message flips `isStreaming: false`, call `fetchSessionData(sessionId)` and update state
- Exposes `timeline: List<TimelineEventModel>` and `brief: ClinicalBriefModel?`

```dart
class SessionDataState {
  final List<TimelineEventModel> timeline;
  final ClinicalBriefModel? brief;
}
```

Map `AppointmentBriefOutput` → `ClinicalBriefModel`:
- `clinical_brief` → `clinicalBrief`
- `patient_prep_sheet` → `patientPrepSheet`
- `patients_own_words` → `patientsOwnWords`
- `confidence_tier` → parse to `ConfidenceTier` enum (`HIGH`/`MODERATE`/`LOW`)
- `evidence_summary` → `evidenceSummary`

### 7. `flutter/lib/features/timeline/timeline_screen.dart`

- Change `StatelessWidget` → `ConsumerWidget`
- Watch `sessionDataProvider`
- If `timeline` is non-empty: render from `List<TimelineEventModel>` (same `_EntryRow` widget, map `resourceType` → type string)
- If empty: show a centered placeholder ("No timeline yet — chat with Advocate to pull your records.")
- Remove hardcoded `_entries` const

### 8. `flutter/lib/features/brief/brief_screen.dart`

- Change `StatefulWidget` → `ConsumerStatefulWidget` (keeps `_copy` method)
- Watch `sessionDataProvider`
- Use `brief` from provider when non-null; show placeholder when null ("Your clinical brief will appear here after your first conversation.")
- Remove `_stub` and hardcoded "Serena Williams-Parker" / "DOB: 1990-03-15" strings
- Header still says "CLINICAL BRIEF" but patient name/DOB fields are removed (not available from tool output)

### 9. `flutter/lib/features/prep/prep_screen.dart`

**`_PatientPrepTab`** → `ConsumerWidget`, watch `sessionDataProvider`:
- `patientPrepSheet` is markdown text. Split on newlines and render non-empty lines as checklist items (replacing hardcoded `_bringItems` / `_questionItems`)
- Simple heuristic: lines starting with `-` or `•` = items; section headers (ALL CAPS or lines ending `:`) = section labels
- If no brief: show placeholder card
- Checkbox state (local `_prepCheckedProvider`) is keyed by index — reset when brief changes

**`_ClinicalBriefTab`** → `ConsumerWidget`, watch `sessionDataProvider`:
- Replace hardcoded "Serena Williams-Parker" header with generic "CLINICAL BRIEF"
- Render `brief.clinicalBrief` as chief concern, `brief.patientPrepSheet` as relevant history
- If no brief: show placeholder

**`_MyOwnWordsTab`** → `ConsumerWidget`, watch `sessionDataProvider`:
- Replace hardcoded quote/key points with `brief.patientsOwnWords` when non-null
- Parse `patientsOwnWords` markdown: quoted paragraph + bullet points
- If null: show placeholder ("Your 'own words' summary will appear here after you describe your symptoms.")

### 10. `flutter/lib/features/settings/settings_screen.dart`

**`_AccountCard`** → `ConsumerWidget`:
- Watch `authStateProvider` (already exists in `router.dart`)
- Import: `import '../../navigation/router.dart' show authStateProvider;`
  (or use `FirebaseAuth.instance.currentUser` directly via a simple provider)
- Display:
  - Name: `user?.displayName ?? (user?.isAnonymous == true ? 'Anonymous' : user?.email?.split('@')[0] ?? 'User')`
  - Email: `user?.email ?? (user?.isAnonymous == true ? 'Anonymous session' : '')`
  - Initials: first letter of name, or '?' for anonymous
- No other settings sections change

---

## Critical Files

| File | Change type |
|---|---|
| `advocate/models.py` | Add 2 fields to `SessionState` |
| `advocate/agent.py` | Save tool results to `session_state.timeline_result` / `.brief_result` |
| `advocate/main.py` | Add `GET /session/{session_id}/data` endpoint |
| `flutter/lib/services/advocate_api.dart` | Add `fetchSessionData()` |
| `flutter/lib/shared/models/timeline_event.dart` | New model |
| `flutter/lib/features/session/session_data_provider.dart` | New Riverpod provider |
| `flutter/lib/features/timeline/timeline_screen.dart` | Wire to provider |
| `flutter/lib/features/brief/brief_screen.dart` | Wire to provider |
| `flutter/lib/features/prep/prep_screen.dart` | Wire to provider |
| `flutter/lib/features/settings/settings_screen.dart` | Wire to Firebase Auth |

---

## Verification

1. `cd advocate && uvicorn main:app --reload`
2. Sign in, send a message that triggers `symptom_timeline`
3. Timeline tab: shows real FHIR events (not Oct/Nov/Dec 2025 hardcodes)
4. Send a message triggering `appointment_brief_generator`
5. Brief tab: shows real brief text, no "Serena Williams-Parker" / "DOB: 1990-03-15"
6. Prep tab: Patient Prep shows real checklist from `patient_prep_sheet`; My Own Words shows real `patients_own_words`
7. Settings: shows logged-in user's real name and email
8. Sign out → Settings account card shows blank/anonymous state
9. `cd flutter && flutter analyze` — no new errors
