# Plan: Seed conditions to Firestore instead of OpenEMR

## Context

`seed_patient.py` attempts to write Condition resources to OpenEMR after creating each Patient.
Neither write path works on `seven.openemr.io`:
- `POST /fhir/Condition` → 404 (route not implemented on hosted instance)
- `POST /api/patient/{id}/medical_problem` → 403 (admin scope not granted to demo OAuth client)

The agent already has a Firestore-based FHIR bundle layer: `firestore_fhir.get_fhir_bundle(patient_id, db)` reads from `fhir_data/{patient_id}` and populates `session_state.fhir_raw`. Tools consume `fhir_raw.get("conditions")` directly. Writing conditions to `fhir_data/{patient_id}` in Firestore is therefore sufficient — no OpenEMR write needed.

## Approach

In `seed_patient.py`, after Patient is created and `patient_id` is obtained:
1. Build FHIR Condition resources using the existing `_condition_resource()` helper
2. Write them to Firestore `fhir_data/{patient_id}` with `{"conditions": [...]}` and `merge=True`
3. Remove the OpenEMR Condition POST loop
4. Remove `user/Condition.write` from the OAuth scope

## Files modified

- `advocate/seed_patient.py` — only file changed

## Changes

### Import to add (top of file)
```python
from google.cloud import firestore as _firestore
```
(`google-cloud-firestore` is already a project dependency via `firebase-admin`)

### OAuth scope
Drop `user/Condition.write` — no longer needed:
```python
"scope": "openid api:fhir user/Patient.write user/Patient.read",
```

### Firestore client in `seed()`
Add after `fhir_base = ...` line:
```python
firebase_project = os.environ.get("FIREBASE_PROJECT_ID")
db = _firestore.AsyncClient(project=firebase_project)
```
Call `await db.close()` at the end of `seed()` (in a `try/finally`).

### Replace condition POST loop
Replace the `for icd10 in p["conditions"]:` block with:
```python
if p["conditions"]:
    condition_docs = [_condition_resource(patient_id, icd10, p["dob"]) for icd10 in p["conditions"]]
    await db.collection("fhir_data").document(patient_id).set(
        {"conditions": condition_docs}, merge=True
    )
```

## Key reuse

- `_condition_resource()` — already in `seed_patient.py`, produces the exact structure expected by `fhir_bundle.get("conditions")` in the tools
- `_firestore.AsyncClient(project=...)` — same pattern as `auth.py:29-31` (`_make_db()`)
- `fhir_data/{patient_id}` collection — already read by `firestore_fhir.get_fhir_bundle()` (`agent.py:253`)

## Verification

1. Run: `ENV=dev .venv/bin/python3 seed_patient.py`
   - Expected: all 8 patients print `{alias} ({name}): patient_id=...` with no ERROR lines, exit 0
2. In Firebase console, confirm `fhir_data/{patient_id}` doc exists with `conditions` array for synth-001 (should have S09.90XA and G43.909)
3. Start the backend, open a chat as synth-001 — symptom timeline tool should see the two conditions
