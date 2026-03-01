# Plan: Address Audit Findings

## Context

A Gemini CLI audit scored the project 8.2/10 and identified 5 areas of technical debt: duplicate tool files, broken tests, stale eval dataset, bare exception blocks, and incomplete seeding. This plan addresses all findings in priority order. Investigation revealed the dataset issue is larger than initially reported — 4 tool name mappings are stale (not just 1).

---

## Finding A — Deduplicate Tools & Remove Dead Code (Critical)

**Files modified:** `agent.py`, `models.py`, `dataset.json`, `FIRESTORE_SCHEMA.md`, `test_human_first_session.py`
**Files deleted:** `tools/symptom_writer.py`

1. **Delete** `tools/symptom_writer.py` — identical to `fhir_symptom_record.py` except function name
2. **`agent.py`** — Remove dead import `from tools.symptom_writer import run_symptom_writer` (line 47) and unused `SymptomWriterInput` from the models import block (line 31)
3. **`models.py`** — Remove `SymptomWriterInput` class (lines 230-233). Keep `FhirSymptomRecordInput` and `SymptomWriterOutput`
4. **`tests/eval/dataset.json`** — Fix all 4 stale tool name mappings (~22 edits):
   - `symptom_writer` → `fhir_symptom_record` (4 occurrences)
   - `save_symptom_note` → `patient_voice_note` (4 occurrences)
   - `get_symptom_notes` → `get_patient_voice_notes` (4 occurrences)
   - `read_medical_history` → `symptom_timeline` (10 occurrences)
5. **`FIRESTORE_SCHEMA.md`** line 70 — Change `symptom_writer.py` reference to `fhir_symptom_record.py`
6. **`tests/test_agent/test_human_first_session.py`** — Update comment (line 210) and rename test functions (lines 214, 226) from `symptom_writer` to `fhir_symptom_record`

---

## Finding B — Fix Broken Test Suite (High)

**Files modified:** `tests/test_tools/test_symptom_writer.py` → renamed to `test_fhir_symptom_record.py`

1. **Rename** `test_symptom_writer.py` → `test_fhir_symptom_record.py`
2. **Fix mock fixture** — Current mocks `.collection().add()` but implementation uses `.document().update()` with `ArrayUnion`. New fixture:
   ```python
   mock_doc_ref = MagicMock()
   mock_doc_ref.update = AsyncMock(return_value=None)
   db.collection.return_value.document.return_value = mock_doc_ref
   ```
3. **Redirect all imports** from `tools.symptom_writer` → `tools.fhir_symptom_record`, call `run_fhir_symptom_record`
4. **Fix observation_id assertions** — No longer from mock; assert non-empty 32-char hex (uuid4)
5. **Fix payload assertions** — Inspect `update()` call args → extract payload from `ArrayUnion`
6. **Use `@pytest.mark.asyncio`** instead of deprecated `asyncio.get_event_loop().run_until_complete()`

---

## Finding C — Add Tool Selection Evaluator (Medium)

**Files modified:** `tests/eval/run_evals.py`

1. **Update `_run_agent()`** — Capture tool names from `agent._history.messages` (filter for `ToolMessage` instances)
2. **Update `_target_fn()`** — Include `tools_called` list in returned dict
3. **Add `_evaluator_tool_selection()`** — Compare `expected_tools` from dataset against actual `tools_called` using subset semantics (agent may call extra tools; all expected must be present)
4. **Register** the new evaluator in the `evaluate()` call

---

## Finding D — Harden Exception Handling + Extract Model Config (Medium)

**Files modified:** `auth.py`, `prompts/somatic.py`, `prompts/validation.py`, `tools/dismissal_detector.py`, `agent.py`, `tests/eval/run_evals.py`, `.env.example`

1. **`auth.py` line 54** — Replace `except Exception:` with specific Firebase auth exceptions (`InvalidIdTokenError`, `ExpiredIdTokenError`, `RevokedIdTokenError`, `CertificateFetchError`), add `logging.warning`
2. **`prompts/somatic.py` line 44** — Replace redundant `except Exception:` with `except pydantic.ValidationError:` + `except Exception as exc:` with logging
3. **`prompts/validation.py` line 52** — Same pattern as somatic.py
4. **`tools/dismissal_detector.py` line 118** — Keep broad catch but add `logging.warning` before fallback
5. **`agent.py` line 145** — Split into `json.JSONDecodeError` (silent) + `except Exception as exc:` (logged)
6. **`agent.py` line 575** — Add `logging.warning` before fallback
7. **`tests/eval/run_evals.py` line 71** — Narrow to `LangSmithNotFoundError` or string-match guard
8. **`agent.py` line 443** — Extract `"gemini-2.5-flash"` to `os.environ.get("ADVOCATE_LLM_MODEL", "gemini-2.5-flash")`; add to `.env.example`

---

## Finding E — Seeding Gap (Low — Document Only)

**Files modified:** `seed_patient.py`

1. Add a comment block documenting that Observations/Encounters/Medications/Coverage/AllergyIntolerance are only fetched, not created. Note that `run_evals.py` provides its own hardcoded mock data. Defer implementation.

---

## Verification

```bash
cd /Users/kelsiandrews/gauntlet/advocate

# 1. Confirm no remaining stale references (excluding .claude/ worktrees)
grep -r "symptom_writer" --include="*.py" --include="*.json" . | grep -v ".claude/"
# Expected: only test_listening_gate_config.py asserting "symptom_writer" not in tool_names

# 2. Confirm imports resolve
python -c "from tools.fhir_symptom_record import run_fhir_symptom_record; print('OK')"
python -c "from models import FhirSymptomRecordInput, SymptomWriterOutput; print('OK')"

# 3. Lint
ruff check .

# 4. Run full test suite
python -m pytest tests/ -x --tb=short

# 5. Run eval dry-run (if LangSmith creds available)
python tests/eval/run_evals.py --dry-run
```
