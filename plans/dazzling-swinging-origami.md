# Plan: Fix Flutter Web 25-Second Load Time

## Context

The Flutter web app at `advocate-dc14c.web.app` takes ~25 seconds on first load. The build currently uses the **CanvasKit renderer** (default when no `--web-renderer` flag is specified), which forces the browser to download and JIT-compile a 5.4–6.8 MB WebAssembly binary before the first frame can render. This app is a text/chat/card UI with no custom Canvas painting — CanvasKit provides zero benefit and costs ~20 seconds of load time.

## Root Causes

1. **CanvasKit renderer** (primary — ~15–20s): `flutter build web -O4 --release` defaults to canvaskit. Browser downloads `canvaskit.wasm` (5.4 MB on Chrome) and JIT-compiles it before any Flutter paint.
2. **No preload hints** (secondary — ~1–2s): `main.dart.js` (3.1 MB) is not discovered until `flutter_bootstrap.js` executes, adding a sequential waterfall penalty.

## Changes

### 1. `Makefile` — line 32: add `--web-renderer html`

```
# Before
@cd flutter && flutter build web -O4 --release

# After
@cd flutter && flutter build web -O4 --release --web-renderer html
```

Also update the help text on line 46:
```
# Before
  build-frontend   Build Flutter web app (Standard release, max optimization)

# After
  build-frontend   Build Flutter web app (HTML renderer, no CanvasKit WASM)
```

### 2. `flutter/web/index.html` — add preload hint after line 4 (`<base href>`)

Insert after line 4:
```html
  <link rel="preload" href="main.dart.js" as="script">
```

This starts the 3.1 MB JS download in parallel with `flutter_bootstrap.js` instead of sequentially after it.

## Build & Deploy

```bash
make build-frontend
firebase deploy --only hosting
```

## Verification

After build, before deploying:
```bash
grep '"renderer"' flutter/build/web/flutter_bootstrap.js
# Expected: "renderer":"html"

ls flutter/build/web/canvaskit/
# Should be empty or absent — canvaskit/ directory eliminated
```

After deploy — Chrome DevTools > Network > Hard reload (Disable cache):

| Asset | Before | After |
|---|---|---|
| `canvaskit.wasm` | 1,630 kB (6+ min total) | **Gone** |
| `main.dart.js` | Sequential, after bootstrap | Starts with HTML parse |
| First frame | ~25s | ~2–4s |

## Expected Result

| Connection | Before | After |
|---|---|---|
| Fast (100+ Mbps) | 15–18s | 1.5–2.5s |
| Average (25 Mbps) | 22–25s | 2.5–4s |

Repeat visits unchanged — already cached via Firebase Hosting `max-age=31536000`.
