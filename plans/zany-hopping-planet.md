# Fix Remaining PWA Gaps (Post-522c013)

## Context

Commit `522c013` fixed the 25s load time by addressing 3 critical issues (API route collision, blocking Firebase init, CanvasKit WASM). Gemini's root cause analysis identified 5 findings total — 2 remain unresolved plus a renderer build mismatch:

1. **Missing PWA assets** — `index.html` references `manifest.json`, `favicon.png`, and `icons/Icon-192.png` but none exist. Firebase's SPA rewrite (`** → /index.html`) serves HTML with 200 OK for these paths, and the 1-year cache header for `.json`/`.png` extensions poison-caches the wrong content.
2. **Service worker "poison pill"** — Flutter's deprecated SW self-unregisters on activation and force-reloads all open tabs. Provides zero caching benefit but causes a visible reload on first visit.
3. **Renderer build mismatch** — `flutter_bootstrap.js` template says `renderer: "html"` but the build command doesn't pass `--web-renderer html`, so only CanvasKit is compiled and the runtime hint is ignored.

## Changes

### 1. Create `flutter/web/manifest.json` (NEW)

Minimal valid PWA manifest with theme color `#1976D2` (matches loading spinner in index.html).

```json
{
  "name": "Advocate",
  "short_name": "Advocate",
  "start_url": ".",
  "display": "standalone",
  "background_color": "#f3f3f3",
  "theme_color": "#1976D2",
  "description": "Conversational health navigation agent",
  "orientation": "portrait-primary",
  "prefer_related_applications": false,
  "icons": [
    { "src": "icons/Icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "icons/Icon-512.png", "sizes": "512x512", "type": "image/png" },
    { "src": "icons/Icon-maskable-192.png", "sizes": "192x192", "type": "image/png", "purpose": "maskable" },
    { "src": "icons/Icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable" }
  ]
}
```

### 2. Create placeholder icon files (NEW)

Generate solid `#1976D2` blue PNGs using Python (Pillow or raw `struct`+`zlib`):

- `flutter/web/icons/Icon-192.png` (192x192)
- `flutter/web/icons/Icon-512.png` (512x512)
- `flutter/web/icons/Icon-maskable-192.png` (192x192)
- `flutter/web/icons/Icon-maskable-512.png` (512x512)
- `flutter/web/favicon.png` (48x48)

### 3. Remove service worker from `flutter/web/flutter_bootstrap.js`

Remove the `serviceWorkerSettings` block. This prevents `flutter build web` from generating the self-destructing `flutter_service_worker.js`.

```javascript
{{flutter_js}}
{{flutter_build_config}}

_flutter.loader.load({
  config: {
    renderer: "html",
  },
});
```

### 4. Add inline SW cleanup to `flutter/web/index.html`

Insert before the `flutter_bootstrap.js` script tag to proactively unregister the old SW for returning users (prevents one final force-reload):

```html
<script>
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.getRegistrations().then(function(r) {
      r.forEach(function(reg) { reg.unregister(); });
    });
  }
</script>
```

Also fix the default meta description (line 12) and title (line 23):
- `<meta name="description" content="Conversational health navigation agent">`
- `<title>Advocate</title>`

### 5. Add `--web-renderer html` to all build commands

**`Makefile:32`** — `build-frontend` target:
```
@cd flutter && flutter build web --web-renderer html -O4 --release
```

**`.github/workflows/deploy.yml:56`**:
```
- run: cd flutter && flutter build web --web-renderer html --release
```

**`.github/workflows/preview.yml:19`**:
```
- run: cd flutter && flutter build web --web-renderer html --release
```

This ensures the build compiles only the HTML renderer (no 1.6MB CanvasKit WASM).

## Files Modified

| File | Action |
|------|--------|
| `flutter/web/manifest.json` | Create |
| `flutter/web/icons/Icon-192.png` | Create |
| `flutter/web/icons/Icon-512.png` | Create |
| `flutter/web/icons/Icon-maskable-192.png` | Create |
| `flutter/web/icons/Icon-maskable-512.png` | Create |
| `flutter/web/favicon.png` | Create |
| `flutter/web/flutter_bootstrap.js` | Edit — remove serviceWorkerSettings |
| `flutter/web/index.html` | Edit — add SW cleanup script, fix meta/title |
| `Makefile` | Edit — add `--web-renderer html` |
| `.github/workflows/deploy.yml` | Edit — add `--web-renderer html` |
| `.github/workflows/preview.yml` | Edit — add `--web-renderer html` |

## Verification

1. Run `cd flutter && flutter build web --web-renderer html --release`
2. Confirm `flutter/build/web/flutter_service_worker.js` is NOT generated
3. Confirm `flutter/build/web/manifest.json` exists with correct content
4. Confirm `flutter/build/web/icons/` contains all 4 icon files
5. Confirm `flutter/build/web/favicon.png` exists
6. Confirm `flutter/build/web/flutter_bootstrap.js` contains `"renderer":"html"` (not `"canvaskit"`)
7. Confirm `flutter/build/web/canvaskit/` directory is NOT generated (saves ~1.6MB)
