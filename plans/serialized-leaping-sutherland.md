# Fix: Flutter Web 25-Second Load Time

## Context

The deployed Flutter web app at advocate-dc14c.web.app takes **25.5 seconds** to become interactive (per the network waterfall). DOMContentLoaded is 209ms and resource Load is 522ms — the extra ~25 seconds are caused by three compounding issues in initialization, routing, and renderer choice.

## Root Causes (in priority order)

### 1. CRITICAL: firebase.json rewrite conflict steals `/chat` from the SPA

`firebase.json` lines 30-43 rewrite `/chat` and `/chat/**` to Cloud Run (`advocate-api`). But Flutter's `initialLocation` in `router.dart:31` is also `/chat`. On first load:

1. Browser requests `advocate-dc14c.web.app/chat`
2. Firebase Hosting matches the `/chat` → Cloud Run rewrite **before** the catch-all `**` → `/index.html`
3. Cloud Run expects a POST with auth headers → returns an error or unexpected response
4. SPA eventually loads through the fallback `**` → `/index.html` rewrite, adding a full round-trip to Cloud Run

The Flutter API client (`advocate_api.dart:39-41`) uses `API_BASE_URL` with an **empty default**, so all API calls go to same-origin relative paths (`/chat`, `/chat/stream`, `/sessions`, etc.). This means the firebase.json rewrites are the intended proxy mechanism — but they collide with the SPA route namespace.

### 2. HIGH: Blocking Firebase init in main()

`main.dart:13-16` blocks `runApp()` behind `Future.wait([Firebase.initializeApp(), SharedPreferences.getInstance()])`. On web, Firebase JS SDK init involves network calls to googleapis.com, firebaseinstallations, and identitytoolkit — typically 2-5 seconds on cold start. The demo_mode cleanup (lines 19-22) adds another sequential await.

### 3. MEDIUM: CanvasKit WASM download (1.6MB)

The app uses the default CanvasKit renderer. For a forms-based app (text fields, buttons, lists, navigation bars) with no canvas/custom painting, the HTML renderer is sufficient and avoids the 1.6MB WASM download.

---

## Implementation Plan

### Phase 1: Fix firebase.json rewrite conflict

**Goal**: Prefix all API rewrites with `/api/` so they don't collide with SPA routes.

#### 1a. `firebase.json` — change rewrite sources
```
/chat       → /api/chat
/chat/**    → /api/chat/**
/health     → /api/health
```
Also add rewrites for `/api/sessions/**` and `/api/session/**` to cover all backend endpoints.

#### 1b. `main.py` — prefix all FastAPI routes with `/api`
Use FastAPI's `APIRouter` with `prefix="/api"`:
- `/health` → `/api/health`
- `/chat` → `/api/chat`
- `/chat/stream` → `/api/chat/stream`
- `/session/{id}/state` → `/api/session/{id}/state`
- `/session/{id}/data` → `/api/session/{id}/data`
- `/sessions` → `/api/sessions` (if it exists, check for list endpoint)

#### 1c. `flutter/lib/services/advocate_api.dart` — prefix all URL paths
Update all `Uri.parse('$_baseUrl/...')` calls to include `/api`:
- `$_baseUrl/chat` → `$_baseUrl/api/chat`
- `$_baseUrl/chat/stream` → `$_baseUrl/api/chat/stream`
- `$_baseUrl/sessions` → `$_baseUrl/api/sessions`
- `$_baseUrl/sessions/$sessionId` → `$_baseUrl/api/sessions/$sessionId`
- `$_baseUrl/session/$sessionId/data` → `$_baseUrl/api/session/$sessionId/data`

**Files**: `firebase.json`, `main.py`, `flutter/lib/services/advocate_api.dart`

### Phase 2: Defer Firebase initialization

**Goal**: Render the app shell immediately; initialize Firebase in the background.

#### 2a. `flutter/lib/main.dart` — make main() synchronous
Remove all async init. Just call `runApp()`:
```dart
void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const ProviderScope(child: AdvocateApp()));
}
```

#### 2b. `flutter/lib/shared/providers/app_providers.dart` — add firebaseInitProvider
```dart
final firebaseInitProvider = FutureProvider<void>((ref) async {
  await Firebase.initializeApp(options: DefaultFirebaseOptions.currentPlatform);
  final prefs = await SharedPreferences.getInstance();
  if (prefs.getBool('demo_mode') == true) {
    await FirebaseAuth.instance.signOut();
    await prefs.remove('demo_mode');
  }
});
```

#### 2c. `flutter/lib/app.dart` — gate router on Firebase init
Use `firebaseInitProvider.when()` to show a splash during init, then render the real app:
```dart
final firebaseInit = ref.watch(firebaseInitProvider);
return firebaseInit.when(
  loading: () => MaterialApp(home: Scaffold(body: Center(child: CircularProgressIndicator()))),
  error: (e, st) => MaterialApp(home: Scaffold(body: Center(child: Text('Init error: $e')))),
  data: (_) {
    final router = ref.watch(goRouterProvider);
    // ... existing theme/router logic
  },
);
```

**Files**: `flutter/lib/main.dart`, `flutter/lib/shared/providers/app_providers.dart`, `flutter/lib/app.dart`

### Phase 3: Switch to HTML renderer

#### 3a. `flutter/web/flutter_bootstrap.js` — set renderer to html
```js
_flutter.loader.load({
  config: {
    renderer: "html",
  },
  serviceWorkerSettings: {
    serviceWorkerVersion: {{flutter_service_worker_version}},
  },
});
```

**File**: `flutter/web/flutter_bootstrap.js`

---

## Files Modified (summary)

| File | Change |
|------|--------|
| `firebase.json` | Prefix API rewrites with `/api/` |
| `main.py` | Move routes to APIRouter with `/api` prefix |
| `flutter/lib/services/advocate_api.dart` | Prefix all URL paths with `/api` |
| `flutter/lib/main.dart` | Remove blocking async init, make synchronous |
| `flutter/lib/shared/providers/app_providers.dart` | Add `firebaseInitProvider` |
| `flutter/lib/app.dart` | Gate router on Firebase init completion |
| `flutter/web/flutter_bootstrap.js` | Set `renderer: "html"` |

## Verification

1. `flutter build web --web-renderer html` — build succeeds
2. `firebase serve` or deploy — verify `/chat` serves `index.html` (not Cloud Run)
3. Open DevTools Network tab — confirm no Cloud Run round-trip on initial load
4. Time to first frame should drop from ~25s to <5s
5. Auth flows still work: anonymous sign-in, Google sign-in, email sign-in
6. Chat messages still reach the backend via `/api/chat`
7. Run existing Flutter tests: `cd flutter && flutter test`
8. Run Python tests: `python -m pytest tests/ -x --tb=short` (verify `/api` prefix routes)
