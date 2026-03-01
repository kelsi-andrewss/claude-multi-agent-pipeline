# Plan: Fix hang in demo and anonymous mode

## Context

Three related hangs reported:
1. **Chat screen spins forever** — `isStreaming: true` placeholder appears, no response ever arrives
2. **Backend POST /chat never responds** — agent execution hangs (FHIR or LLM call blocks indefinitely)
3. **Demo screen (/demo) hangs** — scripted walkthrough gets stuck

All three share a root cause chain: the `AdvocateAgent` is constructed with a live `FHIRService` pointing at `demo.openemr.io`, and the LangChain `AgentExecutor` has `max_iterations=25` and no timeout — so if any tool call hangs, the entire `/chat` request hangs too. The demo screen problem is separate: it's purely client-side but the `WalkthroughController` auto-advances every 2 seconds, which means it can race past hard-stop annotations before the user reads them (appears "stuck" when actually at a hard-stop waiting for a tap).

## Root Causes

### Hang 1 & 2: Backend agent hangs

**`agent.py:134`** — `FHIRService` is always initialized with the live OpenEMR URL, even for anonymous/demo users who have no real FHIR records:
```python
fhir_service = FHIRService(_FHIR_BASE_URL, "", "")  # blank credentials
```
When the agent calls a tool that hits FHIR (e.g. `symptom_timeline`, `appointment_brief`), the FHIR client makes a network request to `demo.openemr.io` with blank credentials → times out or auth-fails after ~20s → LangChain retries up to 25 iterations.

**`agent.py:179-186`** — `AgentExecutor` has no `timeout` parameter. A single stuck tool call blocks the entire request indefinitely.

**`auth.py:89-101`** — `get_patient_id` creates a Firestore `AsyncClient` per request and calls `db.close()` synchronously in `finally`. This is correct per the recent fix, but there's no timeout on the Firestore `doc_ref.get()` call. For new anonymous users (first request), it also runs a Firestore transaction — combined latency can be 3-8s.

### Hang 3: Demo screen

`walkthrough_controller.dart:86` — `_scheduleAdvance()` fires a `Timer(2 seconds, _advance)`. If `_advance()` transitions to `hardStop`, the timer stops correctly. But if the user is on the `/demo` screen and navigates away and back, `walkthroughProvider` is a `StateNotifierProvider` which persists across navigation — the state is intact. The reported hang is likely the hard-stop state where the `Continue` button is shown but the auto-advance timer is already cancelled. The user needs to tap `Continue` — this is working as designed. The real issue is that the `/demo` tab is reachable from the nav bar while authenticated anonymously, and users may expect it to work like a live chat.

More likely root: when `sign_in_screen.dart:109` routes to `/chat` after demo persona selection, the `sessionId` saved via `storage.saveSessionId(key)` is the **persona key** ("serena"/"maya"/"ruth"), not a UUID. The `chat_provider.dart` uses `_sessionId` starting as `null`, but `sessionIdProvider` starts as `''`. On first message, `_api.streamMessage(text, null)` is called (on non-web), which sends `session_id: null` in the body. The backend assigns a new UUID, returns it, and Flutter updates `_sessionId`. This part works.

The actual demo-screen hang: after selecting a persona in `_PersonaSheet`, the app goes to `/chat` (not `/demo`). The `/demo` route is the separate `DemoScreen` which is offline. The user meant they're stuck on the live `/chat` screen after selecting a demo persona — which is hang #1/#2.

## Fix Plan

### Fix 1: Add `AgentExecutor` timeout (Python — `agent.py`)

Add `max_execution_time=30` to `AgentExecutor`. This is a built-in LangChain parameter that raises `OutputParserException` or returns partial results after the specified seconds.

```python
self.executor = AgentExecutor(
    agent=agent,
    tools=registered_tools,
    memory=self.memory,
    verbose=True,
    handle_parsing_errors=True,
    max_iterations=25,
    max_execution_time=30,  # ADD THIS
)
```

This caps the total agent run time at 30s. The `TimeoutError` handler in `main.py:132-139` already catches this and returns a graceful response.

