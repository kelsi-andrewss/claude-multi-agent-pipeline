# Plan: Fix dark mode — theme color tokens not imported

## Context
Dark mode appears to have no effect — UI surfaces, backgrounds, and containers remain bright (light mode colors) even when `data-theme="dark"` is set on `<html>`. The M3 adoption epic added 6 theme color files (`_color-indigo.css`, `_color-teal.css`, etc.) each defining `[data-theme-color='X'][data-theme='dark']` CSS selectors with correct dark values. However, **none of these files are imported** in `src/styles/tokens.css`. Only `_color-base.css` (light mode `:root` defaults) is loaded, so the dark overrides never apply.

The user noted the M3 changes we just made — this is a direct consequence of that epic: the token files were created but the import wiring was omitted.

## Root cause
`src/styles/tokens.css` is missing `@import` statements for all 6 theme color files.

## Fix

**File to edit**: `src/styles/tokens.css`

Add imports for all 6 theme color files after the existing `_color-base.css` import:

```css
@import './tokens/_color-base.css';
@import './tokens/_color-indigo.css';
@import './tokens/_color-teal.css';
@import './tokens/_color-rose.css';
@import './tokens/_color-amber.css';
@import './tokens/_color-violet.css';
@import './tokens/_color-sage.css';
@import './tokens/_typography.css';
@import './tokens/_elevation.css';
@import './tokens/_shape.css';
@import './tokens/_spacing.css';
@import './tokens/_state.css';
@import './tokens/_motion.css';
@import './tokens/_a11y.css';
```

Order matters: theme color files must come after `_color-base.css` (base defaults) so the `[data-theme-color][data-theme]` selectors override the `:root` defaults.

## Files
- **Write**: `src/styles/tokens.css`
- **Read**: `src/styles/tokens/_color-indigo.css` (verify file exists — confirmed), all 6 theme color files exist in `src/styles/tokens/`

## Secondary findings (not blocking, defer)
- `UserAvatarMenu.css` line 94: hover background uses hardcoded `rgba(103, 80, 164, ...)` instead of `var(--md-sys-color-primary)` — wrong in non-indigo themes. Separate story.
- `PresenceAvatars.css` pulse animation uses `rgba(255,255,255,...)` white glow — looks odd on dark. Separate story.

## Verification
1. `npm run build` — no CSS errors
2. Open app, open Appearance panel, toggle dark mode → all surfaces should switch to dark (`#1b1b1f` background, light text)
3. Switch theme colors (teal, rose, etc.) in dark mode → each should apply its dark palette
