# Routing Overhaul: Structured Hash-Based URLs

## Context

The current routing uses ambiguous single-segment hashes (`#groupSlug`, `#boardId`) that require a localStorage heuristic to distinguish groups from boards. This has caused persistent navigation bugs and the `__ungrouped__` sentinel leaks into state. Replacing with structured, prefix-based URLs eliminates all ambiguity.

## New URL Format

```
Home:              (no hash)
Root group:        #group/<slug>
Subgroup:          #group/<parentSlug>/subgroup/<childSlug>
Deep subgroup:     #group/<rootSlug>/subgroup/<midSlug>/subgroup/<leafSlug>
Board in group:    #group/<slug>/board/<boardId>
Board in subgroup: #group/<parentSlug>/subgroup/<childSlug>/board/<boardId>
Ungrouped board:   #board/<boardId>
```

## Files to Change (in order)

### 1. `src/utils/slugUtils.js`
- Remove `UNGROUPED_SLUG` and `groupToSlug()`
- Keep `toSlug()` and `findGroupBySlug()` (remove `__ungrouped__` guard from findGroupBySlug)
- Add `buildSlugChain(group, allGroups)` — walks parentGroupId up to root, returns `string[]`
- Add `resolveSlugChain(slugChain, allGroups)` — walks slug chain down from root, returns group object
- Add `isSlugTaken(slug, parentGroupId, allGroups, excludeGroupId?)` — checks sibling collision

### 2. `src/hooks/useRouting.js` — Full rewrite
- **State**: Replace `groupSlug: string|null` with `groupPath: string` (slugs joined by `/`). Derive `groupSlugs = groupPath ? groupPath.split('/') : []`. Using a string avoids array identity issues in effect deps.
- **`parseHash()`**: Token-based parser — reads `group/`, `subgroup/`, `board/` prefixes. Falls back to `parseLegacyHash()` for old URLs.
- **`buildHash(groupSlugs, boardId)`**: Constructs `group/<s>/subgroup/<s>/board/<id>` from state.
- **Navigation functions**:
  - `navigateHome()` — `setGroupPath(''), setBoardId(null), setBoardName('')`
  - `navigateToGroup(slugChain)` — accepts `string[]`, sets `groupPath = chain.join('/')`
  - `navigateToBoard(slugChain, id, name)` — accepts `string[]` (empty for ungrouped) + board info
- **Hash sync effect**: Use `buildHash()`. Depend on `[boardId, boardName, groupPath]` (all primitives).
- **Legacy redirect**: One-time mount effect converts old hash format to new.
- **Return**: `groupSlugs` (derived array), `setGroupSlugs` (wrapper around setGroupPath), rest same.

### 3. `src/hooks/useGroupsList.js`
- **`createGroup()` (line 67-87)**: Replace auto-suffix logic with collision check. Throw `Error('SLUG_TAKEN')` if `groups.some(g => g.slug === slug && !g.parentGroupId)`.
- **`createSubgroup()` (line 147-167)**: Same — check siblings with same `parentGroupId`. Throw `Error('SLUG_TAKEN')` on collision.

### 4. `src/App.jsx`
- Destructure `groupSlugs, setGroupSlugs` instead of `groupSlug, setGroupSlug`
- **Board metadata effect (lines 112-123)**: Use `buildSlugChain(boardGroup, groups)` instead of `groupToSlug(boardGroup)`. Check `groupSlugs.length === 0` instead of `!groupSlug`.
- **`aiCreateBoard` (line 128)**: `setGroupSlugs(boardGroup ? buildSlugChain(boardGroup, groups) : [])`
- **View switch (line 479)**: `groupSlugs.length > 0` instead of `groupSlug && groupSlug !== '__ungrouped__'`
- **GroupPage props**: Pass `groupSlugs={groupSlugs}` instead of `groupSlug`
- **onSelectBoard (line 498)**: Already calls `navigateToBoard` — pass `[]` instead of `null`

### 5. `src/components/GroupPage.jsx`
- Props: `groupSlugs` replaces `groupSlug`
- Resolve group: `resolveSlugChain(groupSlugs, groups)` instead of `findGroupBySlug`
- Back button: `onNavigateToGroup(buildSlugChain(parent, groups))`
- Breadcrumb clicks: `onNavigateToGroup(buildSlugChain(ancestor, groups))`
- Subgroup click: `onNavigateToGroup(buildSlugChain(sub, groups))`
- Board click: `onOpenBoard(groupSlugs, b.id, b.name)`
- Remove `__ungrouped__` filter (line 89)

### 6. `src/components/GroupCard.jsx`
- Import `buildSlugChain` instead of `groupToSlug`
- Remove `const slug = groupToSlug(group)` (line 25)
- Group click (line 41): `onNavigateToGroup(buildSlugChain(group, allGroups))`
- Board click (line 146): `onNavigateToBoard(group ? buildSlugChain(group, allGroups) : [], b.id, b.name)`

### 7. `src/components/HeaderLeft.jsx`
- Import `buildSlugChain` instead of `groupToSlug`
- Board switcher click: `onSwitchBoard(bGroup ? buildSlugChain(bGroup, groupsList) : [], b.id, b.name)`

### 8. `src/components/BoardSelector.jsx`
- Remove `groupToSlug` import
- Standalone board click (line 619): Pass `[]` instead of `null`
- Drag-drop: Replace `'__ungrouped__'` sentinel with `null` (use a separate boolean for drop-target highlight)
- **"Name already taken" UX**: Wrap `createGroup`/`createSubgroup` calls in try/catch. On `SLUG_TAKEN`, show inline error below the name input.

### 9. Test files
- Rewrite `useRouting.test.js` for new URL format and `parseHash` behavior
- Add tests for `buildSlugChain`, `resolveSlugChain`, `isSlugTaken` in `slugUtils.test.js`
- Update `GroupPage.test.js` for `groupSlugs` prop

## Backward Compatibility

`parseLegacyHash()` handles old URLs:
- `#slug/boardId` -> `{ groupSlugs: [slug], boardId }`
- `#slug` -> `{ groupSlugs: [slug], boardId: null }`
- `#boardId` (matched via localStorage) -> `{ groupSlugs: [], boardId }`
- `#__ungrouped__` -> `{ groupSlugs: [], boardId: null }`

A one-time mount effect rewrites old URLs to new format.

## Verification

1. Build passes (`npm run build`)
2. All tests pass (`npx vitest run`)
3. Manual checks:
   - Click root group -> URL is `#group/<slug>`
   - Click subgroup -> URL is `#group/<parent>/subgroup/<child>`
   - Click board in group -> URL appends `/board/<id>`
   - Click ungrouped board -> URL is `#board/<id>`
   - Back button walks up correctly
   - Breadcrumb links work
   - Load old-format URL -> redirects to new format
   - Create group with duplicate name -> shows "name already taken"
   - Browser back/forward works
