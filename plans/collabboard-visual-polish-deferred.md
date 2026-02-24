# CollabBoard — Visual Polish (Deferred)

> These todos are ready to implement but saved for a later pass.
> They depend on Todos 13–15 (unified shell, group pages, routing) being done first.

---

## Todo 16: Home Page Visual Polish

### Context

The board selector is functional but visually flat — solid neutral backgrounds, generic `Layout` placeholder icon, abrupt hover effects, and no visual hierarchy between group labels and board cards. This todo applies a subtle polish pass using the existing indigo accent and dark theme as the foundation. No redesign — just quality improvements.

### Changes

#### 1. Board Card Preview — Indigo Gradient
Replace the flat `bg-tertiary` + `Layout` icon with a soft indigo gradient and a faint canvas icon:

```css
.board-card-preview {
  height: 120px;
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
  /* dark mode: linear-gradient(135deg, #3730a3 0%, #6d28d9 100%) */
  display: flex;
  align-items: center;
  justify-content: center;
  color: rgba(255, 255, 255, 0.3);  /* faint icon */
}
```

The `Layout` icon stays but at reduced opacity — present but not the focus.

#### 2. Board Card Hover — Indigo Glow Instead of Hard Border Flash
```css
/* Before: */
.board-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3);
  border-color: var(--accent-primary);
}

/* After: */
.board-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 8px 25px -4px rgba(79, 70, 229, 0.35);
  border-color: transparent;
}
```

Subtle indigo glow on hover instead of a border color jump. Feels more premium.

#### 3. Group Title — Bolder, More Readable
```css
/* Before: */
.group-title {
  font-size: 1.25rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-secondary);
}

/* After: */
.group-title {
  font-size: 1rem;
  font-weight: 700;
  text-transform: none;
  letter-spacing: 0;
  color: var(--text-primary);
}
```

Less "spreadsheet column header", more legible section title.

#### 4. Timestamp as Subtle Badge
Wrap the "Updated X ago" text in a small chip-style span:
```css
.board-card-date {
  font-size: 0.72rem;
  color: var(--text-tertiary);
  background: var(--bg-tertiary);
  padding: 2px 7px;
  border-radius: 999px;
}
```

#### 5. Create Board FAB — Resize to 56px
The create board FAB is 70px while all other FABs are 56px. Align it:
```css
.create-board-fab {
  width: 56px;
  height: 56px;
  border-radius: 28px;
}
```

#### 6. Empty State — More Generous Treatment
```css
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 60px 20px;
  color: var(--text-tertiary);
}
.empty-state-icon {
  width: 64px; height: 64px;
  background: linear-gradient(135deg, rgba(79,70,229,0.15), rgba(124,58,237,0.15));
  border-radius: 16px;
  display: flex; align-items: center; justify-content: center;
  color: var(--accent-primary);
}
```

Icon gets a soft indigo tinted background pill. Heading bumped to `1rem` bold, subtext stays muted.

### Files to Modify

| File | Change |
|---|---|
| `src/App.css` | Update `.board-card-preview`, `.board-card:hover`, `.group-title`, `.create-board-fab`, `.empty-state`; add `.board-card-date` |
| `src/components/BoardSelector.jsx` | Wrap timestamp in `<span className="board-card-date">`; add `empty-state-icon` wrapper in empty state |

### Verification
1. Board cards show indigo gradient preview area
2. Hovering a card shows a soft indigo glow (no hard border flash)
3. Group titles are bold and full-size (not all-caps muted)
4. Timestamps appear as small rounded chips
5. Create board FAB matches the 56px size of other FABs
6. Empty state has a tinted icon container and better typography
7. All changes look correct in both light and dark mode

---

## Todo 17: Modernize Login Screen

### Context

The current login is a bare centered div — plain `bg-secondary` background, 3rem title (moves to header in Todo 13), a subtitle line, and an unstyled indigo button. After Todo 13 the header handles the logo, so the content area needs a focused, polished sign-in card that feels like it belongs to the same app as the board selector.

**Target:** A centered card with an indigo gradient accent at the top (matching board card previews from Todo 16), a clear heading, subtitle, and a well-styled Google sign-in button with the Google logo icon.

