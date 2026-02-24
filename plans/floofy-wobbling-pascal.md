# Epic-003: Material Design 3 Adoption

## Context

CollabBoard currently uses a minimal custom CSS variable system (~15 tokens in App.css) with hardcoded colors, font sizes, border radii, and spacing scattered across 18 CSS files. There is no design system, no typography scale, and no spacing grid. The dark mode toggle reads from `prefers-color-scheme` and sets `data-theme="dark"` on `<html>`.

This epic adopts Material Design 3 across all DOM-based UI, adds 6 user-selectable color themes with light/dark variants, imports Roboto Flex, adds accessibility options (high contrast, reduced motion, large text), and persists preferences to Firestore.

The CLAUDE.md will be updated to mandate M3 adherence for all future UI work.

---

## Architecture Decisions

- **Static CSS variables** -- all 6 themes x 2 modes = 12 palettes pre-generated via Google's M3 Theme Builder, hardcoded as CSS custom properties. Zero runtime cost.
- **Theme application** -- `data-theme-color="indigo"` + `data-theme="dark|light"` on `<html>`. CSS selectors: `[data-theme-color='indigo'][data-theme='light']`.
- **Compat layer** -- old variable names (`--bg-primary` etc.) aliased to M3 tokens so existing CSS works unchanged. Components migrate incrementally; compat.css removed when all done.
- **Font** -- Roboto Flex via Google Fonts CDN with `preconnect` in `index.html`. Fallback: `system-ui, sans-serif`.
- **Accessibility** -- additive data attributes: `data-high-contrast`, `data-reduced-motion`, `data-large-text`. Independent of theme. CSS overrides in `_a11y.css`.
- **Preferences storage** -- Firestore `users/{userId}.preferences` field (merge-safe). localStorage as read-through cache + unauthenticated fallback.
- **Protected Konva files** -- untouched. They render to canvas, not DOM. `darkMode` prop drilling remains for BoardCanvas.

---

## File Structure (new)

```
src/styles/
  tokens/
    _color-base.css          ~90 lines  -- M3 color roles on :root (indigo-light defaults)
    _color-indigo.css         ~120 lines -- [data-theme-color='indigo'] light + dark
    _color-teal.css           ~120 lines
    _color-rose.css           ~120 lines
    _color-amber.css          ~120 lines
    _color-violet.css         ~120 lines
    _color-sage.css           ~120 lines
    _typography.css           ~120 lines -- 15 type styles x 5 props each
    _elevation.css            ~40 lines  -- 6 levels (0-5) shadow + tint
    _shape.css                ~20 lines  -- none/xs/sm/md/lg/xl/full
    _spacing.css              ~20 lines  -- 4px grid: 4,8,12,16,20,24,32,40,48,64
    _state.css                ~15 lines  -- hover/focus/pressed/dragged opacities
    _motion.css               ~30 lines  -- M3 durations + easings
    _a11y.css                 ~80 lines  -- high contrast, large text, reduced motion
  compat.css                  ~30 lines  -- aliases: --bg-primary -> --md-sys-color-surface
  tokens.css                  ~20 lines  -- barrel: @import all token files

src/hooks/useUserPreferences.js     (NEW)
src/components/AppearanceSettings.jsx  (NEW)
src/components/AppearanceSettings.css  (NEW)
```

---

## Story Breakdown

### Story 1: M3 Token Foundation + Font Loading
**Agent**: architect | **Model**: sonnet | **Trivial**: no

Create the full M3 token system and wire it into the app. This is the prerequisite for all other stories.

**Write files**:
1. `src/styles/tokens.css` (barrel)
2. `src/styles/tokens/_color-base.css`
3. `src/styles/tokens/_typography.css`
4. `src/styles/tokens/_elevation.css`
5. `src/styles/tokens/_shape.css`

**Read files**: `src/App.css`, `src/index.css`

**Plan**: Create barrel file importing all token partials. Define M3 color roles on `:root` (indigo-light defaults), typography scale with Roboto Flex, elevation levels 0-5, and shape corner tokens.

