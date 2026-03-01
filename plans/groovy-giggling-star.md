# Fix Remaining Failing/Hanging Tests (test_core)

## Context

The previous round fixed 452 tests across `test_verification/`, `test_agent/`, `test_api/`, and `test_tools/`. However, `tests/test_core/` was skipped. It contains 16 tests across two files that hang when run together, blocking `pytest tests/` from completing.

**Root cause:** `test_fhir_client.py` uses `asyncio.run()` inside sync test functions combined with an `autouse` `restore_event_loop` fixture that creates a new event loop after each test. The first test passes, but the fixture's `asyncio.set_event_loop(asyncio.new_event_loop())` corrupts the loop state for subsequent `asyncio.run()` calls, causing an indefinite hang.

**Evidence:**
- Each of the 5 `test_fhir_client.py` tests passes individually
- All 11 `test_deployment_hardening.py` tests pass when run alone (11/11)
- Running both files together (16 tests) hangs after the deployment tests complete and `test_fhir_client.py` begins its second test
- Running `test_fhir_client.py` alone (5 tests) also hangs on the 2nd test

## Changes

### 1. Convert `test_fhir_client.py` to use `@pytest.mark.asyncio`
**File**: `tests/test_core/test_fhir_client.py`

- Remove the `restore_event_loop` fixture entirely (lines 11-15)
- Convert all 5 test functions from sync `def` + inner `async def run_test()` + `asyncio.run()` → direct `async def` with `@pytest.mark.asyncio`
- This matches the pattern already used in `test_deployment_hardening.py`'s `TestFHIRTokenCache` class (lines 209-260)

Before:
```python
def test_post_returns_json_on_201(fhir_service):
    async def run_test():
        # ... async test body ...
    asyncio.run(run_test())
```

After:
```python
@pytest.mark.asyncio
async def test_post_returns_json_on_201(fhir_service):
    # ... async test body (flattened, no wrapper) ...
```

Apply this to all 5 tests:
- `test_post_returns_json_on_201`
- `test_post_raises_auth_error_on_401`
- `test_put_returns_json_on_200`
- `test_put_raises_not_found_error_on_404`
- `test_token_scope_contains_write_scopes`

Remove the `import asyncio` line since it's no longer needed.

## Files Modified

| File | Action |
|---|---|
| `tests/test_core/test_fhir_client.py` | Remove `restore_event_loop` fixture, convert 5 tests to `async def` + `@pytest.mark.asyncio` |

## Verification

```bash
# 1. test_core passes alone
.venv/bin/python -m pytest tests/test_core/ --tb=short -q

# 2. Full suite passes (all directories)
.venv/bin/python -m pytest tests/ --ignore=tests/eval --tb=short -q
```

All 468 tests (452 existing + 16 test_core) should pass with no hangs.
