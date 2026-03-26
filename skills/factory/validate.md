# Validate Phase

## Step 0: Parse args

**Flags:** `--dry-run`, `--pattern <pattern>`, `--format <format>` (gauntlet|canonical|auto, default auto)
**Input:** file ending `.json` → file mode. Otherwise → inline JSON. No args → error with usage.

## Step 0.5: Format detection and normalization

See [adapters.md](adapters.md) for full adapter contract.

**Auto-detection heuristics (first match):**
- `fields` entry has `kind` instead of `type` → gauntlet
- `permissions` is string not array → gauntlet
- `integrations` is flat string array → gauntlet
- `pattern` has underscore → gauntlet
- None match → canonical

**Gauntlet normalization:** `kind→type`, underscore→hyphen in pattern, string permissions→array, flat string integrations→objects.

## Step 0.5b: Schema validation

FeatureSpec shape:
```json
{
  "product": "string (required)",
  "pattern": "crud-ui | integration | workflow | analytics | library-extension (required)",
  "entity": "string (required)",
  "fields": [{"name": "string", "type": "string", "required?": true, "sensitive?": false, "ui_type?": "string"}],
  "permissions": ["string"],
  "audit": false,
  "integrations": [{"service": "string", "direction": "inbound|outbound|bidirectional", "events": ["string"]}],
  "ui": {"list": true, "detail": true, "form": true, "dashboard": true}
}
```

Print ALL validation errors, not just first. Stop on failure.

## Step 0.75: Decision conflict check

Skip if `--dry-run` (log conflicts but don't block).

1. Find `<project-root>/.claude/decisions.sql`. Missing → skip.
2. Parse SQL INSERTs for decision content/reasoning/scope.
3. Check spec against decisions. Examples:
   - Spec implies REST but decision says tRPC → CONFLICT
   - Spec has `sensitive: true` but no vault decision → WARNING
4. CONFLICTs require human choice. Present ALL at once:
   ```
   Decision conflicts found (N):
     [decision-1] <domain>: "<decision>"
       Spec implies: <default behavior>
       Options:
         (a) ADAPT — use project convention
         (b) CHANGE DECISION — supersede (requires rationale)
   ```
   All options must have equal detail.
5. WARNINGs are logged, no choice needed.
6. Store resolved `project_decisions` for planner prompt.