---

### Story 2: Theme Color Files + Spacing/State/Motion Tokens
**Agent**: quick-fixer | **Model**: haiku | **Trivial**: no

**Write files**:
1. `src/styles/tokens/_color-indigo.css`
2. `src/styles/tokens/_color-teal.css`
3. `src/styles/tokens/_color-rose.css`
4. `src/styles/tokens/_spacing.css`
5. `src/styles/tokens/_state.css`

**Read files**: `src/styles/tokens/_color-base.css`

**Plan**: Define indigo and teal theme palettes (light+dark selectors each), plus spacing scale, state layer opacities.

---

### Story 3: Remaining Theme Colors + Motion + A11y
**Agent**: quick-fixer | **Model**: haiku | **Trivial**: no

**Write files**:
1. `src/styles/tokens/_color-amber.css`
2. `src/styles/tokens/_color-violet.css`
3. `src/styles/tokens/_color-sage.css`
4. `src/styles/tokens/_motion.css`
5. `src/styles/tokens/_a11y.css`

**Read files**: `src/styles/tokens/_color-base.css`

**Plan**: Define amber, violet, sage palettes. Add M3 motion tokens (durations + easings). Add accessibility overrides (high contrast color boosts, large text scale, reduced motion zero-durations).

---

### Story 4: Compat Layer + Integration Wiring
**Agent**: architect | **Model**: sonnet | **Trivial**: no

Wire the token system into the app. Replace old token definitions with M3 + compat aliases. Update font loading.

**Write files**:
1. `src/styles/compat.css`
2. `src/App.css` (remove lines 1-32 old tokens, import tokens.css)
3. `src/index.css` (replace Vite boilerplate with M3 body defaults)
4. `index.html` (add Roboto Flex preconnect + link)
5. `src/main.jsx` (add `import './styles/tokens.css'` before other CSS)

**Read files**: `src/App.css`, `src/index.css`, `index.html`, `src/main.jsx`

**Plan**: Create compat.css mapping old names to M3 tokens. Remove old `:root`/`[data-theme='dark']` blocks from App.css. Replace Vite boilerplate in index.css with M3 body defaults (Roboto Flex font, surface color, on-surface text). Add Google Fonts CDN links to index.html. Add token barrel import to main.jsx. Update `data-theme` attribute format to support `data-theme-color`.

**Depends on**: Stories 1, 2, 3

---

### Story 5: useUserPreferences Hook + App.jsx Wiring
**Agent**: architect | **Model**: sonnet | **Trivial**: no

Build the preferences system. Persist theme/dark-mode/accessibility choices to Firestore.

**Write files**:
1. `src/hooks/useUserPreferences.js` (NEW)
2. `src/App.jsx` (remove old darkMode state, wire useUserPreferences, update data-attribute logic)

**Read files**: `src/hooks/useAuth.js`, `src/firebase/config.js`, `src/App.jsx`

**Plan**: Create useUserPreferences hook that: reads from localStorage on mount (instant hydration), subscribes to Firestore `users/{uid}` for authenticated users, applies data-attributes (`data-theme`, `data-theme-color`, `data-high-contrast`, `data-reduced-motion`, `data-large-text`) to `<html>`, exposes `{ preferences, updatePreference, isLoading }`. In App.jsx: replace `darkMode`/`setDarkMode` state with `preferences.darkMode` from the hook, pass `preferences.darkMode` to all existing consumers (BoardCanvas, FABButtons, EmptyStateOverlay, etc.), update both FAB and header dark mode toggles to call `updatePreference`.

**Depends on**: Story 4

---

### Story 6: AppearanceSettings Panel + Menu Link
**Agent**: architect | **Model**: sonnet | **Trivial**: no

The UI for choosing themes and toggling accessibility options.

**Write files**:
1. `src/components/AppearanceSettings.jsx` (NEW)
2. `src/components/AppearanceSettings.css` (NEW)
3. `src/components/UserAvatarMenu.jsx` (add "Appearance" menu item)
4. `src/App.jsx` (add showAppearanceSettings state, render overlay, pass callback)

