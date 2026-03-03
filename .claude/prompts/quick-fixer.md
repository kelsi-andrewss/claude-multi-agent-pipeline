# Quick-Fixer Coder Prompt Template

Copy this template and fill in the bracketed sections when launching a quick-fixer coder agent.

---

Implementing story-[STORY-ID]: "[STORY TITLE]" in worktree [WORKTREE_PATH].

Use absolute paths only. CWD may not match target directory.

## Todo descriptions

[List every todo explicitly. The coder must confirm all are implemented before committing.]

- [ ] [Todo 1 description]
- [ ] [Todo 2 description]

## Validation-first

[Include this section ONLY if the story has validation_first: true. Delete it otherwise.]

Before modifying any write target, write a failing test that captures the expected behavior for each todo. Run the test. Confirm it fails for the right reason. Then implement. Then confirm it passes. If no test infrastructure exists for the target files, skip this step and note it in your return message.

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

## Ambiguity protocol

If any todo requires a judgment call not covered by this plan (naming, UX behavior, business logic), implement the most conservative option and leave a `// DECISION: [description of what was chosen and why]` comment. Do NOT guess at intent. Report all DECISION comments in your return message.

## Pitfalls

[Query `pm_list_patterns` with categories matching this story's file types. Include only active patterns with severity 'must' or 'should'. Do not include the full static list — query for relevance.]

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
