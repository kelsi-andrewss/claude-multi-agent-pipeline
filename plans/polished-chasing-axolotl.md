# CollabBoard: 7 New Features Implementation Plan

## Context

CollabBoard is a React 19 + Konva.js collaborative whiteboard with Firebase Firestore for persistence and Google Gemini 2.0 Flash for AI. The user requests 7 features: click-outside color picker close, transparent color history, line shape, resize+rotate on all objects, frames, AI move/resize/recolor, and AI grid generation.

## Files Overview

| File | Role |
|------|------|
| `src/App.jsx` | Main component - toolbar, canvas, color picker, state |
| `src/components/Shape.jsx` | Rectangle/circle/triangle rendering with Transformer |
| `src/components/StickyNote.jsx` | Sticky note rendering (rotation disabled currently) |
| `src/hooks/useAI.js` | Gemini AI integration with function-calling tools |
| `src/hooks/useBoard.js` | Firestore CRUD (`addObject`, `updateObject`, `deleteObject`) |
| `src/App.css` | Full styling with dark/light CSS variables |

---

## Feature 1: Color Picker - Click Outside to Close

**File:** `src/App.jsx`

- Add a `useEffect` that listens for document clicks when `showColorPicker` is non-null
- If click target is not inside a `.tool-split-button`, set `showColorPicker(null)`
- Use `setTimeout(0)` to avoid the opening click immediately closing it
- Also close on `Escape` key
- Add `onClick={e => e.stopPropagation()}` on `ColorPickerMenu` container to prevent native color dialog clicks from closing it

---

## Feature 2: Color History - Transparent Colors

**Files:** `src/App.jsx`, `src/App.css`

- Add `hexToRgba(hex, alpha)` and `parseColorForInput(colorStr)` helpers
- Extend `shapeColors` state to include `opacity` per shape type (default 1)
- Add opacity slider (range 0-1) to `ColorPickerMenu`
- When creating shapes, compose final color via `hexToRgba` when opacity < 1
- Store rgba strings in history alongside hex strings
- Add checkerboard background pattern on `.color-swatch` so transparent colors are visible

---

## Feature 3: Resize + Rotate Handles on All Objects

**Files:** `src/components/StickyNote.jsx`, `src/components/Shape.jsx`, `src/App.jsx`

**StickyNote.jsx:**
- Change `rotateEnabled={false}` to `rotateEnabled={true}`
- Add all 8 anchor points (currently corner-only)
- Accept `rotation` prop (default 0), apply to inner `<Rect>`
- Accept `onTransformEnd` prop
- Add `onTransformEnd` handler on `<Group>` that reads width/height/rotation from node, resets scale, persists via `onTransformEnd(id, {...})`

**Shape.jsx:**
- Accept `rotation` prop (default 0), apply to shape nodes
- Add `rotation: node.rotation()` to the existing `onTransformEnd` handler

**App.jsx:**
- Pass `onTransformEnd={board.updateObject}` to `<StickyNote>` (currently missing)

No Firestore migration needed - `updateObject` uses spread so new `rotation` field is handled automatically. Existing objects default to `rotation=0`.

---

## Feature 4: New Shape - Line Object

**New file:** `src/components/LineShape.jsx`
**Modified:** `src/App.jsx`, `src/hooks/useAI.js`

**LineShape.jsx** - New component following Shape.jsx patterns:
- Props: `id, x, y, points=[0,0,200,0], color, strokeWidth, rotation, isSelected, onSelect, onDragEnd, onTransformEnd, onDelete`
- Renders Konva `<Line>` inside a `<Group>` with `<Transformer>`
- `hitStrokeWidth={20}` for easier click targeting on thin lines
- On transform end: scale the points array, reset scale to 1, persist

**App.jsx:**
- Import `LineShape` and `Minus` icon from lucide-react
- Add `line` to `shapeColors` initial state
- Add `handleAddLine()` function
- Add toolbar button with color picker dropdown
- Add render case for `type === 'line'` in the object render loop

**useAI.js:**
- Add `"line"` to the `createShape` tool's type enum

**Firestore model:** `{ type: 'line', x, y, points: [0,0,200,0], color, strokeWidth, rotation, userId }`

---

## Feature 5: Frames

**New file:** `src/components/Frame.jsx`
**Modified:** `src/App.jsx`, `src/hooks/useAI.js`

**Frame.jsx** - Visual container with title:
- Dashed-border `<Rect>` for the frame body
- Semi-transparent title bar `<Rect>` at top (32px height)
- Editable `<Text>` for the title (double-click to edit, blur to save)
- Full Transformer support with rotation
- Min dimensions: 100x80

**App.jsx:**
- Import `Frame` component and `Frame as FrameIcon` from lucide-react
- Add `handleAddFrame()` - creates frame at center with 400x300 default size
- Add toolbar button for frame
- Sort objects in render loop: frames render first (behind all other objects) for z-ordering

**useAI.js:**
- Add `createFrame` tool declaration with `title, x, y, width, height, color` parameters
- Add execution handler calling `boardActions.addObject({ type: 'frame', ... })`

**Firestore model:** `{ type: 'frame', x, y, width, height, title, color, rotation, userId }`

---

## Feature 6: AI Controls - Move, Resize, Change Colors

**Files:** `src/hooks/useAI.js`, `src/App.jsx`

**App.jsx:**
- Pass `objects: board?.objects` to `useAI` hook (currently only passes `addObject` and `updateObject`)

**useAI.js - Three new tools:**
1. `moveObject(objectId, x, y)` - calls `updateObject(objectId, {x, y})`
2. `resizeObject(objectId, width, height)` - calls `updateObject(objectId, {width, height})`
3. `changeObjectColor(objectId, color)` - calls `updateObject(objectId, {color})`

**Object identification approach:**
- Prepend current board state to each user message as context: `[Current board objects: id:abc, type:sticky, text:"Hello", pos:(100,200), ...]`
- AI uses object IDs from this context to target operations
- Update system instruction to explain the new capabilities and how to match objects by text/type

---

## Feature 7: AI Grid Generation

**File:** `src/hooks/useAI.js`

**New `createGrid` tool:**
- Parameters: `objectType, rows, columns, startX, startY, cellWidth, cellHeight, gapX, gapY, color, labels[]`
- Required: `objectType, rows, columns`
- Defaults: startX=100, startY=100, cellWidth=150, cellHeight=150, gap=20
- Execution: nested loop creating `rows * columns` objects via `boardActions.addObject`
- Labels array (optional) provides text for each cell in row-major order

**System instruction update:** Add guidance for when to use `createGrid` vs individual create calls.

---

## Implementation Order

```
1. Click-outside close    (isolated, App.jsx only)
2. Resize+Rotate all      (Shape.jsx + StickyNote.jsx + App.jsx)
3. Transparent colors      (App.jsx + App.css, builds on color picker)
4. Line object             (new LineShape.jsx + App.jsx + useAI.js)
5. Frames                  (new Frame.jsx + App.jsx + useAI.js)
6. AI move/resize/recolor  (useAI.js + App.jsx)
7. AI grid generation      (useAI.js, builds on #6)
```

## Verification

- Run `npm run dev` and test each feature in the browser
- Color picker: click outside should close; transparent colors should show checkerboard pattern in swatches
- Rotation: drag rotate handle on sticky notes and shapes; reload to verify rotation persists
- Line: create from toolbar, drag endpoints, change color
- Frame: create, edit title, resize; verify it renders behind other objects
- AI: test "move the sticky note to position 300,400", "make the rectangle red", "resize the circle to 200x200"
- AI grid: test "create a 2x3 grid of sticky notes for pros and cons"