**Read files**: `src/components/BoardSettings.jsx` (reference for modal pattern), `src/components/UserAvatarMenu.jsx`

**Plan**: Create AppearanceSettings modal with: theme section (3x2 swatch grid, checkmark on active), dark mode toggle, accessibility section (3 toggles with descriptions). Add "Appearance" item with Palette icon to UserAvatarMenu. Wire open/close state in App.jsx.

**Depends on**: Story 5

---

### Story 7: Global Base Styles (Modals, Buttons, Forms, Login)
**Agent**: quick-fixer | **Model**: sonnet | **Trivial**: no

Migrate App.css global classes to M3 tokens.

**Write files**:
1. `src/App.css` (migrate `.modal-overlay`, `.modal-card`, `.primary-btn`, `.secondary-btn`, `.form-group`, `.login-*`, `.board-loading`, `.error-tooltip`, `.view-only-banner`)

**Read files**: `src/App.css`

**Plan**: Replace all `var(--bg-*)` with `var(--md-sys-color-surface*)`, all `var(--text-*)` with `var(--md-sys-color-on-surface*)`, all `var(--accent-*)` with `var(--md-sys-color-primary*)`. Update border-radii to M3 shape tokens. Add M3 state layers (::after pseudo) to buttons. Update modals to M3 dialog spec (28px corner, surface-container-highest). Update typography to M3 typescale tokens.

**Depends on**: Story 4

---

### Story 8: Header + Toolbar + BoardSwitcher CSS
**Agent**: architect | **Model**: sonnet | **Trivial**: no

**Write files**:
1. `src/App.css` (header classes only: `.header`, `.header-left`, `.header-right`, `.header-divider`)
2. `src/components/BoardSwitcher.css` (toolbar, split buttons, board switcher dropdown, snap toggle, zoom controls)

**Read files**: `src/components/HeaderLeft.jsx`, `src/components/BoardSwitcher.css`

**Plan**: Migrate header to M3 top app bar pattern (surface at elevation 0). Toolbar icon buttons: 40px touch target, state layers, shape-small corners. Board switcher dropdown: M3 menu spec (surface-container, shape-extra-small, elevation 2). Zoom controls: M3 small button spec. Snap toggle: M3 icon toggle (primary-container when active). Replace all hardcoded `rgba()` hover values with M3 state layer system.

**Depends on**: Story 7

---

### Story 9: FABs + SelectedActionBar + ContextMenu + ColorPicker CSS
**Agent**: quick-fixer | **Model**: sonnet | **Trivial**: no

**Write files**:
1. `src/components/FABButtons.css`
2. `src/components/SelectedActionBar.css`
3. `src/components/ContextMenu.css`
4. `src/components/ColorPicker.css`

**Read files**: corresponding JSX files

**Plan**: FABs to M3 spec (56px, 16px corners, tertiary/primary container, elevation 3). Context menu to M3 menu (surface-container, shape-extra-small, elevation 2, 48px items, state layers). Color picker: M3 menu surface. SelectedActionBar: surface-container + elevation 2. Replace all hardcoded danger colors with `var(--md-sys-color-error*)`. Add reduced-motion guards on pulse animations.

**Depends on**: Story 7

---

### Story 10: BoardSelector CSS
**Agent**: architect | **Model**: sonnet | **Trivial**: no | **needsTesting**: yes

**Write files**:
1. `src/components/BoardSelector.css`

**Read files**: `src/components/BoardSelector.jsx`

**Plan**: Migrate search bar to M3 search (surface-container-highest, full shape). Sort/filter buttons to M3 segmented button. Buttons to M3 filled/outlined. Tabs to M3 primary tabs. All invite/member components to M3 list items. Empty states to M3 typography. Dropdown lists to M3 menu surface.

**Depends on**: Story 7

**Note**: BoardSelector.jsx is protected testable. This story is CSS-only; if no JSX class name changes are needed, needsTesting may be false. Verify during implementation.

