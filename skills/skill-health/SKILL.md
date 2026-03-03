---
name: skill-health
description: >
  Friction and skill health dashboard: friction events by category and trend, skill
  invocation counts, outcome correlation, and pattern detection. Use when the user says
  "/skill-health", "skill health", "show friction", or "show skill metrics".
args:
  - name: args
    type: string
    description: >
      Optional. "since YYYY-MM-DD" to filter by date, a skill name to focus on one,
      "friction" for friction-only view, or empty for full dashboard.
---

# Skill Health Dashboard Invoked

User has requested: `/skill-health {{args}}`

---

## Step 1: Parse args

Parse `{{args}}` for:
- `since_date`: if args contains `since YYYY-MM-DD`, extract the date. Default: no filter (all time).
- `focus_skill`: if args is a single skill name (not "since", not "friction"), set it. Default: null.
- `friction_only`: if args is exactly "friction", set true. Default: false.

---

## Step 2: Read data sources

Read all four data sources. Missing files are not errors — report what's available.

1. **Friction log**: Read `~/.claude/friction-log.md`. Parse each `## ` entry into structured data:
   - date, category, story_id, type, skill, expected, actual, counterfactual, recurrence
   - Apply `since_date` filter if set
   - Apply `focus_skill` filter if set (match against **Skill** field)

2. **Skill telemetry**: Read `~/.claude/.claude/tracking/skill-telemetry.jsonl`. Parse each JSONL line:
   - timestamp, date, skill, args, session_id
   - Apply `since_date` filter if set
   - Apply `focus_skill` filter if set

3. **Outcomes**: Read `~/.claude/outcomes.md`. Parse each `## ` entry:
   - date, story_id, title, intent, result, agent, model, cycle_time, coder_effort,
     skills_used, friction_events, memory_attributed, what_worked, what_failed
   - Apply `since_date` filter if set

4. **Skill changelog**: Read `~/.claude/skill-changelog.md`. Parse each `- ` entry:
   - date, action (created/modified/retired), skill_name, description
   - No date filter — always show all for before/after analysis

---

## Step 3: Compute friction metrics

- Events by category (escalation, restart, blocked, conflict, decision, retry, reroute, discovery)
- Events by skill (which skill was running when friction occurred)
- Automatic vs. judgment ratio
- Recurring vs. first-seen ratio
- Events per session trend (last 14 days, using date grouping)
- Clean outcome rate (outcomes with "0 (clean)" in friction_events field / total outcomes)

---

## Step 4: Compute efficiency metrics (from outcomes with extended fields)

- Avg cycle time for 0-friction stories vs. 2+-friction stories (parse cycle_time field)
- Avg coder effort (tokens, calls) for clean vs. friction-heavy outcomes (parse coder_effort field)
- Cycle time trend over time (by week, last 4 weeks)

Skip if fewer than 2 outcomes have cycle_time data.

---

## Step 5: Compute skill metrics

- Invocations by skill, by date, unique sessions (from telemetry)
- Outcome correlation: for each skill in telemetry, count how many outcomes list it in skills_used,
  grouped by result (merged/blocked/rejected)
- Friction-per-skill rate: friction events where skill matches / total invocations of that skill
- Before/after comparison: for skills with changelog entries, compare friction rates before and
  after the changelog date

---

## Step 6: Display dashboard

```
Skill Health Dashboard
Period: [since or "all time"] — [today]

FRICTION
  Total events: N (A automatic, J judgment)
  Clean outcome rate: X% (N/M outcomes with zero friction)

  By category:
    escalation    4   ████
    conflict      3   ███
    retry         2   ██
    reroute       1   █

  By skill:
    run-stories   5 events / 10 invocations (50% friction rate)
    merge-worktree 2 events / 9 invocations (22%)
    manual        2 events

  Recurring patterns:
    "<pattern description>" — N occurrences → promoted to tool-learning
    "<pattern description>" — appeared Nx (M more → promotion)

  Trend (last 14 days):
    03-01: ██ (2)
    03-02: █ (1)
    03-03: ███ (3)
    ...

EFFICIENCY
  Avg cycle time: X.Xh (clean) vs Y.Yh (2+ friction)
  Avg coder tokens: Xk (clean) vs Yk (2+ friction)
  Trend: [cycle time by week, last 4 weeks]

BEFORE/AFTER (from skill-changelog.md)
  /skill-name modified YYYY-MM-DD:
    Before: category N/session, category N/session
    After:  category N/session, category N/session  ← interpretation

INVOCATIONS
  Total: N across M sessions
  [skill table with counts]

OUTCOMES
  Total: N
  Results: merged N, blocked N, rejected N
  Memory attribution: N/M outcomes (X%)
```

If `friction_only` is true, show only the FRICTION and BEFORE/AFTER sections.
If `focus_skill` is set, filter all sections to that skill only.

---

## Step 7: Data sufficiency check

- If <10 outcomes: show available data but note "N outcomes — need 10+ for meaningful trends.
  Efficiency and before/after comparisons will appear once enough data accumulates."
- If <3 friction events: show raw events instead of aggregated view, skip trend analysis
- If skill-changelog.md is empty or missing: skip BEFORE/AFTER section, note "No skill changelog
  entries. Append entries when skills ship to enable before/after analysis."
- If skill-telemetry.jsonl is empty or missing: skip INVOCATIONS section, note "No skill telemetry
  data yet. Telemetry begins after the next skill invocation."

---

## Step 8: Pattern detection (only if 10+ outcomes)

- Flag friction categories that increased after a skill was introduced (using changelog dates)
- Flag skills with high friction rate (>40% of invocations have friction)
- Flag recurring patterns approaching promotion threshold (2 occurrences, 1 more → promotion)
- Note friction categories that dropped to zero after a skill change (skill working as intended)

If fewer than 10 outcomes, skip this section and note: "Pattern detection requires 10+ outcomes."
