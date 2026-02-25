---
name: todo
description: "Initiates the full development pipeline for a new task, bug fix, or feature request. Use this skill when the user asks to fix a bug, add a feature, make a code change, or uses the /todo command. This is the ONLY correct way to start a code change. Do not attempt to implement changes directly — launch the orchestrator."
args:
  - name: task_description
    type: string
    description: "A clear, one-sentence description of the task."
---

# Todo Skill Invoked

User has requested: "{{task_description}}"

Your job is to initiate the full development pipeline. Do NOT implement the change yourself.

## Steps

1. Read `/Users/kelsiandrews/.claude/ORCHESTRATION.md` and the project `CLAUDE.md` if not already read this session.
2. Read `.claude/epics.json` to check for an existing story that covers this request (dedup check).
3. Preprocess: strip filler from the user message, extract core intent as one sentence, append one-line summary of current story context.
4. Spawn the `todo-orchestrator` agent (foreground, Haiku) with the condensed task description.
5. Check the orchestrator's output type:

   **A. STAGING_PAYLOAD** → The orchestrator writes the payload to `$TMPDIR/staging-<todo-slug>.json` and returns `STAGING_PAYLOAD written to $TMPDIR/staging-<todo-slug>.json`. Read that file, validate per ORCHESTRATION.md §6 (story state must be `draft`), immediately write the story to epics.json (via update-epics.sh or direct node command), create `TaskCreate` entries, and print the summary to the user. Wait for run trigger before launching any coder. Supports `--backlog` flag: if present, stage story directly to the backlog epic (no orchestrator needed), state `draft`.

   **B. DUPLICATE** → Inform the user which existing story covers this request. Stop.

   **C. NEEDS_PLANNING** → Enter the planning loop (ORCHESTRATION.md §4.1):
   1. Group the orchestrator's questions into categories (scope, approach, schema, UX).
   2. Select model: Opus if Complexity is "high", Touches includes "AI tools"/"Firestore schema", or Files explored > 10. Sonnet otherwise.
   3. Derive `<todo-slug>` (kebab-case, ≤5 words) from the task description.
   4. Launch `epic-planner` agent (foreground, selected model) with planning prompt including MODE: planning, the original task, orchestrator findings, and grouped questions.
   5. Wait for planner to complete, then read `$TMPDIR/planning-<todo-slug>.md`.
   6. Re-launch `todo-orchestrator` (foreground, Haiku) with PLANNING_CONTEXT block containing the original task, resolved plan, and union of explored files. Instruct it to produce STAGING_PAYLOAD.
   7. Check the re-launched orchestrator's output:
      - STAGING_PAYLOAD → validate and present as in step 5A.
      - NEEDS_PLANNING again → surface remaining questions to user directly. Stop. No infinite loop.
      - UNRESOLVABLE → surface reason to user. Stop.

The orchestrator classifies and returns a structured result. You process that result — you do not write code.
