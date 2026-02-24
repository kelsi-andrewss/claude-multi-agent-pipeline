# Plan: Firestore server-side security enforcement

## Context

Board-level access enforcement is currently client-side only (`canEdit` flag in App.jsx). A malicious authenticated user can bypass the React app and write directly to Firestore. This plan hardens `firestore.rules` to enforce the same ACL server-side.

The existing rules already have a solid structure (owner/member/visibility/groupAdmin model). The gaps are:
1. **Board create** — any auth'd user can create a board owned by someone else
2. **Board update ownerId** — editors/group admins can transfer ownership
3. **Board update ACL fields** — editors can change `members`/`visibility` (should be owner-only)
4. **Group create** — any auth'd user can create a group with arbitrary ownerId
5. **Group update ownerId** — group admins can transfer group ownership
6. **Object field injection** — editors can write arbitrary fields to object docs
7. **Object userId spoofing** — editors can write any `userId` on object create

---

## File to Modify

**Write target:**
- `firestore.rules`

No React source files are touched. No `needsTesting` flag needed (no `.test.*` counterpart).

---

## Implementation

### Gap 1 & 4 — Create must enforce `ownerId == caller`

**boards create:**
```
allow create: if request.auth != null
  && request.resource.data.ownerId == request.auth.uid;
```

**groups create:**
```
allow create: if request.auth != null
  && request.resource.data.ownerId == request.auth.uid;
```

### Gap 2 & 5 — Update must lock `ownerId` (except global admin)

Add `request.resource.data.ownerId == resource.data.ownerId` as a mandatory condition on all non-admin update paths for both `boards` and `groups`. Legacy boards (`ownerId == null`) satisfy `null == null` so they are unaffected.

### Gap 3 — Restrict ACL field writes to owner/groupAdmin/globalAdmin

Use `diff().affectedKeys()` to distinguish ACL writes from content writes:

```
function boardAclKeys() {
  return ['members', 'visibility', 'ownerId'];
}
function boardContentKeys() {
  return ['name', 'thumbnail', 'thumbnailLight', 'thumbnailDark',
          'groupId', 'protected', 'template', 'templateSnapshotAt', 'updatedAt'];
}
function touchedKeys() {
  return request.resource.data.diff(resource.data).affectedKeys();
}
function isAclWrite() { return touchedKeys().hasAny(boardAclKeys()); }
function isContentOnlyWrite() { return touchedKeys().hasOnly(boardContentKeys()); }
```

Updated board update rule:
```
allow update: if request.auth != null
  && (
    isGlobalAdmin()
    || (
      request.resource.data.ownerId == resource.data.ownerId
      && (
        isLegacyBoard()
        || isOwner()
        || isGroupAdmin()
        || (isOpen() && !isAclWrite())
        || (isMember() && resource.data.members[request.auth.uid] == 'editor'
            && isContentOnlyWrite())
      )
    )
  );
```

Note: `inviteMember`/`removeMember` writes a map sub-key under `members` — Firestore's `diff().affectedKeys()` returns the top-level key `members`, so these correctly register as ACL writes and are blocked for editors. Only owners/group admins/global admins can invite/remove members. This is already the intended behavior.

### Gap 6 — Object field allowlist

Exact allowed fields verified from code search across `objectCreationHandlers.js`, `stageHandlers.js`, `objectHandlers.js`, `toolExecutors.js`:

```
function allowedObjectKeys() {
  return [
    'type', 'x', 'y', 'width', 'height', 'color', 'text', 'title',
    'rotation', 'zIndex', 'frameId', 'childIds', 'strokeWidth', 'points',
    'userId', 'createdAt', 'updatedAt', 'fontSize',
    'startConnectedId', 'startConnectedPort',
    'endConnectedId', 'endConnectedPort'
  ];
}
function validObjectFields() {
  return request.resource.data.keys().hasOnly(allowedObjectKeys());
}
```

