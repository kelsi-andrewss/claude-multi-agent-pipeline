# Plan: Demo Data — Seed Patients, Map FHIR IDs, Wire Credentials

## Context

The demo flow (Serena, Maya, Ruth) fires tool calls that hit the backend, but FHIR queries
fail because:

1. **Merge conflict in auth.py** (lines 139–143): `<<<<<<< HEAD` markers crash Python on import.
2. **patient_id mismatch**: `auth.py` assigns the string `"serena"` / `"maya"` / `"ruth"` to
   Firebase users, and these strings flow directly into FHIR URLs (e.g. `/Patient/serena/Encounter`).
   OpenEMR needs the numeric patient ID that `seed_patient.py` generates — but that ID is only
   printed to stdout, never stored.
3. **Empty FHIR credentials**: Every tool (`symptom_timeline.py`, `insurance_coverage.py`) and
   `agent.py` construct `FHIRService(FHIR_BASE_URL, "", "")` with blank client_id/secret.
4. **seed_patient.py doesn't persist IDs**: After seeding, the real FHIR IDs are unknown to the
   backend.

The fix has two parts: **backend** (resolve conflict, store real FHIR IDs, map persona → ID,
pass real credentials) and **seed script** (write IDs to `.env` after seeding).

---

## Changes

### Part A: `seed_patient.py` — write FHIR IDs to `.env` after seeding

After each patient seeds successfully, append/update lines in `.env`:
```
DEMO_PATIENT_ID_SERENA=<numeric_id>
DEMO_PATIENT_ID_MAYA=<numeric_id>
DEMO_PATIENT_ID_RUTH=<numeric_id>
```

Use a simple file-patch approach: read `.env`, replace or append the `DEMO_PATIENT_ID_*` lines.

Add a helper `_update_env_file(path, key, value)` that reads the file, replaces the line if
present, or appends it if not.

Also update `.env.example` to document these three keys.

### Part B: `auth.py` — resolve merge conflict + map persona → FHIR ID

**Fix merge conflict** (lines 127–143): remove conflict markers, keep `await db.close()` (the
correct async version).

**Add FHIR ID lookup**: add a `_demo_patient_fhir_id(alias: str) -> str | None` helper that
reads `DEMO_PATIENT_ID_SERENA` etc. from env and returns the numeric ID if set.

**Update `get_patient_id`**: after fetching `patient_id` from Firestore (e.g. `"serena"`),
check `_demo_patient_fhir_id(patient_id)`. If set, return that numeric ID instead. Otherwise
return the alias as-is (graceful degradation — tools will 404 but won't crash).

```python
_FHIR_ID_ENV = {
    "serena": "DEMO_PATIENT_ID_SERENA",
    "maya":   "DEMO_PATIENT_ID_MAYA",
    "ruth":   "DEMO_PATIENT_ID_RUTH",
}

def _demo_fhir_id(alias: str) -> str | None:
    env_key = _FHIR_ID_ENV.get(alias)
    return os.environ.get(env_key) if env_key else None
```

In `get_patient_id`, replace `return patient_id` with:
```python
fhir_id = _demo_fhir_id(patient_id)
return fhir_id if fhir_id else patient_id
```

### Part C: `fhir_client.py` / tools — pass real credentials from env

`FHIRService` already reads `base_url`, `client_id`, `client_secret` as constructor args. The
problem is the call sites pass `""` for credentials.

Add a module-level factory in `fhir_client.py`:
```python
import os

def make_fhir_service() -> FHIRService:
    return FHIRService(
        base_url=os.environ.get("FHIR_BASE_URL", "https://demo.openemr.io/apis/default/fhir"),
        client_id=os.environ.get("OPENEMR_CLIENT_ID", ""),
        client_secret=os.environ.get("OPENEMR_CLIENT_SECRET", ""),
    )
```

Replace all call sites that use `FHIRService(FHIR_BASE_URL, "", "")` with `make_fhir_service()`:
- `tools/symptom_timeline.py` line ~121
- `tools/insurance_coverage.py` (wherever FHIRService is instantiated)
- `agent.py` line ~137

Remove the now-redundant `FHIR_BASE_URL` module-level constants from `symptom_timeline.py` and
`insurance_coverage.py` (they'll be read from env via `make_fhir_service`).

Also remove the duplicate `_make_db` / `assign_patient_id` function definitions in `auth.py`
(there are two copies — a side-effect of the merge conflict). Keep only the second (correct)
definition.

### Part D: `.env.example` — document new keys

Add after existing FHIR block:
```
# Demo patient FHIR IDs (populated automatically by seed_patient.py)
DEMO_PATIENT_ID_SERENA=
DEMO_PATIENT_ID_MAYA=
DEMO_PATIENT_ID_RUTH=
```

---

## Files changed

| File | Change |
|---|---|
| `advocate/seed_patient.py` | Write DEMO_PATIENT_ID_* to `.env` after seeding |
| `advocate/auth.py` | Resolve merge conflict; add `_demo_fhir_id()`; map alias → FHIR ID in `get_patient_id` |
| `advocate/fhir_client.py` | Add `make_fhir_service()` factory |
| `advocate/tools/symptom_timeline.py` | Use `make_fhir_service()` |
| `advocate/tools/insurance_coverage.py` | Use `make_fhir_service()` |
| `advocate/agent.py` | Use `make_fhir_service()` |
| `advocate/.env.example` | Document DEMO_PATIENT_ID_* keys |

---

## Verification

1. Run `python seed_patient.py` (with valid OPENEMR creds in `.env`) — check that
   `DEMO_PATIENT_ID_SERENA`, `_MAYA`, `_RUTH` appear in `.env`.
2. Restart backend: `uvicorn main:app --reload`.
3. Run Ruth demo in Flutter — expect `symptom_timeline`, `specialist_navigator`,
   `appointment_brief_generator`, `insurance_coverage_check` to appear in the Tool Calls panel
   with actual FHIR data (not 404 errors).
4. Run `python -m pytest tests/ -x --tb=short` — verify no regressions.
5. Confirm `auth.py` imports cleanly: `python -c "import auth"` from the advocate directory.
