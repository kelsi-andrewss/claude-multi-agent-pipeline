# Plan: Replace rotation_state round-robin with client-supplied persona

## Context

The Flutter demo screen has a persona picker (Serena / Maya / Ruth). When selected, the user is dropped into a **real** session: real LangChain agent, real Gemini calls, real tool execution, real FHIR queries — against that persona's synthetic patient records in `fhir_data/{persona}`.

The bug: the selected persona is **never sent to the backend**. `auth.py` assigns personas via a round-robin counter in `rotation_state/counter` — completely disconnected from the UI choice. So a user who picks Serena may get Maya's FHIR data.

**Goal:** Flutter sends the chosen persona as an `X-Persona` header. Backend resolves `patient_id` from that header instead of from `rotation_state`. Remove the round-robin assignment logic.

`fhir_data/{patient_id}` top-level collection stays unchanged.

---

## Changes

### 1. `flutter/lib/services/advocate_api.dart`

Add `X-Persona` header to all outbound requests. `_storageService` already exists on the class (currently unused — has `// ignore: unused_field`). `LocalStorageService.getPersona()` already reads key `selected_persona`.

Add a helper and include the header in `sendMessage`, `streamMessage`, and `fetchSessionData`:

```dart
Future<String?> _getPersona() => _storageService.getPersona();

// In each _doPost / http.get call:
final persona = await _getPersona();
if (persona != null) headers['X-Persona'] = persona;
```

### 2. `flutter/lib/features/demo/walkthrough_controller.dart`

Read first to confirm whether `savePersona(persona.name)` is called when a persona is selected. If not, add it in `DemoScreen.onPersonaSelected` so the value is persisted to `shared_preferences` before the first chat request fires.

### 3. `advocate/auth.py`

Replace round-robin logic with header-based resolution:

- Add `x_persona: str | None = Header(default=None)` to `get_patient_id`
- Validate against known personas; default to `"serena"` if missing/invalid
- Resolve FHIR ID from `DEMO_PATIENT_ID_{PERSONA.upper()}` env var (same lookup already on line 85)
- Keep `last_active_at` update on `users/{uid}`
- Remove: `_PERSONAS` list, `rotation_state/counter` transaction, `patient_id` field write

```python
_VALID_PERSONAS = {"serena", "maya", "ruth", "priya", "marcus", "ava", "elena", "diane"}

async def get_patient_id(
    uid: str = Depends(verify_firebase_token),
    x_persona: str | None = Header(default=None),
) -> str:
    persona = x_persona if x_persona in _VALID_PERSONAS else "serena"
    db = _make_db()
    try:
        user_ref = db.collection("users").document(uid)
        doc = await user_ref.get()
        if doc.exists:
            await user_ref.update({"last_active_at": _firestore.SERVER_TIMESTAMP})
        else:
            await user_ref.set({
                "created_at": _firestore.SERVER_TIMESTAMP,
                "last_active_at": _firestore.SERVER_TIMESTAMP,
            })
        fhir_id = os.environ.get(f"DEMO_PATIENT_ID_{persona.upper()}")
        return fhir_id if fhir_id else persona
    finally:
        db.close()
```

---

## Files to modify

| File | Change |
|---|---|
| `advocate/auth.py` | Replace round-robin with `X-Persona` header; remove `rotation_state` writes; remove `_PERSONAS` |
| `flutter/lib/services/advocate_api.dart` | Add `X-Persona` header to all outgoing requests |
| `flutter/lib/features/demo/walkthrough_controller.dart` | Read first; add `savePersona()` call if missing |

---

## What is NOT changing

- `rotation_state/counter` Firestore document — can be manually deleted from console after deploy
- `fhir_data/{patient_id}` collection — stays as-is
- `users/{uid}` — keeps `created_at`, `last_active_at`; `patient_id` field no longer written
- Flutter persona picker UI, `DemoPersona` enum, `demo_script.dart` — no changes
- `firestore_fhir.py` — no changes

---

## Verification

1. Select "Maya" on the persona screen, send a chat message
2. Confirm backend resolves `patient_id = maya` (check logs)
3. Navigate to Timeline — should show Maya's FHIR data (ADHD/autism conditions)
4. Select "Serena", send a message — Timeline should show post-concussion data
5. Confirm `rotation_state/counter` is no longer incrementing (Firestore console)
