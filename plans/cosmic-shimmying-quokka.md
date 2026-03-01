# PR #2: Selective merge — Windows fixes only

## Context

PR #2 by FpSilSha adds Windows compatibility and auto key-prompts extraction. Decision: take the Windows/UTF-8 fixes, skip the auto key-prompts extraction, and open a GitHub issue for the extraction feature assigned to both kelsi-andrewss and FpSilSha.

The PR was authored against pre-v1.3.0 main, so it cannot be merged as-is. We manually apply the wanted changes as a new commit.

---

## Files to take (apply manually)

| File | What to take |
|------|-------------|
| `src/platform_utils.py` | Take as-is (new file) |
| `src/stop-hook.js` | Take as-is (new file) |
| `install.js` | Take as-is, revert repo URL to `kelsi-andrewss/` |
| `uninstall.js` | Take as-is (new file) |
| `bin/claude-tracker-cost.js` | Take as-is (new file) |
| `src/init-templates.py` | Take as-is, but add `agents.json: []` entry (our v1.3.0 addition missing from PR) |
| `src/parse-session.py` | Take, but remove the `extract_key_prompts` import and the `write_key_prompts` call at the bottom |
| `src/backfill.py` | Take only: `platform_utils` import + `get_transcripts_dir()` usage + `encoding="utf-8"` fixes. Drop the `extract_key_prompts` import and the entire "Extract key prompts" block at the bottom. Keep `run_python_script` import since backfill uses it for chart regen. |
| `src/stop-hook.sh` | Take only the 3 `encoding='utf-8'` additions. Drop the `extract_key_prompts` inline Python block. |
| `src/generate-charts.py` | Take all: `platform_utils` import + `slugify_path()` usage + all `encoding="utf-8"` additions. Must merge carefully with our v1.3.0 agents section. |
| `src/cost-summary.py` | Take all changes (platform_utils import, git root fix, file open fix, encoding fix) |
| `src/patch-durations.py` | Take encoding fixes only |
| `src/update-prompts-index.py` | Take encoding fix only |
| `install.sh` | Take only the `.gitignore` warning block at the end. Our v1.3.0 SubagentStop changes stay intact. |
| `package.json` | Take all changes except: revert repo URL back to `kelsi-andrewss/` |
| `skills/view-tracking/SKILL.md` | Take as-is (adds Windows `start` branches) |
| `.gitignore` | Take as-is |

## Files to skip entirely

| File | Reason |
|------|--------|
| `src/extract_key_prompts.py` | Auto-populates key-prompts on every session; breaks the curated intent and the efficiency metric |
| `CHANGELOG.md` from PR | PR's v1.2.5 entry conflicts with our v1.3.0; write a fresh v1.3.1 entry instead |

---

## Conflict notes

These files overlap with our v1.3.0 commit and need careful manual merging:

- **`src/generate-charts.py`** — PR adds `platform_utils` import at top + slugify change at line ~86 + encoding fixes. Our v1.3.0 added the agents section (loads `agents.json`, aggregates, renders Agents dashboard section). Both sets of changes are in different parts of the file — no logical conflict, just needs both applied.
- **`install.sh`** — PR adds `.gitignore` warning at the end. Our v1.3.0 added `SUBAGENT_HOOK_CMD` derivation and SubagentStop registration in the Python heredoc. No overlap — append warning block after our changes.
- **`src/init-templates.py`** — New file from PR, but missing `agents.json: []` which we added to `init-templates.sh` in v1.3.0. Add it to the `templates` dict.
- **`src/stop-hook.sh`** — PR only adds 3 `encoding=` fixes and the `extract_key_prompts` block. Take the encoding fixes, skip the extraction block. No conflict with our SubagentStop work (separate file).

---

## GitHub issue to open

**Title**: `feat: auto key-prompts extraction from transcripts`

**Body**:
```
Proposed in PR #2 by @FpSilSha. Deferred from the Windows support merge because the current design auto-populates key-prompts files with every non-trivial message, which conflicts with the curated intent of the feature and breaks the prompt efficiency metric.

## What was proposed
- `src/extract_key_prompts.py` — extracts non-trivial human messages from JSONL transcripts and writes them to `key-prompts/YYYY-MM-DD.md` with auto-assigned categories
- Wired into `stop-hook.sh`, `backfill.py`, and `parse-session.py` to run on every session and backfill

## Issues to resolve before merging
1. **Opt-in required** — should be disabled by default; users who want auto-extraction enable it via a config flag
2. **Categorization quality** — keyword heuristics misclassify too often; consider leaving category blank for manual fill instead
3. **Duplicate detection** — first-80-chars substring match is fragile for prompts that start with common phrases
4. **Missing fields** — auto entries omit `Why It Worked` and `Prior Attempts That Failed`; either generate stubs or redesign the entry format for auto entries
5. **Efficiency metric** — auto-extracted entries should not count toward the prompt efficiency ratio (or the metric needs a separate "auto vs manual" breakdown)
```

