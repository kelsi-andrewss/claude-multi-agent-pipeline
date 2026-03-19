This report provides a comprehensive code audit of the Gemini MCP server, evaluating its quality, security, and functional integrity.

# AUDIT.md

## Executive Summary
The Gemini MCP server provides a sophisticated set of tools for codebase analysis, project management, and automated planning. However, the codebase is currently in a high-risk state due to critical security vulnerabilities and significant platform-specific dependencies. The presence of a fatal syntax error in a core utility module (likely due to environment corruption) prevents the server from operating in its current form. While the architectural intent and feature set are advanced, the implementation requires immediate remediation of directory traversal risks and cross-platform process management before it can be considered production-ready.

## Code Quality and Smells
*   **Environment-Specific Hardcoding**: The server relies heavily on hardcoded paths within the user's home directory (e.g., `.claude/epics.db`). This tight coupling makes the application difficult to containerize, deploy in diverse environments, or use in multi-user settings.
*   **Brittle Migration Logic**: Database schema migrations in `tools_pm_helpers.py` use a manual, imperative approach with repeated `ALTER TABLE` attempts wrapped in try-except blocks. This is error-prone compared to a standard versioned migration system.
*   **Global State and Implicit Imports**: `server.py` uses `globals().update()` to register tools from multiple modules. This pattern obscures the origin of tools and makes static analysis and debugging more difficult.
*   **Non-Atomic ID Generation**: The `_next_id` function in `tools_pm_helpers.py` calculates the next ID by querying the maximum current value. In a concurrent environment, this will lead to race conditions and primary key collisions during epic or story creation.
*   **Mixed Response Types**: The system inconsistently returns plain strings, JSON strings, and structured error dictionaries, which complicates client-side parsing and error handling.

## Identified Bugs and Fixes

### 1. Fatal Syntax Error in Database Helpers (High Priority)
*   **File**: `tools_pm_helpers.py`
*   **Issue**: Line 31 contains a corrupted string referencing a virtual environment path (`@.venv/lib/...`) instead of the required `contextmanager` decorator. This prevents the Python interpreter from loading the module.
*   **Fix**: Replace the corrupted line with `@contextmanager` (imported from `contextlib`). Ensure the decorator correctly precedes the `_db_op` function definition.

### 2. Directory Traversal Vulnerability (High Priority)
*   **File**: `gemini_client.py` (functions `_discover_files` and `_read_files_within_budget`)
*   **Issue**: The server resolves file paths provided by the user without validating that they reside within the `PROJECT_ROOT`. An attacker could pass absolute paths or relative sequences (e.g., `../../etc/passwd`) to read sensitive system files.
*   **Fix**: Implement a validation step using `os.path.commonpath` or `Path.relative_to` to ensure that the resolved absolute path of any requested file starts with the absolute path of the workspace root.

### 3. Unix-Specific Process Management (High Priority)
*   **File**: `gemini_client.py`, Line 63
*   **Issue**: The use of `os.killpg` and `os.getpgid` for timeout management is specific to POSIX systems. Running the server on Windows will result in an `AttributeError` and crash the process when a command times out.
*   **Fix**: Utilize `asyncio.create_subprocess_exec`'s returned process object directly. Use `proc.terminate()` or `proc.kill()` which are cross-platform.

### 4. Hardcoded Virtual Environment Paths (Medium Priority)
*   **File**: `tools_test.py`, Line 17
*   **Issue**: The test runner assumes a Unix-style structure (`bin/python3`) for the virtual environment. This will fail on Windows where the executable is located in `Scripts/python.exe`.
*   **Fix**: Use `sys.executable` or detect the platform using `os.name` to resolve the correct path to the environment's Python interpreter.

### 5. Insecure Temporary Directory Usage (Medium Priority)
*   **File**: `format_response.py`
*   **Issue**: The `DETAIL_DIR` is hardcoded to `/tmp/gemini`. This is not only Unix-specific but also creates a predictable location that could lead to file-jacking or permission conflicts in shared environments.
*   **Fix**: Use the `tempfile` module to generate a proper system-native temporary directory or use a sub-folder within the project's own directory.

## Recommendations for Improvements
*   **Path Jailing**: Create a centralized filesystem utility that "jails" all operations to the workspace root, raising a security exception for any attempted access outside the boundary.
*   **Centralized Configuration**: Move all hardcoded timeouts, model IDs, and directory paths into a single `Settings` class or an environment-aware configuration file.
*   **Atomic ID Generation**: Refactor `_next_id` to use database-native `AUTOINCREMENT` columns or a thread-safe sequence generator to prevent collisions.
*   **Response Unification**: Refactor `format_response.py` to ensure all tools return a consistent structured object (e.g., a dictionary with `status`, `data`, and `ui_path` fields).

## Overall Score: 3/10
**Rationale**: While the functional logic for project management and AI planning is impressive and well-structured, the system suffers from a "blocker" syntax error and a critical security vulnerability (directory traversal). The platform-specific code further limits its utility. A score of 3 reflects a project with high potential that is currently unusable and unsafe without significant surgical repair.