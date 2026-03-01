# Plan: Consolidate Firestore Schema — `patients/` + `providers/` + `sessions/`

## Context

Current Firestore has two collections that overlap:
- `users/{uid}` — identity fields (patient_id, auth_type, etc.)
- `fhir_data/{patient_id}` — FHIR bundle

User direction: **"user and sessions are the only top level keys. merge fhir data into users."** Then clarified: **"change users to patients."**

Final top-level collections: **`patients/`**, **`providers/`**, **`sessions/`**. `fhir_data/` is eliminated. `users/` is renamed to `patients/`.

**Key design decision**: `seed_patient.py` knows `patient_id` (FHIR UUID) but not Firebase uid — it runs before any user authenticates. `auth.py` currently writes `users/{uid}` keyed by uid. Fix: write to `patients/{patient_id}` keyed by `patient_id`, storing `uid` as a field. `get_fhir_bundle(patient_id, db)` reads from `patients/{patient_id}` directly.

**`patients` key rename**: `appointment_brief.py` reads `fhir_raw.get("patients") or []`. The key name `"patients"` is confusing alongside the new `patients/` collection and implies multiple patients per doc. Rename to `fhir_patient` (single dict). Update `appointment_brief.py` to read `fhir_raw.get("fhir_patient") or {}`.

---

## Schema

### `patients/{patient_id}` (replaces `users/{uid}` + `fhir_data/{patient_id}`)

```
patients/{patient_id}
  uid: string           # Firebase Auth uid (written by auth.py on first sign-in)
  patient_id: string    # FHIR UUID or persona slug (doc key — written by seed + auth)
  auth_type: string     # "anonymous"
  created_at: timestamp
  last_active_at: timestamp
  seeded_at: timestamp  # set by seed_patient.py
  fhir_patient: dict    # single FHIR Patient resource (name, birthDate, gender, id, etc.)
  conditions: list[dict]
  observations: list[dict]
  encounters: list[dict]
  medications: list[dict]
  coverage: list[dict]
  allergies: list[dict]
```

### `providers/{provider_id}` (new — clinician users, separate from patient data)

```
providers/{provider_id}
  uid: string           # Firebase Auth uid (same as doc key)
  provider_id: string   # same as uid
  auth_type: string     # "email" | "sso"
  name: string
  email: string
  npi: string | null    # National Provider Identifier
  specialty: string | null
  org: string | null    # clinic or hospital affiliation
  created_at: timestamp
  last_active_at: timestamp
```

Provider auth: separate `get_provider_id()` FastAPI dependency — **not in scope for this plan** (schema definition only, no code changes).

### `sessions/{patient_id}/sessions/{session_id}` (unchanged)

No change to `save_session_state()`. Callers pass `patient_id` as the `uid` arg after auth.py change.

---

## Fix 1 — `auth.py`: write to `patients/{patient_id}`, add `uid` field

**File**: `advocate/auth.py`

`get_patient_id()` writes to `db.collection("users").document(uid)`. Change to `patients/{patient_id}`, add `uid` field.

```python
# Before
user_ref = db.collection("users").document(uid)

# After
user_ref = db.collection("patients").document(patient_id)
# Both set() calls gain: "uid": uid
# e.g. {"uid": uid, "patient_id": patient_id, "auth_type": "anonymous", "last_active_at": ...}
```

---

## Fix 2 — `seed_patient.py`: write to `patients/{patient_id}`, use `fhir_patient` key

**File**: `advocate/seed_patient.py` lines 288–297

```python
# Before
await db.collection("fhir_data").document(patient_id).set({
    "patient": patient_resource_data,
    "conditions": conditions,
    ...
}, merge=True)

# After
await db.collection("patients").document(patient_id).set({
    "fhir_patient": patient_resource_data,
    "conditions": conditions,
    ...
}, merge=True)
```

---

## Fix 3 — `firestore_fhir.py`: read from `patients/{patient_id}`

**File**: `advocate/firestore_fhir.py`

```python
# Before
doc_ref = db.collection("fhir_data").document(patient_id)

# After
doc_ref = db.collection("patients").document(patient_id)
```

---

## Fix 4 — `symptom_writer.py`: ArrayUnion on `patients/{patient_id}.observations`

**File**: `advocate/tools/symptom_writer.py` line 34

Current: writes to `fhir_data/{patient_id}/observations` subcollection — invisible to `doc.to_dict()`.

```python
# Before
_, doc_ref = await db.collection("fhir_data").document(patient_id).collection("observations").add(payload)
observation_id = doc_ref.id

# After
import uuid as _uuid
from google.cloud.firestore_v1 import ArrayUnion
observation_id = _uuid.uuid4().hex
payload["id"] = observation_id
await db.collection("patients").document(patient_id).update({
    "observations": ArrayUnion([payload])
})
```

---

## Fix 5 — `appointment_brief.py`: read `fhir_patient` dict instead of `patients[0]`

**File**: `advocate/tools/appointment_brief.py` ~line 372

```python
# Before
patient_resources: list[dict] = fhir_raw.get("patients") or []
patient_resource = patient_resources[0] if patient_resources else {}

# After
patient_resource: dict = fhir_raw.get("fhir_patient") or {}
```

---

## Fix 6 — `cleanup_anonymous_users.py`: query by `uid` field in `patients/`

Doc key is now `patient_id`. Cleanup has `uid` from Firebase Auth. Must query.

**File**: `advocate/functions/cleanup_anonymous_users.py`

```python
# Before
batch.delete(db.collection("users").document(uid))

# After
docs = db.collection("patients").where("uid", "==", uid).limit(1).stream()
for doc in docs:
    batch.delete(doc.reference)
```

---

## Fix 7 — `FIRESTORE_SCHEMA.md` (new file)

**File**: `advocate/FIRESTORE_SCHEMA.md`

Canonical reference: all collections, fields, types, writer/reader ownership per field.

---

## Files to Modify

| File | Change |
|---|---|
| `advocate/auth.py` | `users/{uid}` → `patients/{patient_id}`, add `uid` field |
| `advocate/seed_patient.py` | `fhir_data/{patient_id}` → `patients/{patient_id}`, `fhir_patient` key |
| `advocate/firestore_fhir.py` | `fhir_data/{patient_id}` → `patients/{patient_id}` |
| `advocate/tools/symptom_writer.py` | ArrayUnion on `patients/{patient_id}.observations` |
| `advocate/tools/appointment_brief.py` | `fhir_patient` dict instead of `patients[0]` |
| `advocate/functions/cleanup_anonymous_users.py` | Query `patients/` by `uid` field |

**New file**:

| File | Purpose |
|---|---|
| `advocate/FIRESTORE_SCHEMA.md` | Canonical schema reference |

---

## Verification

1. Re-run `python seed_patient.py` — Firestore: `patients/{patient_id}` doc has `fhir_patient` dict + FHIR arrays. No `fhir_data` or `users` docs written.
2. API call through Flutter — `auth.py` writes `patients/{patient_id}` with `uid` field.
3. `run_appointment_brief_generator` — patient name + DOB appear (from `fhir_patient`).
4. `run_symptom_writer` then `run_symptom_timeline` — observation appears in timeline.
5. `cd advocate && python -m pytest tests/ -x --tb=short` — no regressions.