**Assignees**: `kelsi-andrewss`, `FpSilSha`

---

## CHANGELOG entry (v1.3.1)

```markdown
## [1.3.1] - 2026-02-24

### Added
- **Windows support** — full Windows compatibility via Node.js wrappers (`install.js`, `uninstall.js`, `stop-hook.js`, `bin/claude-tracker-cost.js`) and a new `platform_utils.py` module centralizing OS-specific path handling and file opening.
- **`src/parse-session.py`** — transcript parsing logic extracted from the `stop-hook.sh` heredoc into a standalone module, callable by both `stop-hook.sh` and `stop-hook.js`.
- **`src/init-templates.py`** — cross-platform Python replacement for `init-templates.sh`.
- **`.gitignore` warning** — `install.sh` and `install.js` now warn if `.claude/` is not covered by the project's `.gitignore`, preventing accidental commits of tracking data.
- **Skills Windows support** — `/view-tracking` skill now uses `start ""` on Windows alongside existing `open`/`xdg-open` paths.

### Fixed
- **`encoding="utf-8"`** added to all file open calls across `stop-hook.sh`, `backfill.py`, `generate-charts.py`, `cost-summary.py`, `patch-durations.py`, `update-prompts-index.py` — prevents crashes on Windows when transcripts contain non-ASCII characters.
- **Path slugification** — `generate-charts.py` and `backfill.py` now use `platform_utils.slugify_path()` for cross-platform project path → slug conversion (handles Windows backslashes and drive letter colons).
```

---

## Verification

1. `python3 -c "import ast; ast.parse(open('src/generate-charts.py').read())"` — confirm no syntax errors after merge
2. `bash -n src/stop-hook.sh` — confirm shell syntax valid
3. `python3 -c "import ast; ast.parse(open('src/parse-session.py').read())"` — no extract_key_prompts import
4. `python3 -c "import ast; ast.parse(open('src/backfill.py').read())"` — no extract_key_prompts import
5. `python3 -c "import ast; ast.parse(open('src/init-templates.py').read())"` — confirm `agents.json` entry present
6. Confirm `~/.claude/settings.json` still has SubagentStop hook after re-running `install.sh`
7. Confirm GitHub issue created and assigned to both users

## Context

The tracker currently only captures main-session token usage via the `Stop` hook. Users running multi-agent pipelines (background Task agents — coders, reviewers, testers) have no way to attribute cost per agent invocation. This feature adds a `SubagentStop` hook that fires when each spawned agent finishes, captures its token usage from the agent's own transcript, and surfaces it in a new "Agents" dashboard section.

