#!/bin/bash
# PostToolUse hook for Agent tool.
# Detects friction markers in agent results and appends entries to friction-log.md.
# Exit 0 always (advisory). Async.

INPUT=$(cat)

echo "$INPUT" | python3 -c "
import sys, json, re
from datetime import datetime

d = json.load(sys.stdin)
ti = d.get('tool_input', {})
result = d.get('tool_result', '')

subagent = ti.get('subagent_type', '')
skip_types = {'Explore', 'Plan', 'epic-planner', 'claude-code-guide'}
if not subagent or subagent in skip_types:
    sys.exit(0)

if not result:
    sys.exit(0)

patterns = {
    'blocked':    (r'\bBLOCKED\b', 0),
    'decision':   (r'\bNEED_DECISION\b', 0),
    'escalation': (r'(Haiku.*→.*Sonnet|Sonnet.*→.*Opus|escalat(ing|ed)\s+to)', re.IGNORECASE),
    'conflict':   (r'merge conflict', re.IGNORECASE),
    'retry':      (r'(retry|retrying|sent back|re-running|test fail)', re.IGNORECASE),
}

counterfactuals = {
    'blocked':    'Story would have completed in one pass without manual intervention',
    'decision':   'Coder would have made the call autonomously',
    'escalation': 'Lower-cost model would have handled the task',
    'conflict':   'Merge would have been clean without manual resolution',
    'retry':      'Tests would have passed on first run',
}

matched = []
for cat, (pat, flags) in patterns.items():
    if re.search(pat, result, flags):
        matched.append(cat)

if not matched:
    sys.exit(0)

story_m = re.search(r'story-(\d+)', result)
story_id = f'story-{story_m.group(1)}' if story_m else 'session'

prompt_text = (ti.get('prompt', '') + ' ' + ti.get('description', '')).lower()
known_skills = ['ship', 'run-stories', 'merge-worktree', 'draft-plan', 'audit', 'argue']
skill = 'unknown'
for s in known_skills:
    if s in prompt_text:
        skill = s
        break

today = datetime.now().strftime('%Y-%m-%d')
import os
log_path = os.path.expanduser('~/.claude/friction-log.md')

entries = []
for cat in matched:
    entries.append(f'''
## {today} — {cat} — {story_id}
**Type**: automatic
**Skill**: {skill}
**Expected**: clean completion
**Actual**: {cat} detected in agent result
**Counterfactual**: {counterfactuals[cat]}
**Recurrence**: first-seen
''')

with open(log_path, 'a') as f:
    for e in entries:
        f.write(e)
" 2>/dev/null

exit 0
