# Factory Spec Format Adapters

## Purpose

Different organizations and challenge frameworks use different spec formats. The Gauntlet SF-2026-02 challenge format uses `kind` instead of `type`, flat string arrays for integrations, and underscored pattern names. Rather than requiring users to manually reformat specs, the factory normalizes any supported format to the canonical FeatureSpec before schema validation.

Adapters are the normalization layer. Each adapter knows how to take a raw JSON blob in a specific format and produce canonical FeatureSpec output.

---

## Adapter contract

**Input:** Raw parsed JSON (any shape — the adapter decides what to do with it).

**Output:** Canonical FeatureSpec JSON conforming to the schema defined in SKILL.md Step 0.5b.

**Requirements:**

1. Adapters MUST be idempotent. Running an adapter on already-canonical input MUST produce identical output. This guarantees that `--format gauntlet` on a canonical spec is harmless.
2. Adapters MUST NOT drop unknown fields. Any field not explicitly mapped passes through unchanged.
3. Adapters MUST return the count of fields actually transformed (for logging).

---

## Built-in adapters

### `canonical` (identity)

Pass-through. Returns the input unchanged with a transformation count of 0. Used when auto-detection finds no non-canonical signals.

### `gauntlet` (Gauntlet SF-2026-02 format)

Normalizes Gauntlet challenge specs to canonical FeatureSpec.

**Field mappings:**

| Gauntlet field | Canonical field | Transformation |
|---|---|---|
| `pattern` with underscores | `pattern` with hyphens | Replace `_` with `-` (`crud_ui` -> `crud-ui`) |
| `fields[].kind` | `fields[].type` | Rename key, preserve value |
| `fields[].values` | `fields[].values` | No change (canonical accepts enum values) |
| `permissions` (string) | `permissions` (array) | Wrap in array: `"perm"` -> `["perm"]` |
| `integrations` (string array) | `integrations` (object array) | Each string becomes `{"service": "<string>", "direction": "bidirectional", "events": ["sync"]}` |

All other fields (product, entity, audit, ui, fields[].name, fields[].required, fields[].sensitive, fields[].ui_type) pass through unchanged.

---

## Auto-detection

When `--format` is `auto` (default) or omitted, Step 0.5 runs a heuristic chain to detect the format. Heuristics are evaluated in order; the first match determines the format.

**Heuristic chain:**

1. Any `fields[]` entry has a `kind` key (instead of `type`) -> `gauntlet`
2. `permissions` is a string (not an array) -> `gauntlet`
3. `integrations` is a flat string array (elements are strings, not objects) -> `gauntlet`
4. `pattern` contains an underscore -> `gauntlet`
5. None of the above -> `canonical`

Multiple matching heuristics reinforce the `gauntlet` detection (they don't conflict). There is no "mixed" state that causes ambiguity -- if any gauntlet signal is present, the gauntlet adapter handles all normalization, and fields that are already canonical pass through unchanged due to idempotency.

**Precedence:** Explicit `--format` always wins over auto-detection.

---

## Adding a new adapter

To support a new spec format:

1. **Add detection heuristic.** In SKILL.md Step 0.5, add a new heuristic to the auto-detection chain (before the final `canonical` fallback). The heuristic should check for a field or naming convention unique to the new format.

2. **Define normalization rules.** Document the field-by-field transformation from the new format to canonical FeatureSpec. Every mapped field must be idempotent (running on canonical input is a no-op).

3. **Register the format name.** Add the new format name to the `--format` flag's accepted values in SKILL.md Step 0.

4. **Document the mapping.** Add a new subsection under "Built-in adapters" in this file, following the same table format as the `gauntlet` adapter.

5. **Add a worked example.** Include a raw -> canonical transformation example showing the exact JSON before and after.

---

## Worked example: Gauntlet Payment Methods spec

### Raw input (Gauntlet format)

```json
{
  "product": "collabboard",
  "pattern": "crud_ui",
  "entity": "PaymentMethod",
  "fields": [
    { "name": "provider", "kind": "string", "required": true },
    { "name": "status", "kind": "string", "values": ["active", "expired", "revoked"] },
    { "name": "last_four", "kind": "string" },
    { "name": "is_default", "kind": "boolean" }
  ],
  "permissions": "admin:write",
  "integrations": ["vault", "stripe"],
  "audit": true,
  "ui": { "list": true, "detail": true, "form": true, "dashboard": false }
}
```

### Auto-detection

Heuristic evaluation:
1. `fields[0].kind` exists -> **gauntlet detected** (first heuristic matches)
2. (Also: `permissions` is string, `integrations` is string array, `pattern` has underscore -- all reinforce)

Log: `Format detected: gauntlet (via auto). Normalized 8 fields.`

### Normalized output (canonical FeatureSpec)

```json
{
  "product": "collabboard",
  "pattern": "crud-ui",
  "entity": "PaymentMethod",
  "fields": [
    { "name": "provider", "type": "string", "required": true },
    { "name": "status", "type": "string", "values": ["active", "expired", "revoked"] },
    { "name": "last_four", "type": "string" },
    { "name": "is_default", "type": "boolean" }
  ],
  "permissions": ["admin:write"],
  "integrations": [
    { "service": "vault", "direction": "bidirectional", "events": ["sync"] },
    { "service": "stripe", "direction": "bidirectional", "events": ["sync"] }
  ],
  "audit": true,
  "ui": { "list": true, "detail": true, "form": true, "dashboard": false }
}
```

### What changed

| Field | Before | After | Count |
|---|---|---|---|
| `pattern` | `"crud_ui"` | `"crud-ui"` | 1 |
| `fields[0].kind` | `"string"` | renamed to `fields[0].type` | 1 |
| `fields[1].kind` | `"string"` | renamed to `fields[1].type` | 1 |
| `fields[2].kind` | `"string"` | renamed to `fields[2].type` | 1 |
| `fields[3].kind` | `"boolean"` | renamed to `fields[3].type` | 1 |
| `permissions` | `"admin:write"` | `["admin:write"]` | 1 |
| `integrations[0]` | `"vault"` | `{"service":"vault",...}` | 1 |
| `integrations[1]` | `"stripe"` | `{"service":"stripe",...}` | 1 |
| **Total** | | | **8** |
