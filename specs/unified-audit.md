# Unified Audit — Feature Spec

## Objective

Replace `/audit` and `/gemini-audit` with a single `/audit` skill that runs Gemini large-context analysis followed by Claude critique, synthesizing both into a scored report with per-finding acceptance criteria — so every finding is directly actionable and testable.

## User Stories

- As a developer, I want to run one audit command and get findings from both Gemini and Claude so that I don't have to choose an engine or cross-reference two reports.
- As a developer, I want each finding to include acceptance criteria so that I can verify the fix without re-running the full audit.
- As a developer, I want to see which engine found each issue so that I can calibrate my trust in audit results over time.

## Requirements

### Scoping
- Accept file paths, directories, story diffs (`story-NNN`), or time ranges (`--since 2d`) as scope input
- Default scope: entire project (respecting .gitignore)
- Section filters: `--security`, `--bugs`, `--completeness`, `--quality` (run only specified sections; default: all)

### Gemini pass (Step 1)
- Feed scoped files to `mcp__gemini__audit` MCP tool
- Receive structured findings with severity, file:line, category, evidence, and description
- If `--claude-only` flag: skip this step entirely

### Claude pass (Step 2)
- Launch a foreground Claude agent (Sonnet default, Opus with `--opus`)
- Agent reads the same scoped files AND Gemini's findings
- For each Gemini finding: confirm, downgrade severity, or reject with one-line reasoning
- Agent independently identifies findings Gemini missed
- If `--gemini-only` flag: skip this step entirely

### Synthesis (Step 3)
- Merge both passes into a single finding list
- Tag each finding's source: `gemini`, `claude`, or `both`
- Rejected Gemini findings go to an appendix (transparent, not hidden)
- Deduplicate: if both engines flag the same file:line with the same category, merge into one finding tagged `both`

### Per-finding acceptance criteria
- Every confirmed finding includes a testable Given/When/Then statement
- The acceptance criterion describes the correct behavior, not the fix implementation
- Example: "Given a user submits a form with XSS payload in the name field, when the server processes the input, then the payload is sanitized before storage"

### Scoring
- Each finding has a severity: critical (4), high (3), medium (2), low (1)
- Section weights: security 4x, bugs 3x, completeness 2x, quality 1x
- Score = 100 - sum(severity * section_weight) for all confirmed findings, floored at 0
- Perfect score (no findings) = 100

### Output formats
- Default: write `AUDIT.md` to project root (or path from `--output`)
- `--summary`: print one-paragraph summary to stdout, skip file write
- `--json`: write structured JSON instead of markdown
- `--append`: append to existing AUDIT.md instead of overwriting

### Report structure (markdown)
1. Executive summary (1 paragraph: what was audited, finding count by severity, score)
2. Score breakdown (table: section, finding count, weighted score, raw score)
3. Findings by section (security, bugs, completeness, quality — each with its findings)
4. Each finding: severity badge, file:line, description, evidence (code snippet), source tag (gemini/claude/both), acceptance criteria
5. Appendix: rejected findings with rejection reasoning

### Backward compatibility
- `/audit` becomes the unified entry point (replaces both old skills)
- `--claude-only` reproduces old `/audit` behavior (Claude agent only, no Gemini)
- `--gemini-only` reproduces old `/gemini-audit` behavior (Gemini only, no Claude critique)
- All existing flags preserved: `--requirements`, `--output`, `--append`, `--ignore`, `--summary`, `--json`, `--no-completeness`, `--since`, `--opus`

## Acceptance Criteria

- Given a user runs `/audit` with no flags, when both Gemini and Claude passes complete, then a single AUDIT.md is written containing findings from both engines with source tags
- Given a user runs `/audit --claude-only`, when the audit completes, then only the Claude agent runs and the report contains no Gemini findings
- Given a user runs `/audit --gemini-only`, when the audit completes, then only the Gemini MCP tool runs and the report contains no Claude critique or rejections
- Given Gemini finds a security issue and Claude confirms it, when the report is generated, then the finding is tagged `both` and appears once (not duplicated)
- Given Gemini finds an issue and Claude rejects it, when the report is generated, then the finding appears in the Appendix with Claude's rejection reasoning
- Given Claude finds an issue Gemini missed, when the report is generated, then the finding is tagged `claude` and appears in the main findings
- Given any confirmed finding, when the report is generated, then the finding includes a Given/When/Then acceptance criterion
- Given a project with no findings, when the audit completes, then the score is 100 and the report says "No findings"
- Given a project with 1 critical security finding, when the score is computed, then the score decreases by 16 (severity 4 * weight 4x)
- Given `--json` flag, when the audit completes, then output is valid JSON matching the structured schema (findings array, score object, metadata)
- Given `--since 2d` flag, when scoping files, then only files modified in the last 2 days are included
- Given `--security --bugs` flags, when the audit runs, then only security and bugs sections are evaluated (completeness and quality skipped)

