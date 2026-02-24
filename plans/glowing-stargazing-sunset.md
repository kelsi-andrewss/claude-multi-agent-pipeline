# Plan: Fix frame z-index overlay bug

## Context

A frame can visually render on top of its own children. This happens because `sortObjects` puts all frames in a fixed tier (sorted before all non-frames), then uses `zIndex` only as a tiebreaker within same-tier objects. When clicking a frame triggers `handleSelectAndRaise`, the frame's `zIndex` rises to `maxZ + 1` — but since it's still in tier 0 (frames), it renders before all non-frames (tier 1). The frame background rect therefore appears on top of children that have lower zIndex values.

The second problem: frame children inherit their relative visual position from the scene graph (they're rendered as sibling Konva nodes at the Layer level, after the frame), so in practice children DO render on top of the frame's background — as long as the frame and its children are compared correctly. The bug surfaces when `handleSelectAndRaise` is called on a non-frame child: that child gets `zIndex: maxZ+1` and jumps to the top of non-frames (correct). But when it's called on a frame, the frame gets `maxZ+1` — still tier 0 — and all its children keep lower zIndexes — still tier 1. Children still render last in Konva, so visually this is fine... unless the zIndex of a frame is COMPARED against the frame's own children in the wrong branch.

**Root cause confirmed:** `sortObjects` never enforces the invariant "a frame must render before all its own descendants." Currently, nested frames (frameId set) sort after root frames — but a non-frame child of a root frame is tier 1 and sorts before a nested frame (tier 0 depth 1). That means a child object can end up rendering before a nested sub-frame it's not even related to.

More critically: `handleSelectAndRaise` on a frame with zIndex=100 vs a child of a DIFFERENT frame with zIndex=50 means the child renders after the selected frame's background — correct. But if a child of this frame has zIndex=50, it renders after the frame — also correct. The actual breakage is: **a non-frame child of frame A can visually sit behind a nested frame B that is inside frame A** (nested frames render last in tier 0, but before tier 1 non-frames with high zIndex).

**The clean fix:** Sort such that for any frame F, F always renders before all objects whose `frameId` chain includes F. This is a topological ordering by parent–child relationship, not a simple two-tier sort.

---

## Design decision

**Raise behavior within a frame:** zIndex controls ordering among siblings only. A non-frame child raised via `handleSelectAndRaise` can move above sibling non-frame objects but never above a nested sub-frame inside the same parent. The topological walk enforces this: non-frame children always emit before nested frames in the same parent slot.

---

## Implementation

### File: `src/components/BoardCanvas.jsx`

**Replace `sortObjects` with a topological sort** that guarantees a frame always renders before all its direct and indirect children.

```js
export function sortObjects(a, b) {
  // A frame must always render before any object in its descendant chain.
  // Check if b is a descendant of a (a must come first).
  if (a.type === 'frame') {
    let cur = b;
    // Walk b's ancestor chain — if we reach a, b is a descendant of a
    // (We need the full objects map for this; see below for the refactor)
  }
  // Existing fallback: frames before non-frames, depth, then zIndex
  const aFrame = a.type === 'frame' ? 0 : 1;
  const bFrame = b.type === 'frame' ? 0 : 1;
  if (aFrame !== bFrame) return aFrame - bFrame;
  if (a.type === 'frame' && b.type === 'frame') {
    const aDepth = a.frameId ? 1 : 0;
    const bDepth = b.frameId ? 1 : 0;
    if (aDepth !== bDepth) return aDepth - bDepth;
  }
  return (a.zIndex || 0) - (b.zIndex || 0);
}
```

The comparator approach is insufficient because ancestry requires the full object map (you can't determine if B is a descendant of A from just two objects). The correct approach is to **pre-compute a render order** via a two-pass stable sort:

**New `buildRenderOrder(objects)` function** (replaces the `.sort(sortObjects)` call in the render loop):

```
1. Separate into frames and non-frames.
2. Topologically sort frames: root frames first, each immediately followed by
   their child frames (depth-first). Within siblings, sort by zIndex.
3. For each frame F in that order, assign a renderSlot = frameSlot + 0.5.
   Non-frame children of F get renderSlot = F.renderSlot + epsilon, where
   epsilon is sub-sorted by zIndex.
4. Root-level non-frame objects (frameId null) sort after all frames,
   by zIndex.
5. Final array is sorted by renderSlot.
```

Simpler equivalent: **stable topological walk**:

```js
export function buildRenderOrder(objects) {
  const objArr = Object.values(objects);
  const byId = objects; // already a map

  // Group frames by parent
  const rootFrames = objArr.filter(o => o.type === 'frame' && !o.frameId)
    .sort((a, b) => (a.zIndex || 0) - (b.zIndex || 0));
  const childFrames = {}; // parentFrameId -> Frame[]
  for (const o of objArr) {
    if (o.type === 'frame' && o.frameId) {
      (childFrames[o.frameId] ||= []).push(o);
    }
  }
  // Non-frame objects by frameId (null = root level)
  const nonFramesByParent = {}; // frameId|null -> obj[]
  for (const o of objArr) {
    if (o.type !== 'frame') {
      const key = o.frameId || '__root__';
      (nonFramesByParent[key] ||= []).push(o);
    }
  }
  for (const arr of Object.values(nonFramesByParent)) {
    arr.sort((a, b) => (a.zIndex || 0) - (b.zIndex || 0));
  }

  const result = [];

  function visitFrame(frame) {
    result.push(frame); // frame renders first
    // Non-frame direct children of this frame
    for (const child of (nonFramesByParent[frame.id] || [])) {
      result.push(child);
    }
    // Nested child frames (recursive)
    const nested = (childFrames[frame.id] || [])
      .sort((a, b) => (a.zIndex || 0) - (b.zIndex || 0));
    for (const nested_frame of nested) {
      visitFrame(nested_frame);
    }
  }

  for (const frame of rootFrames) {
    visitFrame(frame);
  }

  // Root-level non-frame objects last, sorted by zIndex
  for (const obj of (nonFramesByParent['__root__'] || [])) {
    result.push(obj);
  }

  return result;
}
```

**In the render loop**, replace:
```js
allObjs.filter(obj => visibleIds.has(obj.id)).sort(sortObjects)
```
with:
```js
buildRenderOrder(objects).filter(obj => visibleIds.has(obj.id))
```

Note: `buildRenderOrder` takes the full `objects` map (not the filtered array) so the topological walk is complete, then visibility filtering happens after ordering.

---

### `handleSelectAndRaise` — no change needed

`handleSelectAndRaise` correctly raises all object types. Frames raising their own zIndex is fine because zIndex is only used as a tiebreaker within the same parent context in the new sort.

---

## Edge cases addressed

| Scenario | Before | After |
|---|---|---|
| Frame clicked (raised via handleSelectAndRaise) | Frame may render behind high-zIndex non-frame siblings from other frames | Frame still renders before all its own children; sibling ordering by zIndex |
| Nested frame inside frame | Child frame sorted after root frame but before non-frame children of root | visitFrame recurses depth-first: root frame → root's non-frame children → nested frame → nested frame's children |
| Non-frame child with zIndex > parent frame's zIndex | Unpredictable (tier comparison skips zIndex) | Child always renders after its parent frame regardless of zIndex |
| Root-level non-frames with high zIndex | Render after all frames (correct) | Unchanged — still render after all frames |
| Object moved between frames | frameId changes, child moves to new parent's slot | `buildRenderOrder` re-derives grouping from current frameId state |

---

## Additional edge case suggestions (for user consideration)

1. **zIndex monotonic growth**: Every click via `handleSelectAndRaise` increments zIndex by 1. On an active board, zIndex values will grow unboundedly. Consider a periodic renormalization (e.g., compact zIndexes to 0..N on write when max exceeds 10000). Not a blocking bug today but worth tracking.

2. **Lines/arrows that are "inside" a frame**: Lines with `frameId` set will render in the frame's slot (after frame chrome, before nested frames). Lines that span multiple frames have `frameId: null` and render at root level last. This is probably correct but worth confirming visually.

3. **Multi-select raise**: `handleDeleteMultiple` and `handleDuplicateMultiple` exist but there's no `handleRaiseMultiple`. When multi-selecting and sending to front, each object is raised independently, which can produce inconsistent relative ordering within the selection. Not part of this story but a known gap.

---

## Files to modify

- `src/components/BoardCanvas.jsx` — replace `sortObjects` with `buildRenderOrder`; update the render loop call site

## Files to read (context only)

- `src/handlers/objectHandlers.js` — confirm `handleSelectAndRaise` needs no change
- `src/components/Frame.jsx` — confirm frame renders no children (already confirmed: it does not)

## Verification

1. Create a frame, add several stickies and shapes inside it.
2. Click the frame itself — confirm children remain visible on top of the frame background.
3. Click individual children — confirm they raise above siblings inside the frame.
4. Create a nested frame inside the first frame, add stickies to both.
5. Click the outer frame — confirm inner frame and all children remain visible.
6. Click the inner frame — confirm inner frame's children remain on top.
7. Use "Send to Back" on a child — confirm it goes behind siblings but still above the frame background.
8. Run `npm run build` to verify no syntax errors.
