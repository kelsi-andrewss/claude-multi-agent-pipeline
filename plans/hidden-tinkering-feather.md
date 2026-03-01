# Chat-First Navigation Redesign

## Context

The app currently uses a bottom NavigationBar with 3 tabs (Chat, Upload, Settings). The Upload tab is a stub. The design feels like a multi-tab utility rather than a modern chat-first experience. This redesign replaces the bottom nav with a hamburger drawer + AppBar avatar pattern, consolidates controls, adds an attach button with file picker to the chat input, and introduces stage-aware suggestion chips.

## Summary of Changes

1. **Replace bottom nav** with AppBar (hamburger + avatar) + Navigation Drawer
2. **Remove /upload route** — attach button with `file_picker` added to chat input
3. **Move privacy toggle + delete session** into AppBar overflow menu
4. **Embed full chat history** (ChatsListScreen content) in the drawer
5. **Add stage-aware suggestion chips** above chat input
6. **Extract AgentStateFab** as a public widget for the new scaffold's FAB slot

---

## Step 1: Add `file_picker` dependency

**File:** `flutter/pubspec.yaml`

Add under `dependencies`:
```yaml
file_picker: ^8.1.3
```

Run `flutter pub get`.

---

## Step 2: Move `journeyStageProvider` to shared location

**Why:** Currently defined in `chat_screen.dart` (line 16). The new suggestion chips provider and the scaffold both need it — keeping it in `chat_screen.dart` creates circular import risk.

**From:** `flutter/lib/features/chat/chat_screen.dart` — remove line 16
**To:** `flutter/lib/shared/providers/app_providers.dart` — add:
```dart
import '../../shared/models/journey_stage.dart';
final journeyStageProvider = StateProvider<JourneyStage>((ref) => JourneyStage.recognition);
```

**Update imports** in:
- `flutter/lib/features/chat/chat_screen.dart` — import from `app_providers.dart`
- `flutter/lib/shared/widgets/stage_indicator.dart` — if it references the provider (verify)

---

## Step 3: Create suggestion chips provider

**New file:** `flutter/lib/features/chat/suggestion_chips_provider.dart`

```dart
final suggestionChipsProvider = Provider<List<String>>((ref) {
  final stage = ref.watch(journeyStageProvider);
  return switch (stage) {
    JourneyStage.recognition   => ['Tell me about symptoms', 'Summarize my history'],
    JourneyStage.navigation    => ['Find a specialist', 'Review my timeline'],
    JourneyStage.providerSearch => ['Search providers near me', 'Compare specialists'],
    JourneyStage.setupChecklist => ['Prepare for my appointment', 'Check my insurance'],
    JourneyStage.appointmentPrep => ['Generate appointment brief', 'Review my questions'],
  };
});
```

---

## Step 4: Extract `ChatsListBody` from `chats_list_screen.dart`

**File:** `flutter/lib/features/chats/chats_list_screen.dart`

Extract the inner list content (the `chatsAsync.when(...)` block with `_ChatsList`, `_DateHeader`, `_ChatTile`) into a **public** `ChatsListBody` widget with an `onChatSelected` callback. The existing `ChatsListScreen` will reuse `ChatsListBody` internally, keeping the full-page `/chats` route working.

```dart
class ChatsListBody extends ConsumerWidget {
  const ChatsListBody({super.key, this.onChatSelected});
  final void Function(String chatId)? onChatSelected;
  // ... delegates to chatsProvider + _ChatsList with the callback
}
```

The `_ChatTile.onTap` will use `onChatSelected` when provided, falling back to `context.go('/chats/${chat.id}')`.

**Note:** This import must be **eager** (not deferred) since the drawer uses it always. The `/chats` full-page route can remain deferred.

---

## Step 5: Extract `AgentStateFab` from `agent_state_panel.dart`

**File:** `flutter/lib/features/agent_state/agent_state_panel.dart`

Make the FAB trigger a **public** widget:

```dart
class AgentStateFab extends ConsumerWidget {
  // Identical to current _BottomSheetTrigger but public
}
```

Simplify `AgentStatePanel` to only return `_SidePanelLayout` (remove the internal wide/narrow branching — the scaffold now handles that).

---

## Step 6: Rewrite `_ScaffoldWithNavBar` → `_MainScaffold` in router.dart

**File:** `flutter/lib/navigation/router.dart`

This is the core change. Replace lines 146–192 entirely.

### `_MainScaffold` structure:
```
Scaffold
├── appBar: AppBar
│   ├── leading: Builder → IconButton(Icons.menu) → Scaffold.of(ctx).openDrawer()
│   ├── title: Row [Icon(health_and_safety_outlined), "Advocate"]
│   └── actions: [PopupMenuButton (privacy + delete), CircleAvatar → go('/settings')]
├── drawer: _NavigationDrawer
│   ├── "Start New Anonymous Session" FilledButton.icon
│   ├── Divider
│   ├── Expanded(ChatsListBody)
│   ├── Divider
│   └── ListTile "Help"
├── body: (isChatRoute && isWide) ? Row[Expanded(child), AgentStatePanel()] : child
└── floatingActionButton: (isChatRoute && !isWide) ? AgentStateFab() : null
```

