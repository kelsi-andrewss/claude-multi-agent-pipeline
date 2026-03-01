# Plan: Fix blocking verify_id_token + add async auth tests

## Context

`auth.verify_id_token()` is a synchronous Firebase Admin SDK call that makes an HTTP
request to fetch Google's public keys on first run. Calling it directly inside an
`async def` FastAPI dependency blocks the entire uvicorn event loop, causing the POST
`/chat` request to hang indefinitely after the OPTIONS preflight returns 200.

Fix: wrap the call in `asyncio.to_thread()` so it runs in a thread pool without
blocking the event loop.

The user also wants tests covering this and similar blocking-call patterns in auth.py.

---

## Files to change

- **Write target**: `advocate/auth.py`
- **Write target**: `advocate/tests/test_eval_auth.py`

---

## Implementation

### 1. `advocate/auth.py` — wrap blocking call

Add `import asyncio` (already absent from this file).

Change in `verify_firebase_token`:

```python
# before
decoded = auth.verify_id_token(creds.credentials)

# after
decoded = await asyncio.to_thread(auth.verify_id_token, creds.credentials)
```

No other changes needed. `_make_db()` returns an `AsyncClient` (already non-blocking).
`_init_firebase()` is a fast no-op after first call (guard on `firebase_admin._apps`),
so it doesn't need threading.

### 2. `advocate/tests/test_eval_auth.py` — add new tests

Append the following test cases to the existing file (do not touch existing tests):

**a. `test_verify_token_does_not_block_event_loop`**
- Patch `auth.verify_id_token` with a slow synchronous function (uses `time.sleep(0)`)
- Confirm the call succeeds via `asyncio.to_thread` by verifying it still returns the uid
- Rationale: documents the contract that the call is thread-dispatched

**b. `test_verify_token_is_awaitable`**
- Call `verify_firebase_token` and assert the returned coroutine completes without
  blocking (use `asyncio.wait_for` with a short timeout to detect a hang)

**c. `test_verify_token_thread_dispatch`**
- Patch `asyncio.to_thread` directly and assert it is called with
  `auth.verify_id_token` and the token string — confirms wrapping is in place

**d. `test_get_patient_id_no_block_on_token_verify`**
- End-to-end: patch `_init_firebase`, `auth.verify_id_token` (via `to_thread`),
  and `_make_db` — run `get_patient_id` through `verify_firebase_token` and confirm
  the full chain resolves

Follow existing patterns in `test_eval_auth.py`:
- Use `_run()` helper wrapping `asyncio.get_event_loop().run_until_complete()`
- Mock via `unittest.mock.patch` and `AsyncMock`
- Patch `auth._init_firebase` to skip Firebase init

---

## Verification

```bash
cd /Users/kelsiandrews/gauntlet/advocate
python -m pytest tests/test_eval_auth.py -x --tb=short
```

All existing 11 tests + 4 new tests should pass. No imports should fail.
