# Fix: GoogleSignIn "Future already completed" + /chat/stream 404

## Context

Two runtime errors observed in the Flutter web app:

1. `DartError: Bad state: Future already completed` in `google_sign_in_web.dart` — caused by
   multiple `GoogleSignIn` instances being created. PR #10 fixed `sign_in_screen.dart` by
   using the `authServiceInstance` singleton from `router.dart`, but two other files still
   call `AuthService()` directly, creating duplicate instances that conflict on sign-in.

2. `Failed to load resource: 404 /chat/stream` — `advocate_api.dart` sends
   `POST /chat/stream` with SSE headers, but the backend only registers `POST /chat`
   (full JSON response). `chat_provider.dart` catches this and falls back to `/chat`,
   so chat works but streaming is broken and the error is noisy.

## Fix 1 — Singleton AuthService in chat_provider.dart and agent_state_provider.dart

**Files to modify:**
- `flutter/lib/features/chat/chat_provider.dart`
- `flutter/lib/features/agent_state/agent_state_provider.dart`

**Pattern already established by PR #10** (`flutter/lib/navigation/router.dart:13`):
```dart
final authServiceInstance = AuthService();  // top-level singleton
```

### chat_provider.dart (lines 11-13)

Replace the local private provider:
```dart
// BEFORE
final _authServiceProvider = Provider<AuthService>(
  (ref) => AuthService(),
);
```
With an import of the singleton and a provider that reads it:
```dart
// AFTER — import router.dart's singleton
import '../../navigation/router.dart' show authServiceInstance;

final _authServiceProvider = Provider<AuthService>(
  (ref) => authServiceInstance,
);
```

### agent_state_provider.dart (line 75)

Replace the inline `AuthService()` construction:
```dart
// BEFORE
(ref, sessionId) => AgentStateNotifier(sessionId, AuthService()),
```
With:
```dart
// AFTER — import router.dart's singleton
import '../../navigation/router.dart' show authServiceInstance;

(ref, sessionId) => AgentStateNotifier(sessionId, authServiceInstance),
```

## Fix 2 — Add POST /chat/stream SSE endpoint to FastAPI

**File to modify:** `main.py`

Add SSE streaming endpoint using FastAPI's `StreamingResponse`. The existing
`AdvocateAgent.chat()` call is async; we wrap it with `asyncio.Queue` to yield
tokens as they arrive (or yield the full response as a single SSE frame if the
agent doesn't support streaming yet).

```python
from fastapi.responses import StreamingResponse

@app.post("/chat/stream")
async def chat_stream(request: ChatRequest, uid: str = Depends(verify_firebase_token)):
    session_id = request.session_id or str(uuid.uuid4())
    session_key = f"{uid}:{session_id}"
    if session_key not in _sessions:
        session_state = SessionState(
            patient_id=uid,
            entry_point=request.entry_point,
        )
        agent = AdvocateAgent(session_state=session_state)
        _sessions[session_key] = (agent, session_state)

    agent, session_state = _sessions[session_key]

    async def event_stream():
        try:
            response = await agent.chat(request.message)
            payload = json.dumps({
                "response": response,
                "session_id": session_id,
                "confidence_tier": session_state.confidence_tier,
                "escalation_flags": session_state.escalation_flags,
            })
            yield f"data: {payload}\n\n"
        except FHIRAuthError:
            payload = json.dumps({"error": "fhir_auth_error", "session_id": session_id})
            yield f"data: {payload}\n\n"
        except FHIRNotFoundError:
            session_state.fhir_resources_retrieved = {}
            response = await agent.chat_questionnaire_only(request.message)
            payload = json.dumps({
                "response": response,
                "session_id": session_id,
                "confidence_tier": "LOW",
                "escalation_flags": session_state.escalation_flags,
            })
            yield f"data: {payload}\n\n"
        except TimeoutError:
            payload = json.dumps({"error": "timeout", "session_id": session_id})
            yield f"data: {payload}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

Also add `import json` at the top of `main.py` (it's not currently imported).

## Files Modified

| File | Change |
|------|--------|
| `flutter/lib/features/chat/chat_provider.dart` | Use `authServiceInstance` singleton |
| `flutter/lib/features/agent_state/agent_state_provider.dart` | Use `authServiceInstance` singleton |
| `main.py` | Add `POST /chat/stream` SSE endpoint + `import json` |

## Verification

1. `flutter run -d chrome` — sign in with Google; confirm no `Future already completed` error in console
2. Send a chat message; confirm network tab shows `POST /chat/stream` returning `200` with `text/event-stream` content-type
3. Response text streams in (single SSE frame for now, since `agent.chat()` isn't token-streaming yet)
4. `python3 -m pytest tests/ -x --tb=short` — backend tests pass
