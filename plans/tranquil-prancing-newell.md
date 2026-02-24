# Epic Plan: Joy & Delight Features

## Context

CollabBoard is functional but utilitarian. This epic adds 8 features across 4 categories — surprise/discovery, playful tools, social/multiplayer, and AI whimsy — that make the app feel alive and fun to use. Each feature is scoped to be achievable independently with no breaking changes to existing systems.

---

## Epic

**ID**: (next available — check epics.json)
**Title**: Joy & Delight
**Branch**: epic/joy-and-delight

---

## Stories

### Story 1 — Board Confetti on Milestones
**Agent**: quick-fixer | **Model**: haiku | **Trivial**: no

**What**: When a user hits a milestone (creates 10th object, or AI completes a tool call successfully), trigger a Konva-rendered confetti burst at the milestone object's position. Confetti is purely visual — temporary Konva shapes (small colored Rects/Circles) animated via `requestAnimationFrame` or Konva tweens, removed after ~1.5s. No Firestore writes.

**Write files**:
- `src/components/Confetti.jsx` (new) — Konva confetti animation component
- `src/App.jsx` — mount Confetti layer, track object count milestone, wire AI success callback

**Read files**: `src/ai/useAI.js`, `src/components/BoardCanvas.jsx` (for layer structure reference)

**Pitfalls**:
- Do not add the Confetti layer inside `BoardCanvas.jsx` (protected). Mount it as a sibling Konva `Layer` in `App.jsx` or render it outside the canvas entirely using DOM-based CSS animation.
- Konva Groups return 0 from `.width()/.height()` — use `.getClientRect()` for position reference.
- Use `requestAnimationFrame` + `clearTimeout` cleanup in a `useEffect` return to prevent memory leaks.

---

### Story 2 — Konami Code Easter Egg
**Agent**: quick-fixer | **Model**: haiku | **Trivial**: yes

**What**: Detect the Konami code (↑↑↓↓←→←→BA) via the existing global `keydown` listener in `App.jsx`. On activation: apply a CSS class to the canvas wrapper that triggers a `transform: rotate(360deg)` animation (1 spin, ~600ms, `ease-in-out`). One-and-done per activation; sequence resets after success.

**Write files**:
- `src/App.jsx` — add `konamiSequenceRef`, detection logic in existing keydown handler
- `src/App.css` (or relevant CSS file) — `.konami-spin` keyframe + class

**Read files**: `src/App.jsx` (keydown handler, lines 318–543)

**Pitfalls**:
- The keydown handler uses empty deps — read state via refs only. The `konamiSequenceRef` pattern is already described in the codebase exploration.
- Add the Konami check before the `if (isEditing) return` guard — arrow keys won't fire when an input is focused, but we still want to clear the partial sequence on non-Konami keys if needed.
- `transform: rotate` on the canvas wrapper should not conflict with Konva's internal transform matrix — they're on separate DOM layers.

---

### Story 3 — Ephemeral Reactions System
**Agent**: architect | **Model**: sonnet | **Trivial**: no

**What**: Double-click any board object to send a floating emoji reaction. The emoji (chosen from a small picker: 👍 🔥 👀 ❤️ ✨) floats upward and fades out over ~1.5s on all connected users' screens. Reactions are written to RTDB at `boards/{boardId}/reactions/{reactionId}` with a short TTL cleanup (client removes its own after animation + `onDisconnect().remove()` as fallback). Never written to Firestore.

**Write files**:
- `src/hooks/useReactions.js` (new) — RTDB subscribe/publish for reactions
- `src/components/ReactionPicker.jsx` (new) — small emoji picker popover (5 emojis, DOM-based, not canvas)
- `src/components/ReactionOverlay.jsx` (new) — animates incoming reactions as floating DOM elements above the canvas
- `src/App.jsx` — wire double-click on objects → show picker, mount ReactionOverlay

**Read files**: `src/hooks/usePresence.js` (RTDB pattern), `src/components/BoardCanvas.jsx` (object click handling)

**Pitfalls**:
- Double-click on canvas objects fires `onDblClick` in Konva — wire this at the object level or stage level, NOT inside protected Konva component files. Handle it in `App.jsx` via `onObjectDblClick` callback passed down.
- RTDB `onDisconnect().remove()` fires when the connection drops, not on page unload — also use `beforeunload` + manual `remove()` for clean cleanup.
- Floating reaction DOM elements need `pointer-events: none` so they don't block canvas interaction.
- Reactions should be positioned in screen coordinates (apply stage scale/offset transform to convert canvas coords → screen coords).

