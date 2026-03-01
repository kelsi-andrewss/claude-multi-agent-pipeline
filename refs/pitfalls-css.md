# Pitfalls: CSS

- Avoid `!important` — use a more specific selector to resolve conflicts instead
- Prefer CSS variables and dark-mode-aware tokens over hardcoded color values
- When adding `:focus-visible`, ensure the outline color contrasts with the button background — test both light and dark modes
- Before adding flex-child properties (`align-self`, `flex-grow`, `order`), verify the parent container has `display: flex`
- `z-index` only works on positioned elements (`relative`, `absolute`, `fixed`, `sticky`) — adding it to a static element does nothing
- `gap` in flexbox is not supported in older Safari (pre-14.1) — use margin fallbacks if legacy support is needed
- CSS Modules: class names are locally scoped — global selectors (`:root`, `body`, `*`) leak and should go in a global stylesheet
- `transform` creates a new stacking context — child `position: fixed` elements will be relative to the transform, not the viewport
