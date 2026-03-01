# Plan: Fix Issues 2, 4, 5 — IMPLEMENTED, commit+push requested

## Context

Three issues from the Gemini audit need targeted fixes:
- **Issue 2**: Flutter routing flash on cold-start (auth loading state not guarded)
- **Issue 4**: Agent reliability — FHIR load crash, silent verification failure with no confidence signal
- **Issue 5**: Misleading `_keySessionId` key name in local storage + shared_preferences not cleared on logout

No PHI is actually at risk (tokens stay in-memory), no routing loop exists, and no major refactor is needed. These are surgical, minimal fixes — ~12 lines of net-new code across 7 files.

---

## Issue 2 — Flutter Routing: Guard Auth Loading State

**File:** `flutter/lib/navigation/router.dart`

**Problem:** When `authStateProvider` is still loading (app cold-start), `valueOrNull` returns `null`, so `isAuthenticated = false`, which fires a redirect to `/sign-in` before Firebase resolves — visible as a flash.

**Fix:** Insert 1 line at the top of the redirect callback:

```dart
redirect: (BuildContext context, GoRouterState state) {
  if (authState.isLoading) return null;   // ADD: wait for auth to resolve

  final isAuthenticated = authState.valueOrNull != null;
  // ... rest unchanged
```

`authState` is already `AsyncValue<User?>` from `ref.watch(authStateProvider)` — `.isLoading` is a native property, no imports needed.

---

## Issue 4 — Agent Reliability: Three Surgical Fixes

### Fix 4a — FHIR bundle load failure: degrade gracefully

**File:** `agent.py` (~line 325–333, `AdvocateAgent.create()`)

**Problem:** `get_fhir_bundle()` exception propagates uncaught, crashing session startup.

**Fix:** Add `except` block before `finally` to catch and continue with `fhir_raw = {}`:

```python
db = _make_db()
try:
    bundle = await get_fhir_bundle(session_state.patient_id, db)
except Exception as exc:                                          # ADD
    print(f"[agent] WARNING: FHIR bundle load failed, running in questionnaire mode: {exc}", file=sys.stderr)  # ADD
    bundle = {}                                                   # ADD
finally:
    db.close()
session_state.fhir_raw = bundle
```

### Fix 4b — Set `confidence_tier = "UNKNOWN"` on pipeline exception

**File:** `agent.py` (~line 574–581, verification pipeline catch block)

**Problem:** Pipeline exception catch returns unverified `output` without setting `confidence_tier`, so frontend has no signal that verification was skipped.

**Fix:** Add one line in the except block:

```python
except Exception as exc:
    print(f"[agent] WARNING: verification pipeline failed: {exc}", file=sys.stderr)
    session_state.confidence_tier = "UNKNOWN"   # ADD
    return output
```

Note: The same pattern appears in the `chat_stream()` path (~line 735). Apply the same fix there.

### Fix 4c — Force `confidence_tier = "LOW"` on 2+ layer failures

**File:** `verification/pipeline.py` (before the final `return VerificationResult(...)`)

**Problem:** Layers fail independently; no cumulative failure detection. If 2+ layers fail the response is effectively unverified but no escalation-triggering signal is emitted.

**Fix:** Insert 3 lines after the last layer's except block, before the return:

```python
    # ADD: force LOW tier if 2 or more verification layers failed
    failed_count = sum(1 for layer in layers_applied if layer.endswith(":failed"))
    if failed_count >= 2:
        confidence_tier = "LOW"

    return VerificationResult(
        verified_text=text,
        ...
    )
```

---

## Issue 5 — Local Storage: Rename Misleading Key + Clear on Logout

### Fix 5a — Rename `_keySessionId` → `_keyDemoPersonaKey`

**File:** `flutter/lib/services/local_storage_service.dart`

**Problem:** `_keySessionId` / `saveSessionId` / `getSessionId` store a demo persona key, not a session ID. Misleading to future developers.

**Fix:** Rename constant and both methods:

```dart
// Before:
static const _keySessionId = 'session_id';
Future<void> saveSessionId(String id) async { ... prefs.setString(_keySessionId, id); }
Future<String?> getSessionId() async { ... return prefs.getString(_keySessionId); }

// After:
static const _keyDemoPersonaKey = 'demo_persona_key';
Future<void> saveDemoPersonaKey(String key) async { ... prefs.setString(_keyDemoPersonaKey, key); }
Future<String?> getDemoPersonaKey() async { ... return prefs.getString(_keyDemoPersonaKey); }
```

Note: SharedPreferences key value changes (`'session_id'` → `'demo_persona_key'`), silently resetting any persisted demo persona on the next run. Acceptable — this is ephemeral demo state.

### Fix 5b — Update the one external caller

**File:** `flutter/lib/features/auth/sign_in_screen.dart` (~line 128)

```dart
// Before:
await storage.saveSessionId(key);
// After:
await storage.saveDemoPersonaKey(key);
```

### Fix 5c — Clear shared_preferences on signOut

**File:** `flutter/lib/services/auth_service.dart`

**Problem:** `signOut()` leaves `anon_uid_reuse_check` and `demo_persona_key` persisted across sessions.

**Fix:** Add import + 2 lines in `signOut()`:

```dart
// Add import:
import 'package:shared_preferences/shared_preferences.dart';

// In signOut():
Future<void> signOut() async {
  await _googleSignIn.signOut();
  await _auth.signOut();
  final prefs = await SharedPreferences.getInstance();  // ADD
  await prefs.clear();                                  // ADD
}
```

---

## Ordering

Apply in this order to keep the codebase always compilable:
1. **Issue 4** (Python only, no cross-file deps) — Fix 4a, 4b, 4c
2. **Issue 2** (single Flutter file) — 1-line insert in router.dart
3. **Issue 5** — Fix 5a (local_storage_service.dart) → 5b (sign_in_screen.dart) → 5c (auth_service.dart)

---

## Files Changed

| File | Change |
|---|---|
| `agent.py` | Fix 4a (FHIR load guard) + Fix 4b (confidence_tier = "UNKNOWN", both call sites) |
| `verification/pipeline.py` | Fix 4c (failed layer count) |
| `flutter/lib/navigation/router.dart` | Fix 2 (loading guard) |
| `flutter/lib/services/local_storage_service.dart` | Fix 5a (rename constant + 2 methods) |
| `flutter/lib/features/auth/sign_in_screen.dart` | Fix 5b (update caller) |
| `flutter/lib/services/auth_service.dart` | Fix 5c (import + prefs.clear on signOut) |

---

## Verification

- **Issue 4:** Run `python -m pytest tests/ -x --tb=short` — existing tests should pass; manually verify a session starts cleanly with FHIR unavailable.
- **Issue 2:** Run `flutter analyze` in `flutter/` — no new warnings. Hot-restart the app and confirm no flash-to-sign-in on cold-start.
- **Issue 5:** Run `flutter analyze` in `flutter/` — no compile errors. Confirm `saveDemoPersonaKey` is the only call site after rename.
