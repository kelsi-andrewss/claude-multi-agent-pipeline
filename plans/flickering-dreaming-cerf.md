# Plan: Ghost-Placement Agreement Tests (+ Fix Stagger Bug)

## Context
The ghost placement bug persists. The existing tests only verify that `onPendingToolPlace` is *invoked* — they don't assert the placed position matches the ghost position. Additionally, `stageHandlers.js` applies a stagger offset (`canvasX + count * 20`) on repeated clicks, which intentionally moves the placed object AWAY from the cursor. This is the bug: the ghost stays at cursor but the object lands elsewhere.

## Root Cause
`src/handlers/stageHandlers.js`, line 55:
```js
onPendingToolPlace(pendingToolRef.current, canvasX + count * 20, canvasY + count * 20);
```
The `+ count * 20` stagger means every click after the first places the object offset from the cursor. The ghost doesn't stagger — it stays under the cursor. This is the source of the mismatch.

## Changes Required

### 1. Fix `src/handlers/stageHandlers.js`
Remove the stagger offset. Pass cursor coordinates directly:
```js
onPendingToolPlace(pendingToolRef.current, canvasX, canvasY);
```
The `pendingToolCount` / `pendingToolCountRef` machinery in App.jsx can stay — it's used for counting placed objects but should not offset placement coordinates.

### 2. Add strict tests to `src/handlers/stageHandlers.test.js`
Add a new describe block that:
- Simulates mousemove (computes ghost position using the same math as `BoardCanvas.handleMouseMoveWrapped`)
- Simulates click (calls `handleStageClick` and captures what `onPendingToolPlace` receives)
- Asserts ghost position === placed position
- Repeats with a different mouse position (move, then click again)
- Covers all tool types: sticky, line, arrow, text, frame, default shape

The tests must **fail before the stagger fix** and **pass after**.

## Files to Modify

1. **`src/handlers/stageHandlers.js`** — remove stagger offset (1 line change)
2. **`src/handlers/stageHandlers.test.js`** — add new describe block

Do NOT modify any other files.

## Test Design

### New describe block: `'ghost-placement agreement — click, move, click'`

**Imports to add at top of test file:**
```js
import { centeredPlacementOffset } from '../utils/geometryUtils.js';
```

**Ghost position helper** (mirrors `BoardCanvas.handleMouseMoveWrapped` logic):
```js
function ghostPos(toolType, canvasX, canvasY, stageScale) {
  if (toolType === 'sticky') {
    const off = centeredPlacementOffset(canvasX, canvasY, 200, stageScale);
    return { x: off.x, y: off.y };
  }
  if (toolType === 'line' || toolType === 'arrow' || toolType === 'text') {
    return { x: canvasX, y: canvasY };
  }
  if (toolType === 'frame') {
    const fw = Math.round(window.innerWidth * 0.55 / stageScale);
    const fh = Math.round((window.innerHeight - 60) * 0.55 / stageScale);
    return { x: canvasX - fw / 2, y: canvasY - fh / 2 };
  }
  // default shape
  return { x: canvasX - 50, y: canvasY - 50 };
}
```

**Fake stage factory** (reuse pattern from existing tests):
```js
function makeFakeStage(canvasPos) {
  return {
    getRelativePointerPosition: () => canvasPos,
    getPointerPosition: () => canvasPos,
    x: () => 0, y: () => 0,
    scaleX: () => 1, scaleY: () => 1,
    name: () => 'bg-rect',
    getStage() { return this; },
  };
}
```

### Test cases to include

**sticky at scale 1.0 — initial click**
- canvasPos = `{ x: 300, y: 400 }`, `stageScale = 1.0`, count = 0
- Ghost: `ghostPos('sticky', 300, 400, 1.0)`
- Click: `handleStageClick` → capture `onPendingToolPlace` args → compute expected placed pos from same math
- Assert placed x === ghost x, placed y === ghost y

**sticky at scale 0.75 — initial click (fractional zoom)**
- canvasPos = `{ x: 333, y: 777 }`, `stageScale = 0.75`
- Same assertion pattern

**sticky — move then click again (the core regression test)**
- Click 1: canvasPos = `{ x: 100, y: 200 }`, count = 0 → assert placement matches ghost
- Move to: canvasPos = `{ x: 500, y: 600 }` (simulate move by changing fakeStage's return value)
- Click 2: same fakeStage now returns `{ x: 500, y: 600 }`, count = 1
- Assert placed position matches ghost position at `{ x: 500, y: 600 }` — NOT at `{ x: 520, y: 620 }` (which would be the stagger bug)
- This test FAILS before the stagger fix and PASSES after

**line at scale 1.0**
- canvasPos = `{ x: 200, y: 300 }`, stageScale = 1.0
- Ghost: `{ x: 200, y: 300 }` (no centering for lines)
- Assert placed x/y equals cursor exactly

**default shape (rectangle) at scale 1.5**
- canvasPos = `{ x: 100, y: 100 }`, stageScale = 1.5
- Ghost: `{ x: 50, y: 50 }` (fixed 50px offset)
- Assert placed x/y = `{ x: 50, y: 50 }`

**frame at scale 0.5 (with stubbed window)**
- `vi.stubGlobal('innerWidth', 1440)`, `vi.stubGlobal('innerHeight', 900)`
- `fw = Math.round(1440 * 0.55 / 0.5)`, `fh = Math.round(840 * 0.55 / 0.5)`
- canvasPos = `{ x: 400, y: 300 }`
- Ghost: `{ x: 400 - fw/2, y: 300 - fh/2 }`
- Assert placed matches ghost

**afterEach**: `vi.unstubAllGlobals()`

### Pattern for "placed position" assertion

Since `onPendingToolPlace` is a spy that just captures `(toolType, canvasX, canvasY)`, the test must compute expected placed position from the captured coords:

```js
const spy = vi.fn();
const cfg = makeConfig({ pendingToolRef: { current: 'sticky' }, pendingToolCountRef: { current: 0 }, onPendingToolPlace: spy });
const { handleStageClick } = makeStageHandlers(cfg);

handleStageClick({ target: makeFakeStage({ x: 300, y: 400 }) });

const [toolType, placedX, placedY] = spy.mock.calls[0];
const expectedGhost = ghostPos(toolType, 300, 400, 1.0);
// Ghost uses centeredPlacementOffset to get final object position:
const expectedPlaced = centeredPlacementOffset(placedX, placedY, 200, 1.0);
expect(expectedPlaced.x).toBe(expectedGhost.x);
expect(expectedPlaced.y).toBe(expectedGhost.y);
```

For line/text/frame/shape: the spy captures `(toolType, canvasX, canvasY)`. The placed object position IS `(canvasX, canvasY)` or `(canvasX - 50, canvasY - 50)`. Assert those match `ghostPos(...)`.

## Protected Files
IMPORTANT: Do NOT edit any of these protected files: BoardCanvas.jsx, StickyNote.jsx, Frame.jsx, Shape.jsx, LineShape.jsx, Cursors.jsx.

`stageHandlers.js` is a protected testable file — editing it sets `needsTesting: true`.

## Verification
```
npm test -- --reporter=verbose src/handlers/stageHandlers.test.js
```
All new tests pass. Existing tests pass. The "move then click again" regression test fails before the stagger line is removed and passes after.
