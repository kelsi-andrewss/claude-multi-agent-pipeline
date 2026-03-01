# Fix seed_patient.py — use OpenEMR REST API for Condition seeding

## Context

The seed script currently POSTs Conditions to the FHIR endpoint (`/apis/default/fhir/Condition`).
`seven.openemr.io` does not expose `user/Condition.write` or `user/Condition.cud` in its supported
scopes, so the FHIR Condition endpoint returns 404 for every create attempt.

The fix is to stop using the FHIR endpoint for Conditions and instead use the OpenEMR proprietary
REST API: `POST /apis/default/api/patient/{puuid}/medical_problem`, which requires the scope
`user/medical_problem.cruds` — a scope that IS supported by this server.

Patient seeding continues to use FHIR (`/apis/default/fhir/Patient`) since that works correctly.

## Critical file

- `advocate/seed_patient.py`

## Changes

### 1. Add `user/medical_problem.cruds` to OAuth scope

In `_get_token`, update the `scope` string:

```python
"scope": "openid api:fhir user/Patient.write user/Patient.read user/medical_problem.cruds",
```

Remove the non-existent `user/Condition.write`, `user/Observation.write`, `user/MedicationRequest.write`
scopes — they cause no harm if included but requesting unsupported scopes can cause auth servers to
reject the entire request on strict implementations. Keep only what is needed.

### 2. Replace `_condition_resource` + FHIR POST with proprietary REST POST

Remove the `_condition_resource` helper (no longer needed).

In the patient loop, replace:
```python
for icd10 in p["conditions"]:
    cond_resp = await client.post(
        f"{fhir_base}/Condition",
        json=_condition_resource(patient_id, icd10),
        headers=headers,
    )
```

With:
```python
api_base = f"{base_url.rstrip('/')}/apis/default/api"

for icd10 in p["conditions"]:
    cond_resp = await client.post(
        f"{api_base}/patient/{patient_id}/medical_problem",
        json={"title": icd10, "begdate": p["dob"], "diagnosis": f"ICD10:{icd10}"},
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    if cond_resp.status_code not in (200, 201):
        raise RuntimeError(
            f"POST /medical_problem ({icd10}) returned {cond_resp.status_code}: {cond_resp.text}"
        )
```

Note: `Content-Type` for the proprietary API is `application/json`, not `application/fhir+json`.
The FHIR `headers` dict uses `application/fhir+json` so we must pass a separate headers dict here.

### 3. Revert the soft-warn back to raise RuntimeError

The previous plan soft-warned on Condition failures. Now that we're using the correct endpoint,
failures should be hard errors again so we know immediately if something is wrong.

## Verification

Run `ENV=dev .venv/bin/python3 seed_patient.py`:
- Browser opens once for OAuth
- All 8 patients print with UUIDs
- No WARN or ERROR lines for conditions
- Script exits 0
- `.env.dev` updated with `DEMO_PATIENT_ID_*` values