Note: LangChain's `max_execution_time` raises `TimeoutError` (or returns early depending on LangChain version). We also need to verify `main.py` catches the right exception. LangChain typically returns the partial output string rather than raising — check: if it just returns the partial output, the response will be well-formed but may be truncated. Either way, the hang is broken.

### Fix 2: Skip FHIR tools for anonymous/demo users (Python — `agent.py`, `models.py`)

For users without real FHIR credentials, FHIR tool calls should fail fast rather than network-timeout. The `FHIRService` already accepts `base_url`, `client_id`, `client_secret` — when constructed with blank strings, the OpenEMR OAuth token exchange will fail.

**Approach**: pass `patient_id` into `AdvocateAgent` and set it on `SessionState`. When `patient_id` is one of the demo/rotation patients ("serena", "maya", "ruth"), the agent is already using a Synthea-seeded demo patient — FHIR *should* work if the demo OpenEMR instance has those patients. But if `demo.openemr.io` is down or slow, we still need the timeout in Fix 1.

**No code change needed here** — Fix 1 (timeout) is sufficient. The demo patients are real Synthea patients in OpenEMR. The hang is purely the missing timeout.

### Fix 3: Flutter — add HTTP timeout to `_doPost` (Flutter — `advocate_api.dart`)

Currently `http.post()` in `_doPost` has no timeout. If the backend hangs (before Fix 1 is deployed), Flutter spins forever with `isStreaming: true`.

Add `.timeout(const Duration(seconds: 45))`:

```dart
Future<http.Response> _doPost({...}) async {
  return http.post(
    uri,
    headers: {...},
    body: jsonEncode(body),
  ).timeout(
    const Duration(seconds: 45),
    onTimeout: () => http.Response('{"error":"timeout"}', 408),
  );
}
```

Also add timeout to `streamMessage`'s `client.send(request)`:
```dart
final response = await client.send(request).timeout(const Duration(seconds: 45));
```

This ensures the Flutter UI un-sticks even if the backend is slow.

### Fix 4: Handle timeout response in `chat_provider.dart`

`_consumeFallback` currently catches all exceptions and replaces the placeholder with "Something went wrong." The 408 response from the timeout handler above will hit the `ApiException` path. Update the error message to be more specific when `statusCode == 408`:

In `_consumeFallback`, after `sendMessage` returns:
```dart
if (response.statusCode == 408 || session.error == 'timeout') {
  // show timeout-specific message
}
```

But `sendMessage` already handles non-200 by throwing `ApiException`. The `catch (_)` in `sendMessage` in `chat_provider.dart:66` will catch it and show the generic error. This is acceptable — no change needed if the timeout response parses cleanly. The `onTimeout` lambda returns a 408 response body `{"error":"timeout"}` which will fail `SessionModel.fromJson` and throw, landing in the `catch (_)` generic handler. That's fine.

### Fix 5: `/demo` screen — not actually broken

The `/demo` screen (`demo_screen.dart` + `walkthrough_controller.dart`) is purely offline and works correctly. The "hang" is the hard-stop mechanic (waiting for user tap), which is intentional. No fix needed.

## Files to Change

| File | Change |
|---|---|
| `advocate/agent.py` | Add `max_execution_time=30` to `AgentExecutor` constructor |
| `advocate/flutter/lib/services/advocate_api.dart` | Add `.timeout(Duration(seconds: 45))` to `_doPost` and `client.send()` |

That's 2 files, minimal changes.

## Critical Paths

- `agent.py:179-186` — `AgentExecutor` constructor (add `max_execution_time`)
- `advocate_api.dart:141-148` — `_doPost` (add timeout)
- `advocate_api.dart:120` — `client.send(request)` (add timeout)
- `main.py:132-139` — existing `TimeoutError` handler (already present, no change needed)

## Verification

1. Start backend: `make dev-backend`
2. Open Flutter web: `make dev-flutter`
3. Sign in anonymously → send a message → should respond within 35s or show timeout message (not spin forever)
4. Select demo persona → send a message → same
5. Simulate timeout: temporarily set `max_execution_time=1` in agent.py, verify the `TimeoutError` handler fires and returns the timeout message
6. Check LangChain version behavior: `pip show langchain` — if ≥0.1.x, `max_execution_time` raises `TimeoutError`; confirm with a test call
