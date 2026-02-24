# Epic Plan: Animations Throughout the App

## Context

CollabBoard has inconsistent animation coverage: some components (ContextMenu, FABs, AIPanel entrance) have transitions, but most panels have no entrance/exit animations, dropdowns appear/disappear instantly, modals have no lifecycle animation, and the canvas layer has zero Tween usage. This epic brings cohesive motion to both the DOM UI layer and the Konva canvas layer, using the M3 motion tokens already defined in `src/styles/tokens/_motion.css`.

User has granted permission to edit all protected Konva files for this epic.

---

## Design Decisions

- **User-created objects**: subtle/functional (150–250ms scale+fade on spawn; fast fade on delete)
- **AI-spawned objects**: expressive wave — frames appear first and settle, then children pop in (mirrors the existing 2-pass strategy in `useAI.js`)
- **Panel exits**: per-component (slide back to origin, scale-down, or fade depending on entrance)

---

## Story Breakdown

### Story 1: DOM Panel & Modal Entrance/Exit Animations
**Agent**: quick-fixer | **Model**: haiku | **Trivial**: no

**Scope — CSS-only with minor JSX unmount coordination**

Targets:
- `AIPanel` — has entrance (`ai-panel-in`), no exit. Add exit animation: slide + fade back to right edge. Use JS `animationend` to defer unmount.
- `AchievementsPanel` — no entrance/exit. Add: slide up from bottom-right, fade out back down.
- `AdminPanel` — no entrance/exit. Add: scale-in from center, scale-out.
- `AppearanceSettings` (settings modal) — no entrance/exit. Add: scale-in, scale-out.
- `Modal overlays` (`.modal-overlay`, `.modal-card` in App.css) — add backdrop fade-in; card scale-in from 95% → 100%; reverse on exit.
- `UserAvatarMenu dropdown` — add scale-in from top-right origin, fade out.
- `ColorPickerMenu` — add scale-in from anchor point, fade out.
- `ReactionPicker` — add scale-in, fade out.
- `SelectedActionBar` — add slide-up from below, slide-down on exit.

**Write files**:
- `src/components/AIPanel.css`
- `src/components/AIPanel.jsx` (unmount delay)
- `src/components/AchievementsPanel.css`
- `src/components/AchievementsPanel.jsx` (unmount delay)
- `src/components/AdminPanel.css`
- `src/components/AdminPanel.jsx` (unmount delay)
- `src/components/AppearanceSettings.css`
- `src/components/AppearanceSettings.jsx` (unmount delay)
- `src/App.css` (modal overlay + card animations)
- `src/App.jsx` (modal unmount delay where needed)
- `src/components/UserAvatarMenu.css`
- `src/components/SelectedActionBar.css`
- `src/components/ColorPicker.css`
- `src/components/ReactionPicker.css` (if exists) or `ReactionPicker.jsx`

**Pattern to use** (unmount delay via CSS class swap):
```jsx
// When closing: add .is-exiting class, listen for animationend, then actually unmount
const [isExiting, setIsExiting] = useState(false);
const handleClose = () => {
  setIsExiting(true);
  // animationend event → call actual onClose prop
};
```

All animations must use `--md-sys-motion-duration-*` and `--md-sys-motion-easing-*` tokens.
All new keyframes must be wrapped in `@media (prefers-reduced-motion: no-preference)` or guarded via `[data-reduced-motion]`.

---

### Story 2: Canvas Object Spawn & Delete Animations
**Agent**: architect | **Model**: sonnet | **Trivial**: no
**Protected files explicitly permitted for this story.**

**Scope**: New hook `useObjectAnimations.js` + wiring into Konva components.

**Approach**:
1. Create `src/hooks/useObjectAnimations.js` — manages a registry of `{ id → animationState }` where state is `spawning | idle | dying`.
2. Expose: `markSpawning(id)`, `markDying(id, onComplete)`, `getAnimationState(id)`.
3. Each Konva component (`StickyNote`, `Shape`, `Frame`, `LineShape`) reads its animation state on mount:
   - **Spawning**: start at `opacity: 0, scaleX: 0.7, scaleY: 0.7` → tween to `opacity: 1, scale: 1` over 200ms using `--md-sys-motion-easing-emphasized-decelerate`
   - **Dying**: tween `opacity: 0, scaleX: 0.7, scaleY: 0.7` over 150ms, then call `deleteObject()` after tween completes
4. Wire spawn marking: in the `addObject` path (`src/hooks/useBoard.js` or `objectCreationHandlers.js`) — after `addDoc` resolves, call `markSpawning(newId)` before the snapshot listener fires.
5. Wire death: wrap `handleDeleteWithCleanup` in `objectHandlers.js` to call `markDying(id, () => board.deleteObject(id))` instead of calling `deleteObject` directly.

**Konva Tween usage**:
```js
// Inside component ref effect when animationState === 'spawning'
const tween = new Konva.Tween({
  node: groupRef.current,
  duration: 0.2,
  opacity: 1,
  scaleX: 1,
  scaleY: 1,
  easing: Konva.Easings.EaseOut,
  onFinish: () => tween.destroy(),
});
tween.play();
```

**Reduced motion**: `useObjectAnimations` reads `document.documentElement.dataset.reducedMotion` — if set, skip tweens entirely (mark spawning/dying as instant).

