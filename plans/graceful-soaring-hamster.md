# Chip Toolbar Polish — Grip, Orientation, Split Buttons, Fixed Chips

## Context

Post-implementation polish on the floating chip toolbar (epic-003, stories 015–020 complete). Several UX issues remain:
1. Grip dots use wrong character (&#10815; instead of braille ⠿ U+28FF)
2. Orient arrow button (↔) should be removed — orientation toggles via double-click on grip instead
3. Split buttons (tool buttons with color-picker arrows) look like two separate outlined buttons — should be borderless with only a divider line between main and arrow
4. Padding between buttons and icons creates visual disparity — needs tightening
5. Identity chip (logo + board switcher) has drag/orient wired but should be fixed-position with a 2-position toggle (top-left ↔ bottom-left)
6. Right chip (presence + user menu) has free drag wired but should be fixed-position with a 2-position toggle (top-right ↔ bottom-right)
7. Tools chip is the only freely draggable one — keeps grip dots + double-click-to-orient
8. Vertical width of chips should match horizontal height (consistent cross-axis dimension)

---

## Chip Behavior Summary

| Chip | Drag | Orientation | Toggle mechanism |
|------|------|-------------|-----------------|
| **Identity** (logo + board switcher) | Fixed — 2 positions (top-left / bottom-left) | Horizontal only (no orient) | Corner-cycle button |
| **Tools** (creation tools + zoom) | Free drag, edge-snap | Horizontal ↔ Vertical | Double-click grip dots |
| **Right** (presence + user menu) | Fixed — 2 positions (top-right / bottom-right) | Horizontal ↔ Vertical | Corner-cycle button (also toggles orient when switching top↔bottom) |

---

## Files to Modify

- `src/hooks/useDraggableFloat.js` — add `onDoubleClick` to returned dragHandleProps; add support for `fixedPositions` mode (2-position cycle, no free drag)
- `src/components/HeaderLeft.jsx` — identity chip: remove drag wiring, add corner-cycle button; tools chip: remove orient button, add `onDoubleClick` to grip; fix padding
- `src/components/HeaderRight.jsx` — remove drag wiring, add corner-cycle button + double-click orient on grip
- `src/App.css` — remove `.chip-orient-btn` rules; add `.chip-corner-btn` for the 2-position toggle; fix vertical chip cross-axis width; fix `.tool-split-button` border removal
- `src/components/BoardSwitcher.css` — remove borders from `.tool-split-button button` (all borders gone, only divider line kept); tighten padding on tool buttons

---

## Implementation Plan

### 1. `useDraggableFloat.js` changes

Current signature: `useDraggableFloat(storageKey, defaultPos)` → `{ pos, orientation, toggleOrientation, dragHandleProps: { onMouseDown, ref } }`

**New behavior — two modes:**

**Mode A: Free drag (tools chip)** — existing behavior, plus:
- Add `onDoubleClick` handler to `dragHandleProps` that calls `toggleOrientation`
- Remove `toggleOrientation` from the returned object (no longer needed externally — invoked via double-click on grip)
- Keep `orientation` in return for `data-orient` attribute

**Mode B: Fixed positions (identity + right chips)** — triggered by passing `fixedPositions` array instead of `defaultPos`:
```js
useDraggableFloat('toolbar-left-identity', null, {
  fixedPositions: [
    { x: 16, y: 16 },          // top-left
    { x: 16, yFromBottom: 16 } // bottom-left — computed as window.innerHeight - chipHeight - 16
  ]
})
```
- No mousedown/drag listeners
- `posIndex` state (0 or 1) persisted to `localStorage[storageKey + '-pin']`
- `cyclePosition()` function returned instead of `dragHandleProps`
- Position computed from `fixedPositions[posIndex]`, with `yFromBottom` resolved at render time via `window.innerHeight`
- `dragHandleProps` returned as `null` in this mode

**Signature change:**
```js
// Free drag (tools chip):
const { pos, orientation, dragHandleProps } = useDraggableFloat('toolbar-left-tools', { x: 16, y: 72 })
// dragHandleProps.onDoubleClick = toggleOrientation

// Fixed positions (identity + right):
const { pos, orientation, cyclePosition } = useDraggableFloat('toolbar-left-identity', null, {
  fixedPositions: [{ x: 16, y: 16 }, { x: 16, yFromBottom: 16 }],
  orientations: ['horizontal'] // optional — locks orientation if provided as single-item array
})
```

**Right chip orientation**: when right chip cycles from top-right to bottom-right, orientation doesn't auto-change. User double-clicks grip to toggle orient separately (same double-click pattern as tools chip, but on the corner-cycle grip element).

### 2. `HeaderLeft.jsx` changes

**Identity chip:**
- Remove `useDraggableFloat` free-drag wiring (dragHandleProps, onMouseDown)
- Wire `useDraggableFloat('toolbar-left-identity', null, { fixedPositions: [{x:16,y:16},{x:16,yFromBottom:16}], orientations:['horizontal'] })`
- Replace `<span className="chip-grip" onMouseDown={...}>` with `<button className="chip-corner-btn" onClick={cyclePosition}>` (corner-pin icon, e.g. ⊡ or a small arrow)
- Remove `<button className="chip-orient-btn">` (no orientation toggle on identity chip)
- Remove `data-orient` attribute (always horizontal)

**Tools chip:**
- Keep `useDraggableFloat('toolbar-left-tools', { x: 16, y: 72 })` free drag
- Add `onDoubleClick={dragHandleProps.onDoubleClick}` to the `<span className="chip-grip">`
- Remove `<button className="chip-orient-btn">` (orient now via double-click grip)
- Keep `data-orient={orientation}`
- Tighten padding: tool split buttons currently have `padding: spacing-sm spacing-md` on inner buttons → reduce to `padding: spacing-xs spacing-sm`

### 3. `HeaderRight.jsx` changes

- Wire `useDraggableFloat('toolbar-right', null, { fixedPositions: [{xFromRight:16,y:16},{xFromRight:16,yFromBottom:16}] })`
  - `xFromRight` computed as `window.innerWidth - chipWidth - 16` at render; `chipWidth` read from `ref.current.offsetWidth`
  - Default CSS fallback: `right: 16px; top: 16px` when pos is null (first load before pin is saved)
- Remove free-drag `onMouseDown` from grip
- Replace `<span className="chip-grip" onMouseDown={...}>` with a grip element that has both:
  - `onDoubleClick={toggleOrientation}` (toggle horizontal/vertical)
  - `onClick={cyclePosition}` (cycle top/bottom on right side)
  - Or: separate `<button className="chip-corner-btn">` for position cycle + grip dots with double-click for orient
- Remove `<button className="chip-orient-btn">` (orient via double-click)
- Keep `data-orient={orientation}`

**Clarification on right chip grip**: Use the same grip dots element for double-click-to-orient, and a separate small corner-cycle button — same pattern as identity chip but with orient also available.

### 4. `App.css` changes

**Remove:**
- `.chip-orient-btn` and `.chip-orient-btn:hover` rules entirely

**Add:**
```css
.chip-corner-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  background: transparent;
  border: none;
  cursor: pointer;
  color: var(--md-sys-color-outline-variant);
  border-radius: var(--md-sys-shape-corner-extra-small);
  padding: 0;
  font-size: 12px;
}
.chip-corner-btn:hover { color: var(--md-sys-color-on-surface); }
```

**Grip dots character fix:**
- In the CSS `content` or in JSX: change `&#10815;` (U+2A3F) to `&#10495;` (U+28FF, ⠿ braille dots-12345678)

**Vertical width fix:**
- Current: `.floating-toolbar-chip[data-orient="vertical"]` has no explicit width constraint — chips expand to content width
- Add `min-width` matching the horizontal height (approx 44px — the chip's height in horizontal mode):
  ```css
  .floating-toolbar-chip[data-orient="vertical"] {
    /* existing: flex-direction: column; align-items: stretch; */
    width: 52px; /* matches horizontal chip height including padding */
  }
  ```
- Buttons in vertical mode need `justify-content: center` since they'll be in a narrow column

**Tools chip orient-button vertical mode**: the orient-btn at end of chip in vertical mode stacks at bottom — this is removed, so no change needed.

### 5. `BoardSwitcher.css` changes

**Split button border removal** (tool buttons with dropdown arrows):

Current `.tool-split-button button`:
```css
border: 1px solid var(--md-sys-color-outline-variant);
border-radius: var(--md-sys-shape-corner-extra-small);
```

Change to:
```css
border: none;
border-radius: 0;
```

`.tool-split-button .dropdown-arrow` still keeps its left border divider (that's the only visual separator between main and arrow):
```css
border-left: 1px solid var(--md-sys-color-outline-variant);
```
This stays as-is.

**Padding tightening:**
- `.tool-split-button button`: change `padding: var(--md-sys-spacing-sm) var(--md-sys-spacing-md)` → `padding: var(--md-sys-spacing-xs) var(--md-sys-spacing-sm)`
- Height can stay at `40px` to maintain touch targets

---

## Stories Required (new stories for epic-003)

**story-021**: `useDraggableFloat` — double-click orient + fixed-positions mode
- Files: `src/hooks/useDraggableFloat.js`
- Agent: quick-fixer
- needsTesting: false (hook has no existing test; new behavior matches existing pattern)

**story-022**: Identity chip → fixed 2-position, remove orient; Tools chip → double-click grip orient, remove orient button
- Files: `src/components/HeaderLeft.jsx`
- Agent: quick-fixer
- Depends on: story-021

**story-023**: Right chip → fixed 2-position, double-click grip orient, remove orient button
- Files: `src/components/HeaderRight.jsx`
- Agent: quick-fixer
- Depends on: story-021

**story-024**: CSS — remove chip-orient-btn, add chip-corner-btn, fix vertical width, fix grip char; remove split-button borders, tighten padding
- Files: `src/App.css`, `src/components/BoardSwitcher.css`
- Agent: quick-fixer
- Trivial: yes (CSS only, no JS)
- Can run in parallel with story-021

Stories 021 and 024 run in parallel. Stories 022 and 023 run in parallel after 021 (and 024) complete.

---

## Pitfalls

- **`yFromBottom` / `xFromRight` computation**: Must be done inside a `useEffect` or computed at render time using `ref.current` — not at hook init time when DOM hasn't mounted. Prefer computing at `cyclePosition` call time using `ref.current.offsetWidth/offsetHeight`.
- **Right chip CSS default**: When `pos` is null (first render before any pin is stored), use CSS `right: 16; top: 16` — same pattern as current. After first `cyclePosition` call, switch to computed `{ left, top }` absolute position.
- **Double-click vs drag conflict**: `onDoubleClick` on the grip element fires after two clicks; `onMouseDown` starts drag after movement. No conflict because drag requires `mousemove` after `mousedown` — a stationary double-click won't trigger drag movement. Still, call `e.preventDefault()` in `onDoubleClick` to prevent text selection.
- **Vertical chip width**: The `width: 52px` on vertical chips must match the actual rendered height of the horizontal chip. Inspect and adjust if needed; using a CSS variable `--chip-cross-axis: 52px` shared by both would be clean.
- **Identity chip always horizontal**: Pass `orientations: ['horizontal']` or simply don't wire `orientation`/`data-orient` at all — leave `data-orient` unset, which defaults to horizontal CSS.
- **Removing chip-orient-btn from JSX**: Both HeaderLeft and HeaderRight currently render this button. Must remove from JSX in the same story as the CSS removal (stories 022/023) — or the button will be invisible but still in the DOM.

---

## Verification

1. Identity chip: fixed at top-left. Click corner-cycle button → moves to bottom-left. Reload → persists.
2. Tools chip: draggable freely. Drag to edge → snaps. Double-click grip → switches horizontal/vertical. Reload → persists both position and orientation.
3. Right chip: fixed at top-right. Click corner-cycle button → moves to bottom-right. Double-click grip → switches horizontal/vertical. Reload → persists.
4. Tool split buttons (sticky, shape, etc.): no outer border, only vertical divider line between icon and arrow.
5. Vertical tools chip: width matches horizontal chip height (~52px).
6. Grip dots: render as ⠿ (braille U+28FF), not the previous character.
7. No orient arrow button visible on any chip.
8. `npm run build` passes with no errors.
