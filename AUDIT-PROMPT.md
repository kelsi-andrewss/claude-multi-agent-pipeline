Perform a comprehensive code audit and generate a detailed report. Use any provided requirements document as the source of truth for evaluating completeness and adherence to specifications.

Focus on the following key areas:
- **Code Quality**: Identify code smells, anti-patterns, and opportunities for improving readability, maintainability, and performance. Look for SOLID principle violations, unnecessary complexity, and poor separation of concerns.
- **Bug Audit**: Review the codebase for bugs, edge cases, logical errors, runtime issues, and potential security risks. Common targets: null dereferences, off-by-one errors, improper error handling, resource leaks, race conditions, injection vulnerabilities.
- **Completeness**: If a requirements document is provided, cross-reference the code against it and flag missing features, incomplete implementations, or deviations.

For each issue identified:
- Assign a priority level: High (critical — affects functionality or security), Medium (important but non-blocking), Low (minor improvement).
- Describe the issue clearly, including file name, line numbers, and relevant code snippets.
- Suggest a mitigation or fix with enough detail (pseudocode or exact code) that a developer can implement it in under 30 minutes.
- If applicable, recommend refactoring steps toward cleaner design.

Structure the report as a Markdown file (AUDIT.md) with the following sections:
- Executive Summary
- Completeness Against Requirements (omit if no requirements document)
- Code Quality and Smells
- Identified Bugs and Fixes
- Recommendations for Improvements
- Overall Score (1–10 scale with brief rationale)

Review all target files systematically and include any assumptions or scope limitations in the report.