## Constraints

**What NOT to build:**
- No auto-fix: the audit reports findings, it does not modify code
- No PR creation from findings
- No watch/continuous mode
- No cross-repo auditing (single project scope only)

**Scoring weights (fixed for v1):**
- security: 4x, bugs: 3x, completeness: 2x, quality: 1x
- Not user-configurable in v1. Hardcoded. Revisit if users disagree with weighting.

**Project decisions:**
- Run `/scout --bootstrap` to detect applicable project decisions before auditing.

## Integration Points

- `mcp__gemini__audit` MCP tool — Gemini large-context analysis (existing, no changes needed)
- `mcp__gemini__find_bug` MCP tool — optionally used by Claude agent for targeted deep dives
- Existing `/audit` SKILL.md — replaced by this spec
- Existing `/gemini-audit` SKILL.md — replaced by this spec (skill file deleted or redirects to unified)
- Claude agent infrastructure — same `general-purpose` foreground agent pattern used by current `/audit`
- `scripts/emit-event.sh` — skill telemetry events

## Out of Scope

- Auto-fixing or patching findings
- PR/commit creation from audit output
- Continuous monitoring or file-watch mode
- Cross-repository auditing
- Custom scoring weight configuration (v1 uses fixed weights)
- SARIF or other standard security report formats (v1 is markdown + JSON only)
- Integration with external vulnerability databases (CVE, NVD)

## Boundaries

- Always: use project's existing test patterns as the reference for acceptance criteria phrasing
- Always: include file:line references for every finding (no vague "somewhere in auth")
- Always: show evidence (code snippet) for every finding
- Ask first: if a finding suggests a dependency is vulnerable, confirm before recommending removal
- Ask first: if findings exceed 50, ask user whether to truncate or include all
- Never: modify any project files during an audit
- Never: expose secrets or credentials found during audit in the report (redact, note existence only)
- Never: run the Gemini pass on files matching .gitignore or .claudeignore patterns

## FeatureSpec

```json
{
  "product": "unified-audit",
  "pattern": "library-extension",
  "entity": "AuditReport",
  "fields": [
    {"name": "scope", "type": "string", "description": "Files/directories/story/time-range being audited"},
    {"name": "gemini_findings", "type": "Finding[]", "description": "Raw findings from Gemini pass"},
    {"name": "claude_findings", "type": "Finding[]", "description": "Raw findings from Claude pass"},
    {"name": "confirmed_findings", "type": "Finding[]", "description": "Merged confirmed findings with source tags"},
    {"name": "rejected_findings", "type": "Finding[]", "description": "Gemini findings rejected by Claude"},
    {"name": "score", "type": "number", "description": "Weighted score 0-100"},
    {"name": "score_breakdown", "type": "ScoreBreakdown", "description": "Per-section score details"},
    {"name": "executive_summary", "type": "string", "description": "One-paragraph summary"},
    {"name": "sections_run", "type": "string[]", "description": "Which sections were evaluated"},
    {"name": "engine_mode", "type": "enum", "values": ["dual", "claude-only", "gemini-only"], "description": "Which engines ran"}
  ],
  "subtypes": {
    "Finding": {
      "fields": [
        {"name": "id", "type": "string", "description": "Finding identifier (F-001, F-002, ...)"},
        {"name": "severity", "type": "enum", "values": ["critical", "high", "medium", "low"]},
        {"name": "section", "type": "enum", "values": ["security", "bugs", "completeness", "quality"]},
        {"name": "file", "type": "string", "description": "File path"},
        {"name": "line", "type": "number", "description": "Line number"},
        {"name": "description", "type": "string", "description": "What the issue is"},
        {"name": "evidence", "type": "string", "description": "Code snippet showing the issue"},
        {"name": "source", "type": "enum", "values": ["gemini", "claude", "both"]},
        {"name": "acceptance_criterion", "type": "string", "description": "Given/When/Then for verifying the fix"},
        {"name": "rejection_reason", "type": "string", "description": "Why Claude rejected (rejected findings only)"}
      ]
    },
    "ScoreBreakdown": {
      "fields": [
        {"name": "section", "type": "string"},
        {"name": "finding_count", "type": "number"},
        {"name": "weight", "type": "number"},
        {"name": "weighted_deduction", "type": "number"},
        {"name": "raw_deduction", "type": "number"}
      ]
    }
  },
  "permissions": [],
  "audit": false,
  "integrations": ["mcp__gemini__audit", "mcp__gemini__find_bug"],
  "ui": []
}
```
