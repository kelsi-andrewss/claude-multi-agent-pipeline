# Prepare Phase

## Step 3a: Prepare plan-writer launches

1. Read `refs/orch-critique-checklist.md` once — keep for agent prompts.
2. Glob `plans/*.md` to get existing names.
3. Generate unique plan file name per story: `plans/<random-adjective>-<random-noun>.md`.

4. **Preference prediction** — for manifest stories, call `pm_predict_preference(domain=<domain>)`. Domain inferred from write_files: `hooks`, `tracking`, `skills`, `refs`, `scripts`, etc.

5. **Decision lookup** — per story:
   - `ToolSearch: select:mcp__decisions__query_project_decisions`
   - `query_project_decisions(active_files=<write_files>)`
   - Store as `decision_constraints`. Empty if none found.

6. **Exemplar matching** — per write_file:
   - Glob `<dir>/*.{ext}`, exclude test files when matching implementation (and vice versa)
   - Pick closest name (shortest edit distance or first alphabetically)
   - Read first 100 lines: package declaration, import patterns, exported signatures, registration patterns, error handling, comments
   - Store as `exemplar_conventions`:
     ```
     ## Exemplar Conventions
     Nearest existing file to `<write_target>`: `<exemplar_path>`
     Conventions observed:
     - <pattern 1>
     - <pattern 2>
     ```
   - Greenfield directory: "No exemplar — greenfield directory."