**Write files**:
- `src/hooks/useObjectAnimations.js` (new)
- `src/components/StickyNote.jsx` (spawn/death tween)
- `src/components/Shape.jsx` (spawn/death tween)
- `src/components/Frame.jsx` (spawn/death tween)
- `src/components/LineShape.jsx` (spawn/death tween)
- `src/hooks/useBoard.js` (markSpawning after addDoc)
- `src/handlers/objectHandlers.js` (markDying wrapping delete)
- `src/App.jsx` (pass animation hook down or via context)

**Read files**: `src/components/BoardCanvas.jsx`, `src/hooks/useUndoStack.js`, `src/hooks/useAI.js`

---

### Story 3: AI Wave Entrance Animation
**Agent**: architect | **Model**: sonnet | **Trivial**: no
**Depends on**: Story 2 (requires `useObjectAnimations` and its `markSpawning` hook)

**Scope**: Special animation mode for AI-batch-created objects.

**Approach**:
1. Add `markAISpawning(frameIds, childrenByFrame)` to `useObjectAnimations`.
2. In `useAI.js` after the 2-pass execution completes:
   - Pass 1 IDs (frame IDs) → animate as normal spawn (200ms each)
   - After all frames have animated (wait ~250ms), stagger children: each child animates in with 80ms delay between successive objects, grouped by parent frame
3. Children start at `opacity: 0, scaleX: 0.8, scaleY: 0.8` and pop in with a slightly more expressive curve (emphasized-decelerate, 300ms)
4. Frames use same 2-pass metadata already tracked by `createMutationTracker()` in useAI.js

**Write files**:
- `src/hooks/useObjectAnimations.js` (extend with AI batch mode)
- `src/hooks/useAI.js` (call markAISpawning after 2-pass completes)

**Read files**: `src/hooks/useObjectAnimations.js` (from Story 2)

---

### Story 4: Selection Pulse & Interaction Animations
**Agent**: quick-fixer | **Model**: haiku | **Trivial**: no
**Protected files explicitly permitted for this story.**

**Scope**: Brief scale pulse when an object is first selected; spring-style snap-back on drag release.

**Selection pulse approach**:
- In `StickyNote.jsx`, `Shape.jsx`, `Frame.jsx`: watch `isSelected` in a `useEffect`. When it transitions false→true, run a brief Konva Tween: scale to 1.04 over 80ms then back to 1.0 over 80ms (total 160ms).
- Don't run the pulse if the object was just created (it already has a spawn animation).

**Drag release spring approach**:
- Currently objects snap to final position on `dragend`. Add a brief overshoot: on `dragend`, Tween to `(finalX - 2, finalY - 2)` over 40ms, then to `(finalX, finalY)` over 80ms.
- Very subtle — just enough to feel physical, not distracting.

**Write files**:
- `src/components/StickyNote.jsx`
- `src/components/Shape.jsx`
- `src/components/Frame.jsx`

**Read files**: `src/hooks/useObjectAnimations.js` (to avoid conflicting with spawn animation), `src/handlers/objectHandlers.js` (dragend handling)

---

## Story Dependencies

```
Story 1 (DOM panels)       — independent, runs in parallel
Story 2 (canvas spawn)     — independent, runs in parallel with Story 1
Story 3 (AI wave)          — depends on Story 2
Story 4 (selection pulse)  — depends on Story 2 (to check animation state before pulsing)
```

Stories 1 and 2 run in parallel. Story 3 and 4 run after Story 2 merges.

---

## Key Files Reference

| File | Role |
|------|------|
| `src/styles/tokens/_motion.css` | M3 motion tokens (duration + easing) — use these, never hardcode |
| `src/styles/tokens/_a11y.css` | Reduced-motion token zeroing — pattern to follow |
| `src/hooks/useObjectAnimations.js` | New hook — animation state registry |
| `src/hooks/useBoard.js` | `addObject` — markSpawning hook point |
| `src/handlers/objectHandlers.js` | `handleDeleteWithCleanup` — markDying hook point |
| `src/hooks/useAI.js` | `createMutationTracker` + 2-pass — AI wave hook point |
| `src/components/StickyNote.jsx` | Protected — spawn, death, selection pulse tweens |
| `src/components/Shape.jsx` | Protected — spawn, death, selection pulse tweens |
| `src/components/Frame.jsx` | Protected — spawn, death, selection pulse tweens |
| `src/components/LineShape.jsx` | Protected — spawn, death tweens |
| `src/components/AIPanel.jsx/css` | Exit animation + unmount delay |
| `src/App.css` | Modal overlay + card animations |

---

## Verification

1. **DOM panels**: Open and close each panel — entrance/exit animations play, match timing tokens, reduced-motion users see instant transitions.
2. **Object spawn**: Create a sticky note, shape, and frame via toolbar — each animates in (scale+fade, ~200ms).
3. **Object delete**: Delete an object — it animates out before disappearing from Firestore.
4. **AI wave**: Use the AI panel to create a multi-object layout — frames appear first, children wave in staggered.
5. **Selection pulse**: Click to select an object — brief scale pulse visible. Drag and release — subtle spring.
6. **Build**: `npm run build` passes with no errors.
7. **Reduced motion**: Toggle `[data-reduced-motion]` — all animations disabled, no layout shift.
