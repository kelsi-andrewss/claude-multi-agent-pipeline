---
name: argue
description: >
  Adversarial Claude-vs-Gemini debate tool. Claude and Gemini form independent positions,
  then debate back-and-forth until convergence or the round cap. Claude participates as a
  genuine debater — not a summarizer. Produces a battle-tested synthesis written to
  ~/.claude/arguments/finals/<slug>.md.
  Use when the user says "/argue <topic>", "/argue plan <topic>", "/argue bug <symptom>",
  or "/argue tech <question>".
args:
  - name: args
    type: string
    description: >
      Topic and optional flags: --rounds N, --paths file1,file2, --seed find_bug|plan|audit,
      --model <id>, --history.
---

# Argue Skill Invoked

User has requested: `/argue {{args}}`

## Steps

### 1. Parse arguments

Parse `{{args}}` into:

- **topic_type**: if args starts with `plan `, `bug `, or `tech `, extract it and strip from topic. Default: `general`.
- **topic**: all text before any `--` flag (after stripping topic_type prefix). Required. If empty, call:
  ```
  AskUserQuestion: "What should Claude and Gemini debate?"
  ```
  Wait for the user's response before proceeding.
- **max_rounds**: value after `--rounds` (integer, 1–8). Default: 4.
- **context_paths**: comma-separated file paths after `--paths`. Split into a list.
- **seed_tool**: value after `--seed` (`find_bug`, `plan`, or `audit`). Default: null.
- **model**: value after `--model`. Default: null.
- **history_flag**: true if `--history` appears in args.

### 2. Load context

**If `--paths` provided**: Read each file using the Read tool. Truncate to 300 lines each. Collect into a context block. Track any paths that don't exist as `skipped_paths`.

**If `--seed` provided**: Load the appropriate Gemini tool via ToolSearch and call it:
- `find_bug` → `mcp__gemini__find_bug`
- `plan` → `mcp__gemini__plan`
- `audit` → `mcp__gemini__audit`

Store the seed output for inclusion in opening positions.

### 3. Opening positions (parallel)

Form two independent opening positions — neither model sees the other's take first.

**Claude's opening**: Reason about the topic yourself (considering any seed analysis and file context). Form a clear, specific position with supporting arguments. Write it down as your Round 1 position.

**Gemini's opening**: Call `gemini_chat` with:
- `messages`: `[{"role": "user", "content": "<topic + context + seed if any>. Form a clear position on this topic with specific supporting arguments."}]`
- `system_instruction`: the debate system instruction (see §Gemini System Instruction below)
- `model`: the parsed `--model` value, or omit

Record both positions. Initialize `conversation_history` as a list for the history file.

### 4. Debate loop

Starting from round 2, up to `max_rounds`:

1. **Claude counters Gemini**: Read Gemini's last position. Form a genuine counterargument — find the weakest point, introduce a new angle, or concede specific points that are stronger than your position. This must be real reasoning, not keyword extraction.

2. **Send to Gemini**: Call `gemini_chat` with the full conversation history so far (alternating user/model roles, where "user" = Claude's turns, "model" = Gemini's turns), plus Claude's new counterargument as the latest user message. Include the debate system instruction.

3. **Gemini responds**: Record the response.

4. **Convergence check**: As a participant, evaluate honestly:
   - Are you repeating arguments? Is Gemini?
   - Do you genuinely disagree with Gemini's last point, or are you reaching for objections?
   - If you agree with Gemini's position and have nothing substantive to counter → mark as converged.
   - Track consecutive convergence count. If converged for 2 consecutive evaluations → stop the loop.

5. **Record**: Add both turns to conversation history.

If `max_rounds == 1`: skip the loop entirely — just use the opening positions.

### 5. Synthesize

Write a final synthesis based on having actually participated in the debate:

- If **converged**:
  > **Agreed position:** <1–3 sentence summary of the convergent position, incorporating the strongest reasoning from both sides>

- If **not converged**:
  > **Positions not fully reconciled after N round(s).**
  > **Key tension:** <the core disagreement that persists>
  > **Strongest argument (Claude):** <your best point that Gemini didn't fully counter>
  > **Strongest argument (Gemini):** <Gemini's best point that you couldn't fully counter>
  > **Best available synthesis:** <your reasoned synthesis weighing both sides>

### 6. Save outputs

**Slug**: topic lowercased, spaces → hyphens, non-alphanumeric stripped, truncated to 40 chars.

**Finals file** (always written):
- Path: `~/.claude/arguments/finals/<slug>.md`
- Content:
  ```
  # Argue: <topic>
  **Type**: <topic_type>  **Rounds**: <rounds_run>  **Converged**: <yes/no>
  **Date**: <YYYY-MM-DD>

  ## Synthesis

  <synthesis text>
  ```
- Overwrite if it already exists.

**History file** (only if `--history` flag was set):
- Path: `~/.claude/arguments/history/<slug>-<topic_type>-<YYYYMMDDTHHMMSS>.md`
- Content: full transcript — each message formatted as `**<MODEL NAME>**: <content>`, separated by `---`.
  Use "Claude" and "Gemini" as the model names (not "user"/"model").
- After writing, list all files in `~/.claude/arguments/history/` matching `<slug>-*`, sort by mtime descending, delete any beyond the 5 most recent.

**Plan handoff** (only if `topic_type == "plan"`):
- Write the synthesis to `plans/<whimsical-adjective-gerund-noun>.md` (check existing plans/ to avoid collision).
- Then ask:
  > "Argument complete. Run `/draft-plan` to wire this into a story, or keep as standalone?"
- If the user says yes: invoke `/draft-plan` pointing at the plan file.

### 7. Report

Print the synthesis inline. Note:
- Path written to finals
- Path written to history (if --history)
- Any skipped_paths

---

## Gemini System Instruction

Use this as the `system_instruction` parameter for every `gemini_chat` call in this debate:

```
You are in an adversarial technical debate with another AI model. Your job:
- Form and defend genuine positions based on evidence and reasoning
- Concede specific points when the counterargument is stronger — don't defend weak positions
- Introduce new angles, not restate old ones
- Be specific: name trade-offs, cite patterns, reference concrete scenarios
- If you agree with the other side's point, say so explicitly and explain why it changed your view
```
