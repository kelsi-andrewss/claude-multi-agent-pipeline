Perform a comprehensive code audit of this Flutter project and generate a detailed report. Use any provided requirements document as the source of truth for evaluating completeness and adherence to specifications.

Focus on the following key areas:

- **Code Quality**: Identify code smells, anti-patterns, and opportunities for improving readability, maintainability, and performance. Look for SOLID principle violations, unnecessary complexity, and poor separation of concerns.
- **Bug Audit**: Review the codebase for bugs, edge cases, logical errors, runtime issues, and potential security risks. Common targets: null dereferences, off-by-one errors, improper error handling, resource leaks, race conditions, injection vulnerabilities.
- **Completeness**: If a requirements document is provided, cross-reference the code against it and flag missing features, incomplete implementations, or deviations.
- **Widget Tree Efficiency**: Identify unnecessary rebuilds, missing `const` constructors on stateless widgets, expensive operations in `build()` methods, overly deep widget trees, and `setState` calls with too wide a scope. Flag `AnimatedBuilder`/`StreamBuilder`/`ValueListenableBuilder` misuse.
- **State Management**: Audit patterns specific to the resolved state management approach (see State Management Context section appended below). Common issues by approach:
  - **bloc**: missing event/state coverage, leaking `StreamController`s, `BlocBuilder` with no `buildWhen`, emitting state after `close()`
  - **riverpod**: `ref.watch` called outside build context, missing `.autoDispose` on providers that hold resources, `ref.read` inside `build()`, invalidating providers unnecessarily
  - **provider**: `context.read` vs `context.watch` misuse, `ChangeNotifier` calling `notifyListeners()` too broadly, missing `MultiProvider` grouping
  - **getx**: controller lifecycle issues (`Get.put` vs `Get.lazyPut` vs `Get.find`), `.obs` overuse on primitive types, missing `onClose()` cleanup
  - **none/unknown**: flag absence of a coherent state management strategy, ad-hoc `setState` at wrong levels
- **Null Safety**: Unsafe `!` (bang) operators without guards, `late` variable misuse (accessing before initialization, using `late` when a default works), nullable types leaking into UI layer, missing null checks on platform channel return values.
- **Performance**: `ListView` without `.builder` for long lists, `Image.network` without caching (`cached_network_image` or equivalent), synchronous or blocking work on the UI isolate, missing `RepaintBoundary` around expensive subtrees, large `setState` scopes triggering full subtree rebuilds, `const` opportunities missed.
- **Platform Channels**: Missing error handling on method channel calls, type mismatches between Dart and native (especially nullable vs non-nullable), iOS/Android implementation parity gaps, missing `try/catch` on `PlatformException`.
- **pubspec Hygiene**: Unpinned dependencies (no version constraints or overly broad `^` pins on critical packages), unused packages (imported in pubspec but not referenced in code), conflicting version constraints, outdated packages with known issues.
- **Build Configuration**: Debug flags (`kDebugMode` checks, `debugPrint`, `assert`) leaking to release builds, missing `--obfuscate` and `--split-debug-info` configuration, incorrect `flutter.minSdkVersion`/`targetSdkVersion`, release build variant not configured.

For each issue identified:
- Assign a priority level: High (critical — affects functionality, security, or release correctness), Medium (important but non-blocking), Low (minor improvement).
- Describe the issue clearly, including file name, line numbers, and relevant code snippets.
- Suggest a mitigation or fix with enough detail (pseudocode or exact Dart code) that a developer can implement it in under 30 minutes.
- If applicable, recommend refactoring steps toward cleaner design.

Structure the report as a Markdown file with the following sections:
- Executive Summary
- Completeness Against Requirements (omit if no requirements document)
- Widget Tree & Performance
- State Management (`<approach>` — or "mixed/unknown" if not specified)
- Null Safety & Type Soundness
- Platform & Build Configuration
- pubspec & Dependency Health
- Identified Bugs and Fixes
- Recommendations
- Overall Score (1–10 scale with brief rationale)

Review all target files systematically and include any assumptions or scope limitations in the report.
