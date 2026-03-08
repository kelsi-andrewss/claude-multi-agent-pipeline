---
name: critique
description: >
  Self-critique loop: iteratively improve whatever Claude just produced —
  plans, code, architecture, design proposals. Loops until NMIP (No Material
  Improvements Possible) on all 5 lenses, then escalates to Gemini for fresh
  eyes. Stores blind spots for future sessions.
  Use when the user says "/critique", "/critique path/to/file.md",
  "/critique 'topic'", or "/critique --deep".
args:
  - name: args
    type: string
    description: >
      Optional file path, quoted topic, or --deep flag.
      No args = critique the most recent substantial artifact in conversation.
---

# Critique Skill Invoked

User has requested: `/critique {{args}}`

---

## Step 1: Parse args and detect target

Parse `{{args}}` to determine what to critique:

1. **`--deep` flag**: if present, set `deep_mode = true` and strip from args. Skips self-critique iterations, goes straight to Gemini.
2. **File path**: token ends with `.md`, `.sh`, `.py`, `.ts`, `.js`, `.json`, `.yaml`, `.yml`, or similar, and the file exists. Read the file — that's the critique target.
3. **Quoted topic**: text in quotes (single or double). Gather relevant context from conversation history and codebase. The topic description + gathered context is the critique target.
4. **No args**: scan conversation for the most recent substantial artifact:
   - Look for the last `##` heading, significant code block (10+ lines), or structured proposal.
   - If multiple candidates exist in the same turn, ask: "Multiple artifacts in your last output — which one should I critique?" and list them.
   - If no substantial artifact found, ask: "What should I critique?" and stop.

Set `target` to the identified content. Set `target_label` to a short description (filename, topic, or "last artifact").

---

## Step 2: Query OpenMemory for past learnings

Before starting the loop, query for relevant context:

```
openmemory_query(
  query="critique learnings [subject domain keywords from target]",
  tags=["critique-learning"],
  user_id="proj:<current-project>"
)

openmemory_query(
  query="critique blind spot [subject domain keywords from target]",
  tags=["gemini-blind-spot"],
  user_id="proj:<current-project>"
)
```

Collect results into two lists:
- `past_learnings` — general critique findings for this domain
- `past_blind_spots` — things Gemini caught that Claude missed previously

If OpenMemory is unavailable, proceed without — the loop still works.

---

## Step 3: Self-critique loop

**If `deep_mode`**: skip to Step 4.

### Iteration 1

Apply each of the 5 core questions to `target`. For each question:

1. **Requirement coverage**: Does every stated requirement map to something concrete? Identify any unmapped requirements.
2. **Gap analysis**: What's missing? Error paths, edge cases, migration steps, testing, deployment, integration points.
3. **Weakest part**: Identify the most fragile element. Why it's weak, what would strengthen it.
4. **Alternative design**: Propose at least one materially different approach. Why the current one wins — or does it?
5. **Assumption audit**: What's unverified? What breaks if an assumption is wrong?

**Past Omissions check**: If `past_blind_spots` is non-empty, add a forced check: "You have historically missed [pattern] when critiquing [domain]. Check for it explicitly." Apply this check during each question where relevant.

For each question, either:
- **Improve**: describe the issue and make the improvement (edit the target content, update the plan, fix the gap)
- **NMIP**: explicitly declare "**NMIP** — No Material Improvements Possible" with a one-line justification

Track: `improvements_made` (boolean), `nmip_declarations` (list of question numbers declared NMIP with justifications).

**If any improvements were made** → proceed to Iteration 2.
**If all 5 are NMIP** → skip Iteration 2, proceed to Step 4 (Gemini always fires).

### Iteration 2

Apply the same 5 questions to the *improved* version of `target`. Same NMIP rules.

Track iteration 2 results separately. After Iteration 2 completes → proceed to Step 4 regardless of outcome.

**Max self-critique iterations: 2.** Do not loop further.

---

## Step 4: Gemini escalation

Load `ToolSearch: select:mcp__gemini__analyze`.

Build the Gemini prompt:

```
mcp__gemini__analyze(
  input: "<the current state of target after self-critique iterations>",
  context: "Self-critique loop iteration 3 (external review).

Claude's critique history:
  Iteration 1: [list improvements made and NMIP declarations with justifications]
  Iteration 2: [list improvements made and NMIP declarations with justifications]
  (If deep_mode: 'Self-critique skipped — direct escalation requested.')

Past blind spots from prior critiques: [past_blind_spots content, or 'None recorded']

Your job:
1. Challenge Claude's NMIP declarations — identify anything Claude missed or prematurely closed.
2. Bring a fresh perspective: different failure modes, unconsidered trade-offs, missed requirements.
3. Check for systemic blind spots: over-engineering, under-specifying, missing error paths, scope drift.
4. Be specific: name the issue, explain why it matters, suggest the fix."
)
```

When using `/critique` from within `/ship` or `/draft-plan` where story IDs are available, use `mcp__gemini__pm_critique` instead of `mcp__gemini__analyze`.

### Process Gemini's response

Review each finding from Gemini:
- **Valid and material**: make the improvement. Note it as a Gemini-sourced fix.
- **Valid but minor**: incorporate if easy, note if not.
- **Disagree**: state why — don't silently discard. "Gemini flagged X but this isn't applicable because Y."

After processing Gemini's findings, do one final self-assessment across all 5 questions on the now-final version. This is a single pass, not a full loop — just confirm nothing was introduced by the fixes.

---

## Step 5: Store learnings

### After every critique run

Store a summary of what was found and improved:

```
openmemory_store(
  content="Critique of [target_label]: [1-2 sentence summary of key improvements and NMIP areas]",
  tags=["critique-learning"],
  user_id="proj:<current-project>"
)
```

### After Gemini finds something Claude NMIP'd

This is the highest-value learning — Claude declared "no improvements possible" but Gemini found one:

```
openmemory_store(
  content="Critique blind spot: Claude NMIP'd [question] but Gemini found [issue]. Pattern: [what to check for]. Domain: [domain]",
  tags=["gemini-blind-spot"],
  user_id="proj:<current-project>"
)
```

If OpenMemory is unavailable, skip — the critique itself still delivered value.

---

## Step 6: Present results

Output depends on context:

### Plan mode / file critique
- Edit the file with improvements inline.
- Append a `## Self-critique` section at the end with:
  - Iteration count
  - NMIP declarations (which questions, which iterations)
  - Gemini findings and responses
  - Past blind spot check results

### Conversation (no file target)
State the critique naturally:
```
**Critique of [target_label]** (2 self-iterations + Gemini review)

[Key improvements made — bulleted, concise]

Gemini flagged: [findings and how they were addressed]

Past blind spot check: [relevant patterns checked — applicable or not]

NMIP on: [list questions that were NMIP across all iterations]
```

### /ship and /draft-plan integration
- Fix plan files inline with improvements.
- Surface remaining concerns in the report step.
- Don't append a `## Self-critique` section to plan files used by coders — it's noise for them. Instead, note critique results in the ship/draft-plan report.

---

## Behavioral notes

- The NMIP mechanism runs on honesty. Declaring NMIP means "I genuinely cannot see how to improve this aspect." Gemini's role is to catch premature NMIP declarations — and blind spots are stored so the same mistake doesn't repeat.
- Don't inflate findings to avoid NMIP. Five genuine NMIPs is a good outcome — it means the work was solid.
- Don't deflate findings to rush through. Each question gets real consideration.
- The loop should take 1-3 minutes of wall time, not 10. Concise improvements, not essays.
