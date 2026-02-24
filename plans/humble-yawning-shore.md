# Plan: Color History Fix, Frame Drag-Drop, Frame Background Color

## Context
The CollabBoard whiteboard app needs three improvements: (1) color history shows pre-populated defaults instead of actual user history, (2) frames have no drag-drop containment logic, and (3) frames lack background color support.

---

## Feature 1: Fix Color History

**Files:** `src/App.jsx`, `src/App.css`

1. **Empty default history** — Change `shapeColors` initial state (line 328-336) to use `history: []` for all shape types instead of pre-populated color arrays
2. **Always render 10 slots** — In `ColorPickerMenu` (lines 81-95), render `Array.from({ length: 10 })` and show either a colored swatch or an empty blank square
3. **Empty swatch CSS** — Add `.color-swatch.empty-swatch` style: no checkerboard, dashed border, muted background, no hover effect

---

## Feature 2: Frame Drag-Drop Containment

**Files:** `src/App.jsx`, `src/components/Frame.jsx`, `src/components/Shape.jsx`, `src/components/StickyNote.jsx`, `src/components/LineShape.jsx`, `src/hooks/useBoard.js`

1. **Containment helper** — Add `isInsideFrame(obj, frame)` and `findOverlappingFrame(obj, allObjects)` functions in App.jsx (center-point hit test, pick smallest overlapping frame)
2. **Drag state** — Add `dragState` state: `{ draggingId, overFrameId, action: 'add'|'remove'|null }`
3. **`handleDragMove`** — Called by all draggable components during drag. Checks if object is over a frame, determines if this is an add or remove action, updates `dragState`
4. **`handleContainedDragEnd`** — Wraps `board.updateObject` to set/clear `frameId` on dropped objects based on containment
5. **`handleFrameDragEnd`** — When a frame is dragged, move all contained objects (`frameId === frame.id`) by the same delta using `batchUpdateObjects`
6. **`batchUpdateObjects` in useBoard.js** — Add Firestore `writeBatch` function for efficient multi-object updates
7. **Add `onDragMove` to Shape, StickyNote, LineShape** — Wire `onDragMove` into each component's `<Group>` element, calling `props.onDragMove(id, {x, y})`
8. **Frame visual indicators** — In Frame.jsx, render highlight overlays based on `dragState`:
   - `action === 'add'`: green highlight + "+" text
   - `action === 'remove'`: red highlight + "-" text
   - All indicator shapes use `listening={false}`
9. **Frame deletion cleanup** — When deleting a frame, clear `frameId` on all contained children

---

## Feature 3: Frame Background Color

**Files:** `src/App.jsx`, `src/components/Frame.jsx`, `src/App.css`

1. **Background rect in Frame.jsx** — Add a filled `<Rect>` as the first child inside the Group, rendered only when `backgroundColor` is truthy. Uses `listening={false}` so clicks pass through
2. **Frame properties panel** — When a frame is selected, show a small floating panel (positioned near the existing FABs) with:
   - Color input for background color
   - "None" button to clear the background
3. **CSS for panel** — Style `.frame-props-panel` as a fixed-position card

---

## Verification
- Start the app with `npm run dev`
- Color history: Open a shape color picker → confirm 10 slots with blanks. Pick colors → they appear in history. Refresh → localStorage persists
- Frame containment: Create a frame, drag a shape over it → green highlight + plus icon. Drop → shape associates. Drag frame → shape moves with it. Drag shape out → red highlight + minus icon. Drop → shape disassociates
- Frame background: Select frame → background panel appears. Pick color → frame fills. Click "None" → transparent again
