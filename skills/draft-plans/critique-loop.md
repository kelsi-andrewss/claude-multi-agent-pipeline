# Critique Loop

## Step 4: Critique (MCP Delegation)

**Skip when:** `skip_critique = true` or caller will invoke `/critique --plans` separately.

Delegate entire critique to a foreground subagent to keep verbose MCP JSON out of main context.

### Subagent prompt

```
You are the critique subagent for /draft-plans.

## Plan files to critique
<For each plan: path, story_id, has test_files, agent>

## Tool loading
ToolSearch: select:mcp__gemini__pm_critique,mcp__gemini__pm_add_decision
ToolSearch: select:mcp__openmemory__openmemory_query,mcp__openmemory__openmemory_store

## Critique logic

### 1. Query OpenMemory
openmemory_query(query="critique learnings [domain keywords]", tags=["critique-learning"])
openmemory_query(query="critique blind spot [domain keywords]", tags=["gemini-blind-spot"])

### 2. Self-critique (2 passes max, 5 lenses)
1. Requirement coverage — tasks cover all story requirements?
2. Gap analysis — missing error paths, edge cases?
3. Weakest part — most likely to fail?
4. Alternative design — simpler approach missed?
5. Assumption audit — what does plan assume about existing code?

Past blind spots → force-check relevant patterns.
Each lens: Improve (edit plan) or NMIP (with justification).
Iteration 1 → if any improvements, Iteration 2. All NMIP → skip.

### 3. Gemini escalation
pm_critique(story_id, input=<plan content>, context="Plan critique — external review. Claude NMIP history: [...]. Past blind spots: [...]. Challenge NMIPs, check for missing tasks, flag hidden complexity.")

### 4. Contract gate (agent-path only)
- test_files present + no ## Contract → reject, retry once
- Missing/insufficient ## Acceptance criteria → reject, retry once

### 5. Record decisions and store learnings
- pm_add_decision for significant decisions
- openmemory_store critique learnings + blind spots

### 6. Do NOT append ## Self-critique to plan files

## Return format
CRITIQUE_SUMMARY:
  plans_improved: <N>
  plans_clean: <M>
  total_plans: <N+M>

PLAN_RESULTS:
  <path>:
    status: improved | clean
    improvements: ["..."] | []
    gemini_findings: <count> (<addressed>, <noted>, <disagreed>)
    unresolved: ["..."] | []
    decisions_recorded: ["..."] | []

LEARNINGS_STORED: <count>
DECISIONS_RECORDED: ["decision-NNN: <summary>"] | []
```

### Parse result

1. Extract CRITIQUE_SUMMARY for Step 5 report.
2. If any plan has `unresolved` entries → surface to user: "Critique found unresolved concerns. Proceed anyway?"
3. Contract gate rejections that failed retry → surface as unresolved.

## Step 5: Report

```bash
bash ~/.claude/scripts/emit-event.sh "skill.draft-plans.completed" "claude" "draft-plans" '{"plans_written":"'"$PLANS_WRITTEN"'"}'
```

```
Draft plans complete.
  story-NNN -> plans/<name>.md
  story-NNN -> plans/<name>.md (fast-path)
  story-NNN -> BLOCKED: <reason>

Critique: N plans improved, M passed clean.
```

## Artifact contract

**Reads:** `.ship-manifest.json` or inline story/epic IDs
**Writes:** `plans/*.md` (one per story)
**DB:** `pm_update_story(plan_file=...)` per successful plan
