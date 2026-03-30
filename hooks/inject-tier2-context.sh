#!/bin/bash
# UserPromptSubmit hook: scans user prompts for infrastructure keywords
# and injects targeted Tier 2 context on demand. Pure bash + grep for
# sub-200ms latency. Always exits 0 — injection hooks never block.

source "$(dirname "$0")/lib/profile.sh"
require_profile 1
[[ -z "$SESSION_ID" ]] && SESSION_ID="fallback-$$"

INPUT=$(cat)

# Session injection cap — max 3 per session
COUNTER_FILE="$CLAUDE_TEMP_DIR/tier2-count-${SESSION_ID}"
COUNT=0
if [[ -f "$COUNTER_FILE" ]]; then
  COUNT=$(cat "$COUNTER_FILE" 2>/dev/null)
  COUNT=${COUNT:-0}
fi
if (( COUNT >= 3 )); then
  exit 0
fi

# Extract prompt text via python3 JSON parsing
PROMPT=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('prompt', ''))
" 2>/dev/null)
if [[ -z "$PROMPT" ]]; then
  exit 0
fi

# Keyword patterns -> context categories
declare -a MATCHED_CATEGORIES=()

if echo "$PROMPT" | grep -iqE 'story-[0-9]+'; then
  MATCHED_CATEGORIES+=("story_detail")
fi
if echo "$PROMPT" | grep -iqE 'epics\.db|epics db'; then
  MATCHED_CATEGORIES+=("infra_db")
fi
if echo "$PROMPT" | grep -iqE 'openmemory|open memory'; then
  MATCHED_CATEGORIES+=("infra_openmemory")
fi
if echo "$PROMPT" | grep -iqE 'hook|pipeline'; then
  MATCHED_CATEGORIES+=("infra_hooks")
fi
if echo "$PROMPT" | grep -iqE 'worktree'; then
  MATCHED_CATEGORIES+=("infra_worktree")
fi
if echo "$PROMPT" | grep -iqE 'orchestrat'; then
  MATCHED_CATEGORIES+=("infra_orch")
fi
if echo "$PROMPT" | grep -iqE 'hotfix|quickfix|handoff|protected.file|/clear|merge.procedure|commit.rule'; then
  MATCHED_CATEGORIES+=("infra_procedures")
fi
if echo "$PROMPT" | grep -iqE 'correction|distill'; then
  MATCHED_CATEGORIES+=("infra_corrections")
fi
if echo "$PROMPT" | grep -iqE 'skill'; then
  MATCHED_CATEGORIES+=("infra_skills")
fi
if echo "$PROMPT" | grep -iqE '\bship\b'; then
  MATCHED_CATEGORIES+=("remind_ship_skill")
fi

if [[ ${#MATCHED_CATEGORIES[@]} -eq 0 ]]; then
  exit 0
fi

# Build context fragments
FRAGMENTS=()

for cat in "${MATCHED_CATEGORIES[@]}"; do
  case "$cat" in
    story_detail)
      DB_FILE="${DB_FILE:-$HOME/.claude/.claude/epics.db}"
      if [[ -f "$DB_FILE" ]]; then
        STORY_IDS=$(echo "$PROMPT" | grep -oE 'story-[0-9]+' | sort -u | head -3)
        for SID in $STORY_IDS; do
          ROW=$(python3 - "$DB_FILE" "$SID" <<'PYEOF'
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1], timeout=5)
row = conn.execute("SELECT id, title, state, branch, write_files, depends_on, agent FROM stories WHERE id=? AND archived=0", (sys.argv[2],)).fetchone()
if row:
    print("|".join(str(c) if c else "" for c in row))
conn.close()
PYEOF
)
          if [[ -n "$ROW" ]]; then
            IFS='|' read -r s_id s_title s_state s_branch s_writes s_deps s_agent <<< "$ROW"
            FRAGMENTS+=("[$s_id] $s_title | state: $s_state | branch: ${s_branch:-(none)} | writes: ${s_writes:-(none)} | deps: ${s_deps:-(none)} | agent: ${s_agent:-(none)}")
          fi
        done
      fi
      ;;
    infra_db)
      FRAGMENTS+=("epics.db schema: stories(id, epic_id, title, state, branch, write_files, depends_on, agent, plan_file, worktree_path). Query via sqlite3 or pm_* MCP tools.")
      ;;
    infra_openmemory)
      FRAGMENTS+=("OpenMemory MCP: tools=openmemory_store/query/list/get/reinforce/delete. Storage=~/.claude/.claude/openmemory.sqlite. Scoping: user_id=\"global\" (cross-project) or user_id=\"proj:<name>\". Embeddings: Ollama nomic-embed-text. Write discipline: all writes via om_write.py, tag whitelist enforced, dedup at 0.85 threshold.")
      ;;
    infra_hooks)
      FRAGMENTS+=("Hooks: SessionStart(load-session-context.sh), PreToolUse(guard-direct-edit, guard-protected-files, track-skill-changes, warn-sync-heavy-bash, block-enter-worktree, block-env-read), PostToolUse(context-check, log-skill-invocation), Stop(cost-alert, session-learning-check, stop-hook), UserPromptSubmit(inject-tier2-context). Profile levels: minimal(1), standard(2), strict(3).")
      ;;
    infra_worktree)
      FRAGMENTS+=("Worktrees at ~/.claude/worktrees/story/<branch>/. Coder agents run inside worktrees, not main session. EnterWorktree/ExitWorktree tools manage lifecycle.")
      ;;
    infra_orch)
      FRAGMENTS+=("Architecture and workflow in ~/.claude/ORCHESTRATION.md. Session procedures (merges, hotfixes, commits, context mgmt) in ~/.claude/refs/orch-procedures.md. Read with the Read tool -- do not rely on session context alone.")
      ;;
    infra_procedures)
      FRAGMENTS+=("Session procedures (hotfix/quickfix rules, merge flow, context management, protected files, commit discipline) in ~/.claude/refs/orch-procedures.md. Read with the Read tool.")
      ;;
    infra_corrections)
      FRAGMENTS+=("Corrections: logged directly to correction_groups table (epics.db) via log-correction.sh. Auto-detected by signal_processor.py at session end. Auto-promoted when count>=3. Preferences rendered from DB to .claude/rendered-prefs.md at session start. No corrections.md — that surface is dead.")
      ;;
    infra_skills)
      FRAGMENTS+=("Skills: ~/.claude/skills/*.md. Invoked via /skill-name. Telemetry logged to .claude/tracking/skill-telemetry.jsonl by log-skill-invocation.sh hook.")
      ;;
    remind_ship_skill)
      FRAGMENTS+=("REMINDER: User said 'ship'. Invoke the /ship skill via the Skill tool. Do NOT plan or code manually — /ship orchestrates the full pipeline (quickfix, plan-stories, draft-plans, critique, env-preflight, run-stories, verify).")
      ;;
  esac
done

if [[ ${#FRAGMENTS[@]} -eq 0 ]]; then
  exit 0
fi

# Assemble context
CONTEXT="=== TIER 2 CONTEXT (on-demand, keyword-triggered) ==="
for frag in "${FRAGMENTS[@]}"; do
  CONTEXT="$CONTEXT"$'\n'"$frag"
done

# Increment injection counter
COUNT=$((COUNT + 1))
echo "$COUNT" > "$COUNTER_FILE"

# JSON-escape the context string via json.dumps (handles all control characters)
ESCAPED=$(printf '%s' "$CONTEXT" | python3 -c "import json,sys; print(json.dumps(sys.stdin.read()))")

printf '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":%s}}' "$ESCAPED"
exit 0
