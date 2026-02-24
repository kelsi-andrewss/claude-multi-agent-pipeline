# Plan: Fix vertical chip styling regression

## Context
The story-037 CSS changes reduced button sizes to 32px but caused two visible regressions in the left tools chip (vertical orientation):
1. **Icons became smaller than needed** — reducing `width` on tool buttons made icons appear shrunk inside the chip. The goal was tighter vertical spacing, not smaller icons. Only `height` needed to shrink.
2. **Dropdown arrows are overflowing outside the chip** — the `tool-split-button` chevron buttons (`dropdown-arrow`) now render outside the chip boundary in vertical mode because their container layout broke when `width: 32px` was applied to buttons within the split-button.

The right chip (profile/icons) is unaffected — `help-btn` and `chip-orient-btn` don't have dropdowns and the width reduction there is acceptable.

## Root Cause
In `BoardSwitcher.css`, the coder added:
```css
.floating-toolbar-chip[data-orient="vertical"] .tool-split-button button {
  height: 32px;
}
```
This reduces height of ALL buttons inside `.tool-split-button` — including `dropdown-arrow` buttons — causing the chevrons to shrink and overflow. Also `.toolbar-btn` and `.snap-toggle` had their `width` set to 32px unnecessarily (icons are 18px inside a 40px hit area — 32px is still fine, but the `tool-split-button` buttons must NOT have width constrained).

The real issue: the chip was already tall because of `gap` and `padding` between sections, not because of button heights. The height reduction helped somewhat but broke the split-button layout.

## Fix

### `src/App.css`
The new rules added at the bottom (lines ~771–784) are fine. No changes needed here.

### `src/components/BoardSwitcher.css`
Remove or correct these rules added by story-037:

1. **Remove width from `.tool-split-button button`** — keep height reduction but remove width constraint. Split-button buttons need full width to lay out correctly:
   ```css
   /* WRONG (from story-037): */
   .floating-toolbar-chip[data-orient="vertical"] .tool-split-button button {
     height: 32px;
   }
   /* This is fine — but the main tool button in the split needs width: 100% not a fixed width */
   ```

2. **Fix `.tool-split-button` layout in vertical mode** — the existing rule at line 133-136 sets `flex-direction: row; justify-content: space-between` which is correct. But the `dropdown-arrow` button needs to be constrained. Add:
   ```css
   .floating-toolbar-chip[data-orient="vertical"] .tool-split-button {
     overflow: visible; /* already exists in BoardSwitcher.css line 547 */
     width: 100%;
   }
   .floating-toolbar-chip[data-orient="vertical"] .tool-split-button > button:first-child {
     flex: 1;
     height: 32px;
   }
   .floating-toolbar-chip[data-orient="vertical"] .tool-split-button .dropdown-arrow {
     width: 20px;
     height: 32px;
     flex-shrink: 0;
   }
   ```

3. **Remove `width: 32px` from `.toolbar-btn` and `.snap-toggle`** — keep height 32px but set width back to the container width (auto/100%) or keep as 32px if the icons still look fine. The icons are 18px so they'll center fine in 32px width.

Actually, looking at the screenshot more carefully: the overflow issue is that the `dropdown-arrow` chevrons render **outside** the chip to the right. This means the chip `width: 52px` is too narrow for `tool-split-button` which needs to fit the tool icon button + dropdown arrow side by side.

## Revised Fix

The chip width in vertical mode is `52px`. A `tool-split-button` row layout needs: main button (32px) + dropdown arrow (20px) = 52px. This should fit exactly. The overflow is likely because `overflow: visible` on the chip combined with the split-button pushing the chevron outside.

### Correct approach:
1. **Revert `width: 32px` on `.toolbar-btn`** and `.snap-toggle` in vertical — use `width: 100%` so they fill the 52px chip width
2. **For `.tool-split-button` in vertical**: main button gets `flex: 1`, dropdown-arrow gets fixed `width: 20px`, both `height: 32px`
3. **Keep height reductions** — only heights, not widths, should be constrained
4. **The chip `width: 52px`** may need to increase slightly to `56px` to accommodate split-button layout (36px icon + 20px arrow)

## Files to modify
- `src/components/BoardSwitcher.css` — fix the vertical rules added in story-037
- `src/App.css` — possibly increase chip vertical width from 52px to 56px

## Verification
1. Switch left tools chip to vertical orientation
2. Confirm: icons are normal size (not shrunk)
3. Confirm: dropdown chevrons are inside the chip, not overflowing
4. Confirm: overall chip height is reduced vs before story-037
5. Confirm: horizontal orientation is unchanged