### AppBar overflow menu (PopupMenuButton):
- **Private Session** — row with label + Switch watching `privacyModeProvider`
- **Delete Session** — calls `deleteSession()` with confirmation dialog (same logic as current `_ChatHeader`)

### Avatar:
- Watches `authStateProvider` to get user
- Shows initials in CircleAvatar (radius: 18, primary bg, onPrimary text) — matching `_AccountCard` in settings
- `GestureDetector` → `context.go('/settings')`

### Route changes:
- **Remove** `/upload` route and its deferred import
- **Add** eager import for `ChatsListBody` from chats_list_screen.dart
- **Add** eager import for `AgentStateFab` from agent_state_panel.dart
- ShellRoute builder: `_MainScaffold(child: child)` instead of `_ScaffoldWithNavBar(child: child)`

---

## Step 7: Simplify `chat_screen.dart`

**File:** `flutter/lib/features/chat/chat_screen.dart`

### Remove `_ChatHeader`
Delete the entire `_ChatHeader` class (lines 208–296). Remove `const _ChatHeader()` from the Column in `build()` (line 117).

### Add `_SuggestionChips` widget
New private widget, placed between the typing indicator and `_ChatInput`:
- Watches `suggestionChipsProvider`
- Renders `SingleChildScrollView(scrollDirection: Axis.horizontal)` with `ActionChip` per label
- On chip tap: populate and send the message via `chatProvider.notifier.sendMessage(label)`
- Only show when NOT in demo mode

### Add attach button to `_ChatInput`
- Convert `_ChatInput` from `StatefulWidget` to `ConsumerStatefulWidget` (for provider access)
- Add `IconButton(icon: Icon(Icons.add))` to the left of the text field in the Row
- `onPressed`: call `FilePicker.platform.pickFiles(allowMultiple: true)` — store result in a local state or show a snackbar with file names
- Disabled when `isStreaming`

### Updated Column children order:
```dart
const _JourneyStageHeader(),
const _DisclaimerBanner(),
Expanded(child: /* messages or empty state */),
if (lastIsStreaming) /* typing indicator */,
if (demoPersona != null) ...[DemoBanner, DemoChatInput]
else ...[_SuggestionChips(), _ChatInput(/* now with attach button */)],
```

---

## Step 8: Update tests

**File:** `flutter/test/features/chat/chat_screen_test.dart`

The existing tests check for `Switch` and `Icons.delete_outline` which are moving from `_ChatHeader` to `_MainScaffold`'s AppBar overflow menu. These tests wrap `ChatScreen` directly in `MaterialApp` — they won't find the relocated widgets.

### Changes needed:
- **Remove or skip** existing Switch and delete_outline tests (they tested `_ChatHeader` which no longer exists in ChatScreen)
- **Add new test file:** `flutter/test/navigation/main_scaffold_test.dart`
  - Test hamburger opens drawer
  - Test "Start New Session" button in drawer
  - Test avatar taps navigate to /settings
  - Test overflow menu contains privacy toggle and delete session
- **Update `chat_screen_test.dart`:**
  - Add test for suggestion chips presence
  - Add test for attach button (Icons.add) presence
  - Add test that chips change when `journeyStageProvider` changes

---

## Files Modified (ordered by implementation)

| # | File | Change |
|---|------|--------|
| 1 | `flutter/pubspec.yaml` | Add `file_picker: ^8.1.3` |
| 2 | `flutter/lib/shared/providers/app_providers.dart` | Add `journeyStageProvider` |
| 3 | `flutter/lib/features/chat/suggestion_chips_provider.dart` | **New** — stage-aware chip labels |
| 4 | `flutter/lib/features/chats/chats_list_screen.dart` | Extract public `ChatsListBody` widget |
| 5 | `flutter/lib/features/agent_state/agent_state_panel.dart` | Extract public `AgentStateFab`, simplify `AgentStatePanel` |
| 6 | `flutter/lib/navigation/router.dart` | Replace `_ScaffoldWithNavBar` with `_MainScaffold`, add drawer, remove bottom nav, remove /upload route |
| 7 | `flutter/lib/features/chat/chat_screen.dart` | Remove `_ChatHeader`, add `_SuggestionChips`, add attach button to `_ChatInput`, update `journeyStageProvider` import |
| 8 | `flutter/test/features/chat/chat_screen_test.dart` | Update tests for new layout |
| 9 | `flutter/test/navigation/main_scaffold_test.dart` | **New** — tests for scaffold, drawer, AppBar |

---

## Verification

1. `cd flutter && flutter pub get`
2. `cd flutter && flutter analyze` — zero errors
3. `cd flutter && flutter test` — all tests pass
4. `cd flutter && flutter build web` — successful build
5. **Manual checks:**
   - No bottom navigation bar visible
   - Hamburger icon opens drawer with "Start New Session" button + full chat history
   - Avatar in AppBar shows user initial; tapping navigates to /settings
   - Overflow menu (three-dot) has privacy toggle and delete session
   - Chat input has + attach button on left; tapping opens file picker
   - Suggestion chips appear above input and change per journey stage
   - Wide screen (>800px): AgentStatePanel sidebar on right
   - Narrow screen: AgentStateFab (heart monitor FAB) for bottom sheet
   - Demo walkthrough still works (banner, pre-scripted input, hard stops)
   - StageIndicator remains below AppBar, above disclaimer