```
┌─────────────────────────────────┐
│  ▓▓▓▓ indigo gradient band ▓▓▓▓ │  ← same gradient as board card previews
├─────────────────────────────────┤
│                                 │
│   Welcome to CollabBoard        │  ← bold heading
│   Real-time collaborative       │  ← muted subtitle
│   whiteboard with AI            │
│                                 │
│   [G]  Sign in with Google  →   │  ← styled button
│                                 │
└─────────────────────────────────┘
```

### Files to Modify

| File | Change |
|---|---|
| `src/App.jsx` | Replace `.login-container` with `.login-content` wrapping a `.login-card` |
| `src/App.css` | Replace `.login-container` styles; add `.login-content`, `.login-card`, `.login-card-banner`, `.login-google-btn` |

### Detailed Changes

**`App.jsx`** — new login JSX (rendered as content below the persistent header, per Todo 13):
```jsx
<div className="login-content">
  <div className="login-card">
    <div className="login-card-banner" />
    <div className="login-card-body">
      <h2>Welcome to CollabBoard</h2>
      <p>Real-time collaborative whiteboard with AI</p>
      <button className="login-google-btn" onClick={login}>
        <img src="https://www.google.com/favicon.ico" width={18} height={18} alt="" />
        Sign in with Google
      </button>
    </div>
  </div>
</div>
```

**`App.css`** — new styles:
```css
.login-content {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary);
}

.login-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  overflow: hidden;
  width: 100%;
  max-width: 380px;
  box-shadow: 0 20px 40px -8px rgba(0, 0, 0, 0.2);
}

.login-card-banner {
  height: 100px;
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
  /* dark mode: linear-gradient(135deg, #3730a3 0%, #6d28d9 100%) — same as board card */
}

.login-card-body {
  padding: 32px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.login-card-body h2 {
  margin: 0;
  font-size: 1.4rem;
  font-weight: 700;
  color: var(--text-primary);
}

.login-card-body p {
  margin: 0;
  font-size: 0.9rem;
  color: var(--text-tertiary);
  line-height: 1.5;
}

.login-google-btn {
  margin-top: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  width: 100%;
  padding: 11px 20px;
  background: var(--accent-primary);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s, transform 0.1s;
}

.login-google-btn:hover {
  background: var(--accent-hover);
  transform: translateY(-1px);
}
```

### Verification
1. Login screen shows the persistent header (logo + theme toggle) above the content
2. Content area shows a centered card with indigo gradient banner
3. Card has "Welcome to CollabBoard" heading, subtitle, and Google sign-in button
4. Button has the Google favicon icon alongside the label
5. Gradient banner matches the board card preview gradient from Todo 16
6. Card looks correct in both light and dark mode

---

## Todo 18: Modernize Board Group Page

### Context

The group page (`GroupPage.jsx`) is new from Todo 15, so it has no existing styles to fight against. It should feel like a natural middle tier between the home screen (group cards) and the canvas — sharing the same board card aesthetic from Todo 16 but with a cleaner page header that contextualises the group.

**Target layout:**
```
┌─ persistent header (Todo 13) ──────────────────────────┐
├────────────────────────────────────────────────────────┤
│  ← Back    [group icon]  Design Team    12 boards      │  ← group page header
│            ─────────────────────────────────────────── │
│  [search input]                                        │
├────────────────────────────────────────────────────────┤
│  [card] [card] [card] [card]                           │  ← same board card grid
│  [card] [card] ...                                     │     as home screen
└────────────────────────────────────────────────────────┘
```

### Changes

#### 1. Group Page Header Strip
A subtle strip below the persistent header with the group name, board count, and a back button. Uses the same indigo gradient as the card preview banners — but as a very low-opacity tint (`rgba(79,70,229,0.06)`) so it's a hint rather than a banner:

```css
.group-page-header {
  padding: 24px 40px 20px;
  border-bottom: 1px solid var(--border-color);
  background: linear-gradient(135deg, rgba(79,70,229,0.06) 0%, rgba(124,58,237,0.06) 100%);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.group-page-back {
  display: flex; align-items: center; gap: 6px;
  background: none; border: none; cursor: pointer;
  color: var(--text-tertiary); font-size: 0.85rem;
  padding: 0; margin-bottom: 8px;
  transition: color 0.15s;
}
.group-page-back:hover { color: var(--text-primary); }

.group-page-title {
  display: flex; align-items: center; gap: 12px;
  font-size: 1.5rem; font-weight: 700;
  color: var(--text-primary); margin: 0;
}

.group-page-count {
  font-size: 0.8rem; font-weight: 400;
  color: var(--text-tertiary);
  background: var(--bg-tertiary);
  padding: 2px 8px; border-radius: 999px;
}
```

