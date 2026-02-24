# Plan: Connector drag tracking + Transformer suppression + styling (story-047)

## Context
Three related connector/selection UX improvements:
1. **Connector live drag (frames)** — connectors follow regular objects during drag already (`dragPos` path works). Frames are broken because `handleFrameDragMove` never calls `setDragPos` during move — only at drag-end.
2. **Suppress resize handles during connector mode** — when line/arrow tool is active, port circles appear on all objects. The resize Transformer should be hidden to reduce visual noise.
3. **Style Transformer to match the app** — Konva defaults are unstyled blue/gray; app accent is indigo (`#6366f1`), matching connector port circles.

---

## Task 1 — Frame connector live drag

**File**: `src/handlers/frameDragHandlers.js` (protected-testable → `needsTesting: true`)

Inside `handleFrameDragMove`, after `setDragState({...})` (~line 67), add:
```js
if (setDragPos) setDragPos({ id, x: pos.x, y: pos.y });
```
`setDragPos` is already destructured from config. Same `if (setDragPos)` guard is already used at line 216 (`handleFrameDragEnd`). No `areEqual` or props changes needed — `dragPos` is already tracked.

**Edge case**: Connectors attached to children of a dragged frame won't follow live (child ids ≠ frame id). Acceptable — out of scope.

---

## Task 2 — Suppress Transformer when connector tool active

**Condition**: `pendingTool === 'line' || pendingTool === 'arrow'`

When a line/arrow is *selected* (not tool-active), the selected object is a line — Shape/StickyNote/Frame/TextShape all have `isSelected=false`, so their Transformers already don't render. No extra logic needed for that case.

**Change per component** (Shape.jsx, StickyNote.jsx, Frame.jsx, TextShape.jsx):
1. Add `pendingTool` to destructured props
2. Transformer render guard: add `&& pendingTool !== 'line' && pendingTool !== 'arrow'` to existing condition
3. In the `useEffect` attaching `trRef.current.nodes(...)`, add null guard:
   ```js
   if (isSelected && !isEditing && trRef.current) {
     trRef.current.nodes([groupRef.current]);
     trRef.current.getLayer().batchDraw();
   }
   ```
   (Prevents throw when Transformer not rendered and `trRef.current` is null.)

**BoardCanvas.jsx**: Add `pendingTool={pendingTool}` to `<Shape>`, `<StickyNote>`, `<Frame>`, `<TextShape>` in the render map. `pendingTool` is already in `state` (~line 308) and already in `areEqual` (~line 865). No new BoardCanvas prop.

---

## Task 3 — Style Transformer to match app

Add to every `<Transformer>` in Shape.jsx, StickyNote.jsx, Frame.jsx, TextShape.jsx:
```jsx
borderStroke="#6366f1"
borderStrokeWidth={1.5}
borderDash={[4, 4]}
anchorFill="#ffffff"
anchorStroke="#6366f1"
anchorStrokeWidth={1.5}
```
`anchorSize={10}` and `anchorCornerRadius={2}` are already present — no change. The dashed indigo border echoes the selection cue; white anchors with indigo stroke match port circle style.

---

## Files

| File | Tasks | Protected |
|---|---|---|
| `src/handlers/frameDragHandlers.js` | 1 | Testable only |
| `src/components/BoardCanvas.jsx` | 2 | Konva — permission granted |
| `src/components/Shape.jsx` | 2+3 | Konva — permission granted |
| `src/components/StickyNote.jsx` | 2+3 | Konva — permission granted |
| `src/components/Frame.jsx` | 2+3 | Konva — permission granted |
| `src/components/TextShape.jsx` | 2+3 | Konva — permission granted |

**Agent**: quick-fixer (mechanical changes — prop forwarding, one-line handler addition, Transformer prop additions)
**needsTesting**: true (frameDragHandlers.js is testable)
**needsReview**: false

---

## Verification
1. Drag a frame with a connector → connector endpoint follows in real-time
2. Activate line/arrow tool → resize handles disappear on all objects; port circles visible
3. Deactivate line/arrow tool → resize handles reappear on selected object
4. Select any shape → Transformer shows indigo dashed border, white anchors with indigo stroke
5. Build: `npm run build` passes in worktree
