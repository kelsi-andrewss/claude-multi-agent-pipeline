# Plan: Frame Interaction Fixes (3 bugs)

## Context
Three related frame interaction bugs:
1. **Frame overlays children on click** — the transparent `hitRectRef` Rect in Frame.jsx covers the full frame body with `listening={true}`, so clicking any child object (sticky, shape) always hits the frame first and selects it instead of the child.
2. **Tool placement blocked by frame** — `handleStageClick` only fires `onPendingToolPlace` when `e.target === stage || e.target.name() === 'bg-rect'`. Clicking inside a frame while a tool is active hits the frame's Group, so the tool never places. The `onPendingToolPlace` in App.jsx already has correct post-placement frame assignment logic — it just never gets called.
3. **No hover highlight when tool is active** — the frame's drag `+` overlay only shows when `dragState.overFrameId === id && dragState.action`. There's no hover tracking for the "about to place here" state.

## Files to Modify

| File | Protected? |
|------|-----------|
| `src/components/Frame.jsx` | YES — needs explicit user permission |
| `src/handlers/stageHandlers.js` | YES (protected testable) |
| `src/components/BoardCanvas.jsx` | YES — needs explicit user permission |

**Note**: All three files are protected. User has requested these fixes — that constitutes explicit permission for this session.

---

## Fix 1: Frame body stops intercepting child clicks

**File**: `src/components/Frame.jsx`, line 78–94

The transparent hit Rect covers `width × height` and intercepts every click inside the frame. The fix: make the hit Rect cover **only the title bar** (top 48px), so clicks on the body pass through to children.

```jsx
// BEFORE (line 78–94)
<Rect
  ref={hitRectRef}
  width={width}
  height={height}
  fill="transparent"
  listening={true}
  onDblClick={...}
  onDblTap={...}
/>

// AFTER — title bar only
<Rect
  ref={hitRectRef}
  width={width}
  height={titleBarHeight}   // ← 48px only, not full height
  fill="transparent"
  listening={true}
  onDblClick={...}
  onDblTap={...}
/>
```

Also move the `onClick`/`onTap` handlers from the Group (lines 52–59) to the hit Rect, so they fire only when the title bar is clicked — not when children are clicked:

```jsx
// Remove onClick/onTap from the <Group> (lines 52–59)
// Add them to the hit Rect instead:
<Rect
  ref={hitRectRef}
  width={width}
  height={titleBarHeight}
  fill="transparent"
  listening={true}
  onClick={(e) => { e.cancelBubble = true; onSelect(id); }}
  onTap={(e) => { e.cancelBubble = true; onSelect(id); }}
  onDblClick={(e) => { ... onAutoFit ... }}
  onDblTap={(e) => { ... onAutoFit ... }}
/>
```

The `hitRectRef` imperative resize calls in `onTransformEnd` (lines 311–314, 349) also need to update height. Change those to update `width` only (height is now always `titleBarHeight = 48`, constant). Actually simpler: leave `hitRectRef.current.width(finalW)` calls as-is and just don't call `hitRectRef.current.height(...)` — or set it to `titleBarHeight`. Either works; keep it consistent.

---

## Fix 2: Tool placement fires even when clicking inside a frame

**File**: `src/handlers/stageHandlers.js`, lines 49–107

The condition `e.target === stage || e.target.name() === 'bg-rect'` blocks tool placement when the click lands on a frame's Konva elements. When a `pendingTool` is active, we should allow placement regardless of what was hit.

```js
// BEFORE (line 49–50)
const handleStageClick = (e) => {
  if (e.target === e.target.getStage() || e.target.name() === 'bg-rect') {

// AFTER — also allow when pendingTool is active
const handleStageClick = (e) => {
  const tool = pendingToolRef?.current;
  const isBackground = e.target === e.target.getStage() || e.target.name() === 'bg-rect';
  if (isBackground || tool) {
```

Then inside, keep the existing logic unchanged — `tool === 'line'/'arrow'` paths and `onPendingToolPlace` call are all correct. The only change is the outer gate.

**Edge case**: When a tool is active and the user clicks on an *object* (not a frame), we should still place — the existing `onPendingToolPlace` already handles frame assignment via `findOverlappingFrame`. We do NOT want tool clicks to also trigger selection. The `return` after `onPendingToolPlace` already prevents that.

**Line/arrow exception**: Lines and arrows use connector snapping (`findSnapTarget`) which intentionally clicks on objects — this path is fine because `pendingToolRef.current === 'line'/'arrow'` and those tools already handle their own click flow inside the existing block.

---

## Fix 3: Show "+" hover highlight when tool is active over a frame

**File**: `src/components/BoardCanvas.jsx` — `handleMouseMoveWrapped` or a new `onMouseMove` on Stage

**File**: `src/components/Frame.jsx` — render the `+` overlay when `toolHoverFrameId === id`

### State
Add to `BoardCanvas.jsx` (or pass from App.jsx):
```js
const [toolHoverFrameId, setToolHoverFrameId] = useState(null);
```

### Mouse move detection
In `BoardCanvas.jsx`, in the existing `handleMouseMoveWrapped` (line 519 area), when `pendingTool` is active (and not 'line'/'arrow'/'frame'), use `findFrameAtPoint` to find if cursor is over a frame:

```js
// Inside handleMouseMoveWrapped, after updating cursor presence:
if (pendingTool && pendingTool !== 'line' && pendingTool !== 'arrow' && pendingTool !== 'frame') {
  const stage = e.target.getStage();
  const pointer = stage.getPointerPosition();
  if (pointer) {
    const canvasX = (pointer.x - stagePos.x) / stageScale;
    const canvasY = (pointer.y - stagePos.y) / stageScale;
    const overFrame = findFrameAtPoint(canvasX, canvasY, objects);
    setToolHoverFrameId(overFrame ? overFrame.id : null);
  }
} else {
  setToolHoverFrameId(null);
}
```

`findFrameAtPoint` is already imported in `objectHandlers.js`; import it in `BoardCanvas.jsx` from `../utils/frameUtils.js`.

### Pass to Frame
Pass `toolHoverFrameId` as a prop to `<Frame>` (alongside the existing `dragState` prop, line 691).

### Render in Frame.jsx
In the overlay block (lines 231–264), add a third condition:

```jsx
const showToolHover = pendingTool && pendingTool !== 'line' && pendingTool !== 'arrow'
  && toolHoverFrameId === id;
if (!showIllegal && !showAction && !showToolHover) return null;
```

When `showToolHover` is true, render the same green overlay + `+` text as `action === 'add'`.

Frame component already receives `pendingTool` (line 702 in BoardCanvas.jsx). Add `toolHoverFrameId` prop.

---

## Verification
1. Click a sticky inside a frame — sticky is selected, not the frame
2. Click the frame's title bar — frame is selected
3. With sticky tool active, click inside a frame — sticky is placed and assigned to that frame
4. With sticky tool active, hover over a frame — green `+` overlay appears
5. `npx vitest related --run src/handlers/stageHandlers.js` passes
6. `npm run build` passes