#### 2. Search Bar
Same style as the home screen `.dashboard-search-input` — positioned below the group title, max-width 360px.

#### 3. Board Grid
Identical to the home screen `.boards-grid` — same card component, same hover glow from Todo 16, same indigo gradient preview. No visual distinction needed; consistency is the goal.

#### 4. Board Count Badge
Group name shown with a small rounded pill showing the board count — using the `.group-page-count` chip style above.

#### 5. AI FAB
Same as home screen (from Todo 14) — present in the bottom-right corner.

### Files to Modify / Create

| File | Change |
|---|---|
| `src/components/GroupPage.jsx` | **Create** (new from Todo 15) — implement with styles above |
| `src/App.css` | Add `.group-page-header`, `.group-page-back`, `.group-page-title`, `.group-page-count` |

### Verification
1. Group page has a subtle indigo-tinted header strip with back button, group name, and board count badge
2. Back button returns to home
3. Board grid matches home screen card style exactly (same gradient, same glow hover)
4. Search filters boards within the group
5. Looks correct in light and dark mode

---

## Todo 19: Modernize Board/Canvas Screen Chrome

### Context

The canvas screen chrome (header, FABs, AI panel, action bar) is functional but has a few rough edges: the AI panel has no open/close animation, shadow depths are inconsistent, the action bar floats without a background, and the FAB container in `FABButtons.jsx` uses inline styles instead of CSS. This todo applies a focused polish pass — no layout changes, just quality improvements.

### Changes

#### 1. AI Panel — Slide-in Animation
```css
.ai-panel {
  /* existing styles + */
  transform-origin: bottom right;
  animation: ai-panel-in 0.18s ease;
}

@keyframes ai-panel-in {
  from { opacity: 0; transform: translateY(8px) scale(0.97); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}
```

#### 2. AI Panel Header — Gradient Instead of Flat Indigo
```css
.ai-header {
  /* existing styles + */
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
}
```

#### 3. Standardise Shadow Depth
```css
/* Add to :root */
--shadow-sm: 0 4px 6px -1px rgba(0,0,0,0.12), 0 2px 4px -1px rgba(0,0,0,0.07);
--shadow-lg: 0 10px 25px -4px rgba(0,0,0,0.25), 0 4px 8px -2px rgba(0,0,0,0.1);
```

Apply `var(--shadow-sm)` to `.action-fab`, `.recenter-fab`, `.theme-fab`. Apply `var(--shadow-lg)` to `.ai-panel`, `.color-dropdown`, `.user-avatar-dropdown`.

#### 4. Action Bar Background
```css
.selected-actions {
  /* existing styles + */
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  box-shadow: var(--shadow-sm);
}
```

#### 5. FAB Container — Move Inline Styles to CSS
```css
.fab-cluster {
  position: absolute;
  bottom: 20px; right: 20px;
  display: flex; flex-direction: column;
  align-items: flex-end; gap: 6px;
}
```

Replace inline `style={{...}}` in `FABButtons.jsx` with `className="fab-cluster"`.

#### 6. Easing Upgrade
```css
transition: transform 0.15s cubic-bezier(0.34, 1.56, 0.64, 1), background 0.15s ease, box-shadow 0.15s ease;
```

### Files to Modify

| File | Change |
|---|---|
| `src/App.css` | Add `--shadow-sm`, `--shadow-lg` to `:root`; add `.ai-panel` animation; update `.ai-header`, `.selected-actions`, `.action-fab`, `.recenter-fab`, `.theme-fab`, `.ai-fab` transitions; add `.fab-cluster` |
| `src/components/FABButtons.jsx` | Replace inline style with `className="fab-cluster"` |

### Verification
1. AI panel slides up smoothly when opened
2. AI panel header shows indigo gradient matching board card previews
3. Action bar has a visible background container when an object is selected
4. FAB hover animations have a slight spring feel
5. Shadow depths feel consistent across panels and dropdowns
6. No layout changes — all elements remain in their current positions
