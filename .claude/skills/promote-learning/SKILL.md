# /promote-learning

Trigger: user types `/promote-learning N` where N is an entry number (1-based)

## Steps

1. **Locate reviewer-learnings.md**
   - Use the project root directory (from CURRENT_PROJECT env or by checking if .claude/ exists)
   - File path: `<project-root>/.claude/reviewer-learnings.md`
   - If not found, report: "reviewer-learnings.md not found in `<project-root>/.claude/`. Did you run a review recently?"

2. **Parse and extract entry N**
   - Read the file line by line
   - Count entries: each entry starts with `## YYYY-MM-DD — title`
   - For the Nth entry (1-based), extract the line matching "**Suggested checklist addition**:"
   - If entry N does not exist, report: "Entry N not found. The file contains X entries (1 through X)."

3. **Extract the suggestion text**
   - The line format is: `**Suggested checklist addition**: <text>`
   - Extract everything after the colon and trim whitespace
   - This is the proposed bullet point

4. **Map to CLAUDE.md section**
   - Read the project's `CLAUDE.md` (at `<project-root>/.claude/CLAUDE.md` or `<project-root>/CLAUDE.md`)
   - Analyze the suggestion text and choose the best-fit section:
     - "Communication style" → phrasing, messaging, clarity, collaboration tone
     - "Code style" → code review practices, refactoring, error handling, abstraction, naming
     - "React" → hooks, state, useEffect, props, closures, re-renders
     - "Firebase" → writeBatch, constraints, document operations, consistency
     - "Parallelism" → async, background tasks, batching, timing, dependencies
     - "Before suggesting a commit" → git workflow, linting, staging, secrets
     - "Tracking" → prompt assessment, documentation practices
     - Other → "Integration surfaces" or new section (rare)
   - If unclear, pick the closest match and note the ambiguity in the proposal

5. **Propose to user via AskUserQuestion**
   - Format:
     ```
     ## Promote entry N to CLAUDE.md

     **Entry**: 2026-02-20 — <title>
     **Suggested addition**:
     <extracted text>

     **Proposed section**: <section name>

     **Proposed bullet** (one sentence):
     - <suggestion text as a single bullet>

     Approve adding this bullet to the `<section name>` section of CLAUDE.md?
     ```
   - Ask: "Add to CLAUDE.md?" with options "Yes" / "No" / "Edit first"

6. **On "Yes"**
   - Append the bullet to the end of the chosen CLAUDE.md section (before the next `##` section header)
   - Add a newline before it to maintain spacing
   - Save the file
   - Report: "Added to CLAUDE.md, `<section name>` section."

7. **On "No"**
   - Report: "Skipped. Not added to CLAUDE.md."

8. **On "Edit first"**
   - Re-ask the user to provide the edited text
   - Once provided, repeat step 5 (re-propose the edited version)
   - Then await approval again (go to step 6 or 7)

9. **Errors**
   - File not found: report clearly and stop
   - Entry N not found: report range and stop
   - CLAUDE.md not found: report "CLAUDE.md not found in project root" and stop
   - Other parsing issues: report the issue and the raw extracted line for manual review