Key notes:
- `title` is written only by `objectCreationHandlers.handleAddFrame` and read by AI context
- Connector field names are `startConnectedId/Port` and `endConnectedId/Port` (NOT `connectedStart/End` or `startPort/endPort` — those names don't exist)
- `hasOnly` on update checks the final merged document, which is correct

### Gap 7 — userId spoofing on create

```
allow create: if request.auth != null
  && (isGlobalAdmin() || boardIsLegacy() || boardIsOpen() || boardIsOwner() || boardIsEditor() || boardIsGroupAdmin())
  && validObjectFields()
  && (!('userId' in request.resource.data) || request.resource.data.userId == request.auth.uid);
```

The `!('userId' in ...)` arm handles AI executor paths that omit `userId` entirely (confirmed: `toolExecutors.js` AI creation calls don't always include `userId`).

---

## Complete updated `firestore.rules`

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {

    function isGlobalAdmin() {
      return get(/databases/$(database)/documents/users/$(request.auth.uid)).data.role == 'admin';
    }

    match /users/{userId} {
      allow read: if request.auth != null;
      allow create: if request.auth != null && request.auth.uid == userId
        && !('role' in request.resource.data);
      allow update: if request.auth != null && request.auth.uid == userId
        && (request.resource.data.role == resource.data.role || isGlobalAdmin());
    }

    match /boards/{boardId} {
      function isOwner()       { return request.auth.uid == resource.data.ownerId; }
      function isMember()      { return resource.data.members != null && request.auth.uid in resource.data.members; }
      function isPublic()      { return resource.data.visibility == 'public'; }
      function isOpen()        { return resource.data.visibility == 'open'; }
      function isLegacyBoard() { return !('ownerId' in resource.data) || resource.data.ownerId == null; }
      function isGroupAdmin() {
        return resource.data.groupId != null
          && exists(/databases/$(database)/documents/groups/$(resource.data.groupId))
          && get(/databases/$(database)/documents/groups/$(resource.data.groupId)).data.members != null
          && get(/databases/$(database)/documents/groups/$(resource.data.groupId)).data.members[request.auth.uid] == 'admin';
      }

      function boardAclKeys() {
        return ['members', 'visibility', 'ownerId'];
      }
      function boardContentKeys() {
        return ['name', 'thumbnail', 'thumbnailLight', 'thumbnailDark',
                'groupId', 'protected', 'template', 'templateSnapshotAt', 'updatedAt'];
      }
      function touchedKeys() {
        return request.resource.data.diff(resource.data).affectedKeys();
      }
      function isAclWrite()        { return touchedKeys().hasAny(boardAclKeys()); }
      function isContentOnlyWrite() { return touchedKeys().hasOnly(boardContentKeys()); }

      allow read: if request.auth != null
        && (isGlobalAdmin() || isLegacyBoard() || isPublic() || isOpen() || isOwner() || isMember() || isGroupAdmin());

      allow create: if request.auth != null
        && request.resource.data.ownerId == request.auth.uid;

      allow update: if request.auth != null
        && (
          isGlobalAdmin()
          || (
            request.resource.data.ownerId == resource.data.ownerId
            && (
              isLegacyBoard()
              || isOwner()
              || isGroupAdmin()
              || (isOpen() && !isAclWrite())
              || (isMember() && resource.data.members[request.auth.uid] == 'editor'
                  && isContentOnlyWrite())
            )
          )
        );

      allow delete: if request.auth != null
        && (isGlobalAdmin() || isLegacyBoard() || isOwner());

      match /objects/{objectId} {
        function boardData()         { return get(/databases/$(database)/documents/boards/$(boardId)).data; }
        function boardIsLegacy()     { return !('ownerId' in boardData()) || boardData().ownerId == null; }
        function boardIsPublic()     { return boardData().visibility == 'public'; }
        function boardIsOpen()       { return boardData().visibility == 'open'; }
        function boardIsOwner()      { return request.auth.uid == boardData().ownerId; }
        function boardIsMember()     { return boardData().members != null && request.auth.uid in boardData().members; }
        function boardIsEditor()     { return boardData().members != null && boardData().members[request.auth.uid] == 'editor'; }
        function boardIsGroupAdmin() {
          return boardData().groupId != null
            && exists(/databases/$(database)/documents/groups/$(boardData().groupId))
            && get(/databases/$(database)/documents/groups/$(boardData().groupId)).data.members != null
            && get(/databases/$(database)/documents/groups/$(boardData().groupId)).data.members[request.auth.uid] == 'admin';
        }

        function allowedObjectKeys() {
          return [
            'type', 'x', 'y', 'width', 'height', 'color', 'text', 'title',
            'rotation', 'zIndex', 'frameId', 'childIds', 'strokeWidth', 'points',
            'userId', 'createdAt', 'updatedAt', 'fontSize',
            'startConnectedId', 'startConnectedPort',
            'endConnectedId', 'endConnectedPort'
          ];
        }
        function validObjectFields() {
          return request.resource.data.keys().hasOnly(allowedObjectKeys());
        }

        allow read: if request.auth != null
          && (isGlobalAdmin() || boardIsLegacy() || boardIsPublic() || boardIsOpen()
              || boardIsOwner() || boardIsMember() || boardIsGroupAdmin());

        allow create: if request.auth != null
          && (isGlobalAdmin() || boardIsLegacy() || boardIsOpen() || boardIsOwner()
              || boardIsEditor() || boardIsGroupAdmin())
          && validObjectFields()
          && (!('userId' in request.resource.data) || request.resource.data.userId == request.auth.uid);

        allow update: if request.auth != null
          && (isGlobalAdmin() || boardIsLegacy() || boardIsOpen() || boardIsOwner()
              || boardIsEditor() || boardIsGroupAdmin())
          && validObjectFields();

        allow delete: if request.auth != null
          && (isGlobalAdmin() || boardIsLegacy() || boardIsOpen() || boardIsOwner()
              || boardIsEditor() || boardIsGroupAdmin());
      }
    }

    match /groups/{groupId} {
      function isGroupOwner()  { return request.auth.uid == resource.data.ownerId; }
      function isGroupMember() { return resource.data.members != null && request.auth.uid in resource.data.members; }
      function isGroupPublic() { return resource.data.visibility == 'public'; }
      function isGroupOpen()   { return resource.data.visibility == 'open'; }

      allow read: if request.auth != null
        && (isGlobalAdmin() || isGroupPublic() || isGroupOpen() || isGroupOwner() || isGroupMember());

      allow create: if request.auth != null
        && request.resource.data.ownerId == request.auth.uid;

      allow update: if request.auth != null
        && (
          isGlobalAdmin()
          || (
            request.resource.data.ownerId == resource.data.ownerId
            && (isGroupOwner() || (isGroupMember() && resource.data.members[request.auth.uid] == 'admin'))
          )
        );

      allow delete: if request.auth != null
        && (isGlobalAdmin() || isGroupOwner());
    }
  }
}
```

---

## Known pre-existing issue (not fixed here)

`AdminPanel.jsx` uses `setDoc` with merge to grant `role: 'admin'` to other users. The current `users` update rule requires `request.auth.uid == userId`, so an admin granting another user admin access would fail. This is a pre-existing bug unrelated to this plan — fixing it would require a separate rule change (e.g. `|| (isGlobalAdmin() && request.resource.data.keys().hasOnly(['role']))`) and is out of scope here.

---

## Pitfalls
- `diff().affectedKeys()` on a map sub-key write (e.g. `members.uid123`) returns the top-level key `members` — this is intentional and correct for the ACL write detection
- Legacy boards (`ownerId == null`) satisfy `null == null` in the ownerId lock — no regression
- `validObjectFields()` on update checks the full merged document, not just the patched keys — this is correct Firestore behavior and catches stored dirty data too
- If a new field is ever added to the object schema, `allowedObjectKeys()` must be updated at the same time or writes will be rejected
- The `title` field on frame objects is real — omitting it from `allowedObjectKeys()` would break frame creation

---

## Verification
1. A non-owner editor attempts to write `visibility: 'public'` to a private board → rejected
2. A non-owner attempts to create a board with `ownerId: 'someone-elses-uid'` → rejected
3. An editor creates an object with an unknown field `__proto__: {...}` → rejected
4. An editor creates an object with `userId: 'victim-uid'` → rejected
5. An owner invites a member (writes `members.uid`) → accepted
6. An editor updates `name` on a board → accepted
7. An editor tries `inviteMember` (writes `members.uid`) → rejected (ACL write)
8. Legacy board (no ownerId) — all existing mutations → accepted (isLegacyBoard passthrough)
9. `firebase deploy --only firestore:rules` — deploys without error
