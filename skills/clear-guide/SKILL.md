---
name: clear-guide
description: >
  Show whether it is safe to run /clear right now, and why. Use when
  the user says "/clear-guide", "is it safe to clear", "should I clear",
  or "can I clear now". Read-only — checks agent and story state only.
---

# Clear Guide

Determine if it's safe to run `/clear` right now.

## Steps

1. **Check TaskList** for any tasks currently `in_progress`. If any: note which agents are running.

2. **Read** `.claude/epics.json`. Find any stories in `in-progress`, `in-review`, or `approved` state.

3. **Output decision**:

```
Safe to /clear: yes/no

Reason: [one of the following]
- No background agents running and no in-flight stories.
- Background agent is running: <task description>. Wait for it to complete first.
- Story <id> is in <state> — result needed to proceed. Not safe to clear.
- Story <id> is in <state> but no agent is running and no result is pending. Safe.
```

4. **What survives /clear**:
   - Git branches, worktrees, epics.json, all disk state
   - ORCHESTRATION.md will be reloaded automatically on your next relevant request

5. **What is lost**:
   - In-session memory, coder task status, agent task list

6. If not safe: suggest what to wait for before clearing.
7. If safe: output the standard checkpoint message — "Context checkpoint reached. Run `/clear` to reset the session. All epic and story state is saved in epics.json."
