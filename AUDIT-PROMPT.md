Let's perform a comprehensive code audit and generate a detailed report for this early submission of the ColabBoard project. Use the attached PDF file containing the requirements as the source of truth for evaluating completeness and adherence to specifications.

Focus on the following key areas:
- **Code Smells and Quality Check**: Identify code smells, anti-patterns, and opportunities for improving code quality, readability, maintainability, and performance. Ensure the code follows SOLID principles (Single Responsibility, Open-Closed, Liskov Substitution, Interface Segregation, Dependency Inversion) and promotes modular design.
- **Bug Audit**: Thoroughly review the entire codebase for bugs, vulnerabilities, edge cases, logical errors, runtime issues, and potential security risks. Test for common issues like null pointer exceptions, off-by-one errors, improper error handling, resource leaks, and concurrency problems if applicable.
- **Completeness Check**: Cross-reference the code against the PDF requirements to flag any missing features, incomplete implementations, or deviations.

For each issue identified (bug, code smell, or quality concern):
- Assign a priority level: High (critical, affects functionality or security), Medium (important but non-blocking), Low (minor improvements).
- Describe the issue clearly, including the file name, line numbers, and relevant code snippets.
- Suggest mitigations or fixes, providing enough detail (e.g., pseudocode or exact code changes) so a developer or AI can implement the fix quickly (ideally in under 30 minutes).
- If applicable, recommend refactoring steps to align with modular and SOLID methodologies.

Structure the report as a Markdown file (AUDIT.md) with sections like:
- Executive Summary
- Completeness Against Requirements
- Code Quality and Smells
- Identified Bugs and Fixes
- Recommendations for Improvements
- Overall Score or Rating (e.g., on a scale of 1-10)

Review the entire codebase systematically, file by file, and include any assumptions or limitations in the report.