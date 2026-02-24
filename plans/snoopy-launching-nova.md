# Plan: Nested Groups + Delete Protection

## Context
Groups are currently flat (one level). Users want unlimited nesting (groups within groups), with subgroups rendered inline inside their parent GroupCard. Additionally, boards and groups should be protectable from accidental deletion.

## Scope
Two features, implemented together since they share schema and delete logic:
1. **Nested groups** — `parentGroupId` on groups, recursive GroupCard rendering, subgroup creation from the group header
2. **Delete protection** — `protected: boolean` field on boards and groups; protected items cannot be deleted without first unprotecting

---

## Data Schema Changes

### `groups/{groupId}` — add two fields:
```js
parentGroupId: string | null,  // null = root group
protected: boolean,            // default false
```
No `childGroupIds` array — children are derived by querying `where('parentGroupId', '==', groupId)`. Since `useGroupsList` already loads all visible groups into memory, tree building is done client-side from the flat list.

### `boards/{boardId}` — add one field:
```js
protected: boolean,  // default false
```

---

## Files to Change

### 1. `src/hooks/useGroupsList.js`
- Add `createSubgroup(parentGroupId, name, visibility)` — sets `parentGroupId` on the new group doc
- Rename/replace `deleteGroupDoc` with `deleteGroupCascade(groupId, allGroups, allBoards)`:
  - Collect all descendant group IDs recursively (client-side from flat list via `getDescendants`)
  - Collect all boards where `groupId` is in that descendant set
  - If any are `protected: true` — throw with list of protected item names
  - `writeBatch` delete all boards + groups
- Add `setGroupProtected(groupId, bool)` — `updateDoc` patch
- Add non-exported helper `getDescendants(groupId, allGroups)` — recursive walk

### 2. `src/hooks/useBoardsList.js`
- Add `setBoardProtected(boardId, bool)` — `updateDoc` patch

### 3. `src/components/GroupCard.jsx`
- New props: `subgroups`, `depth` (default 0), `onCreateSubgroup`, `onSetGroupProtected`, `onSetBoardProtected`, `allGroups`
- Render subgroups **above** boards inside expanded body, each as a nested `<GroupCard depth={depth+1}>`
- Visual depth: `style={{ '--depth': depth }}` → CSS left-border indentation
- "+ Add subgroup" button in header (owner only, hover-visible) → inline name input → calls `onCreateSubgroup(groupId, name)`
- Shield icon button in header to toggle `group.protected` → calls `onSetGroupProtected`
- Shield icon on each board card to toggle `board.protected` → calls `onSetBoardProtected`
- Delete button disabled (`opacity: 0.4`, `cursor: not-allowed`, tooltip) when item is `protected`
- Header badge: `N boards` + (if subgroups) `, M subgroups`
- On cascade delete blocked: show modal listing protected items

### 4. `src/components/BoardSelector.jsx`
- Build tree from flat `groupsProp` using `parentGroupId`:
  ```js
  const rootGroups = groupsProp.filter(g => !g.parentGroupId);
  const childrenOf = (id) => groupsProp.filter(g => g.parentGroupId === id);
  ```
- Pass `subgroups={childrenOf(group.id)}` to each root `<GroupCard>`
- Wire `onCreateSubgroup`, `onSetGroupProtected`, `onSetBoardProtected`

### 5. `src/components/GroupPage.jsx`
- Breadcrumb: walk `parentGroupId` up the chain → `Home > Parent > Current`
- Back button: navigate to parent group (if exists) else home
- Subgroups section above boards when group has children

### 6. `src/hooks/useRouting.js`
- No URL format change — subgroup slugs are globally unique, existing routing handles them

### 7. `src/components/GroupCard.css`
- `.group-card--nested`: slightly reduced border-radius, lighter border, smaller header padding
- CSS `--depth` for `padding-left: calc(var(--depth, 0) * 12px)` on nested cards
- `.group-card-subgroup-section`: section wrapper above board grid
- `.group-card-add-subgroup`: inline input row
- `.board-card-protect-btn`, `.group-card-protect-btn`: shield buttons, styled like existing delete/move buttons
- `.board-card--protected`, `.group-card--protected`: small filled shield badge

---

## Tree Building Pattern

```js
// BoardSelector.jsx
const rootGroups = groupsProp.filter(g => !g.parentGroupId);
const childrenOf = (id) => groupsProp.filter(g => g.parentGroupId === id);
const boardsOf = (groupId) => boards.filter(b => b.groupId === groupId);

// Each GroupCard gets:
// subgroups={childrenOf(group.id)}  boards={boardsOf(group.id)}
// GroupCard renders each subgroup as <GroupCard subgroups={childrenOf(sub.id)} depth={depth+1} .../>
```

---

## Delete Protection UX
- Protected items show a filled shield badge
- Delete button is visually disabled with tooltip "Remove protection first"
- Cascade delete blocked if any descendant is protected: modal lists the protected items by name
- No force-delete option — user must unprotect manually

---

## Implementation Sequence
1. `useGroupsList.js` — createSubgroup, deleteGroupCascade, setGroupProtected, getDescendants
2. `useBoardsList.js` — setBoardProtected
3. `GroupCard.css` — nesting + protection styles
4. `GroupCard.jsx` — subgroup rendering, add-subgroup UI, protect buttons, disabled delete
5. `BoardSelector.jsx` — tree building, prop wiring
6. `GroupPage.jsx` — breadcrumbs, subgroups section

---

## Verification
- Create root group → add subgroup inside it → add board to subgroup → verify nested render
- Expand/collapse both levels independently
- Protect a board → try delete → verify button disabled
- Protect a subgroup → delete parent → verify blocked modal lists protected item
- Unprotect all → delete parent → verify cascade removes subgroup + boards
- Navigate to subgroup's GroupPage → verify breadcrumb shows ancestor chain
