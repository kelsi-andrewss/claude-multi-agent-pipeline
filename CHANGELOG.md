# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

---

## [2026-02-26]

### Fixed

- Sync epic branch from origin before creating story branch to avoid stale base refs (#3) (f6ba3b7)

---

## [2026-02-25]

### Fixed

- Remove CollabBoard-specific content from audit skill so it applies generically (55b46a0)
- Delete stale story branches after merge and add branch cleanup step to `/merge` skill (8c3f16c)

---

## [2026-02-24]

### Added

- Pipeline self-hosting and capability expansion — agents can now operate on the pipeline itself (#2) (2947116)
- Tighten Opus escalation documentation and preserve roadmap content after `/ingest` (f446d6c)
- `/roadmap-progress` skill for tracking epic and story completion status (92347a4, 0f1fca1)
- `/roadmap` and `/ingest` skills for research-to-pipeline ingestion flow (4f76ce3)
- `merge-epic` skill and clarified merge skill scope (a903d36, 46604b4)
- `--manual-only` flag to `/ingest` skill (56ae958, 778014d)
- Color-coded `/status` output by state, agent, and model (b88ac93)

### Changed

- Rewrite `/roadmap` and `/ingest` for natural-language format (c847ba4, c656e5a)
- Remove staging approval gate from `/todo` skill — write to epics.json immediately on `STAGING_PAYLOAD` (d5c6705, 64479bb)
- Tighten Opus escalation rules in `ORCHESTRATION.md` (a8a4392, c986b88)
- Clean up `TMPDIR` ephemeral files after story merge (7e30a3a, 648b3df)

### Fixed

- Stage and close story branches correctly after epic/story lifecycle events (8f03daa, b1e6cbd, 31c78bd, 5100418, 57b6be7, 2947116)

---

## [2026-02-23]

### Added

- Pipeline self-hosting and capability expansion — initial merge (#1) (80f2e59)
- Pipeline capability expansion: error recovery, enforcement, and new features (8a76110)
- Harden agent frontmatter with `permissionMode`/tool constraints; add stale story check (82aa9fc)

### Changed

- Update README with repo contents, skills, hooks, and file structure (ad2f8bb)

### Fixed

- Quote git-ops description to fix YAML parse error (d3862b3)
- Remove `tools`/`disallowedTools` from `git-ops.md` to restore agent loading (9d8a480)
- Clear merged epic-022 branch ref after merge (2073eba)

---

## [2026-02-22]

### Added

- `git-ops` subagent and accompanying documentation (7df601b)
- Integration surface reconciliation to `epic-planner` (084c4fc)
- `NEEDS_PLANNING` exit path, `epic-planner` agent, and pipeline guides (1259e5f)
- `merge-queue.sh` strategy and serial merge rules documentation (4306e1c)
- Git branching paradigm section to README (8004769)

### Fixed

- Close two gaps in integration surface reconciliation logic (ff02d30)

---

## [2026-02-21]

### Added

- Initial Claude multi-agent pipeline workflow (a176344)

### Changed

- Refactor to lightweight pipeline with cross-session recovery (8faf7fe)

### Changed (docs)

- Update unit-tester section with `vitest --related`, coverage attestation, lint gate, and failure classification (13e9129)
- Add inline parallelism rule to token optimizations documentation (b1f521d)

---

[Unreleased]: https://github.com/kelsi-andrewss/claude-multi-agent-pipeline/compare/f6ba3b7...HEAD
