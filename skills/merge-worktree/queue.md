# Queue Mode (Auto-merge)

Invoked as `/merge-worktree --queue`. Discovers and merges all eligible stories.

## Step Q1: Discover eligible stories

1. Call `pm_list_stories()` across all active epics.
2. Filter: `state = "done"` AND `worktree_active = true`.
3. None match → "No stories eligible for auto-merge." Stop.

## Step Q2: Check hold list

```bash
HOLDS=$(cat .claude/merge-holds.json 2>/dev/null || echo '[]')
```

Parse as JSON array of story IDs. Held stories → `ON HOLD`, exclude from processing.

## Step Q3: Dependency ordering

Topological sort:
1. Read `depends_on` per story.
2. Group 0: no unmerged dependencies. Group N: all dependencies in earlier groups.
3. External dependency not done → defer: "story-NNN: DEFERRED — depends on story-MMM (not done)"

## Step Q4: Execute merges

Process in dependency order. Use [batch.md](batch.md) when 2+ eligible, [single.md](single.md) inline when 1.

- No approval gate — automatic.
- Conflict → skip (CONFLICT), don't abort queue.
- Double-check hold list before each merge.

## Step Q5: Report

```
Auto-merge complete:
  story-NNN: merged (abc1234)
  story-MMM: merged (def5678)
  story-PPP: ON HOLD — skipped
  story-QQQ: CONFLICT — <description>
  story-RRR: DEFERRED — depends on story-SSS
```

## Hold flag management

File: `<project-root>/.claude/merge-holds.json` — JSON array of story IDs.

- **Queue mode:** checks before each merge.
- **Single-story / batch mode:** ignores hold list (explicit invocations always merge).
- **Missing/malformed:** treated as empty.

Add: `python3 -c "import json,os; f='.claude/merge-holds.json'; h=json.load(open(f)) if os.path.exists(f) else []; h.append('story-NNN'); json.dump(sorted(set(h)),open(f,'w'))"`
Remove: `python3 -c "import json; f='.claude/merge-holds.json'; h=[x for x in json.load(open(f)) if x!='story-NNN']; json.dump(h,open(f,'w'))"`
