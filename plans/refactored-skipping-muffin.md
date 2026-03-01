# Story-186: Replace global `_sessions` dict with Firestore-backed session store

## Context

`main.py` holds all live sessions in a module-level dict:
```python
_sessions: dict[str, tuple[AdvocateAgent, SessionState, asyncio.Queue]] = {}
```
This dict is never pruned and is local to a single Cloud Run instance. On multi-instance deployments a user may hit a cold instance that has no record of their session, losing conversation history. Over time the dict also exhausts memory.

Firestore already partially persists `SessionState` (7 of 24 fields) via `save_session_state` / `load_session_state` in `firestore_fhir.py`, and `_get_or_create_session` already attempts a Firestore restore on cache miss. The gap is that **conversation history (`_history`) is never persisted**, so a cold instance recreates the agent with an empty context window.

The fix: persist the rolling conversation history alongside the existing `SessionState` fields, add a `ttl_expires_at` field for Firestore-native TTL, and add a lightweight L1 eviction loop so the in-process dict doesn't grow unboundedly.

---

## Files to Modify

| File | Change |
|---|---|
| `advocate/models.py` | Add `history` and `last_accessed_at` fields to `SessionState` |
| `advocate/firestore_fhir.py` | Persist `history` + `ttl_expires_at` in save; restore `history` in load |
| `advocate/agent.py` | Seed `_history` from `session_state.history` on init; sync back after each turn |
| `advocate/main.py` | Update `last_accessed_at` on each access; add startup L1 eviction task |

---

## Implementation Steps

### Step 1 — `models.py`: Add history + TTL tracking fields

Add two new fields to `SessionState`:

```python
history: list[dict[str, str]] = []       # [{"role": "human"|"ai", "content": "..."}]
last_accessed_at: float = 0.0            # unix timestamp, for L1 eviction
```

`history` must be excluded from the session-state JSON injected into the prompt in `_build_messages`. Add `model_dump(exclude={"history", "fhir_raw"})` there (see Step 3).

### Step 2 — `firestore_fhir.py`: Persist history + TTL

**`save_session_state`** — add to the `data` dict:
```python
"history": [{"role": m["role"], "content": m["content"]} for m in session_state.history],
"ttl_expires_at": datetime.utcnow() + timedelta(hours=24),
```
Keep all existing fields. Keep `merge=True`.

**`load_session_state`** — after building `data` from `doc.to_dict()`:
```python
data.pop("ttl_expires_at", None)   # server field, not in model
# history is a plain list[dict], no reconstruction needed
```
`SessionState.model_validate(data)` will populate `history` automatically.

### Step 3 — `agent.py`: Seed history on init; sync after each turn

**`__init__`** — after `self._history = InMemoryChatMessageHistory()`, add:
```python
for msg in session_state.history:
    if msg["role"] == "human":
        self._history.add_user_message(msg["content"])
    else:
        self._history.add_ai_message(msg["content"])
```

**`_build_messages`** — change `self.session_state.model_dump_json()` to:
```python
state_json = self.session_state.model_dump_json(exclude={"history", "fhir_raw"})
```
`fhir_raw` was already large; excluding it keeps prompt size stable. (If `fhir_raw` is currently included, confirm and exclude it too.)

**After every turn** in both `chat` and `chat_stream` — add a helper and call it before returning:
```python
def _sync_history(self) -> None:
    self.session_state.history = [
        {"role": "human" if isinstance(m, HumanMessage) else "ai", "content": m.content}
        for m in self._history.messages
    ]
```
Call `self._sync_history()` at the end of `chat` and after the final `yield` in `chat_stream`.

### Step 4 — `main.py`: L1 eviction background task

**In `_get_or_create_session`** — after caching the session triple, update the timestamp:
```python
session_state.last_accessed_at = time.time()
```
Do the same at the top of each chat handler when the session is retrieved from `_sessions`.

**Add a startup eviction task** using FastAPI's lifespan or `@app.on_event("startup")`:
```python
import asyncio, time

async def _evict_stale_sessions() -> None:
    while True:
        await asyncio.sleep(3600)          # run hourly
        cutoff = time.time() - 3600       # evict sessions idle > 1h
        stale = [k for k, (_, ss, _) in _sessions.items()
                 if ss.last_accessed_at < cutoff]
        for k in stale:
            _sessions.pop(k, None)

@app.on_event("startup")
async def startup() -> None:
    asyncio.create_task(_evict_stale_sessions())
```

### Step 5 — Firestore TTL policy (one-time GCP config)

In the GCP Console → Firestore → TTL policies, add a policy on collection group `sessions` pointing to the `ttl_expires_at` field. This is a one-time manual step; document it in `.env.example` or `README` as a deployment prerequisite.

---

## What Does NOT Change

- `asyncio.Queue` stays in-memory. SSE streaming is instance-local; this is an existing known limitation and out of scope.
- Demo patients continue to skip all Firestore persistence (`is_demo_patient()` guard in `save_session_state` is unchanged).
- The Firestore client factory (`_make_db()` in `auth.py`) is unchanged — clients are short-lived per operation, which is the existing pattern.
- Story-187 (interim TTL eviction) can be closed as superseded once this lands.

---

## Verification

1. **Unit test (new):** In `tests/test_agent.py`, instantiate `AdvocateAgent` with a `SessionState` pre-populated with `history`, assert `_history.messages` matches on init. Call `_sync_history()` and assert `session_state.history` reflects the messages.
2. **Unit test (new):** In `tests/test_tools/test_firestore_fhir.py`, mock Firestore and assert `save_session_state` writes a `history` list and a `ttl_expires_at` datetime. Assert `load_session_state` reconstructs the `history` field correctly.
3. **Integration smoke test:** Start the API, send 3 chat turns, manually pop `_sessions[key]`, send a 4th turn, assert the agent references earlier turns in its response.
4. **Prompt size regression:** Log token count before/after excluding `history`+`fhir_raw` from `_build_messages` injection to confirm no prompt bloat.
5. **Run existing tests:** `cd advocate && python -m pytest tests/ -x --tb=short` — no regressions.
