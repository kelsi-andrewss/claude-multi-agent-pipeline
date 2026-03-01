# Fix Flutter Web Blank Screen + Eliminate Dead-Weight Dependency

## Context

The previous plan's bootstrap fix removed the invalid `renderer: "html"` override but also accidentally removed the **`{{flutter_build_config}}`** template variable. This variable is mandatory — it sets `_flutter.buildConfig` which tells the Flutter loader what builds/renderers are available. Without it, the loader throws:

```
FlutterLoader.load requires _flutter.buildConfig to be set
```

The app loads 6 requests in 254ms (fast!) but renders nothing because the engine never initializes. The 3 console errors in the screenshot are this crash.

Additionally, `flutter_secure_storage` is a dead dependency — its 3 methods (`saveAuthToken`, `getAuthToken`, `clearAuthToken`) are defined but **never called** from anywhere in the codebase. The package adds ~200KB+ to the JS bundle and causes WASM incompatibility warnings during build. Removing it is pure gain.

## Changes

### 1. Fix flutter_bootstrap.js — add missing `{{flutter_build_config}}`

**File:** `flutter/web/flutter_bootstrap.js`

The [Flutter web initialization docs](https://docs.flutter.dev/platform-integration/web/initialization) require three template tokens: `{{flutter_js}}` (the loader), `{{flutter_build_config}}` (sets `_flutter.buildConfig`), and optionally `{{flutter_service_worker_version}}`.

```javascript
{{flutter_js}}
{{flutter_build_config}}

_flutter.loader.load({
  serviceWorkerSettings: {
    serviceWorkerVersion: {{flutter_service_worker_version}},
  },
});
```

### 2. Remove `flutter_secure_storage` — dead dependency

The package is imported solely in `local_storage_service.dart` for 3 auth-token methods that are **never called** anywhere in the app. Removing it:
- Shrinks the JS bundle (~200KB+)
- Eliminates WASM dry-run warnings (`dart:html unsupported`, `dart:js_util unsupported`)
- Removes the only web-incompatible dependency

**File:** `flutter/pubspec.yaml`
- Remove `flutter_secure_storage: ^9.0.0`

**File:** `flutter/lib/services/local_storage_service.dart`
- Remove `import 'package:flutter_secure_storage/flutter_secure_storage.dart';`
- Remove `_secure` field, constructor parameter, and the 3 unused token methods
- Keep all `SharedPreferences`-based methods unchanged

### 3. Keep Makefile and firebase.json as-is

The changes from the previous round (no canvaskit deletion, no canvaskit ignore) are correct and stay.

## Files Modified

| File | Change |
|------|--------|
| `flutter/web/flutter_bootstrap.js` | Add `{{flutter_build_config}}` template token |
| `flutter/pubspec.yaml` | Remove `flutter_secure_storage: ^9.0.0` |
| `flutter/lib/services/local_storage_service.dart` | Remove secure storage import, field, constructor param, and 3 unused methods |

## Verification

1. `cd flutter && flutter pub get` — confirm no dependency errors
2. `cd flutter && flutter analyze` — confirm no lint errors
3. `cd flutter && flutter test` — existing tests pass
4. `make build-frontend` — confirm build succeeds, canvaskit present, **no WASM dry-run warnings about flutter_secure_storage**
5. **Local test before deploy:**
   ```bash
   cd flutter/build/web && python3 -m http.server 8080
   # Open http://localhost:8080 in Chrome DevTools
   # Confirm: canvaskit.wasm loads, app renders, no console errors
   ```
6. `firebase deploy --only hosting` — deploy
7. Open `advocate-dc14c.web.app` in incognito — app should render in <2s