---

### Story 11: GroupCard + Board Card CSS
**Agent**: architect | **Model**: sonnet | **Trivial**: no | **needsTesting**: yes

**Write files**:
1. `src/components/GroupCard.css`
2. `src/App.css` (`.board-card*` and `.boards-grid` rules only)

**Read files**: `src/components/GroupCard.jsx`, `src/App.css`

**Plan**: Group cards to M3 filled card (surface-container, shape-medium, elevation 1 on hover). Board cards to M3 elevated card. Card hover: elevation change instead of translateY. Badges to M3 badge spec. Drag states: M3 elevation 4. Delete buttons: M3 error tokens.

**Depends on**: Story 7

**Note**: GroupCard.jsx is protected testable. CSS-only if no class name changes needed.

---

### Story 12: GroupPage CSS
**Agent**: quick-fixer | **Model**: haiku | **Trivial**: no | **needsTesting**: yes

**Write files**:
1. `src/components/GroupPage.css`

**Read files**: `src/components/GroupPage.jsx`

**Plan**: Page header to M3 surface gradient. Breadcrumbs to label-medium typescale. Buttons/inputs to same M3 patterns established in Stories 7-10. Controls bar unified with BoardSelector patterns.

**Depends on**: Story 10

**Note**: GroupPage.jsx is protected testable. CSS-only story.

---

### Story 13: BoardSettings + GroupSettings CSS
**Agent**: quick-fixer | **Model**: sonnet | **Trivial**: no | **needsTesting**: yes

**Write files**:
1. `src/components/BoardSettings.css`
2. `src/components/GroupSettings.css`

**Read files**: `src/components/BoardSettings.jsx`, `src/components/GroupSettings.jsx`

**Plan**: Both modals inherit M3 dialog from Story 7. Section headers to title-small typescale. Member rows to M3 list-item pattern. Invite forms to M3 outlined text field. Toggle buttons to M3 switch (32x52px). Template/danger buttons to M3 filled/outlined/error variants.

**Depends on**: Story 7

**Note**: Both JSX files are protected testable. CSS-only story.

---

### Story 14: UserAvatarMenu + Avatar + PresenceAvatars CSS
**Agent**: quick-fixer | **Model**: haiku | **Trivial**: no

**Write files**:
1. `src/components/UserAvatarMenu.css`
2. `src/components/Avatar.css`
3. `src/components/PresenceAvatars.css`

**Read files**: corresponding JSX files

**Plan**: Menu dropdown to M3 menu spec. Menu items: 48px height, state layers. Avatar: M3 full-round shape. Presence modal inherits M3 dialog. Badge to M3 badge spec. Reduced-motion guard on presence-pulse animation.

**Depends on**: Story 7

---

### Story 15: AIPanel + Tutorial + AdminPanel CSS
**Agent**: quick-fixer | **Model**: sonnet | **Trivial**: no

**Write files**:
1. `src/components/AIPanel.css`
2. `src/components/Tutorial.css`
3. `src/components/AdminPanel.css`

**Read files**: corresponding JSX files

**Plan**: AI panel to M3 surface-container + elevation 3. Chat bubbles: primary-container (user), surface-container-highest (AI). Tutorial tooltip to M3 surface + M3 button variants. Admin panel to M3 dialog body, stat cards as M3 surface-container-low. All status colors to M3 semantic tokens.

**Depends on**: Story 7

---

### Story 16: EmptyStateOverlay + ResizeTooltip Inline Colors
**Agent**: quick-fixer | **Model**: haiku | **Trivial**: yes

**Write files**:
1. `src/components/EmptyStateOverlay.jsx` (replace hardcoded inline colors with M3 CSS vars)
2. `src/components/ResizeTooltip.jsx` (minimal -- inherits error-tooltip from App.css)

**Read files**: both JSX files

**Plan**: Replace inline style hardcoded colors (arrowColor, labelColor, GHOST_FAB_STYLE) with `var()` references to M3 tokens.

**Depends on**: Story 7

---

