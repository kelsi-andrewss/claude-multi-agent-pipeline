# Plan: Redirect symptom_writer FHIR POST to Firestore

## Context

`tools/symptom_writer.py` POSTs an FHIR Observation resource to the OpenEMR FHIR endpoint. That endpoint returns 404 because the OAuth scope only requests `.read` permissions and `fhir_client.py` is off-limits. The fix: write the Observation document to Firestore instead, using the same pattern as `seed_patient.py` commit b168a5e (Conditions redirected to `fhir_data/{patient_id}`).

---

## Files to modify

| File | Role |
|------|------|
| `tools/symptom_writer.py` | Replace FHIR POST with Firestore write |
| `agent.py` | Remove `fhir_service` arg from `make_symptom_writer_tool` call |
| `tests/test_tools/test_symptom_writer.py` | Rewrite all tests: FHIR mocks → Firestore mocks |

---

## 1. `tools/symptom_writer.py`

- Remove `fhir_service: FHIRService` parameter from `run_symptom_writer()`.
- Import `_make_db` from `auth` (already used elsewhere).
- Build the same Observation payload (no change to structure).
- Write via Firestore `add()` to `fhir_data/{patient_id}/observations` subcollection.
  - `add()` auto-generates a document ID → use as `observation_id`.
- Open and close `db` within the function (same pattern as `AdvocateAgent.create()`).

```python
from auth import _make_db

async def run_symptom_writer(symptom, onset_date, severity, patient_id):
    payload = { ...same Observation dict... }
    db = _make_db()
    try:
        _, doc_ref = await db.collection("fhir_data").document(patient_id).collection("observations").add(payload)
        observation_id = doc_ref.id
    finally:
        db.close()
    return SymptomWriterOutput(
        observation_id=observation_id,
        symptom=symptom,
        recorded_at=onset_date,
        status="created",
        message=f"Symptom '{symptom}' recorded successfully.",
    ).model_dump()
```

---

## 2. `agent.py`

- Line ~238: change `make_symptom_writer_tool(session_state, make_fhir_service())` → `make_symptom_writer_tool(session_state)`.
- Line ~437: drop `fhir_service: FHIRService` parameter from `make_symptom_writer_tool` signature.
- Inner `_run` closure: remove `fhir_service=fhir_service` from the `run_symptom_writer` call.

---

## 3. `tests/test_tools/test_symptom_writer.py`

Full rewrite using the Firestore mock pattern established in `test_symptom_notes.py`.

**Fixtures:**
```python
@pytest.fixture
def mock_db():
    db = MagicMock()
    db.close = MagicMock()
    # Simulate add() returning (update_time, doc_ref)
    mock_doc_ref = MagicMock()
    mock_doc_ref.id = "obs-generated-001"
    db.collection.return_value.document.return_value.collection.return_value.add = AsyncMock(
        return_value=(MagicMock(), mock_doc_ref)
    )
    return db
```

**Tests (5 tests, replace all existing):**

1. **`test_run_symptom_writer_returns_observation_id`**
   - Patch `tools.symptom_writer._make_db` → `mock_db`
   - Call `run_symptom_writer(symptom="fatigue", onset_date="2026-01-01", severity="moderate", patient_id="p1")`
   - Assert `result["observation_id"] == "obs-generated-001"`
   - Assert `result["status"] == "created"`

2. **`test_run_symptom_writer_writes_to_correct_collection`**
   - Patch `_make_db` → `mock_db`
   - Call the function
   - Assert `mock_db.collection.called_with("fhir_data")`
   - Assert `mock_db.collection().document.called_with("p1")`
   - Assert `mock_db.collection().document().collection.called_with("observations")`
   - Assert `add` was called once

3. **`test_run_symptom_writer_payload_structure`**
   - Patch `_make_db` → `mock_db`
   - Capture the `add()` call args: `call_args = mock_db.collection.return_value.document.return_value.collection.return_value.add.call_args`
   - Assert payload has `resourceType == "Observation"`, `subject.reference == "Patient/p1"`, `code.text == "fatigue"`, `effectiveDateTime == "2026-01-01"`, `valueString` contains "moderate"

4. **`test_run_symptom_writer_closes_db`**
   - Patch `_make_db` → `mock_db`
   - Call the function
   - Assert `mock_db.close.assert_called_once()`

5. **`test_make_symptom_writer_tool_invokes_run`**
   - Import `make_symptom_writer_tool` from `agent`
   - Create a `SessionState` with `patient_id="p2"`
   - Patch `tools.symptom_writer._make_db` → `mock_db`
   - Call the tool's coroutine directly: `await tool.coroutine(symptom="pain", onset_date="2026-01-02", severity="mild")`
   - Assert `result["observation_id"] == "obs-generated-001"`

---

## Firestore document structure

```
fhir_data/{patient_id}/observations/{auto-id}
{
  "resourceType": "Observation",
  "status": "preliminary",
  "category": [...],
  "code": {"text": "<symptom>"},
  "subject": {"reference": "Patient/<patient_id>"},
  "effectiveDateTime": "<onset_date>",
  "valueString": "Patient-reported: <symptom> (severity: <severity>)",
  "note": [{"text": "Recorded by Advocate AI from patient self-report"}]
}
```

---

## Verification

1. Start server: `cd advocate && uvicorn main:app --reload`
2. Trigger a chat that invokes `symptom_writer` — confirm no 404 in server logs.
3. Firebase console: check `fhir_data/{patient_id}/observations` for new document.
4. Run tests: `cd advocate && python -m pytest tests/test_tools/test_symptom_writer.py -x --tb=short`
