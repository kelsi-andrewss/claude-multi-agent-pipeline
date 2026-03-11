---
name: verify
description: >
  Integrated review + build + test + acceptance criteria verification for a dev branch.
  Launches a reviewer agent on the full diff, runs build and tests, and walks acceptance
  criteria from all plan files. Use after stories merge into dev — independently of /ship.
  Invoked as "/verify .ship-manifest.json", "/verify epic-NNN", or "/verify" (auto-detects
  manifest in cwd).
args:
  - name: args
    type: string
    description: >
      Optional. A path to .ship-manifest.json, an epic-NNN ID, or nothing (auto-detect
      manifest in cwd).
---

# Verify Skill Invoked

User has requested: `/verify {{args}}`

---

## Step 0: Parse args and resolve inputs

Determine invocation mode from `{{args}}`:

1. **Manifest mode**: `{{args}}` is a file path (ends with `.json` and the file exists). Read it to extract `epic_id`, `dev_branch`, story list (with story IDs, titles, plan_file paths), and any other metadata.

2. **Epic mode**: `{{args}}` matches `epic-\d+`.
   - Load `ToolSearch: select:mcp__gemini__pm_get_epic,mcp__gemini__pm_list_stories,mcp__gemini__pm_dev_branch`
   - Call `pm_get_epic(epic_id)` for title and metadata.
   - Call `pm_list_stories(epic_id=<epic_id>)` to get all stories with their plan_file paths.
   - Call `pm_dev_branch(epic_id)` to get `dev_branch`.

3. **No args**: Look for `.ship-manifest.json` in the current working directory.
   - If found → treat as manifest mode, read it.
   - If not found → error: "Provide a manifest path or epic ID: `/verify .ship-manifest.json` or `/verify epic-NNN`"

After resolving inputs, determine `<base>` commit:
```bash
git merge-base <dev-branch> main
```
Use this as the base for diffing. If `merge-base` fails (branches have no common ancestor), fall back to `main`.

Record the current branch before any checkout:
```bash
ORIGINAL_BRANCH=$(git branch --show-current)
```

---

## Step 1: Integrated review (reviewer agent)

Generate the full diff of all changes on the dev branch:

```bash
git diff <base>...<dev-branch>
```

If the diff is empty, skip review entirely. Set review result to "No changes on dev branch vs base." and proceed to Step 2.

If the diff is non-empty, launch a reviewer agent (background, **Sonnet**) with this prompt:

```
You are reviewing the combined diff of all stories merged into a dev branch.

Epic: <epic title> (<epic_id>)
Dev branch: <dev-branch>
Base: <base commit>

Your job: identify cross-story integration issues in this diff. Check for:
- Cross-story naming inconsistencies (same concept, different names)
- Duplicate code across stories (similar functions that should be shared)
- Conflicting patterns or import inconsistencies
- Any BLOCKING issues that would prevent the code from working

Classify each finding as either BLOCKING or WARNING.

BLOCKING = the code will not work correctly as-is (broken imports, type mismatches,
conflicting implementations of the same interface).

WARNING = code smell or inconsistency that works but should be cleaned up
(duplicate utilities, naming drift, style inconsistencies).

For each finding, identify which file(s) and which story likely caused the issue.

Return your findings in this exact format:

REVIEW_RESULT:
  blocking:
    - finding: "<description>"
      files: [<file paths>]
      likely_story: "<story-NNN or unknown>"
  warnings:
    - finding: "<description>"
      files: [<file paths>]
      likely_story: "<story-NNN or unknown>"

If no issues found, return:
REVIEW_RESULT:
  blocking: []
  warnings: []

DIFF:
<full diff content>
```

Wait for the reviewer to return. Parse the result:

- **BLOCKING findings**: Store for the final report. These are surfaced prominently.
- **Warnings**: Append to `<project-root>/.claude/review-findings.md` with a timestamped header. Do NOT print warnings inline — they go to the file only.
- **Max 1 review round.** Do not attempt to fix BLOCKING issues or re-run the reviewer. Fixing is the caller's responsibility.

If the reviewer finds no issues, set review result to "clean".

---

## Step 2: Build and test

Checkout the dev branch:
```bash
git checkout <dev-branch>
```

### Project-type detection

Detect the project type by checking for build system files in the project root:

| File | Project type | Build command | Test command |
|---|---|---|---|
| `package.json` | Node/TS | `npm install && npm run build` (or `npx tsc --noEmit` if no `build` script) | `npm test` (only if `test` script exists and is not the default error stub) |
| `pubspec.yaml` | Flutter | `flutter pub get && flutter build` | `flutter test` |
| `Cargo.toml` | Rust | `cargo build` | `cargo test` |
| `go.mod` | Go | `go build ./...` | `go test ./...` |
| `pyproject.toml` or `setup.py` | Python | `pip install -e .` | `pytest` (if pytest installed) |

If no recognized build system file is found, skip build and test. Set build result to "skipped (no build system)". This is a warning, not an error.

### Build

Run the build command for the detected project type. Capture stdout and stderr.

- **Success (exit 0)**: Set build result to "pass".
- **Failure (non-zero exit)**: Set build result to "fail". Capture the last 30 lines of error output. Attempt to identify the likely story cause by cross-referencing failing files against the story list and their write_files.

### Test

If the build passed (or was skipped), check for test infrastructure and run tests.

- **Success**: Record pass count from test runner output if available.
- **Failure**: Capture failing test names and output. Record pass/fail counts.
- **No test infrastructure**: Set test result to "skipped (no test infra)".

---

## Step 3: Acceptance criteria walk

Collect all plan files:
- **Manifest mode**: plan_file paths from the manifest's story list.
- **Epic mode**: plan_file paths from each story's DB entry (via `pm_list_stories` / `pm_get_story`).

For each plan file that exists, read it and extract the `## Acceptance criteria` section. If the section is missing, skip that plan file.

For each criterion, attempt programmatic verification:

| Criterion type | Detection signal | Verification method |
|---|---|---|
| API endpoint | URL pattern, HTTP method, "endpoint", "route" | `curl` the endpoint, verify response status and shape |
| CLI command | "run", "execute", command-line syntax | Run the command, verify output |
| File output | "file exists", "generates", file path | Check file exists, verify contents match expectations |
| UI/visual | "displays", "renders", "shows", "UI", "visual" | Skip — report as "manual verification needed" |
| Behavioral/logic | Everything else not clearly programmatic | Skip — report as "manual verification needed" |

Track counts:
- `verified`: criteria that were checked programmatically and passed
- `failed`: criteria that were checked programmatically and failed
- `manual`: criteria that require manual verification

---

## Step 4: Report

Return to the original branch:
```bash
git checkout $ORIGINAL_BRANCH
```

Print the combined verification report:

```
Verify: <epic title> (<epic_id>)
  Review: <clean | N warnings | BLOCKING: description>
  Build:  <pass | fail: error | skipped (no build system)>
  Tests:  <N/M pass | skipped (no test infra)>
  Acceptance: K/L verified, J manual
```

If BLOCKING review findings exist, append:
```

BLOCKING:
  - <finding> — likely caused by <story-NNN> (<file>)
```

If warnings were logged, append:
```

Warnings logged to .claude/review-findings.md
```

If acceptance criteria failed, append:
```

Failed criteria:
  - <criterion> — <what went wrong>
```

If manual checks are needed, append:
```

Manual verification needed:
  - <criterion>
```