The `SubagentStop` payload provides `agent_transcript_path` (the subagent's own JSONL) and `agent_type` (the `subagent_type` string passed to Task, e.g. `architect`, `quick-fixer`, `Explore`, `Bash`). Token extraction follows the exact same pattern as `stop-hook.sh`.

---

## Files to modify

| File | Change |
|------|--------|
| `src/subagent-stop-hook.sh` | **New** — SubagentStop hook script |
| `src/init-templates.sh` | Add `agents.json` initialization |
| `src/generate-charts.py` | New "Agents" section with 2 charts + stat tile |
| `install.sh` | Register SubagentStop hook + permission entry |
| `CHANGELOG.md` | Add v1.3.0 entry |
| `README.md` | Document SubagentStop hook and agents.json |

---

## agents.json schema

One entry appended per SubagentStop event. No deduplication needed — each firing is a unique invocation.

```json
{
  "timestamp": "2026-02-23T14:30:00Z",
  "session_id": "abc123",
  "agent_id": "def456",
  "agent_type": "architect",
  "input_tokens": 45000,
  "output_tokens": 2100,
  "cache_creation_tokens": 8000,
  "cache_read_tokens": 60000,
  "total_tokens": 115100,
  "turns": 8,
  "estimated_cost_usd": 0.2341,
  "model": "claude-sonnet-4-6"
}
```

Token approach: **sum all turns** in the subagent transcript (all assistant-message usage blocks). `turns` = count of assistant messages processed.

---

## 1. src/subagent-stop-hook.sh (new file)

Structure mirrors `stop-hook.sh` exactly.

```bash
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

INPUT="$(cat)"

# Extract fields from SubagentStop payload
CWD="$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('cwd',''))" 2>/dev/null || true)"
TRANSCRIPT="$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('agent_transcript_path',''))" 2>/dev/null || true)"
SESSION_ID="$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('session_id',''))" 2>/dev/null || true)"
AGENT_ID="$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('agent_id',''))" 2>/dev/null || true)"
AGENT_TYPE="$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('agent_type','unknown'))" 2>/dev/null || true)"

if [[ -z "$CWD" || -z "$TRANSCRIPT" || ! -f "$TRANSCRIPT" ]]; then exit 0; fi

# Find project root (walk up to .git)
PROJECT_ROOT="$CWD"
while [[ "$PROJECT_ROOT" != "/" ]]; do
  [[ -e "$PROJECT_ROOT/.git" ]] && break
  PROJECT_ROOT="$(dirname "$PROJECT_ROOT")"
done
if [[ "$PROJECT_ROOT" == "/" ]]; then exit 0; fi

TRACKING_DIR="$PROJECT_ROOT/.claude/tracking"
# Only run if tracking is already initialized — don't auto-init from subagent hook
if [[ ! -d "$TRACKING_DIR" ]]; then exit 0; fi

# Parse token usage from subagent JSONL — sum all turns
python3 - "$TRANSCRIPT" "$TRACKING_DIR/agents.json" "$SESSION_ID" "$AGENT_ID" "$AGENT_TYPE" <<'PYEOF'
import sys, json, os
from datetime import datetime, date

transcript_path = sys.argv[1]
agents_file     = sys.argv[2]
session_id      = sys.argv[3]
agent_id        = sys.argv[4]
agent_type      = sys.argv[5]

# Sum usage across ALL assistant messages in the transcript
total_inp = total_out = total_cache_create = total_cache_read = 0
model = "unknown"
turns = 0
first_ts = None

with open(transcript_path) as f:
    for line in f:
        try:
            obj = json.loads(line)
            msg = obj.get('message', {})
            if not isinstance(msg, dict):
                continue
            if msg.get('role') == 'assistant':
                usage = msg.get('usage', {})
                if usage:
                    total_inp          += usage.get('input_tokens', 0)
                    total_out          += usage.get('output_tokens', 0)
                    total_cache_create += usage.get('cache_creation_input_tokens', 0)
                    total_cache_read   += usage.get('cache_read_input_tokens', 0)
                    turns += 1
                m = msg.get('model', '')
                if m:
                    model = m
            ts = obj.get('timestamp')
            if ts and first_ts is None:
                first_ts = ts
        except:
            pass

total = total_inp + total_out + total_cache_create + total_cache_read
if total == 0:
    sys.exit(0)

if 'opus' in model:
    cost = total_inp * 15/1e6 + total_cache_create * 18.75/1e6 + total_cache_read * 1.50/1e6 + total_out * 75/1e6
else:
    cost = total_inp * 3/1e6 + total_cache_create * 3.75/1e6 + total_cache_read * 0.30/1e6 + total_out * 15/1e6

try:
    ts_str = datetime.fromisoformat(first_ts.replace('Z', '+00:00')).strftime('%Y-%m-%dT%H:%M:%SZ')
except:
    ts_str = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

entry = {
    'timestamp':             ts_str,
    'session_id':            session_id,
    'agent_id':              agent_id,
    'agent_type':            agent_type,
    'input_tokens':          total_inp,
    'output_tokens':         total_out,
    'cache_creation_tokens': total_cache_create,
    'cache_read_tokens':     total_cache_read,
    'total_tokens':          total,
    'turns':                 turns,
    'estimated_cost_usd':    round(cost, 4),
    'model':                 model,
}

data = []
if os.path.exists(agents_file):
    try:
        with open(agents_file) as f:
            data = json.load(f)
    except:
        data = []

data.append(entry)
with open(agents_file, 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
PYEOF

# Regenerate charts (agents.json path is derived from tokens.json dirname inside generate-charts.py)
python3 "$SCRIPT_DIR/generate-charts.py" "$TRACKING_DIR/tokens.json" "$TRACKING_DIR/charts.html" 2>/dev/null || true
```

Key differences from `stop-hook.sh`:
- Uses `agent_transcript_path` not `transcript_path`
- No `stop_hook_active` loop guard (not needed for SubagentStop)
- Does NOT auto-init `TRACKING_DIR` — silently exits if not present
- Sums all turns instead of pairing user/assistant messages
- Appends to `agents.json` (no upsert — each invocation is unique)

---

## 2. src/init-templates.sh

Add after line 9 (after `tokens.json` block):

```bash
cat > "$TRACKING_DIR/agents.json" <<'EOF'
[]
EOF
```

---

## 3. src/generate-charts.py

### Python changes

After `tokens_file = sys.argv[1]`:
```python
# Load agent data (optional — file may not exist on older installs)
agents_file = os.path.join(os.path.dirname(os.path.abspath(tokens_file)), 'agents.json')
agent_data = []
if os.path.exists(agents_file):
    try:
        with open(agents_file) as f:
            agent_data = json.load(f)
    except:
        pass
```

Aggregate (only if `agent_data`):
```python
by_agent_type = defaultdict(lambda: {"cost": 0, "count": 0})
for a in agent_data:
    t = a.get('agent_type', 'unknown')
    by_agent_type[t]["cost"]  += a.get('estimated_cost_usd', 0)
    by_agent_type[t]["count"] += 1

agent_types_sorted = sorted(by_agent_type.keys(), key=lambda t: -by_agent_type[t]["cost"])
total_agent_cost = sum(a.get('estimated_cost_usd', 0) for a in agent_data)
total_agent_invocations = len(agent_data)

agent_labels_js = json.dumps(agent_types_sorted)
agent_costs_js  = json.dumps([round(by_agent_type[t]["cost"], 4) for t in agent_types_sorted])
agent_counts_js = json.dumps([by_agent_type[t]["count"] for t in agent_types_sorted])
```

### HTML changes

1. **New stat tile** (after existing 7 tiles, conditional on `agent_data`):
```html
<!-- only rendered if agent_data -->
<div class="stat">
  <div class="stat-label">Agent cost</div>
  <div class="stat-value">${total_agent_cost:.2f}</div>
  <div class="stat-sub">{total_agent_invocations} invocations</div>
</div>
```

2. **New CSS** (in `<style>`):
```css
.section-header.agents { border-left: 3px solid #f97316; color: #fb923c; }
```

3. **New section** between Cost & Usage and Key Prompts (conditional on `agent_data`):
```html
<div class="section">
  <div class="section-header agents">Agents</div>
  <div class="grid">
    <div class="card">
      <h2>Cost by agent type</h2>
      <canvas id="agentCost"></canvas>
    </div>
    <div class="card">
      <h2>Invocations by agent type</h2>
      <canvas id="agentCount"></canvas>
    </div>
  </div>
</div>
```

4. **JS constants** (in `<script>`):
```js
const AGENT_LABELS = {agent_labels_js};
const AGENT_COSTS  = {agent_costs_js};
const AGENT_COUNTS = {agent_counts_js};
```

5. **Chart instances**:
```js
new Chart(document.getElementById('agentCost'), {
  type: 'bar',
  data: { labels: AGENT_LABELS,
    datasets: [{ label: 'Cost ($)', data: AGENT_COSTS,
      backgroundColor: '#f97316', borderRadius: 4 }] },
  options: { ...baseOpts, plugins: { ...baseOpts.plugins,
    tooltip: { callbacks: { label: ctx => ' $' + ctx.parsed.y.toFixed(4) } } } }
});

new Chart(document.getElementById('agentCount'), {
  type: 'bar',
  data: { labels: AGENT_LABELS,
    datasets: [{ label: 'Invocations', data: AGENT_COUNTS,
      backgroundColor: '#fb923c', borderRadius: 4 }] },
  options: baseOpts
});
```

**Conditional rendering strategy**: Use Python f-string conditional blocks — if `not agent_data`, set `agents_section_html = ''` and `agents_stat_html = ''`, else render them. Insert via `{agents_section_html}` and `{agents_stat_html}` in the f-string template.

---

## 4. install.sh

### Bash changes

After `HOOK_CMD=...` in both branches (Homebrew + direct), derive:
```bash
SUBAGENT_HOOK_CMD="${HOOK_CMD/stop-hook.sh/subagent-stop-hook.sh}"
```

Pass as third arg to the Python heredoc:
```bash
python3 - "$SETTINGS" "$HOOK_CMD" "$SUBAGENT_HOOK_CMD" <<'PYEOF'
```

### Python patcher changes (inside heredoc)

Add `subagent_hook_cmd = sys.argv[3]` after existing argv reads.

After the `SessionStart` block, add:
```python
# SubagentStop hook
subagent_entry = {"type": "command", "command": subagent_hook_cmd, "timeout": 30, "async": True}
subagent_hooks = hooks.setdefault("SubagentStop", [])
subagent_hooks[:] = [
    g for g in subagent_hooks
    if not any("subagent-stop-hook.sh" in h.get("command", "") for h in g.get("hooks", []))
]
subagent_hooks.append({"hooks": [subagent_entry]})
```

In the permissions block, also clean/add subagent entry:
```python
subagent_allow = f"Bash({subagent_hook_cmd}*)"
allow_list[:] = [e for e in allow_list if "stop-hook.sh" not in e and "subagent-stop-hook.sh" not in e]
allow_list.append(allow_entry)
allow_list.append(subagent_allow)
```

---

## 5. CHANGELOG.md

Prepend new version block:

```markdown
## [1.3.0] - 2026-02-23

### Added
- **SubagentStop hook** — new `subagent-stop-hook.sh` fires when each spawned Task agent
  finishes. Parses the agent's own transcript (`agent_transcript_path`), sums token usage
  across all turns, and appends an entry to `agents.json` in the project's tracking directory.
- **`agents.json`** — new per-invocation ledger: `agent_type`, `input_tokens`,
  `output_tokens`, `cache_creation_tokens`, `cache_read_tokens`, `total_tokens`, `turns`,
  `estimated_cost_usd`, `model`, `timestamp`, `session_id`, `agent_id`.
- **Agents dashboard section** — new "Agents" section in `charts.html` (between Cost & Usage
  and Key Prompts) with cost-by-agent-type and invocations-by-agent-type bar charts, plus
  a stat tile showing total agent cost and invocation count. Section is hidden when no agent
  data exists (older projects unaffected).
```

---

## 6. README.md

### Update "What it tracks" section

Add bullet:
```markdown
- **Per-agent cost breakdown**: SubagentStop hook captures each spawned agent's token usage
  separately — see which agent types (architect, quick-fixer, Explore, etc.) drive the most cost
```

### Update "What gets created" file tree

Add `agents.json` to the tree:
```
.claude/tracking/
  tokens.json          # main session data (auto-updated)
  agents.json          # per-agent invocation data (auto-updated)
  charts.html          # Chart.js dashboard (auto-updated)
  ...
```

### Add new section "Multi-agent tracking"

Between "View the dashboard" and "Cost CLI":
```markdown
## Multi-agent tracking

When using Claude Code's Task tool to spawn background agents, each agent's cost is tracked
separately. The `SubagentStop` hook fires when each agent finishes and appends an entry to
`agents.json` with:
- `agent_type` — the subagent type (e.g. `architect`, `quick-fixer`, `Explore`, `Bash`)
- token counts summed across all internal turns
- `estimated_cost_usd` using the same list-price formula as main sessions

The dashboard shows an "Agents" section with cost and invocation count by agent type, letting
you identify which agent types are expensive relative to their output.

No configuration needed — the SubagentStop hook is registered automatically on install.
```

---

## Verification

1. **Install the new hook**: run `./install.sh`, verify `~/.claude/settings.json` has a `SubagentStop` entry pointing at `subagent-stop-hook.sh` and a `Bash(...)` allow entry for it.

2. **Trigger a subagent**: use the Task tool in a project that has `tracking/` initialized. When the agent finishes, check that `agents.json` has a new entry with correct `agent_type` and non-zero token counts.

3. **Charts update**: open `charts.html` — confirm the "Agents" section appears with correct data. Open a project with no `agents.json` — confirm the section is absent (no JS errors).

4. **init-templates**: delete a project's `tracking/` directory, run a session to trigger auto-init via `stop-hook.sh`, confirm both `tokens.json` and `agents.json` are created as empty arrays.

5. **Token accuracy**: compare `estimated_cost_usd` in `agents.json` against total session cost in `tokens.json` for a session that used only one background agent — agent cost should be less than or equal to session cost.
