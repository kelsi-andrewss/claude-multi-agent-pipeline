# Plan: Seed all FHIR data to Firestore for all patients

## Context

`seed_patient.py` currently only writes conditions to Firestore — and only for patients that have conditions in the PATIENTS array. Patients without conditions (synth-004, synth-005, synth-007) get zero Firestore writes.

The agent startup reads `fhir_data/{patient_id}` from Firestore to populate `session_state.fhir_raw`, which is the in-memory source-of-truth for all tool calls during a session. This means patients without a complete Firestore record will have incomplete or missing data in the agent.

The fix: after posting each patient to the FHIR API, fetch all their FHIR resources and write them to `fhir_data/{patient_id}` in Firestore — not just conditions, and not just for patients with ICD codes.

## What to change

**File:** `advocate/seed_patient.py`

### 1. After posting each patient and verifying they exist, fetch all FHIR resources:

Using the existing FHIR token and `httpx.AsyncClient`, fire parallel requests for:
- `GET /Patient/{patient_id}` (demographics — already done as verify step, reuse the response)
- `GET /Patient/{patient_id}/Condition`
- `GET /Patient/{patient_id}/Observation`
- `GET /Patient/{patient_id}/Encounter`
- `GET /Patient/{patient_id}/MedicationRequest`
- `GET /Patient/{patient_id}/Coverage`
- `GET /Patient/{patient_id}/AllergyIntolerance`

Use `asyncio.gather()` for parallel fetches.

Each response is a FHIR Bundle. Extract `entry[].resource` from each bundle (empty list if 404 or no entries).

### 2. Write all resources to Firestore

Replace the current conditional condition-only write with a single unconditional `set()` call:

```python
await db.collection("fhir_data").document(patient_id).set({
    "patient": patient_resource,       # dict from GET /Patient/{id}
    "conditions": [...],               # list of resource dicts
    "observations": [...],
    "encounters": [...],
    "medications": [...],
    "coverage": [...],
    "allergies": [...],
}, merge=True)
```

This runs for every patient, even those with no conditions.

### 3. Remove the old conditional condition-only block (lines 270-274)

The new unconditional write replaces it entirely.

## Helper needed

Add a small helper in `seed_patient.py`:

```python
async def _fetch_bundle(client, url, headers) -> list[dict]:
    resp = await client.get(url, headers=headers)
    if resp.status_code == 404:
        return []
    resp.raise_for_status()
    return [e["resource"] for e in resp.json().get("entry", [])]
```

## Critical files

- `advocate/seed_patient.py` — only file changed

## Verification

1. Run `ENV=dev .venv/bin/python3 seed_patient.py`
2. Check Firestore console: every patient's `fhir_data/{patient_id}` doc should exist with keys `patient`, `conditions`, `observations`, `encounters`, `medications`, `coverage`, `allergies`
3. Patients with no conditions (Priya, Marcus, Ava) should have docs with empty lists for those keys, not missing docs
