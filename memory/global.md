# Global Memory

## Where knowledge lives
- **Rules/constraints**: CLAUDE.md, ORCHESTRATION.md (always loaded per-project)
- **Behavioral prefs**: correction_groups table (epics.db), rendered to .claude/rendered-prefs.md at session start
- **Decisions**: `pm_list_decisions` (epics.db, authoritative)
- **Tool learnings**: `openmemory_query(query="...", user_id="global")`
- **Project context**: `openmemory_query(query="...", user_id="proj:<name>")`
- **Past sessions**: `openmemory_query(query="...", tags=["transcript"])`
- **Corrections/disagreements**: flat files (audit trail), distilled into correction_groups table (epics.db)
