---
name: audit
description: >
  Unified dual-engine audit: runs Gemini large-context analysis followed by Claude critique,
  synthesizing both into a scored report with per-finding acceptance criteria.
  Use when the user says "/audit", "audit the codebase", "audit story-NNN", or "audit <path>".
  Replaces both old /audit and /gemini-audit. Supports --claude-only and --gemini-only for
  single-engine backward compat. Supports scoping to files, directories, story diffs, or time
  ranges. Section filters, scoring, and all existing flags preserved.
args:
  - name: args
    type: string
    description: >
      Optional. Any combination of: paths, story-NNN, section keywords
      (security|bugs|completeness|quality), and flags
      (--claude-only, --gemini-only, --opus, --security, --bugs, --completeness, --quality,
      --since <commit|date>, --summary, --json, --output <path>, --append, --ignore <glob>,
      --no-completeness, --requirements <path>).
---

# Audit Skill Invoked

User has requested: `/audit {{args}}`

## Flow control

**Continuous execution.** Steps 0 through 8 execute as one uninterrupted flow. Do not pause, narrate, summarize, or ask for confirmation between steps. The only legitimate stops are:
- An error that prevents the next step from running
- The 50+ findings threshold in Step 4 (ask user whether to truncate or include all)

Everything else flows. Each step's output feeds the next -- no commentary in between.

---

## Step 0: Parse arguments

Parse `{{args}}` into the following categories:

- **paths**: any token that is not a flag, not `story-NNN`, and not a section keyword -- collect as target paths
- **story_id**: token matching `story-\d+` -- at most one
- **section_filter**: tokens matching one of: `security`, `bugs`, `completeness`, `quality` -- collect all that match. Also set by the flag variants `--security`, `--bugs`, `--completeness`, `--quality` (equivalent to bare keyword). If none specified, default = all four sections.
- **flag_claude_only**: present if `--claude-only` appears
- **flag_gemini_only**: present if `--gemini-only` appears
- **flag_opus**: present if `--opus` appears -- forces Opus model for the Claude agent
- **flag_since**: value after `--since` if present (commit ref or date like `2d`, `1w`, `2026-03-01`)
- **flag_summary**: present if `--summary` appears -- print one-paragraph summary to stdout, skip file write
- **flag_json**: present if `--json` appears -- write structured JSON instead of markdown
- **flag_output**: value after `--output` if present
- **flag_append**: present if `--append` appears
- **flag_ignore**: all values after each `--ignore` occurrence (collect list)
- **flag_no_completeness**: present if `--no-completeness` appears
- **flag_requirements**: value after `--requirements` if present

**Validation:**
- If both `--claude-only` and `--gemini-only` are set, stop with error: "Cannot use both --claude-only and --gemini-only."
- If none of paths, story_id, or flag_since are provided, set **full_project_mode** = true.

**Derive engine_mode:**
- `--claude-only` --> engine_mode = `claude-only`
- `--gemini-only` --> engine_mode = `gemini-only`
- neither --> engine_mode = `dual`

---

## Step 1: Resolve scope

### 1a. Identify project root

Identify the project root as the directory containing the nearest `.git` folder walking up from the current working directory. Store as `<project-root>`.

### 1b. Resolve target file list

Exactly one of the following applies (in priority order):

**A. story_id is set:**
- Call `pm_get_story("<story_id>")` to get the detail file, extract `branch`.
- If the story is not found or `branch` is null, stop: "story_id not found or has no branch."
- Run: `git -C <project-root> diff dev...<branch> --name-only`
- Collect the output lines as the target file list. If empty, stop: "No files changed in <branch> vs dev."

**B. flag_since is set:**
- Run: `git -C <project-root> log --since="<flag_since>" --name-only --pretty=format:"" | sort -u`
- Collect non-empty output lines as the target file list.
- If empty, stop: "No files changed since <flag_since>."

**C. paths are set:**
- Use the provided paths as the target scope.

**D. No scope given (full_project_mode):**
- Target scope is the full project root, respecting .gitignore and .claudeignore.

Apply ignore filters: for each glob in flag_ignore, exclude matching paths from the target list.

### 1c. Auto-discover requirements document

In order:
1. If flag_requirements is set, use that path. If file does not exist, stop and report.
2. Else check for `<project-root>/REQUIREMENTS.md` -- use if exists.
3. Else check for `<project-root>/requirements.pdf` -- use if exists.
4. Else set requirements_path = null and note: "No requirements document found -- completeness section will be skipped."

If flag_no_completeness is set, override requirements_path to null regardless.

---

## Step 2: Gemini pass

> **Skip this entire step if engine_mode is `claude-only`.**

1. Call `ToolSearch` with query `select:mcp__gemini__audit` to load the deferred tool. This step is **required** -- the tool is not available until loaded.

2. Invoke `mcp__gemini__audit` with:
   - `paths` = resolved target file list (or null for full project)
   - `sections` = section_filter list (or null for all)
   - `summary_only` = false
   - `ignore_patterns` = flag_ignore list (or null)

