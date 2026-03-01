# Plan: Fix Demo Loop, Session Isolation, and Tab Data

## Context
Three related bugs in the Flutter demo/walkthrough system:
1. Demo sends the same question repeatedly instead of advancing
2. Demo sessions share state (chat history, session ID) across personas
3. Timeline/Brief/Prep tabs show empty even though backend has data

---

## Root Causes

### Bug 1 — Demo repeating same question
`chat_provider.dart:14` — `sessionIdProvider` is initialized as `''`. `ChatNotifier._sessionId` is initialized as `null`.

The real problem: `ChatNotifier._sessionId` is an instance field that **never resets** between demo sessions. When a new persona is selected, the notifier is not invalidated, so `_sessionId` still holds the old session ID from the prior run. The backend receives the old session ID and continues that session — which may cause message sequencing issues.

However, the actual "repeating same question" loop is more subtle:
`_handleSend()` at line 60 `await`s `sendMessage()`. During that await, `lastIsStreaming` becomes `true`, which **disables the send button** (`_DemoChatInput` passes `isStreaming: lastIsStreaming` to disable the button). BUT — the index is only advanced at line 82 **after** the await. If `sendMessage()` throws or never sets `isStreaming: false` (e.g., stream error falls into fallback path and updates state correctly, but in some error path the placeholder stays streaming), the index never advances and `demoPendingMessageProvider` keeps returning the same message.

More critically: in `_consumeFallback`, the session always sets `_sessionId` unconditionally (line 148), but in `_consumeStream`, `_sessionId` is only set if `_sessionId == null` (line 101). On a second demo run, `_sessionId != null` (stale from prior session), so the stream path never updates it — the wrong session ID persists for the whole demo.

### Bug 2 — Session isolation
When a new persona is selected in `demo_screen.dart:15-20`, only `demoPersonaProvider` and `demoIndexProvider` are reset. Missing resets:
- `sessionIdProvider` — never cleared, old session ID persists
- `chatProvider` state — chat history never cleared, old messages visible
- `ChatNotifier._sessionId` — private instance field, only way to reset is to invalidate the provider

### Bug 3 — Tabs empty even though data exists
`session_data_provider.dart:44-55` — `_fetchData()` is triggered by this listener condition:
```dart
prevLast.isStreaming == true && nextLast.isStreaming == false
```
This requires the **second-to-last state** to have had a streaming message. The listener fires on every `chatProvider` change. For this condition to be true: the agent placeholder was previously streaming, and just became non-streaming.

This works fine in the normal flow. The issue is that `sessionIdProvider` is stale (from Bug 2). When `_fetchData()` runs, it reads `sessionIdProvider` which either:
- Is empty `''` → early return at line 68, no fetch
- Has old session ID → fetches wrong session's data (or fails silently)

Even if Bug 2 is fixed (session ID resets on new demo), there's still a timing issue: the session ID is received **during** the first stream response. The `_fetchData()` trigger fires when the first agent response finishes streaming. At that exact moment, `sessionIdProvider` has just been set. This should work — but we need to verify the fetch actually happens after the ID is written.

---

## Fix Plan

### 1. Reset all session state on persona selection (`demo_screen.dart`)

In `onPersonaSelected`, after setting persona/index, also:
- `ref.read(sessionIdProvider.notifier).state = ''`
- `ref.invalidate(chatProvider)` — invalidating the `NotifierProvider` rebuilds `ChatNotifier`, which returns `[]` from `build()` and resets `_sessionId` to `null`

**File:** `flutter/lib/features/demo/demo_screen.dart:15-20`

### 2. Also reset on "Exit demo" button (`chat_screen.dart`)

The "Exit demo" `TextButton.onPressed` at line 378-380 only clears `demoPersonaProvider` and `demoIndexProvider`. Add the same resets:
- `ref.read(sessionIdProvider.notifier).state = ''`
- `ref.invalidate(chatProvider)`

**File:** `flutter/lib/features/chat/chat_screen.dart:378-380`

### 3. Fix `_consumeStream` to always accept new session ID (`chat_provider.dart`)

Change the guard at line 101 from:
```dart
if (parsed.containsKey('session_id') && _sessionId == null) {
```
to:
```dart
if (parsed.containsKey('session_id')) {
```
This allows session ID to be updated even if `_sessionId` was stale from a prior run. (After fix 1, `_sessionId` will be null on new demo start anyway — this is belt-and-suspenders.)

**File:** `flutter/lib/features/chat/chat_provider.dart:100-107`

### 4. Add `_fetchData()` trigger on `sessionIdProvider` change (`session_data_provider.dart`)

The existing listener at line 38 resets state when session ID changes but doesn't fetch. Add a fetch trigger for when the session ID transitions from empty to non-empty:

```dart
_ref.listen<String>(sessionIdProvider, (previous, next) {
  if (previous != next) {
    state = const SessionDataState();
  }
  // Trigger fetch when session ID is first assigned
  if ((previous == null || previous.isEmpty) && next.isNotEmpty) {
    _fetchData();
  }
});
```

This ensures that as soon as a session ID arrives (which happens during the first response), we immediately try to fetch data — rather than waiting for a second agent response to complete.

**File:** `flutter/lib/features/session/session_data_provider.dart:38-42`

---

## Files Modified
- `flutter/lib/features/demo/demo_screen.dart` — add `sessionIdProvider` reset + `chatProvider` invalidation
- `flutter/lib/features/chat/chat_screen.dart` — same resets in "Exit demo" button
- `flutter/lib/features/chat/chat_provider.dart` — remove `_sessionId == null` guard in stream handler
- `flutter/lib/features/session/session_data_provider.dart` — add fetch trigger on session ID assignment

## Verification
1. Open demo, select Serena → messages should advance 1→2→3, never repeat
2. Exit demo, re-select Maya → chat history should be blank, no Serena messages visible
3. Complete first message exchange in demo → within a few seconds, Timeline/Brief tabs should populate
4. Exit demo, re-enter with Ruth → tabs should not show Serena/Maya data (should clear then repopulate after first exchange)
5. Run `flutter analyze` — no new errors
