# /estimate
Trigger: user types `/estimate story-X` where X is a story number

---

## Behavior

When the user invokes `/estimate story-165`, the main session:

1. **Parse the story ID** from the command: extract the numeric suffix and construct the full story ID (e.g., `165` → `story-165`).

2. **Read `epics.json`** from the current project root (find it via project detection or use the path passed in the context).

3. **Locate the story** by ID and extract:
   - `title` field
   - `writeFiles` array (count the files)
   - Infer the story's `agent` (see fallback rules below)
   - Infer the story's `model` (see fallback rules below)

4. **Compute estimated tokens**:
   - Base tokens = `writeFiles.length × 500`
   - Agent multiplier:
     - `architect` → 1.5x
     - `quick-fixer` → 1.0x
   - Estimated tokens = `Base tokens × Agent multiplier`

5. **Compute estimated cost**:
   - Input tokens = `Estimated tokens × 0.70` (70%)
   - Output tokens = `Estimated tokens × 0.30` (30%)
   - Per-model pricing (input / output per million tokens):
     - haiku: $0.80 / $4.00
     - sonnet: $3.00 / $15.00
     - opus: $15.00 / $75.00
   - Input cost = `(Input tokens / 1,000,000) × input_rate`
   - Output cost = `(Output tokens / 1,000,000) × output_rate`
   - Total cost = `Input cost + Output cost`

6. **Format the output** as a Markdown table:

```
Story: story-165 — Automated PR description generation
Agent: quick-fixer | Model: haiku

Estimate (approximate):
| Metric | Value |
|---|---|
| Write targets | 2 files |
| Base tokens (500/file) | 1,000 |
| Agent multiplier | 1.0x (quick-fixer) |
| Estimated tokens | ~1,000 |
| Input cost (haiku $0.80/M) | ~$0.001 |
| Output cost (haiku $4.00/M) | ~$0.004 |
| **Total estimated cost** | **~$0.005** |

Note: Actual usage depends on context file sizes, reviewer round-trips, and retries.
Multiply by 2-3x for stories likely to need revision.
```

7. **Return the formatted table** to the user.

---

## Fallback rules (agent and model fields)

The story object in `epics.json` does not include `agent` or `model` fields by default. Apply these fallbacks:

1. **If the story object has `agent` field explicitly set**: use it.
2. **If no `agent` field**: default to `quick-fixer`.
3. **If the story object has `model` field explicitly set**: use it.
4. **If no `model` field**: default to `haiku`.

---

## Cost formatting

- Format dollar amounts with 3 decimal places for values < $0.01 (e.g., `$0.001`)
- Format with 2 decimal places for values ≥ $0.01 (e.g., `$0.05`)
- Use `~` (approximately) prefix for all costs to indicate approximation

---

## Edge cases

- **Story not found**: Report "Story [id] not found in epics.json."
- **No writeFiles**: Report "Story [id] has no write targets."
- **Empty writeFiles array**: Treat as count = 0; show "0 files" and "0 tokens".
