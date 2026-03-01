# Plan: Fix 50 Failing Tests

## Context

Recent refactors (listening gate overhaul in `e78d7e8`, auth simplification, agent restructuring) left 50 tests failing. The failures fall into 4 distinct root causes. All are test-code mismatches with the updated source — not source bugs.

---

## Root Cause 1: Event loop broken by pytest-asyncio (≈23 failures)

**Files:** `test_navigator.py`, `test_dismissal_detector.py`, `test_provider_finder.py`, `test_symptom_notes.py`, `test_injection_guard.py` (TestChatInjectionGuard + TestRegenPathInjectionGuard + TestQuestionnaireModeInjectionGuard), `test_deployment_hardening.py` (2 tests)

**Cause:** These tests use `asyncio.get_event_loop().run_until_complete()`. When the full suite runs, `test_agent/test_listening_gate_hooks.py` (which uses `@pytest.mark.asyncio`) runs first alphabetically. pytest-asyncio v1.3 closes the event loop after those tests complete. All subsequent `get_event_loop()` calls raise `RuntimeError: There is no current event loop`.

**Fix:** Add a `pytest.ini` at `advocate/` setting `asyncio_mode = auto`. This makes pytest-asyncio manage a single persistent event loop for the whole session, eliminating the "closed loop" problem. Also add `pytest-asyncio` to `requirements.txt`.

---

## Root Cause 2: `auth.py` refactored away from `.update()` + rotation (7 failures)

**Files:** `tests/test_eval_auth.py` — 7 failing tests

**Cause:** `auth.py` was simplified. It no longer:
- Calls `patient_ref.update()` — it only calls `.set(..., merge=True)` on both branches
- Uses Firestore transactions or a rotation counter (`rotation_state/counter`)

The failing tests still mock `.update()` and assert `mock_user_ref.update.assert_called_once()`. The passing tests happen to not assert on `.update()`.

Also: `test_verify_token_invalid_token` patches `auth.auth.verify_id_token` with a generic `Exception`, but `auth.py:63` only catches `(InvalidIdTokenError, ExpiredIdTokenError, RevokedIdTokenError, CertificateFetchError)`. Generic `Exception` propagates uncaught.

**Fix:** Update `tests/test_eval_auth.py`:
1. Replace all `mock_user_ref.update = AsyncMock()` with `mock_user_ref.set = AsyncMock()`
2. Replace all `mock_user_ref.update.assert_called_once()` with `mock_user_ref.set.assert_called_once()`
3. Remove all mock transaction/counter setup (no longer exists in auth.py)
4. Fix `test_verify_token_invalid_token`: patch with `InvalidIdTokenError` instead of generic `Exception`

---

## Root Cause 3: `@pytest.mark.asyncio` tests need asyncio_mode config (19 failures)

**Files:** `test_listening_gate_hooks.py` (11), `test_listening_gate_logic.py` (8), `test_validation_classifier.py` (10)

**Cause:** These use `@pytest.mark.asyncio async def test_...`. Without explicit `asyncio_mode` config, pytest-asyncio v1.3 does not auto-run them — they're treated as unawaited coroutines and fail with "async def functions are not natively supported."

**Fix:** Same `pytest.ini` with `asyncio_mode = auto` fixes this group too (covered by Root Cause 1 fix).

---

## Root Cause 4: `test_fhir_symptom_record.py` and `test_core/test_fhir_client.py` (10 failures)

**Files:** `tests/test_tools/test_fhir_symptom_record.py` (5), `tests/test_core/test_fhir_client.py` (5)

**Cause:** Both use `@pytest.mark.asyncio`. Same as Root Cause 3 — fixed by `pytest.ini`.

---

## Implementation Steps

### Step 1: Create `advocate/pytest.ini`
```ini
[pytest]
asyncio_mode = auto
```

### Step 2: Add `pytest-asyncio` to `requirements.txt`
Add line: `pytest-asyncio>=1.3.0`

### Step 3: Fix `tests/test_eval_auth.py`

**test_verify_token_invalid_token** (line 31):
- Change: `side_effect=Exception("invalid")`
- To: `side_effect=InvalidIdTokenError("invalid")` (import from `firebase_admin.auth`)

**test_get_patient_id_existing_user_returns_fhir_id** (line 61):
- Change: `mock_user_ref.update = AsyncMock()`
- To: `mock_user_ref.set = AsyncMock()`

**test_get_patient_id_existing_user_updates_last_active** (lines 83, 92-94):
- Change: `mock_user_ref.update = AsyncMock()`  → `mock_user_ref.set = AsyncMock()`
- Change: `mock_user_ref.update.assert_called_once()` → `mock_user_ref.set.assert_called_once()`
- Change: `mock_user_ref.update.call_args[0][0]` → `mock_user_ref.set.call_args[0][0]`

**test_get_patient_id_new_user_assigns_persona**, **test_get_patient_id_new_user_creates_firestore_doc**, **test_get_patient_id_no_env_var_falls_back_to_uid**, **test_get_patient_id_rotation_wraps_around**:
- Remove all transaction/counter mock setup (mock_counter_ref, mock_transaction, _collection routing by name, etc.)
- Simplify mock to just: `mock_db.collection.return_value.document.return_value = mock_user_ref` with `mock_user_ref.get` and `mock_user_ref.set` as AsyncMocks
- Fix assertions to use `.set` not `.update`

---

## Critical Files

- `advocate/pytest.ini` — CREATE new file
- `advocate/requirements.txt` — add pytest-asyncio line
- `advocate/tests/test_eval_auth.py` — fix 7 tests (mock `.set` not `.update`, fix exception type, remove rotation mocks)

---

## Verification

```bash
/opt/homebrew/bin/python3.11 -m pytest tests/ --tb=short -q
```

Expected: 0 failures (487+ passing). The injection guard, listening gate, validation classifier, navigator, dismissal detector, provider finder, symptom notes, fhir_symptom_record, fhir_client, and deployment hardening tests should all pass in the full suite run.
