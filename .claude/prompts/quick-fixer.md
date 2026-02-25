# Quick-Fixer Coder Prompt Template

Copy this template and fill in the bracketed sections when launching a quick-fixer coder agent.

---

Implementing story-[STORY-ID]: "[STORY TITLE]" in worktree [WORKTREE_PATH].

Use absolute paths only. CWD may not match target directory.

## Todo descriptions

[List every todo explicitly. The coder must confirm all are implemented before committing.]

- [ ] [Todo 1 description]
- [ ] [Todo 2 description]

## Write targets

[Files the coder will modify — one per line.]

- `[/absolute/path/to/file.jsx]`

## Read-only context

[Files to read for context — do not modify these.]

- `[/absolute/path/to/context-file.js]` — [what to look for]

## Edge cases

[Extract from codebase research. This is the highest-leverage section for reducing reviewer round-trips.]

- [Edge case 1]
- [Edge case 2]

## Pitfalls

- Konva Groups return `0` from `.width()` and `.height()` — use `.getClientRect()` for live bounding box
- `onDragMove` / async callbacks must read state from refs (`.current`), not closed-over props
- If adding `:focus-visible` CSS, ensure the outline color contrasts with the button background
- Firestore `batch.update` throws if the document is also being deleted in the same batch — use `batch.set({merge:true})` or guard with a deleteSet check
- Frame `childIds` and child `frameId` must always be updated atomically in the same `writeBatch`
- For new object types: include the CLAUDE.md 6-step checklist
- For CSS alignment fixes: verify the parent container has `display: flex` before adding flex-child properties
- For any new props/params: do not destructure or accept props/params you don't use. Verify every new prop is referenced.
- For any new `async` event handler: capture all React state and props you need into local `const` variables before the first `await`. Never read state after an `await`.

[Add any story-specific pitfalls below:]

- [Story-specific pitfall]

## Protected Konva files

IMPORTANT: Do NOT edit any of these protected files: BoardCanvas.jsx, StickyNote.jsx, Frame.jsx, Shape.jsx, LineShape.jsx, Cursors.jsx — even if you think an edit would improve them. Scope creep into protected files will block the review.

[If the story explicitly requires editing a protected file, replace the line above with:]
[The user has explicitly granted permission to edit [filename] for this story.]

## CWD mismatch note

Use absolute paths only — your CWD may not match the target directory. Do not use Glob/Grep without specifying the full absolute path.

## Return length cap

On success: 1 line — "done: <what changed>"
On deviation or decision required: 5 lines max
On error or blocked: uncapped — include full error output

## Completion

```
git -C [WORKTREE_PATH] add [file1] [file2]
git -C [WORKTREE_PATH] commit -m "fix: [short description]"
```
Return: "done: [what changed]"
