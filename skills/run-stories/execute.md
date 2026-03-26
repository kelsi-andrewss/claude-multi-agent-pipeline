# Execute Phase

Process dependency groups sequentially. Within each group, process conflict batches.

After each batch merges via validate phase, run **batch verification** before launching the next batch.

## Context sharding (>8 stories in a parallel batch)

Split into shards of 3-5 stories. Launch a "lead" agent (general-purpose, Sonnet) per shard that:
1. Receives shard stories with full coder prompts
2. Launches coder agents as background agents
3. Handles tactical NEED_DECISION autonomously
4. Escalates strategic/critical NEED_DECISION to main session
5. Runs fix-loop for each completed coder
6. Returns shard summary: DONE/NEED_DECISION/BLOCKED per story

When batch size ≤8, skip sharding — launch coders directly.

## Launch each story

Launch all stories in the batch in **a single message** as `general-purpose` agents with `run_in_background: true`.

```bash
bash ~/.claude/scripts/emit-event.sh "story.launched" "claude" '{"story_id":"<story_id>","batch":<batch_num>,"agent":"<agent-type>","branch":"<story-branch>"}'
```

Compute per story:
- `story-slug`: lowercase title, replace spaces/special with `-`, truncate 40 chars, append `-<NNN>` (numeric story ID part)
- `story-branch`: `<epic-slug>--<story-slug>`
- `has-test-files`: true if story's `test_files` is non-empty
- `worktree-path`: if has-test-files, use `--code` and `--test` suffixed paths; otherwise single path
- `agent-approach`: quick-fixer→"surgical, minimal"; architect→"full architectural"; ui-coder→"ALL visual via gemini_ui_code, you own wiring only"

**UI codegen pre-launch gate:** If `ui_codegen: true`, agent MUST be `ui-coder` — override if not. If `ui_codegen` not set but title has UI keywords, log warning (non-blocking).

**Per-story data** from resolution subagent: use pitfalls, learnings, read_only_context, gitignore_warnings. No additional MCP calls. If all write targets gitignored → skip as BLOCKED.

**Protected files:** Read `<project-root>/.claude/protected-files.md` if it exists.

Build the coder prompt from [coder-prompt.md](coder-prompt.md). If `has-test-files`, also launch test agent from [test-agent.md](test-agent.md).

## Sequential batches

After previous batch completes, before launching:
1. Sync dev branch: `git fetch origin <dev-branch>`
2. If story branch exists in worktree: `git -C <worktree-path> rebase origin/<dev-branch>`
3. Rebase conflicts → mark BLOCKED, continue

## Agent health monitoring

After launching all agents in a batch:
```bash
python3 ~/.claude/scripts/agent-watchdog.py \
  --session-id "$SESSION_ID" \
  --story-ids "<comma-separated>" \
  --agent-pids "<comma-separated>" \
  --agent-types "<comma-separated>"
```

Run in background. Killed agents → BLOCKED with "Watchdog killed: " prefix.

## Batch verification

After each non-final batch merges into dev:
```bash
RESULT=$(bash ~/.claude/scripts/validation-runner.sh --project-root <project-root> --layer all)
```

- `overall_status: "pass"` → continue to next batch
- `overall_status: "fail"` → mark ALL subsequent batch stories BLOCKED
- `overall_status: "skip"` → continue (no build system)

Single-batch runs skip this entirely. Bootstrap batch uses its own gate (Step 2c in resolve).

## Enrichment reference (for resolution subagent prompt)

> Pass these verbatim to the resolution subagent:
>
> **Pitfalls:** Read `<project-root>/refs/pattern-categories.json`. Map write_file extensions to categories via `extension_map` and `path_overrides`. Call `pm_list_patterns(category=<cat>)` per category. Format as bullets.
>
> **Learnings:** Call `openmemory_query(query="<tech-stack-keywords> <write-target-filenames>", user_id="global", n=5)`. Filter to procedural/semantic sectors. Format as bullets.
>
> **Read-only context:** Extract paths from plan file `## Read-only context` section.
>
> **Gitignore check:** Run `git -C <project-root> check-ignore <write_files>`. Return gitignored files as warnings.