3. Parse the returned findings into a structured list. Each finding must have: severity, file, line, section (category), description, evidence. Tag all findings as `source: "gemini"`.

4. Store as `gemini_findings[]`. If the tool returns zero findings, set `gemini_findings = []` and proceed.

Never run the Gemini pass on files matching .gitignore or .claudeignore patterns.

---

## Step 3: Claude pass

> **Skip this entire step if engine_mode is `gemini-only`.**

### 3a. Build the Claude audit prompt

1. Start with the base text from `~/.claude/AUDIT-PROMPT.md` (read that file verbatim).

2. Append the **Scope section** (always):
   ```
   ## Audit Scope
   <one of the following>
   - Full project: <project-root>
   - Target files/directories: <comma-separated list>
   - Story diff (<branch> vs dev): <file list>
   - Files changed since <flag_since>: <file list>

   Ignored patterns: <flag_ignore list, or "none">
   ```

3. Append **Requirements section** if requirements_path is not null:
   ```
   ## Requirements Document
   Path: <requirements_path>
   Read this file as the source of truth for the Completeness section.
   ```

4. Append **Section filter** if section_filter is set:
   ```
   ## Section Filter
   Only produce the following section(s) of the report: <section_filter list>.
   Omit all other sections from the output.
   ```

5. If engine_mode is `dual`, append a **Gemini Findings for Review** section:
   ```
   ## Gemini Findings for Review
   The following findings were produced by Gemini's large-context analysis.
   For EACH finding, you must:
   1. **Confirm** -- the finding is valid, keep severity as-is
   2. **Downgrade** -- the finding is valid but severity is too high, state new severity with one-line reasoning
   3. **Reject** -- the finding is not a real issue, state one-line rejection reasoning

   Additionally, identify any issues Gemini MISSED that you find in the scoped files.

   <list each gemini finding with its ID, severity, file:line, category, description, evidence>
   ```

6. If engine_mode is `claude-only`, append standard audit instructions -- the Claude agent performs a full independent audit with no Gemini context.

7. Append **output format instructions**: instruct the agent to return findings as a structured list with: id, severity, section, file, line, description, evidence, and for each Gemini finding: verdict (confirm/downgrade/reject) and reasoning.

### 3b. Launch the Claude audit agent

- Model selection: use `sonnet` by default. Use `opus` if flag_opus is set.
- Launch a **foreground** general-purpose subagent with the composed prompt. Wait for completion.

### 3c. Parse agent output

Parse the agent's response into:
- `claude_confirmations[]` -- Gemini findings confirmed (with possible severity changes)
- `claude_rejections[]` -- Gemini findings rejected (with rejection reasoning)
- `claude_new_findings[]` -- issues Claude found independently, tagged `source: "claude"`

---

## Step 4: Synthesis

Merge findings from both passes into a single list.

### 4a. Merge by engine mode

**Dual mode:**
- For each Gemini finding that Claude confirmed at original severity: add to `confirmed_findings[]`, tag `source: "both"`.
- For each Gemini finding that Claude confirmed with downgraded severity: add to `confirmed_findings[]` with new severity, tag `source: "both"`, note "downgraded from X to Y".
- For each Gemini finding that Claude rejected: add to `rejected_findings[]` with rejection reasoning.
- For each Claude-only new finding: add to `confirmed_findings[]`, tag `source: "claude"`.

**Gemini-only mode:**
- All `gemini_findings[]` go directly to `confirmed_findings[]`, tagged `source: "gemini"`. No rejections.

**Claude-only mode:**
- All Claude findings go to `confirmed_findings[]`, tagged `source: "claude"`. No Gemini findings exist.

### 4b. Deduplication

If both engines independently flag the same file:line with the same category (section), merge into one finding tagged `source: "both"`. Keep the higher severity. Use the more detailed description.

### 4c. Assign IDs

Number all confirmed findings sequentially: F-001, F-002, etc.

### 4d. Generate per-finding acceptance criteria

For every confirmed finding, write a testable **Given/When/Then** statement. The acceptance criterion describes the correct behavior, NOT the fix implementation.

Example: "Given a user submits a form with XSS payload in the name field, when the server processes the input, then the payload is sanitized before storage."

### 4e. 50+ findings gate

If `confirmed_findings[]` exceeds 50 entries, ask the user:
> "Found N findings. Include all in the report, or truncate to top 50 by severity?"

Wait for response before proceeding. This is the only legitimate pause in the flow.

---

## Step 5: Scoring

### 5a. Severity values

| Severity | Value |
|---|---|
| critical | 4 |
| high | 3 |
| medium | 2 |
| low | 1 |

### 5b. Section weights

| Section | Weight |
|---|---|
| security | 4x |
| bugs | 3x |
| completeness | 2x |
| quality | 1x |

### 5c. Compute score

For each confirmed finding: `deduction = severity_value * section_weight`.

`score = 100 - sum(all deductions)`, floored at 0. Perfect score (no findings) = 100.

### 5d. Build score breakdown table

