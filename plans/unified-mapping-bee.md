# Plan: Update Firestore DB with Most Recent Structure

## Context

Three gaps need closing:

1. **Session persistence** — `SessionState` lives in `_sessions` (in-memory dict in `main.py`). Real users lose session context on restart. Demo patients (personas: serena, maya, ruth, etc.) are fixed-seed and should NOT be persisted — they reset cleanly per session. Non-demo users need session persistence in Firestore so timeline/brief/escalation state survives.

2. **Flutter field mismatches** — `ClinicalBriefModel.fromJson` reads `fhir_citations` (a list) and joins it into `evidenceSummary`, but the backend now sends a proper `evidence_summary` string. The field mapping is wrong. Additionally `SessionModel` does not capture `confidence_tier` or `escalation_flags` from the `/chat` response, so Flutter cannot react to escalation events.

3. **User doc fields** — `auth.py:get_patient_id` writes `users/{uid}` with only `created_at` / `last_active_at`. It never writes `patient_id` or `auth_type`, which breaks any downstream query that expects those fields.

---

## Files to Modify

| File | Change |
|---|---|
| `advocate/auth.py` | Write `patient_id` and `auth_type` when creating/updating `users/{uid}` |
| `advocate/main.py` | Persist `SessionState` to `sessions/{uid}/{session_id}` on each chat response; skip write for demo personas |
| `advocate/firestore_fhir.py` | Add `save_session_state()` helper |
| `flutter/lib/shared/models/clinical_brief.dart` | Fix `evidenceSummary` to read `evidence_summary` string (not join `fhir_citations`) |
| `flutter/lib/shared/models/session.dart` | Add `confidenceTier` and `escalationFlags` fields; parse from `/chat` response JSON |

---

## Implementation Steps

### 1. `auth.py` — user doc fields

In `get_patient_id()`, when creating a new user doc write:
```python
{
    "created_at": SERVER_TIMESTAMP,
    "last_active_at": SERVER_TIMESTAMP,
    "auth_type": "anonymous",    # hardcoded for now; updated on upgrade
    "patient_id": fhir_id or persona,
}
```
On update (doc exists), also set `patient_id` and `auth_type` if missing (use `set(..., merge=True)` instead of `update()`). The `patient_id` value is the same `fhir_id` already computed at line 69.

### 2. `firestore_fhir.py` — session persistence helper

Add a `save_session_state(uid, session_id, session_state, db)` coroutine that writes:
- Collection path: `sessions/{uid}/{session_id}` (document per session)
- Fields: `patient_id`, `entry_point`, `stages_completed`, `confidence_tier`, `escalation_flags`, `timeline_result` (if set), `brief_result` (if set), `updated_at: SERVER_TIMESTAMP`
- Skip write entirely if `uid` maps to a demo persona (check: `patient_id` matches any `DEMO_PATIENT_ID_*` env var value, or falls back to the raw persona name from the valid set `{"serena","maya","ruth","priya","marcus","ava","elena","diane"}`)

The is-demo check: pass `is_demo: bool` as a parameter — caller determines it.

### 3. `main.py` — call save on each chat response

- Add `uid: str = Depends(verify_firebase_token)` to both `chat()` and `chat_stream()` endpoints (currently they only expose `patient_id`). Thread `uid` through.
- Determine `is_demo = patient_id in _VALID_PERSONAS or patient_id == os.environ.get(f"DEMO_PATIENT_ID_{...}")` — simplest: check if `patient_id` is in the `_VALID_PERSONAS` set from `auth.py`, or expose a `is_demo_patient(patient_id)` helper in `auth.py`.
- After building `ChatResponse`, if `not is_demo`: `await save_session_state(uid, session_id, session_state, db)`.
- Use a separate `db` instance for the save (open + close inline, same pattern as `auth.py`).

### 4. `flutter/lib/shared/models/clinical_brief.dart` — fix evidenceSummary

Change line 33-35:
```dart
// BEFORE (wrong):
evidenceSummary: (json['fhir_citations'] as List<dynamic>?)
    ?.map((e) => e.toString())
    .join(', ') ?? '',

// AFTER (correct):
evidenceSummary: json['evidence_summary'] as String? ?? '',
```

### 5. `flutter/lib/shared/models/session.dart` — add confidence_tier + escalation_flags

Add two fields and parse from JSON:
```dart
final String confidenceTier;           // 'HIGH' | 'MODERATE' | 'LOW'
final List<String> escalationFlags;

// In fromJson:
confidenceTier: json['confidence_tier'] as String? ?? 'LOW',
escalationFlags: (json['escalation_flags'] as List<dynamic>? ?? []).cast<String>(),
```
Also update `copyWith` accordingly.

---

## Constraints / Invariants

- Demo patients (`_VALID_PERSONAS` set in `auth.py`) must never be written to `sessions/` — they are shared across users.
- `writeBatch` is not needed here: each session write is a single document — no related documents touched in same write.
- `save_session_state` must be fire-and-forget safe: wrap in try/except, log warnings, never raise (session persist failure must not break chat response).
- `model_dump()` on `SymptomTimelineOutput` / `AppointmentBriefOutput` is already used in `main.py:get_session_data()` — reuse that same pattern for the Firestore write.
- Keep `auth.py:_VALID_PERSONAS` as the single source of truth for demo persona names.

---

## Verification

1. Run backend locally, log into a non-demo account, send a chat message → check Firestore console for `sessions/{uid}/{session_id}` document.
2. Log into a demo persona (serena) → confirm NO document written under `sessions/`.
3. Check `users/{uid}` in Firestore → confirm `patient_id` and `auth_type` fields are present.
4. In Flutter, after a chat response that includes escalation_flags → verify `SessionModel.escalationFlags` is non-empty.
5. Navigate to Brief tab → verify `ClinicalBriefModel.evidenceSummary` shows the text from `evidence_summary` (not a comma-joined list of citation IDs).