---

### Story 4 — Follow Me Viewport Sync
**Agent**: architect | **Model**: sonnet | **Trivial**: no

**What**: A user can click any collaborator's cursor label/avatar to enter "follow mode" — their viewport (pan + zoom) syncs to that user's in real time. An indicator shows "Following [Name]" with an Escape-to-exit affordance. The followed user's viewport is broadcast via RTDB presence (add `stageX`, `stageY`, `stageScale` to the presence entry, throttled alongside cursor updates).

**Write files**:
- `src/hooks/usePresence.js` — add `stageX/Y/Scale` to presence writes (throttled, same 50ms gate)
- `src/hooks/useFollowMode.js` (new) — tracks which userId is being followed, syncs stagePos/stageScale
- `src/components/Cursors.jsx` — **requires explicit user permission** (protected file) — add clickable cursor label
- `src/components/FollowModeIndicator.jsx` (new) — "Following [Name]" pill with Escape-to-exit button
- `src/App.jsx` — wire follow mode into `useCanvasViewport`, mount indicator

**Read files**: `src/hooks/useCanvasViewport.js`, `src/hooks/usePresence.js`, `src/App.jsx` (stagePos/stageScale usage)

**Pitfalls**:
- `Cursors.jsx` is a protected Konva file — user must approve edits before this story runs.
- `useCanvasViewport` persists to localStorage — when in follow mode, skip the localStorage write or the followed state will "stick" after exiting follow mode.
- Throttle the viewport broadcast to the same 50ms gate as cursor updates to avoid RTDB write amplification.
- When the followed user leaves the board, automatically exit follow mode and notify the user.

**Note**: This story requires permission to edit `Cursors.jsx`. Surface this to the user before running.

---

### Story 5 — AI Board Narrator
**Agent**: quick-fixer | **Model**: haiku | **Trivial**: no

**What**: Add a new AI tool `narrateBoard` that reads all current board objects (text, type, color) and asks Gemini to write a short, absurd 3–5 sentence story incorporating the board content. Output is placed as a new sticky note in the top-left empty area of the board.

**Write files**:
- `src/ai/toolDeclarations.js` — add `narrateBoard` tool schema (no parameters needed)
- `src/ai/toolExecutors.js` — add executor: collects `objs()` text/type/color → formats as context → Gemini generates story → `act().addObject(sticky)`

**Read files**: `src/ai/toolDeclarations.js`, `src/ai/toolExecutors.js`, `src/ai/useAI.js`

**Pitfalls**:
- The executor runs *after* the AI already called the tool — don't make a second Gemini call inside the executor. Instead, pass the narrative content as a tool argument (have Gemini generate the text as part of the tool call itself, using `narrateBoard({ story: "..." })`).
- Update the system prompt to describe the tool and instruct Gemini to generate the story text directly in the tool arguments.
- `findNonOverlappingPos` is available in executor context — use it to avoid placing the sticky on top of existing objects.

---

### Story 6 — Vibe Check Button
**Agent**: quick-fixer | **Model**: haiku | **Trivial**: no

**What**: A toolbar button (sparkle icon) that sends a summary of all board objects to Gemini and asks for a one-word vibe. The result displays as a temporary toast notification for 3s (e.g., "Board vibe: **chaotic**"). Uses the existing rate-limit system. Not an AI tool — fires directly from the button via a one-shot Gemini call.

**Write files**:
- `src/components/HeaderRight.jsx` (or `HeaderLeft.jsx`) — add Vibe Check button
- `src/hooks/useVibeCheck.js` (new) — one-shot Gemini call, returns vibe string, respects rate limit
- `src/components/VibeToast.jsx` (new) — temporary toast component (3s auto-dismiss)

**Read files**: `src/hooks/useAI.js` (for rate-limit pattern), `src/components/HeaderRight.jsx`, `src/firebase/config.js` (Vertex AI init)

**Pitfalls**:
- Don't reuse the `ChatSession` from `useAI` — that's stateful and would corrupt the board AI conversation. Create a fresh one-shot `GenerativeModel.generateContent()` call.
- Respect the 50 req/24h rate limit — check `sessionStorage` before firing (same key as useAI: `aiRequestCount` / `aiRequestDate`).
- Toast should have `pointer-events: none` when fading out to avoid blocking canvas clicks.

