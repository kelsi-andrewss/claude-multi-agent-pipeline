# Plan: Test Infrastructure Setup (Tier 1 — Pure Functions)

## Context
The project has zero test files, no test runner, and no test dependencies. This sets up Vitest and writes tests for all 4 utility modules — the pure-function layer with no external dependencies.

## Step 1: Install dependencies
```bash
npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom
```
Testing-library installed now to avoid a second setup round for Tier 2.

## Step 2: Create `vitest.config.js`
```js
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.test.{js,jsx}'],
  },
})
```

## Step 3: Add scripts to `package.json`
```json
"test": "vitest run",
"test:watch": "vitest"
```

## Step 4: Write test files (in order)

### 4a. `src/utils/slugUtils.test.js` (~8 tests)
- `toSlug` — lowercases, replaces spaces with hyphens, strips special chars, empty string
- `groupToSlug` — null returns UNGROUPED_SLUG, string input, object with .slug, object without .slug
- `findGroupBySlug` — UNGROUPED_SLUG returns null, finds by .slug field, returns null on no match, legacy board.group string matching

### 4b. `src/utils/colorUtils.test.js` (~16 tests)
- `darkenHex` — darkens white by default 30%, custom amount, non-hex passthrough, null passthrough, black stays black
- `hexToRgba` — standard conversion, alpha=1
- `parseColorForInput` — truncates 8-digit hex, 6-digit unchanged, rgb() to hex, rgba() drops alpha, null returns #000000, unrecognized returns #000000
- `parseOpacity` — extracts rgba alpha, rgb returns 1, hex returns 1, null returns 1
- `getContrastColor` — black on white, white on black, black on yellow, null returns #000000
- `getUserColor` — deterministic (same uid = same result), returns valid hex, runs without error

### 4c. `src/utils/tooltipUtils.test.js` (~4 tests, uses `vi.useFakeTimers()`)
- Calls setResizeTooltip with computed position and message
- Flips Y when screenY < 40
- Clears previous timer before setting new one
- Auto-dismisses after 2500ms

### 4d. `src/utils/frameUtils.test.js` (~25 tests)
- `getContentBounds` — empty objects, single rect, multiple objects, line with points, missing width/height defaults, line with insufficient points
- `getLineBounds` — from points array, default points, strokeWidth as minimum
- `isInsideFrame` — center inside, center outside, center on edge
- `findOverlappingFrame` — smallest frame returned, null when no match, excludes self
- `rectsOverlap` — overlapping, non-overlapping, edge-touching (false), with margin
- `findNonOverlappingPosition` — empty board returns center, occupied center spirals out (test invariant: result doesn't overlap)
- `hasDisallowedSiblingOverlap` — no overlap false, frame overlaps sibling true, non-frame only checks sibling frames
- `findFrameAtPoint` — smallest frame at point, null when empty, excludes excludeId
- `findObjectsToAbsorb` — absorbs unparented non-frames inside rect, excludes parented objects, excludes frames
- `getDescendantIds` — recursive collection, empty for childless frame
- `computeAncestorExpansions` — no expansion when child fits, expands right edge, walks up to grandparent

## Step 5: Run `npm test` to verify

## Files modified
- `package.json` — add devDependencies + test scripts
- `vitest.config.js` — new file
- `src/utils/slugUtils.test.js` — new file
- `src/utils/colorUtils.test.js` — new file
- `src/utils/tooltipUtils.test.js` — new file
- `src/utils/frameUtils.test.js` — new file
