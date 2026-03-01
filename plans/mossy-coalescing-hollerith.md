# Plan: `gemini_redesign` MCP Tool

## Context

The existing Gemini MCP server at `/Users/kelsiandrews/.claude/mcp-servers/gemini/server.py` has tools for planning, auditing, and analysis — but nothing for UI/UX design. Gemini's large context window and M3 knowledge make it uniquely suited to scan an entire frontend codebase and produce structured, actionable redesign recommendations. This tool will fill that gap: Gemini scans, analyzes, and writes a `REDESIGN.md` design spec; Claude reads that spec and implements changes in a separate step.

**Design philosophy:**
- Gemini = design intelligence (large context, M3/design system expertise)
- Claude = implementation intelligence (precise Dart/code edits, regression awareness)
- Clear separation of concerns via a persisted `REDESIGN.md` artifact

---

## What We're Building

A new `gemini_redesign` MCP tool that:
1. Detects frontend framework from the target path (`pubspec.yaml` → Flutter, `package.json`+JSX → React, etc.)
2. Scans the codebase for screens, widgets, theme files, navigation config, and icon usage
3. Sends the full context to Gemini with a framework-aware system prompt
4. Writes a structured `REDESIGN.md` to CWD
5. Returns a summary of what was written

**Output format:** Structured Markdown (NOT Dart code — keeps the clean prose contract). Claude implements from the doc separately.

---

## Tool Signature

```python
@mcp.tool()
async def gemini_redesign(
    path: str | None = None,                    # Root of the project to scan (default: PROJECT_ROOT)
    paths: list[str] | None = None,             # Optional scope narrowing (specific dirs/files)
    sections: list[str] | None = None,          # e.g. ["theme", "icons", "navigation", "animations"]
    model: str | None = None,                   # Override Gemini model
    output: str | None = None,                  # Override output file path (default: CWD/REDESIGN.md)
) -> str:
```

Default sections when none specified: `["theme", "icons", "navigation", "animations", "platform"]`

---

## Implementation Plan

### 1. Framework Detection (`_detect_framework`)

New helper function. Checks for framework-identifying files:
- `pubspec.yaml` → `"flutter"`
- `package.json` with react/next dep → `"react"`
- `package.json` with vue dep → `"vue"`
- Falls back to `"unknown"` with generic design guidance

### 2. File Discovery (`_collect_redesign_files`)

Reuse the existing `_collect_files()` pattern (lines 90–131 of server.py) with:
- Flutter: prioritize `.dart` files matching `*screen*.dart`, `*page*.dart`, `*widget*.dart`, `*theme*.dart`, `*app.dart`, `pubspec.yaml`
- React: prioritize `.tsx/.jsx` files, `tailwind.config.*`, `theme.*`
- Budget: reuse `MAX_CODE_BYTES = 200_000` constant already defined

### 3. Framework-Aware System Prompt

One prompt template per framework, injected as `system_instruction`. Flutter template covers:

**M3 Theme section:**
- ColorScheme.fromSeed usage, surface tones, dynamic color eligibility
- Typography scale gaps, text theme completeness
- Component theme overrides (CardTheme, AppBarTheme, etc.)

**Navigation + Transitions section:**
- GoRouter page transitions (current vs. recommended)
- Shared element heroes for screen-to-screen continuity
- Platform-adaptive: `CupertinoPageTransition` on iOS, Material fade/shared-axis on Android
- Web: fade transitions (no slide — feels wrong on web)

**Lucide Icons section:**
- System prompt includes: Lucide package name (`lucide_flutter`), naming convention (PascalCase), and note that navigation icons (bottom nav, drawer) stay as Material
- Gemini maps each `Icons.xxx` usage found → suggest specific `lucide_flutter` equivalent with verify note
- Format: `Icons.search → lucide_flutter: Search (verify exists)`

**Animation Audit section:**
- Flag `setState` calls that could be `AnimatedSwitcher`
- Flag list builds that could use `AnimatedList`
- Flag route transitions missing `AnimationController`
- Suggest `SpringSimulation` for physics-based feel
- Implicit animations: `AnimatedContainer`, `AnimatedOpacity`, `AnimatedAlign`

**Platform Features section:**
- iOS: `HapticFeedback`, safe area insets, `CupertinoSwitch` candidates
- Android: `DynamicColorBuilder` for Material You, predictive back gesture registration
- Web: hover states (`MouseRegion`), cursor changes, responsive breakpoints
- Desktop: dense layout variants, `MenuBar`, pointer-specific interactions

### 4. REDESIGN.md Structure

```markdown
# Redesign Report — {framework} — {date}
## Executive Summary
## 1. M3 Theme & Color System
## 2. Navigation & Transitions
## 3. Icon Migration (Lucide)
## 4. Animation Opportunities
## 5. Platform-Specific Features
## Implementation Priority (High / Medium / Low per item)
```

### 5. Tool Implementation

File to modify: `/Users/kelsiandrews/.claude/mcp-servers/gemini/server.py`

Add after the existing `audit` tool (around line 575):

```
_detect_framework(path) → str
_collect_redesign_files(root, paths, framework) → tuple[str, list[str]]
_build_redesign_prompt(framework, sections, code_context) → str
async gemini_redesign(...) → str   ← the MCP tool
```

The tool **overrides NO_CODE_INSTRUCTION** for its own system prompt — redesign outputs structured prose + icon name suggestions, not code blocks. A `REDESIGN_SYSTEM_INSTRUCTION` constant replaces it for this tool only.

### 6. Output

- Writes `REDESIGN.md` to CWD (or `output` path if provided)
- Returns: `"REDESIGN.md written ({N} sections, {M} files scanned). Review it and implement with Claude."`

---

## Files to Modify

| File | Change |
|------|--------|
| `/Users/kelsiandrews/.claude/mcp-servers/gemini/server.py` | Add `gemini_redesign` tool + 3 helper functions |
| `/Users/kelsiandrews/.claude/mcp-servers/gemini/test_server.py` | Add test cases for new tool |

No new files needed — fits cleanly into the existing server pattern.

---

## Verification

1. **Restart MCP server** — Claude Code picks up new tool from `settings.json` (already configured)
2. **Call the tool**: `gemini_redesign(path="/Users/kelsiandrews/gauntlet/advocate/flutter")`
3. **Check REDESIGN.md** written to CWD with all 5 sections populated
4. **Verify Lucide suggestions** contain specific icon names with `(verify exists)` annotations
5. **Check framework detection**: rename pubspec.yaml temporarily → should fall back to "unknown"
6. **Test section filtering**: `gemini_redesign(sections=["icons"])` → only icon section in output
7. **Run existing tests**: `pytest test_server.py` — all prior tests still pass
