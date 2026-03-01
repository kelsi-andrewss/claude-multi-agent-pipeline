# Plan: Agent Activity Panel — Polish Pass

## Context
The panel redesign (compact rows, isHardStop flag, warning icon) is already implemented and sitting uncommitted on disk. This plan completes that work and layers on three improvements the user requested:
1. Rename the panel header to "Tool Calls"
2. Per-tool icons (each of the 6 backend tools gets a distinct icon)
3. Hard-stop rows expand on tap to show the annotation text

## Current state (already on disk, not committed)
- `agent_state.dart` — `isHardStop` field added
- `agent_state_panel.dart` — compact rows, amber hard-stop tint, warning icon, green checkmark, no dividers
- `chat_screen.dart` — `isHardStop: true` passed when injecting hard-stop events

## Changes needed

### File 1: `flutter/lib/features/agent_state/agent_state_panel.dart`

**A. Rename header** — change `'Agent Activity'` → `'Tool Calls'` in both `_SidePanelLayout` and `_BottomSheetContent`.

**B. Per-tool icons** — add a helper that maps snake_case tool name → `IconData`. Fall back to `Icons.build_outlined` for unknowns.

```dart
IconData _toolIcon(String toolName) => switch (toolName) {
  'symptom_timeline'           => Icons.timeline,
  'specialist_navigator'       => Icons.explore_outlined,
  'appointment_brief_generator'=> Icons.article_outlined,
  'provider_finder'            => Icons.person_search_outlined,
  'clinical_language_translator'=> Icons.translate,
  'insurance_coverage_check'   => Icons.shield_outlined,
  _                            => Icons.build_outlined,
};
```

Each row shows the tool icon (16px, `onSurfaceVariant`) to the LEFT of the status icon. Layout becomes:
```
[tool-icon 16px] [gap 6] [status-icon 16px] [gap 8] [label expanded] [gap 8] [elapsed 10px]
```
Hard-stop rows skip the tool icon (use the warning icon only, centered where tool icon would be, 18px).

**C. Expandable hard-stop annotation** — convert `_EventTile` from `StatelessWidget` to `StatefulWidget`. On tap of a hard-stop row, toggle `_expanded`. When expanded, show the annotation text below the row in a padded container with `tertiaryContainer` tint.

```
⚠  Hard stop — why Advocate paused         4s
─────────────────────────────────────────────
   Somatic trigger detected: sensory
   sensitivity pattern flagged. The agent
   is cross-referencing post-concussion
   syndrome symptom clusters.
```
Text is `bodySmall`, `onTertiaryContainer`, 12px padding left (aligns with label). Animate with `AnimatedCrossFade` or simply `if (_expanded)` — the latter is fine since the list scrolls.

**D. Running state** — for a `running` tool event, show the tool icon in `primary` color (instead of `onSurfaceVariant`) to signal it's active.

### No other files need changes
- `agent_state.dart` — already done
- `chat_screen.dart` — already done
- `agent_state_provider.dart` — already done
- `router.dart` — no change needed

## Critical files
- `flutter/lib/features/agent_state/agent_state_panel.dart` — sole write target
- `flutter/lib/shared/models/agent_state.dart` — read-only (already updated)
- `flutter/lib/features/chat/chat_screen.dart` — read-only (already updated)

## Tool name → icon mapping (complete)
| Backend tool_name | Icon |
|---|---|
| symptom_timeline | Icons.timeline |
| specialist_navigator | Icons.explore_outlined |
| appointment_brief_generator | Icons.article_outlined |
| provider_finder | Icons.person_search_outlined |
| clinical_language_translator | Icons.translate |
| insurance_coverage_check | Icons.shield_outlined |
| Hard stop — why Advocate paused | (no tool icon — warning icon only) |
| unknown / fallback | Icons.build_outlined |

## Verification
1. Run `flutter analyze --no-pub` — no new errors.
2. Start demo (sign in → Try demo → Serena → chat).
3. Panel header reads "Tool Calls".
4. As each message sends, tool rows appear with their specific icon (timeline, explore, etc.) + green checkmark when done.
5. When a hard-stop message is sent, an amber row appears with the warning icon. Tapping it expands to show the annotation text. Tapping again collapses.
6. Running tool shows tool icon in primary color.
7. Commit all three files (agent_state_panel.dart + already-modified agent_state.dart + chat_screen.dart).
