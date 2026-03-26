# Post-Merge Steps

Called from [single.md](single.md) after Step 5.

## Step 5.5: Log outcome

Gather metadata:
- `agent`: from pm_get_story
- `model`: from coder launch context (haiku/sonnet/opus or "unknown")
- `file_count`: from write_files count → `complexity_bucket`: 1-2→small, 3-5→medium, 6+→large
- `cycle_time`: time from `in-progress` to now. Format: decimal hours, one decimal (e.g., `2.1h`, `0.0h`)
- `coder_effort`: from `/tmp/coder-effort-<story_id>.json` (model, tokens, calls, duration). Delete after reading.
- `skills_list`: from `~/.claude/.claude/tracking/skill-telemetry.jsonl`, filter by session_id
- `friction_summary`: from correction_groups in epics.db
- `memory_list`: OpenMemory queries that influenced decisions, or "none"

Write to `~/.claude/.claude/run-state.db` merge_outcomes table:
```python
python3 -c "
import sqlite3, os
db = os.path.expanduser('~/.claude/.claude/run-state.db')
conn = sqlite3.connect(db, timeout=10)
c = conn.cursor()
c.execute('PRAGMA journal_mode=WAL')
c.execute('PRAGMA busy_timeout=5000')
for col in ['what_worked TEXT','what_failed TEXT','friction_events INTEGER DEFAULT 0',
            'file_count INTEGER','complexity TEXT','skills_used TEXT',
            'coder_effort TEXT','memory_attributed TEXT']:
    try: c.execute(f'ALTER TABLE merge_outcomes ADD COLUMN {col}')
    except sqlite3.OperationalError: pass
c.execute('''INSERT OR REPLACE INTO merge_outcomes
    (story_id, epic_id, agent, model, domain_tags, success, cycle_time_s,
     revert_count, what_worked, what_failed, friction_events, file_count,
     complexity, skills_used, coder_effort, memory_attributed)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
    ('[story_id]', '[epic_id]', '[agent]', '[model]', '[skills_list]',
     True, [cycle_time_seconds], [friction_count],
     '[what_worked]', '[what_failed]', [friction_count], [file_count],
     '[complexity_bucket]', '[skills_list]', '[coder_effort]', '[memory_list]'))
conn.commit(); conn.close()
"
```

## Step 5.6: Post-merge regression check

Only in batch mode (2+ stories in same epic). Single-story merges skip.

```bash
REGRESS_RESULT=$(python3 ~/.claude/scripts/regression-check.py \
  --epic-id <epic_id> \
  --just-merged-story-id <story_id> \
  --just-merged-write-files "<comma-separated>" \
  --project-root <project-root> \
  --dev-branch <dev-branch> \
  --session-id <session_id> \
  --story-manifest '<JSON>')
```

- Exit 0 (`criteria_failed == 0`): log clean. Continue.
- Exit 1 (`criteria_failed > 0`): log failures as warnings. Non-blocking — merge already happened.
- Exit 2: log system error. Continue.

## Step 5.7: Coder divergence capture

After successful merge. Skip for blocked/failed.

1. Read plan file `## Tasks` section.
2. Look for deviation indicators in coder result: "matching codebase convention despite plan", "plan specified X but codebase uses Y", "adapted to actual pattern", "followed existing pattern instead".
3. For each divergence, append to `<project-root>/.claude/proposed-decisions.md`:
   ```markdown
   ## Proposed decision (story-NNN, <date>)
   **Convention:** <what coder discovered>
   **Evidence:** Plan said <X>. Coder did <Y> after reading <exemplar>.
   **Scope:** <file pattern or directory>
   **Status:** pending review
   ```

Proposed, not auto-added — user must review before it becomes a recorded decision.
