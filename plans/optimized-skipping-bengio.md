# Plan: Template System Overhaul

## Context
The current template system has a `board.template` boolean and a "Browse" filter tab, but is incomplete:
- The template toggle is a vague checkbox labeled "Show in Browse gallery"
- There is no snapshot mechanism — templates are just live boards
- There is no "use template" (clone) flow
- There is no "update template" workflow

The user wants a proper publish/snapshot/clone lifecycle with clear labeling and confirmation UX.

---

## Schema Changes

### Board document (`boards/{boardId}`)
Add fields:
```js
template: boolean,           // already exists
templateSnapshotAt: Timestamp | null,  // when snapshot was last taken
```

### New subcollection: `boards/{boardId}/templateSnapshot`
- Documents mirror the structure of `boards/{boardId}/objects`
- Written atomically via `writeBatch` when user publishes or updates a template
- Read when another user clones the template

---

## 1. BoardSettings.jsx — Replace Template Section

**Current**: A checkbox labeled "Show in Browse gallery"

**New**: Replace with a "Convert to Template" section when `board.template === false`, and an "Update Template" button when `board.template === true`.

### When board is NOT a template (`!board.template`):
```
[ Convert to Template ]  <-- primary action button
"Make this board available in the Browse gallery. Others can use it
as a starting point — they get their own copy; your board is unchanged."
```
- Clicking "Convert to Template":
  1. Reads all objects from `boards/{boardId}/objects`
  2. Writes snapshot to `boards/{boardId}/templateSnapshot` via `writeBatch` (chunk ≤500 per batch)
  3. Sets `board.template = true` and `board.templateSnapshotAt = serverTimestamp()` on the board doc
  4. Navigates user to Browse gallery (optional — or just shows success state)

### When board IS a template (`board.template === true`):
Show:
```
Template — published [date]
[ Update Template ]   [ Remove from Browse ]
```

**"Update Template" button**:
- Shows a confirmation dialog:
  ```
  Update template?
  This will replace the published version with your board's current state.
  Anyone who uses this template after this point will get the new version.
  Boards already created from this template are not affected.
  [ Cancel ]  [ Update Template ]  [ ] Don't show again
  ```
- "Don't show again" stores preference in `localStorage` (`templateUpdateWarningDismissed`)
- If dismissed: button triggers update directly with no dialog
- On confirm: re-snapshots objects (overwrite templateSnapshot subcollection), updates `templateSnapshotAt`

**"Remove from Browse" button**:
- Sets `board.template = false`, clears `templateSnapshotAt`
- Does NOT delete the templateSnapshot subcollection (cheap to keep, useful if re-published)

---

## 2. useBoardsList.js — New Functions

### `publishTemplate(boardId)`
```js
// 1. getDocs from boards/{boardId}/objects
// 2. delete existing boards/{boardId}/templateSnapshot/* in batch
// 3. write new snapshot docs in batches of ≤500
// 4. updateDoc board: { template: true, templateSnapshotAt: serverTimestamp() }
```

### `updateTemplate(boardId)`
Same as `publishTemplate` — re-snapshots and updates `templateSnapshotAt`. Can share implementation.

### `unpublishTemplate(boardId)`
```js
updateDoc: { template: false, templateSnapshotAt: deleteField() }
// Do NOT delete templateSnapshot subcollection
```

### `createBoardFromTemplate(templateBoardId, name, groupId, visibility)`
```js
// 1. createBoard(name, groupId, visibility) — get new boardId
// 2. getDocs from boards/{templateBoardId}/templateSnapshot
// 3. writeBatch: write each object to boards/{newBoardId}/objects
//    - Reset userId to currentUser.uid on each object
//    - Reset createdAt/updatedAt to serverTimestamp()
// 4. Return new board ref
```
Chunk in batches of ≤500. Objects are copied verbatim except `userId`, `createdAt`, `updatedAt`.

---

## 3. BoardSelector.jsx — "Use Template" Flow in Browse Tab

When `boardView === 'public'`, board cards should show a "Use Template" button (not just navigate to the board).

**"Use Template" click → show a dialog**:
```
Use "Pro/Cons for Food"?
Board name: [Pro/Cons for Food]  <-- pre-populated, editable
Group: [None ▼]                  <-- group picker (existing groups)
Visibility: [Private ▼]          <-- Private / Public / Open
[ Cancel ]  [ Create Board ]
```

On confirm:
1. Call `createBoardFromTemplate(templateId, name, groupId, visibility)`
2. Navigate to the new board

Template cards in Browse should also be visually distinct — a small "Template" badge on the card thumbnail.

---

## 4. Files to Modify

| File | Changes |
|------|---------|
| `src/components/BoardSettings.jsx` | Replace template checkbox with Convert/Update/Remove buttons + confirmation dialog |
| `src/hooks/useBoardsList.js` | Add `publishTemplate`, `updateTemplate`, `unpublishTemplate`, `createBoardFromTemplate` |
| `src/components/BoardSelector.jsx` | Add "Use Template" button + creation dialog in Browse view; add Template badge on cards |
| `src/components/BoardSettings.css` | Styles for new template section buttons and confirmation dialog |

**Protected files NOT touched**: BoardCanvas.jsx, StickyNote.jsx, Frame.jsx, Shape.jsx, LineShape.jsx, Cursors.jsx

**Protected testable files touched**:
- `src/hooks/useBoardsList.js` → requires `needsTesting: true`
- `src/components/BoardSettings.jsx` has a `.test.jsx` counterpart → requires `needsTesting: true`

---

## 5. Edge Cases

- **Large boards**: snapshot write is chunked in ≤500 batches. No upper limit on object count.
- **Re-publish after remove**: `templateSnapshot` subcollection may have stale data from before — always overwrite (delete old, write new) to avoid ghost objects.
- **Frame childIds**: copied verbatim — IDs inside the snapshot refer to the snapshot's own objects. On `createBoardFromTemplate`, the new object IDs will differ from the snapshot IDs. **Decision**: either preserve IDs (by using `batch.set(doc(db, ..., originalId), data)` instead of `addDoc`) or remap all IDs. Recommend **preserving IDs** — simpler, avoids remapping frame childIds/frameId references.
- **Viewing a template board directly**: clicking a template card in Browse should NOT navigate into edit mode — show a "Use Template" interstitial instead. (Or: navigating to a template board you don't own shows a banner "This is a template — use it to create your own copy.")
- **"Don't show again" scope**: localStorage key `templateUpdateWarningDismissed` — per browser, not per user. Acceptable given the low stakes.
- **templateSnapshotAt display**: format as "Published Jan 15, 2026" using `toLocaleDateString()`.

---

## 6. Verification

1. Open a board you own → Board Settings → Template section shows "Convert to Template" button with description
2. Click Convert → objects subcollection snapshot written → board appears in Browse tab
3. Edit the board (add a sticky note) → Settings → "Update Template" → confirmation dialog appears → "Don't show again" checkbox dismisses future warnings → confirm → snapshot updated
4. Log in as a different user → Browse tab → see the template card with "Template" badge → click "Use Template" → dialog pre-populated with template name → choose group/visibility → Create → new board appears in My Boards with all objects → original template board unchanged
5. Back as owner → Settings → "Remove from Browse" → board disappears from Browse, `board.template = false`
6. Run `npm run test -- BoardSettings` and `useBoardsList` tests → pass