---

### Story 7 — Free-draw Scribble Tool
**Agent**: architect | **Model**: sonnet | **Trivial**: no

**What**: A pencil/scribble tool in the toolbar. While the tool is active, `mousemove` events on the canvas accumulate points into a temporary preview line; on `mouseup`, the line is committed to Firestore as a `line` object with `points: [x1,y1,x2,y2,...]`. Uses the existing line schema — no schema changes needed. Thin stroke (2px), current user's theme color.

**Write files**:
- `src/handlers/stageHandlers.js` — add scribble draw state (`isScribbling`, accumulated points ref) to `handleMouseDown/Move/Up`
- `src/components/HeaderLeft.jsx` — add Pencil tool button, set `pendingTool = 'scribble'`
- `src/App.jsx` — wire scribble commit: when mouseup with scribble active, call `addObject({ type: 'line', points: [...] })`

**Read files**: `src/handlers/stageHandlers.js` (full), `src/hooks/useBoard.js` (addObject signature)

**Pitfalls**:
- `stageHandlers.js` is a protected testable file — user must approve edits; story should set `needsTesting: true`.
- Points accumulate fast at high pointer speed — throttle point capture to every ~5px of movement (check Euclidean distance from last point before pushing).
- The preview line during drawing should be a DOM overlay or Konva temporary layer, NOT written to Firestore on every mousemove.
- When `pendingTool === 'scribble'`, disable the default click-to-deselect behavior so a click starts a scribble.

**Note**: This story edits `stageHandlers.js` (protected testable). Set `needsTesting: true`.

---

### Story 8 — Moodboard Auto-Layout
**Agent**: architect | **Model**: sonnet | **Trivial**: no

**What**: An AI tool `moodboardLayout` (or toolbar button) that rearranges all selected objects (or all objects if nothing selected) into an aesthetic masonry-style grid — varied column widths, objects sized to a "card" aspect ratio, soft visual grouping by color. This is a pure board mutation: batch `updateObject` calls moving x/y positions. No schema changes.

**Write files**:
- `src/utils/moodboardUtils.js` (new) — masonry layout algorithm: takes objects array, returns `{id, x, y, width, height}` patch array
- `src/ai/toolDeclarations.js` — add `moodboardLayout` tool schema
- `src/ai/toolExecutors.js` — add executor: reads `objs()`, calls `moodboardUtils.computeMoodboardLayout()`, batch-updates positions

**Read files**: `src/utils/frameUtils.js` (layout algorithm patterns), `src/ai/toolExecutors.js` (batch update patterns), `src/handlers/objectHandlers.js`

**Pitfalls**:
- Masonry layout must respect the frame system: don't move objects that have a `frameId` unless the frame is also being moved. Either skip framed objects or move the frame + children atomically.
- Use `writeBatch` for the position updates — this will touch many objects at once.
- `moodboardUtils.js` is a new file in `src/utils/` — it will be a protected testable file from the moment it's created. Set `needsTesting: true`.

---

## Story Dependencies

- Stories 1–3, 5–6 are fully independent — can run in parallel.
- Story 4 (Follow Me) depends on nothing but requires `Cursors.jsx` permission.
- Story 7 (Scribble) depends on nothing but requires `stageHandlers.js` permission + testing.
- Story 8 (Moodboard) depends on nothing but requires `moodboardUtils.js` testing.

## Files Requiring Permission

Before running:
- **Story 4**: Request permission to edit `src/components/Cursors.jsx` (protected Konva file)
- **Story 7**: Request permission to edit `src/handlers/stageHandlers.js` (protected testable, `needsTesting: true`)
- **Story 8**: New `src/utils/moodboardUtils.js` is auto-protected testable on creation (`needsTesting: true`)

## Verification

Each story verified independently:
1. **Confetti**: Create 10 objects → confetti burst appears and clears within 2s
2. **Konami**: Type ↑↑↓↓←→←→BA → canvas spins once
3. **Reactions**: Double-click object → picker appears → emoji floats on all connected clients
4. **Follow Me**: Click collaborator cursor → viewport locks to theirs → Escape exits
5. **Narrator**: Ask AI "narrate this board" → story sticky note created
6. **Vibe Check**: Click sparkle button → toast shows one-word vibe for 3s
7. **Scribble**: Select pencil → draw on canvas → line committed to Firestore
8. **Moodboard**: Ask AI "moodboard layout" → objects rearrange into masonry grid
