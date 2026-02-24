# Quick-fixer Coder Prompt Template

## Story
Story ID: `<story-id>`
Story title: `<title>`

## Todos
<!-- List every todo explicitly. Coder must confirm all are implemented before committing. -->
1. `<todo description>`
2. `<todo description>`

## Write targets (modify only these)
- `<absolute path to file>`

## Read context (read but do not modify)
- `<absolute path to file>` — `<why needed>`

## Pitfalls
<!-- Required for every non-trivial prompt. Include gotchas specific to the affected files. -->
- `<edge case or gotcha>`

## CWD note
Use absolute paths only — your CWD may not match the target directory. Do not use Glob/Grep without specifying the full absolute path.

## Protected files
IMPORTANT: Do NOT edit any of these protected files: BoardCanvas.jsx, StickyNote.jsx, Frame.jsx, Shape.jsx, LineShape.jsx, Cursors.jsx — even if you think an edit would improve them. Scope creep into protected files will block the review.

## After implementing
1. Stage only write-target files by name (never `git add -A`)
2. Commit with a concise message
3. Return: "done: `<one line summary>`"