| Section | Finding count | Weight | Weighted deduction | Raw deduction |
|---|---|---|---|---|
| Security | N | 4x | sum of (severity * 4) for security findings | sum of severity for security findings |
| Bugs | N | 3x | sum of (severity * 3) for bugs findings | sum of severity for bugs findings |
| Completeness | N | 2x | sum of (severity * 2) for completeness findings | sum of severity for completeness findings |
| Quality | N | 1x | sum of (severity * 1) for quality findings | sum of severity for quality findings |
| **Total** | **N** | | **total weighted** | **total raw** |

Final score line: `Score: <score>/100`

---

## Step 6: Report generation

### Mode A: --summary

> **If flag_summary is set:**

Print a one-paragraph executive summary to stdout containing: what was audited, engine_mode, finding count by severity, score. No file write.

Print completion summary (Step 8 format) and stop.

### Mode B: --json

> **If flag_json is set:**

Write a JSON file to flag_output path (or `<project-root>/AUDIT.json`). Schema:

```json
{
  "metadata": {
    "scope": "...",
    "engine_mode": "dual|claude-only|gemini-only",
    "sections_run": ["..."],
    "timestamp": "ISO8601"
  },
  "score": {
    "total": 0,
    "breakdown": [
      {
        "section": "...",
        "finding_count": 0,
        "weight": 0,
        "weighted_deduction": 0,
        "raw_deduction": 0
      }
    ]
  },
  "findings": [
    {
      "id": "F-001",
      "severity": "...",
      "section": "...",
      "file": "...",
      "line": 0,
      "description": "...",
      "evidence": "...",
      "source": "gemini|claude|both",
      "acceptance_criterion": "Given... When... Then..."
    }
  ],
  "rejected_findings": [
    {
      "id": "...",
      "severity": "...",
      "section": "...",
      "file": "...",
      "line": 0,
      "description": "...",
      "source": "gemini",
      "rejection_reason": "..."
    }
  ],
  "executive_summary": "..."
}
```

Proceed to Step 7.

### Mode C: Default markdown (AUDIT.md)

Determine output_path: flag_output value, or `<project-root>/AUDIT.md`.

If flag_append: read existing file first, append new findings without duplicating existing ones.

Write (or append) the report with this structure:

1. **Executive summary** -- 1 paragraph: what was audited, engine_mode used, finding count by severity, overall score.

2. **Score breakdown** -- the table from Step 5.

3. **Findings by section** -- one heading each for Security, Bugs, Completeness, Quality (only sections that were run). Within each section, list findings ordered by severity (critical first). Each finding includes:
   - Severity badge: `**CRITICAL**`, `**HIGH**`, `**MEDIUM**`, or `**LOW**`
   - File:line reference
   - Description
   - Evidence (code snippet in a fenced code block)
   - Source tag: `[gemini]`, `[claude]`, or `[both]`
   - Acceptance criterion: `> Given... When... Then...`

4. **Appendix: Rejected findings** -- list each rejected Gemini finding with its severity, file:line, description, and Claude's rejection reasoning. If no rejected findings, omit this section entirely.

**Security constraint:** never expose secrets or credentials found during audit in the report. Redact and note existence only.

**Never modify any project files during an audit.** The audit reports findings -- it does not apply fixes.

Proceed to Step 7.

---

## Step 7: Cross-reference and story offers

### 7a. Cross-reference with open stories

1. Call `pm_list_stories()`, filter to stories where state is not `done`, `shipped`, or `archived`. Build:
   ```
   open_story_map = { story_id: { title, writeFiles[] } }
   ```

2. For each confirmed finding referencing a file path, check if any open story's writeFiles overlaps. If so, annotate the finding: `Related open story: story-NNN -- <title>`.

3. If annotations were added to the markdown report, write the updated report back to output_path.

### 7b. Offer story creation

Scan confirmed findings with severity `critical` or `high` that have no related open story.

If any exist, list them and ask:
> "The following High/Critical priority findings are not covered by any open story. Create a /todo story for each? (yes / no / list the ones you want)"

If user approves, invoke `/todo` for each selected finding.

---

## Step 8: Completion summary and telemetry

### 8a. Telemetry

Emit telemetry event:
```bash
bash scripts/emit-event.sh audit '{"engine_mode":"<engine_mode>","finding_count":<N>,"score":<score>}'
```

### 8b. Print completion summary

```
Audit complete.
Engine: <dual|claude-only|gemini-only>
Report: <output_path>
Score: <score>/100
Findings: <N> Critical, <N> High, <N> Medium, <N> Low
Rejected: <N> (see Appendix)
<if stories created>: Stories created: story-NNN, ...
```

---

## Output policy

- The audit skill reads and analyzes code. It never modifies project source files.
- Secrets or credentials discovered during audit are redacted in the report -- note existence only, never include the value.
- Files matching .gitignore or .claudeignore patterns are excluded from both Gemini and Claude passes.
- The report file (AUDIT.md, AUDIT.json) is the only file written by this skill.
