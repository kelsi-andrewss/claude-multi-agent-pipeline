# Plan: Polish "You" Badge on Current User Presence Avatar

## Context
A "You" badge was added to the current user's avatar in the presence stack. The implementation works mechanically but has three visual bugs:
1. **Badge drifts on hover** — the stack hover animates `.avatar-circle` left by 4px, but the badge is a sibling (not a child) of the circle, so it stays put while the avatar moves under it.
2. **Border color wrong in dark mode** — badge border is hardcoded `#1f2937` which matches the header in light mode but is noticeably lighter than `#030712` (dark mode header), showing an unwanted ring.
3. **Badge color not using design token** — background is hardcoded `#6366f1` instead of `var(--accent-primary)`, so it diverges from the accent color in light mode (`#4f46e5`).

## Files to Modify
- `src/components/PresenceAvatars.jsx`
- `src/App.css`

## Implementation

### 1. Move badge inside `.avatar-circle` (fixes drift on hover)

Currently the JSX wraps the avatar circle and badge in a `relative` div as siblings. The `transform: translateX(-4px)` on `.avatar-circle` only moves the circle, not the badge.

**Fix:** Remove the outer relative wrapper entirely. Move the `<span className="avatar-you-badge">` inside the `.avatar-circle` div, making it a child. Since `.avatar-circle` already has `overflow: hidden`... wait — this would clip the badge.

**Correct fix:** Keep the relative wrapper but move the `transition` targeting to include the wrapper. Override the `.avatar-stack:hover` rule so it targets the wrapper div (give it a class `avatar-you-wrapper`) instead of relying on the inherited `.avatar-circle` selector:

```jsx
// For current user:
<div key={i} className="avatar-you-wrapper">
  <div className="avatar-circle" style={{ backgroundColor: u.color, zIndex: 10 - i }} title={u.name}>
    {/* photo or initial */}
  </div>
  <span className="avatar-you-badge">You</span>
</div>

// For other users: unchanged, no wrapper class needed
<div
  key={i}
  className="avatar-circle"
  style={{ backgroundColor: u.color, zIndex: 10 - i }}
  title={u.name}
>
  {/* photo or initial */}
</div>
```

In CSS, add `.avatar-you-wrapper` and make the hover transition move the whole wrapper (circle + badge together):

```css
.avatar-you-wrapper {
  position: relative;
  display: inline-flex;
  transition: transform 0.2s;   /* same duration as avatar-circle */
  margin-right: -8px;           /* take over the overlap margin from avatar-circle for this user */
}

/* Remove margin-right from the avatar-circle when inside the wrapper to avoid double margin */
.avatar-you-wrapper .avatar-circle {
  margin-right: 0;
}
```

And update the hover rule:
```css
.avatar-stack:hover .avatar-circle,
.avatar-stack:hover .avatar-you-wrapper {
  transform: translateX(-4px);
}
```

### 2. Fix badge border color (fixes dark mode mismatch)

Change the hardcoded `border: 1.5px solid #1f2937` to `border: 1.5px solid var(--header-bg)`. This correctly blends with the header background in both themes.

### 3. Fix badge background color (use design token)

Change `background: #6366f1` to `background: var(--accent-primary)`. This correctly tracks the accent color across light (`#4f46e5`) and dark (`#6366f1`) themes.

### Final `.avatar-you-badge` rule:
```css
.avatar-you-badge {
  position: absolute;
  bottom: -1px;
  right: -4px;
  background: var(--accent-primary);
  color: white;
  font-size: 0.5rem;
  font-weight: 700;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  padding: 1px 4px;
  border-radius: 999px;
  border: 1.5px solid var(--header-bg);
  line-height: 1.4;
  pointer-events: none;
  z-index: 20;  /* raise above avatar z-index values (max 10) */
}
```

## Verification
1. Open the app with 2+ users on the same board
2. Hover the avatar stack — verify the "You" badge moves left with the avatar, not independently
3. Toggle dark mode — verify the badge border disappears into the header background in both themes
4. Verify the badge color matches other accent-colored elements (e.g. active snap toggle button)
