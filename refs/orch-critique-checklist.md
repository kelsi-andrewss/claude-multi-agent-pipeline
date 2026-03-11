# Plan Critique Checklist

Read this file during /draft-plan Step 5 (critique phase). Before writing the plan file, Claude must independently review Gemini's output and check for:

1. **Missing files**: are there files that clearly need to change that Gemini didn't list?
2. **Scope creep**: does the plan touch files unrelated to the story's stated goal?
3. **Conflicts**: do any write targets overlap with in-progress stories?
4. **Project conventions**: does the plan follow patterns in this codebase (naming, structure, tooling)?
5. **Edge cases**: are there known gotchas (see `~/.claude/refs/`) that apply?
6. **Existing utilities**: does the plan propose new code where an existing function, hook, or utility already covers the need? Search project `src/` and `refs/` before accepting new abstractions.
7. **Past decisions**: query `pm_list_decisions` for decisions scoped to the story's write-target files or tech stack. Surface any conflicts.
8. **Past learnings**: query OpenMemory for procedural/semantic memories related to the story's tech stack and write targets. This augments (does not replace) pm_list_decisions.
9. **Contract completeness**: Does the plan include a `## Contract` section with function/class signatures (name, params, return type) for every new or modified public interface? Skip for stories without `test_files` or with agent = `quick-fixer`.
10. **Acceptance criteria**: Does the plan include an `## Acceptance criteria` section with testable behavioral statements (given/when/then or equivalent)? Every story needs at least one. For stories with `test_files`, criteria must reference specific test file paths.

**Significant issues** → surface to user before writing the plan file.
**Minor gaps** → incorporate silently into the plan file.

Missing contract or acceptance criteria for a story that has `test_files` is SIGNIFICANT — it blocks the test agent from writing tests against the correct interfaces. Missing them for stories without `test_files` is MINOR — incorporate silently by inferring from tasks.

---

**See also:** `/critique` skill (`skills/critique/SKILL.md`) — self-critique loop for Claude's own output. This checklist validates Gemini's plans; `/critique` validates Claude's work. Both fire during `/ship` and `/draft-plan`.
