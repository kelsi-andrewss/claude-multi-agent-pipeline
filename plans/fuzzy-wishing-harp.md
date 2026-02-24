# Plan: Fix Ghost-Placement Mismatch + Add Strict Tests

## Context

The ghost preview for sticky notes still doesn't match the placed object. The previous fix (`centeredPlacementOffset`) aligned the offset formula but missed a **size mismatch**:

- **Ghost rect** (BoardCanvas.jsx:112): `sw = 200 / stageScale` (unrounded float)
- **Placed object** (App.jsx:574): `sz = Math.round(200 / stageScale)` (rounded integer)
- **Ghost offset** uses `centeredPlacementOffset` which internally rounds: `sz = Math.round(200 / scale)`, then `x = canvasX - sz / 2`

So the ghost is positioned based on a rounded size but drawn with an unrounded size. At scale 1.5x: ghost width = 133.33, but offset assumes width = 133. The ghost visually overshoots by ~0.17px on each side, and the placed object lands at a slightly different visual position.

The fix is two-fold:
1. Expand `centeredPlacementOffset` to also return the rounded size, so the ghost rect uses the same size
2. Write strict unit tests for `centeredPlacementOffset` that enforce ghost === placement at problematic zoom levels

## Step 1 — Expand `centeredPlacementOffset` in `src/utils/geometryUtils.js`

Return `sz` alongside `x` and `y` so callers can use it for width/height:

```js
export function centeredPlacementOffset(canvasX, canvasY, nominalSize, scale) {
  const sz = Math.round(nominalSize / scale);
  return { x: canvasX - sz / 2, y: canvasY - sz / 2, sz };
}
```

## Step 2 — Update ghost rect in `src/components/BoardCanvas.jsx` (protected — permission granted)

**Ghost layer (line 112)**: Replace `const sw = 200 / stageScale` with a call that uses the rounded size from the helper. The ghost Group position is set dynamically in `handleMouseMoveWrapped`, but the ghost **Rect width/height** is set at render time and must match.

Change:
```js
const sw = 200 / stageScale;
```
To:
```js
const sw = Math.round(200 / stageScale);
```

This makes the ghost rect size match `centeredPlacementOffset`'s internal `sz` and match the placed object's `width`/`height`. Also update the tooltip text y-offset on line 128 (`y={sw + 4 / stageScale}`) — this still works since `sw` is now rounded.

## Step 3 — Create `src/utils/geometryUtils.test.js`

Write strict tests that enforce the invariant: **for any canvas position and zoom level, the ghost position+size must exactly equal the placed object position+size**.

Test cases:
- **Scale 1.0** (integer, no rounding): trivial baseline
- **Scale 1.5** (the original bug trigger): `200/1.5 = 133.33...` vs `Math.round(200/1.5) = 133`
- **Scale 0.75**: `200/0.75 = 266.67` vs `round = 267`
- **Scale 1.25**: `200/1.25 = 160` (exact, no rounding issue)
- **Scale 1.33**: extreme fractional
- **Scale 2.0**: integer scale, different from 1.0

For each scale, test at multiple canvas positions (0,0), (100, 200), (333.5, 777.3).

Test structure:
```js
describe('centeredPlacementOffset', () => {
  // Basic return value tests
  it('returns x, y, and sz', ...)

  // Ghost-placement agreement tests
  // These simulate what both code paths do and assert they produce identical results
  describe('ghost and placement agreement', () => {
    const scales = [1, 0.75, 1.25, 1.33, 1.5, 2];
    const positions = [[0, 0], [100, 200], [333.5, 777.3]];

    for (const scale of scales) {
      for (const [cx, cy] of positions) {
        it(`matches at scale=${scale}, pos=(${cx},${cy})`, () => {
          const result = centeredPlacementOffset(cx, cy, 200, scale);

          // Placement path (App.jsx): sz = Math.round(200/scale), x = result.x, y = result.y
          const placedSz = Math.round(200 / scale);
          expect(result.sz).toBe(placedSz);

          // Ghost path (BoardCanvas.jsx): same offset, same size
          // The ghost rect top-left = (result.x, result.y), size = result.sz
          // The placed object top-left = (result.x, result.y), size = placedSz
          // They must be identical:
          expect(result.x).toBe(cx - placedSz / 2);
          expect(result.y).toBe(cy - placedSz / 2);

          // Verify center point is at the original canvas position
          expect(result.x + result.sz / 2).toBe(cx);
          expect(result.y + result.sz / 2).toBe(cy);
        });
      }
    }
  });

  // Edge cases
  it('handles scale = 1 with no rounding artifacts', ...)
  it('handles very small scales', ...)
  it('handles very large scales', ...)
});
```

## Critical Files

| File | Action | Protected? |
|------|--------|-----------|
| `src/utils/geometryUtils.js` | Edit (add `sz` to return) | No |
| `src/components/BoardCanvas.jsx` | Edit (round ghost width) | Yes — permission granted |
| `src/utils/geometryUtils.test.js` | Create (new test file) | No |

## Sequencing

1. Step 1 (expand helper) — must come first
2. Steps 2 and 3 are independent of each other

## Verification

1. `npm test` — new tests pass
2. `npm run build` — no build errors
3. Manual: select sticky tool, hover at zoom 1.5x, click — ghost and object should be pixel-identical