### Story 17: Final Audit + Compat Cleanup + CLAUDE.md Update
**Agent**: architect | **Model**: sonnet | **Trivial**: no

**Write files**:
1. `src/App.css` (remove any remaining old token references)
2. `src/styles/compat.css` (thin down or remove aliases no longer needed)
3. `CLAUDE.md` (add M3 design mandate section)

**Read files**: all CSS files (audit pass)

**Plan**: Audit all CSS files for: remaining hardcoded colors, non-tokenized border-radii, non-tokenized font-sizes, missing state layers, missing reduced-motion guards. Update compat.css. Add "Design System" section to CLAUDE.md mandating M3 adherence.

**Depends on**: All previous stories

---

## Dependency Graph

```
Stories 1,2,3 (tokens) -- parallel
       |
       v
    Story 4 (compat + wiring)
       |
       +--------+--------+
       v        v        v
    Story 5   Story 7   (wait)
    (prefs)   (global)
       |        |
       v        +---> Stories 8,9,10,11,12,13,14,15,16 (component CSS -- many parallel)
    Story 6           |
    (settings UI)     v
                   Story 17 (audit + CLAUDE.md)
```

Stories 8-16 can run in parallel groups (respecting write-file overlap on App.css):
- **Parallel group A**: Stories 8, 9, 14, 15, 16 (no App.css overlap between them after Story 8 carves out header-only)
- **Parallel group B** (after A): Stories 10, 11, 12, 13 (some depend on patterns from A)
- Story 17 runs last

---

## CLAUDE.md Addition (Story 17)

Add this section to the project CLAUDE.md:

```markdown
## Design System -- Material Design 3

All DOM-based UI must follow Material Design 3 specifications unless the user explicitly requests otherwise.

### Token usage
- Colors: use `--md-sys-color-*` tokens. Never hardcode hex values for UI colors.
- Typography: use `--md-sys-typescale-*` tokens. Never hardcode font-size/weight/line-height.
- Elevation: use `--md-sys-elevation-*` for shadows. 6 levels (0-5).
- Shape: use `--md-sys-shape-corner-*` for border-radius. Never hardcode px values.
- Spacing: use `--md-sys-spacing-*` (4px grid). Never hardcode padding/margin values.
- Motion: use `--md-sys-motion-*` for transitions. All animations must respect reduced-motion.
- State layers: all interactive elements must have hover (8%), focus (12%), pressed (12%) state layers.

### Theme system
- 6 themes: indigo, teal, rose, amber, violet, sage. Each has light + dark variant.
- Applied via `data-theme-color` and `data-theme` attributes on `<html>`.
- Accessibility: `data-high-contrast`, `data-reduced-motion`, `data-large-text` attributes.
- Preferences stored in Firestore `users/{uid}.preferences`.

### What M3 does NOT apply to
- Konva canvas components (BoardCanvas, StickyNote, Frame, Shape, LineShape, Cursors) -- these render to canvas, not DOM.
- Object colors chosen by users (sticky note colors, shape fills) -- these are user content, not UI chrome.
```

---

## Verification

1. **Visual**: After Story 4, the app should look identical (compat layer preserves old appearance). After Stories 7-16, all UI matches M3 specs.
2. **Themes**: After Stories 5+6, clicking theme swatches in Appearance Settings should switch the entire UI palette. Verify all 12 variants (6 themes x light/dark).
3. **Accessibility**: Toggle high contrast -- text contrast ratios should meet WCAG AAA (7:1). Toggle large text -- all UI text scales up ~20%. Toggle reduced motion -- no animations or transitions play.
4. **Persistence**: Change theme, refresh page -- preference persists. Sign in on different browser -- Firestore syncs preferences.
5. **Build**: `npm run build` passes after each story.
6. **Tests**: Run `npx vitest --run` after stories touching protected testable files.
7. **Protected files**: Verify no changes to BoardCanvas.jsx, StickyNote.jsx, Frame.jsx, Shape.jsx, LineShape.jsx, Cursors.jsx.
