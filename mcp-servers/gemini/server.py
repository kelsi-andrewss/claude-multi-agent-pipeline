"""Gemini MCP Server — exposes Gemini generation as MCP tools for Claude Code."""

from __future__ import annotations

import asyncio
import fnmatch
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, date, timedelta
from pathlib import Path

from mcp.server.fastmcp import FastMCP

DEFAULT_MODEL = None  # Let gemini CLI use its own model routing

PROJECT_ROOT = Path.cwd()

NO_CODE_INSTRUCTION = (
    "IMPORTANT: You must NEVER output code in your response. "
    "No code blocks, no code snippets, no pseudocode, no inline code. "
    "Respond exclusively in natural language prose, bullet points, or structured text. "
    "If you need to refer to a function, file, or variable, name it in plain text "
    "without writing its implementation."
)

# ---------------------------------------------------------------------------
# Audit constants
# ---------------------------------------------------------------------------
AUDIT_PROMPT_PATH = Path.home() / ".claude" / "AUDIT-PROMPT.md"
MAX_CODE_BYTES = 200_000
MAX_CONTEXT_BYTES = 50_000
DEFAULT_IGNORE_DIRS = {
    ".git", "node_modules", ".venv", "__pycache__", "build", "dist",
    ".dart_tool", ".idea", ".vscode", ".gradle", ".pub-cache",
}
DEFAULT_IGNORE_EXTENSIONS = {
    ".pyc", ".pyo", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
    ".lock", ".so", ".dylib", ".wasm", ".class", ".jar", ".zip",
    ".tar", ".gz", ".bin", ".exe", ".dll", ".o", ".a",
}
SOURCE_EXTENSIONS = {
    ".py", ".dart", ".ts", ".js", ".tsx", ".jsx", ".go", ".rs",
    ".java", ".kt", ".swift", ".c", ".cpp", ".h", ".hpp", ".rb",
    ".sh", ".yaml", ".yml", ".toml", ".json", ".md", ".html", ".css",
}
VALID_AUDIT_SECTIONS = {"quality", "bugs", "completeness", "security"}

# ---------------------------------------------------------------------------
# Redesign constants
# ---------------------------------------------------------------------------
DEFAULT_REDESIGN_SECTIONS = ["theme", "icons", "navigation", "animations", "platform"]
VALID_REDESIGN_SECTIONS = {"theme", "icons", "navigation", "animations", "platform"}

REDESIGN_SYSTEM_INSTRUCTION = (
    "You are a senior UI/UX engineer and design systems expert. "
    "Analyze the provided codebase and produce a structured redesign specification in Markdown. "
    "Focus on design quality, M3/platform conventions, and actionable improvements. "
    "Output structured prose with specific component names, icon names, and file references — "
    "NOT code implementations. Use bullet points and headers for clarity. "
    "For each recommendation, indicate priority: High, Medium, or Low."
)

DOCUMENTS: dict[str, dict[str, str]] = {
    "claude": {"path": "CLAUDE.md", "description": "Project implementation guide and conventions"},
    "requirements": {"path": "REQUIREMENTS.md", "description": "Full project requirements"},
    "bounty": {"path": "BOUNTY.md", "description": "Bounty spec and deliverables"},
    "architecture": {"path": "ARCHITECTURE.md", "description": "System architecture overview"},
    "roadmap": {"path": "ROADMAP.md", "description": "Development roadmap and milestones"},
    "cost_analysis": {"path": "COST_ANALYSIS.md", "description": "AI cost analysis and token usage"},
    "firestore_schema": {"path": "FIRESTORE_SCHEMA.md", "description": "Firestore database schema"},
    "gemini": {"path": "GEMINI.md", "description": "Gemini integration notes"},
    "audit": {"path": "AUDIT.md", "description": "Codebase audit report"},
    "presearch": {
        "path": "project_requirements_and_research/advocate_presearch_v10.md",
        "description": "Pre-research: tool schemas, FHIR queries, demo scenarios",
    },
    "demos_extended": {
        "path": "project_requirements_and_research/advocate_demos_3_10.md",
        "description": "Extended demo scenarios (3-10)",
    },
    "demos_updated": {
        "path": "project_requirements_and_research/advocate_demos_updated.md",
        "description": "Updated demo scripts",
    },
    "provider_demos": {
        "path": "project_requirements_and_research/advocate_provider_demos.md",
        "description": "Provider-side demo scenarios",
    },
    "week2_requirements": {
        "path": "project_requirements_and_research/G4 Week 2 - AgentForge - Project Requirements.md",
        "description": "Week 2 AgentForge project requirements",
    },
}


def _read_doc(key: str) -> str:
    """Read a project document by DOCUMENTS key. Returns content or error note."""
    if key not in DOCUMENTS:
        return f"[Document '{key}' not found]"
    file_path = PROJECT_ROOT / DOCUMENTS[key]["path"]
    if not file_path.exists():
        return f"[File not found: {DOCUMENTS[key]['path']}]"
    return file_path.read_text(encoding="utf-8")


def _discover_files(
    paths: list[str] | None = None,
    ignore_patterns: list[str] | None = None,
) -> list[Path]:
    """Walk source tree and return matching files sorted by size ascending."""
    ignore_patterns = ignore_patterns or []
    roots: list[Path] = []

    if paths:
        for p in paths:
            resolved = (PROJECT_ROOT / p).resolve()
            if not resolved.exists():
                continue
            roots.append(resolved)
    else:
        roots = [PROJECT_ROOT]

    found: list[Path] = []
    for root in roots:
        if root.is_file():
            if root.suffix in SOURCE_EXTENSIONS:
                found.append(root)
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            # Prune ignored directories in-place
            dirnames[:] = [
                d for d in dirnames if d not in DEFAULT_IGNORE_DIRS
            ]
            for fname in filenames:
                fpath = Path(dirpath) / fname
                if fpath.suffix in DEFAULT_IGNORE_EXTENSIONS:
                    continue
                if fpath.suffix not in SOURCE_EXTENSIONS:
                    continue
                rel = str(fpath.relative_to(PROJECT_ROOT))
                if any(fnmatch.fnmatch(rel, pat) for pat in ignore_patterns):
                    continue
                found.append(fpath)

    # Sort by file size ascending to maximize file count within budget
    found.sort(key=lambda f: f.stat().st_size)
    return found


def _read_files_within_budget(
    file_list: list[Path], budget: int
) -> tuple[str, list[Path]]:
    """Read files until budget is exhausted. Returns (content, skipped_paths)."""
    parts: list[str] = []
    total = 0
    skipped: list[Path] = []

    for fpath in file_list:
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            skipped.append(fpath)
            continue
        size = len(text.encode("utf-8"))
        if total + size > budget:
            skipped.append(fpath)
            continue
        rel = fpath.relative_to(PROJECT_ROOT)
        parts.append(f"### {rel}\n\n{text}\n\n---")
        total += size

    return "\n\n".join(parts), skipped


def _load_audit_context() -> str:
    """Scan PROJECT_ROOT for requirements/research docs and return concatenated content."""
    context_parts: list[str] = []

    for name in ("REQUIREMENTS.md", "ARCHITECTURE.md", "BOUNTY.md"):
        fpath = PROJECT_ROOT / name
        if fpath.exists():
            context_parts.append(f"### {name}\n\n{fpath.read_text(encoding='utf-8')}")

    research_dir = PROJECT_ROOT / "project_requirements_and_research"
    if research_dir.is_dir():
        for md_file in sorted(research_dir.glob("*.md")):
            context_parts.append(
                f"### {md_file.relative_to(PROJECT_ROOT)}\n\n"
                f"{md_file.read_text(encoding='utf-8')}"
            )

    full = "\n\n---\n\n".join(context_parts)
    if len(full.encode("utf-8")) > MAX_CONTEXT_BYTES:
        full = full.encode("utf-8")[:MAX_CONTEXT_BYTES].decode("utf-8", errors="ignore")
    return full


def _load_audit_prompt() -> str:
    """Load audit prompt from disk or return a built-in fallback."""
    if AUDIT_PROMPT_PATH.exists():
        return AUDIT_PROMPT_PATH.read_text(encoding="utf-8")
    return (
        "Perform a comprehensive code audit and generate a detailed report.\n\n"
        "Focus on:\n"
        "- **Code Quality**: code smells, anti-patterns, readability, maintainability\n"
        "- **Bug Audit**: bugs, edge cases, logical errors, runtime issues, security risks\n"
        "- **Completeness**: cross-reference against requirements if provided\n"
        "- **Security**: injection, auth issues, data exposure, misconfigurations\n\n"
        "For each issue assign a priority: High, Medium, or Low.\n"
        "Describe the issue with file name and location.\n\n"
        "Structure the report with these sections:\n"
        "- Executive Summary\n"
        "- Completeness Against Requirements (omit if no requirements)\n"
        "- Code Quality and Smells\n"
        "- Identified Bugs and Fixes\n"
        "- Security Review\n"
        "- Recommendations for Improvements\n"
        "- Overall Score (1-10 scale with brief rationale)\n"
    )


async def _gemini(prompt: str, *, model: str | None = DEFAULT_MODEL) -> str:
    """Call gemini CLI in headless mode and return the response text."""
    cmd: list[str] = ["gemini"]
    if model:
        cmd.extend(["-m", model])
    cmd.extend(["-o", "json"])
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(input=prompt.encode())
    if proc.returncode != 0:
        err = stderr.decode().strip()
        return f"[gemini error (exit {proc.returncode})]: {err}"
    data = json.loads(stdout.decode())
    return data.get("response", "(empty response)")


mcp = FastMCP("gemini")


@mcp.tool()
async def gemini_generate(
    prompt: str,
    model: str | None = None,
    system_instruction: str | None = None,
) -> str:
    """Raw Gemini prompt — no project context injected. Use plan() for implementation planning or analyze() for code/design review instead.

    Args:
        prompt: The input prompt to send to Gemini.
        model: Optional Gemini model ID. Omit to use CLI default.
        system_instruction: Optional system instruction to guide the model.
    """
    combined_instruction = NO_CODE_INSTRUCTION
    if system_instruction:
        combined_instruction = f"{NO_CODE_INSTRUCTION}\n\n{system_instruction}"
    full_prompt = f"[System: {combined_instruction}]\n\n{prompt}"
    return await _gemini(full_prompt, model=model)


@mcp.tool()
async def gemini_chat(
    messages: list[dict[str, str]],
    model: str | None = None,
    system_instruction: str | None = None,
) -> str:
    """Raw multi-turn Gemini conversation — no project context injected. Use for back-and-forth dialogue only.

    Args:
        messages: List of message objects with "role" ("user" or "model") and "content" keys.
        model: Optional Gemini model ID. Omit to use CLI default.
        system_instruction: Optional system instruction to guide the model.
    """
    lines = []
    for msg in messages:
        role = msg.get("role", "user").capitalize()
        lines.append(f"{role}: {msg.get('content', '')}")
    conversation = "\n".join(lines)

    combined_instruction = NO_CODE_INSTRUCTION
    if system_instruction:
        combined_instruction = f"{NO_CODE_INSTRUCTION}\n\n{system_instruction}"
    full_prompt = f"[System: {combined_instruction}]\n\n{conversation}"
    return await _gemini(full_prompt, model=model)


@mcp.tool()
async def fetch_doc(document: str = "list") -> str:
    """Retrieve an Advocate project document by key (CLAUDE.md, REQUIREMENTS.md, etc.).

    Args:
        document: Document key to retrieve, or "list" to see all available documents.
    """
    if document == "list":
        lines = ["| Key | File | Lines | Description |", "| --- | --- | ---: | --- |"]
        for key, info in DOCUMENTS.items():
            file_path = PROJECT_ROOT / info["path"]
            if file_path.exists():
                line_count = len(file_path.read_text(encoding="utf-8").splitlines())
            else:
                line_count = 0
            lines.append(f"| `{key}` | `{info['path']}` | {line_count} | {info['description']} |")
        return "\n".join(lines)

    if document not in DOCUMENTS:
        valid_keys = ", ".join(DOCUMENTS.keys())
        return f"Unknown document '{document}'. Valid keys: {valid_keys}"

    file_path = PROJECT_ROOT / DOCUMENTS[document]["path"]
    if not file_path.exists():
        return f"File not found: {DOCUMENTS[document]['path']}"

    return file_path.read_text(encoding="utf-8")


@mcp.tool()
async def plan(
    task: str,
    documents: list[str] | None = None,
) -> str:
    """Generate an implementation plan for a task. Automatically loads CLAUDE.md, REQUIREMENTS.md, and ARCHITECTURE.md as context and uses a senior-developer system prompt. Prefer this over gemini_generate for any planning task.

    Args:
        task: Description of what needs to be implemented.
        documents: Document keys to include as context (default: claude, requirements, architecture).
            Use fetch_doc(document="list") to see available keys.
    """
    if documents is None:
        documents = ["claude", "requirements", "architecture"]

    context_parts: list[str] = []
    for key in documents:
        content = _read_doc(key)
        label = DOCUMENTS.get(key, {}).get("description", key)
        context_parts.append(f"### {label}\n\n{content}")

    context_block = "\n\n---\n\n".join(context_parts)

    system_instruction = (
        "You are a senior developer on this project. Given the task and project context, "
        "produce a concrete implementation plan. Include:\n"
        "1. Numbered steps with specific file paths and function names\n"
        "2. Key risks or edge cases to watch for\n"
        "3. Testing strategy (what to test, how)\n"
        "4. Dependencies or prerequisites\n"
        "Keep it actionable — no hand-waving.\n\n"
        f"{NO_CODE_INSTRUCTION}"
    )

    full_prompt = (
        f"[System: {system_instruction}]\n\n"
        f"## Task\n{task}\n\n"
        f"## Project Context\n{context_block}"
    )
    return await _gemini(full_prompt)


@mcp.tool()
async def analyze(
    input: str,
    context: str | None = None,
) -> str:
    """Review code or a design proposal against project conventions. Automatically loads CLAUDE.md as context and returns a structured verdict (APPROVE/NEEDS CHANGES/REJECT for code, PROCEED/REVISE/RECONSIDER for design). Prefer this over gemini_generate for any review task.

    Args:
        input: Code snippet or design description to analyze.
        context: Optional additional context about what the input is for.
    """
    project_conventions = _read_doc("claude")

    prompt_parts = [f"## Input\n\n{input}"]
    if context:
        prompt_parts.append(f"## Additional Context\n\n{context}")
    prompt_parts.append(f"## Project Conventions\n\n{project_conventions}")

    system_instruction = (
        "You are a senior architect reviewing submissions for this project. "
        "Auto-detect whether the input is code or a design proposal.\n\n"
        "For CODE: review for correctness, style adherence, edge cases, security. "
        "Give a verdict: APPROVE, NEEDS CHANGES, or REJECT with specific line-level feedback.\n\n"
        "For DESIGN: evaluate feasibility, alignment with project architecture, trade-offs. "
        "Give a verdict: PROCEED, REVISE, or RECONSIDER with concrete reasoning.\n\n"
        "Be opinionated and direct. Reference project conventions where relevant.\n\n"
        f"{NO_CODE_INSTRUCTION}"
    )

    full_prompt = f"[System: {system_instruction}]\n\n" + "\n\n".join(prompt_parts)
    return await _gemini(full_prompt)


async def _run_tests(
    suite: str, tests: list[str] | None = None, timeout: int = 300
) -> tuple[str, bool]:
    """Run project tests and return (output_text, all_passed).

    Args:
        suite: "backend" or "frontend".
        tests: Optional specific test paths/node IDs (backend only).
        timeout: Maximum seconds to wait (default 300).
    """
    if suite == "backend":
        venv_python = str(PROJECT_ROOT / ".venv" / "bin" / "python3")
        cmd = [venv_python, "-m", "pytest"]
        if tests:
            cmd.extend(tests)
        else:
            cmd.append("tests/")
        cmd.append("--tb=short")
        cwd = str(PROJECT_ROOT)
        env = {**os.environ, "PYTHONPATH": "."}
    elif suite == "frontend":
        cmd = ["flutter", "test"]
        cwd = str(PROJECT_ROOT / "flutter")
        env = None
    else:
        return (f"Unknown suite: {suite}", False)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
            env=env,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = stdout.decode(errors="replace")
        passed = proc.returncode == 0
        return (output, passed)
    except FileNotFoundError:
        executable = cmd[0]
        return (f"Executable not found: {executable}", False)
    except asyncio.TimeoutError:
        proc.kill()
        return (f"Tests timed out after {timeout}s", False)


TEST_ANALYSIS_PROMPT = (
    "You are a senior test engineer analyzing test failures. "
    "Given the test output below, produce a structured analysis with these sections:\n\n"
    "1. **SUMMARY**: Overview of the test run — how many passed, failed, errored. "
    "Which test suites or modules are affected.\n\n"
    "2. **FAILURES**: For each distinct failure:\n"
    "   - Test name and location\n"
    "   - Root cause hypothesis\n"
    "   - Investigation areas (what to check, what might be wrong)\n"
    "   - Suggested fix described in natural language\n\n"
    "3. **PATTERNS**: Any cross-cutting issues you see across multiple failures "
    "(shared root cause, common misconfiguration, missing fixture, etc.).\n\n"
    f"{NO_CODE_INSTRUCTION}"
)


@mcp.tool()
async def test(suite: str = "all", tests: list[str] | None = None) -> str:
    """Run project tests and analyze failures with Gemini. Returns a brief summary if all pass, or a structured failure analysis if any fail.

    Args:
        suite: Which test suite to run — "backend", "frontend", or "all" (default).
        tests: Optional specific test paths or pytest node IDs (backend only).
    """
    if suite not in ("backend", "frontend", "all"):
        return f"Invalid suite '{suite}'. Must be 'backend', 'frontend', or 'all'."

    results: list[tuple[str, str, bool]] = []

    if suite in ("backend", "all"):
        output, passed = await _run_tests("backend", tests=tests)
        results.append(("backend", output, passed))

    if suite in ("frontend", "all"):
        output, passed = await _run_tests("frontend")
        results.append(("frontend", output, passed))

    all_passed = all(passed for _, _, passed in results)

    combined_output = ""
    for name, output, passed in results:
        status = "PASSED" if passed else "FAILED"
        combined_output += f"=== {name.upper()} ({status}) ===\n{output}\n\n"

    if all_passed:
        summary_lines = []
        for name, _, passed in results:
            summary_lines.append(f"{name}: all tests passed")
        return "\n".join(summary_lines)

    # Truncate to 50KB to stay within Gemini context limits (keep tail for tracebacks)
    max_bytes = 50_000
    if len(combined_output) > max_bytes:
        combined_output = (
            f"[...truncated {len(combined_output) - max_bytes} bytes from start...]\n"
            + combined_output[-max_bytes:]
        )

    full_prompt = (
        f"[System: {TEST_ANALYSIS_PROMPT}]\n\n"
        f"## Test Output\n\n{combined_output}"
    )
    return await _gemini(full_prompt)


@mcp.tool()
async def audit(
    paths: list[str] | None = None,
    sections: list[str] | None = None,
    summary_only: bool = False,
    ignore_patterns: list[str] | None = None,
    model: str | None = None,
) -> str:
    """Audit source code with Gemini and produce a structured markdown report. Auto-discovers requirements/research docs for completeness checking. Never generates code.

    Args:
        paths: Specific files or directories to audit (default: full project).
        sections: Filter report to specific sections: "quality", "bugs", "completeness", "security".
        summary_only: If True, return only an executive summary.
        ignore_patterns: Glob patterns to exclude files (e.g. "tests/*", "*.generated.*").
        model: Optional Gemini model ID override.
    """
    # Validate sections
    if sections:
        invalid = set(sections) - VALID_AUDIT_SECTIONS
        if invalid:
            return f"Error: invalid section(s): {', '.join(sorted(invalid))}. Valid: {', '.join(sorted(VALID_AUDIT_SECTIONS))}"

    # Check for non-existent explicit paths
    if paths:
        for p in paths:
            resolved = (PROJECT_ROOT / p).resolve()
            if not resolved.exists():
                return f"Error: path not found: {p}"

    # Discover and read source files
    files = _discover_files(paths, ignore_patterns)
    if not files:
        return "Error: no source files found to audit."

    code_content, skipped = _read_files_within_budget(files, MAX_CODE_BYTES)

    # Load context and prompt
    audit_context = _load_audit_context()
    audit_prompt = _load_audit_prompt()

    # Build section filter instruction
    section_instruction = ""
    if sections:
        section_instruction = (
            f"\n\nFocus ONLY on these sections: {', '.join(sections)}. "
            "Omit all other sections from the report."
        )

    summary_instruction = ""
    if summary_only:
        summary_instruction = (
            "\n\nReturn ONLY the Executive Summary section. "
            "Do not include detailed findings."
        )

    # Compose full prompt
    system_block = (
        f"{NO_CODE_INSTRUCTION}\n\n{audit_prompt}"
        f"{section_instruction}{summary_instruction}"
    )

    prompt_parts = [f"[System: {system_block}]"]

    if audit_context:
        prompt_parts.append(f"## Project Context\n\n{audit_context}")

    prompt_parts.append(f"## Files Under Audit\n\n{code_content}")

    if skipped:
        skipped_list = "\n".join(
            f"- {p.relative_to(PROJECT_ROOT)}" for p in skipped
        )
        prompt_parts.append(f"## Skipped Files (exceeded budget)\n\n{skipped_list}")

    full_prompt = "\n\n".join(prompt_parts)

    # Call Gemini
    report = await _gemini(full_prompt, model=model)

    # Write report to disk
    output_path = PROJECT_ROOT / "AUDIT-GEMINI.md"
    output_path.write_text(report, encoding="utf-8")

    return report


def _detect_framework(path: Path) -> str:
    """Detect the frontend framework used at the given project root."""
    if (path / "pubspec.yaml").exists():
        return "flutter"
    pkg = path / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            all_deps = {
                **data.get("dependencies", {}),
                **data.get("devDependencies", {}),
            }
            if "react" in all_deps or "next" in all_deps:
                return "react"
            if "vue" in all_deps or "@vue/core" in all_deps:
                return "vue"
        except (json.JSONDecodeError, OSError):
            pass
    return "unknown"


def _collect_redesign_files(
    root: Path,
    paths: list[str] | None,
    framework: str,
) -> tuple[str, list[str]]:
    """Discover and read frontend-relevant source files within budget."""
    # Build prioritized file list based on framework
    all_files: list[Path] = []

    if paths:
        search_roots = [root / p for p in paths if (root / p).exists()]
    else:
        search_roots = [root]

    if framework == "flutter":
        priority_patterns = {
            "*screen*.dart", "*page*.dart", "*widget*.dart",
            "*theme*.dart", "*app.dart", "pubspec.yaml",
        }
        dart_ext = {".dart"}
        for search_root in search_roots:
            if search_root.is_file():
                all_files.append(search_root)
                continue
            for dirpath, dirnames, filenames in os.walk(search_root):
                dirnames[:] = [d for d in dirnames if d not in DEFAULT_IGNORE_DIRS]
                for fname in filenames:
                    fpath = Path(dirpath) / fname
                    if fpath.suffix not in dart_ext and fname != "pubspec.yaml":
                        continue
                    all_files.append(fpath)
    elif framework in ("react", "vue"):
        priority_ext = {".tsx", ".jsx", ".ts", ".js", ".css", ".json"}
        for search_root in search_roots:
            if search_root.is_file():
                all_files.append(search_root)
                continue
            for dirpath, dirnames, filenames in os.walk(search_root):
                dirnames[:] = [d for d in dirnames if d not in DEFAULT_IGNORE_DIRS]
                for fname in filenames:
                    fpath = Path(dirpath) / fname
                    if fpath.suffix not in priority_ext:
                        continue
                    all_files.append(fpath)
    else:
        # Generic: use existing discover logic
        all_files = _discover_files(paths)

    # Sort by size ascending (maximize file count within budget)
    all_files.sort(key=lambda f: f.stat().st_size if f.exists() else 0)

    content, skipped_paths = _read_files_within_budget(all_files, MAX_CODE_BYTES)
    skipped_names = [str(p.relative_to(root)) for p in skipped_paths if p.is_absolute()]
    return content, skipped_names


def _build_redesign_prompt(
    framework: str,
    sections: list[str],
    code_context: str,
    skipped: list[str],
) -> str:
    """Build the full Gemini prompt for the redesign analysis."""
    from datetime import date
    today = date.today().isoformat()

    section_set = set(sections)

    section_instructions: list[str] = []

    if "theme" in section_set:
        if framework == "flutter":
            section_instructions.append(
                "## Section 1: M3 Theme & Color System\n"
                "Analyze ColorScheme usage: is ColorScheme.fromSeed used? Are surface tones applied "
                "correctly? Is dynamic color (DynamicColorBuilder) eligible?\n"
                "Review Typography: are all text theme slots defined? Are there gaps in the type scale?\n"
                "Check component theme overrides: CardTheme, AppBarTheme, NavigationBarTheme, "
                "FilledButtonTheme, OutlinedButtonTheme, InputDecorationTheme — which are missing?\n"
                "For each finding, specify the file and widget, and assign priority (High/Medium/Low)."
            )
        else:
            section_instructions.append(
                "## Section 1: Theme & Design Tokens\n"
                "Review CSS variables, design tokens, or theme configuration files. "
                "Are colors consistent? Is there a coherent spacing scale? "
                "Identify any hardcoded values that should be tokens. Priority per finding."
            )

    if "navigation" in section_set:
        if framework == "flutter":
            section_instructions.append(
                "## Section 2: Navigation & Transitions\n"
                "Identify the navigation library in use (GoRouter, Navigator 2.0, etc.).\n"
                "Review page transitions: are they using default Material transitions or custom ones?\n"
                "Recommend: GoRouter page transitions with SharedAxisTransition or FadeTransition "
                "for web; CupertinoPageTransition on iOS; Material fade/shared-axis on Android.\n"
                "Identify Hero widget opportunities for shared-element transitions between screens.\n"
                "Flag any screens missing explicit transition configuration. Priority per finding."
            )
        else:
            section_instructions.append(
                "## Section 2: Navigation & Routing\n"
                "Review routing configuration and page transitions. "
                "Are transitions smooth and appropriate for the platform? "
                "Identify missing loading states or transition animations. Priority per finding."
            )

    if "icons" in section_set:
        if framework == "flutter":
            section_instructions.append(
                "## Section 3: Icon Migration (Lucide)\n"
                "Scan for all Icons.xxx usages in the codebase.\n"
                "For each Material icon found, suggest a Lucide equivalent from the lucide_flutter package "
                "(PascalCase naming, e.g. Icons.search → lucide_flutter: Search).\n"
                "NOTE: Navigation icons in BottomNavigationBar, NavigationBar, and NavigationDrawer "
                "should STAY as Material icons — only migrate content/action icons.\n"
                "Format each suggestion as: `Icons.xxx → lucide_flutter: IconName (verify exists)`\n"
                "Group by file. Priority: Medium for all icon migrations."
            )
        else:
            section_instructions.append(
                "## Section 3: Icon Audit\n"
                "Review icon usage across the codebase. Are icons consistent? "
                "Recommend a single icon library if multiple are in use. "
                "Flag any icons used inconsistently or against platform conventions. Priority per finding."
            )

    if "animations" in section_set:
        if framework == "flutter":
            section_instructions.append(
                "## Section 4: Animation Opportunities\n"
                "Scan for setState calls that update visible UI — could these be AnimatedSwitcher, "
                "AnimatedContainer, AnimatedOpacity, or AnimatedAlign instead?\n"
                "Identify list builds that could use AnimatedList for item insertion/removal.\n"
                "Flag route transitions missing AnimationController.\n"
                "Suggest SpringSimulation for physics-based feel where appropriate.\n"
                "For each, note the file, the current pattern, and the recommended replacement. "
                "Priority per finding."
            )
        else:
            section_instructions.append(
                "## Section 4: Animation Opportunities\n"
                "Review CSS transitions and JS animation usage. "
                "Identify janky or missing animations for state changes, route transitions, "
                "and list item changes. Suggest specific CSS animation classes or libraries. Priority per finding."
            )

    if "platform" in section_set:
        if framework == "flutter":
            section_instructions.append(
                "## Section 5: Platform-Specific Features\n"
                "iOS: Is HapticFeedback used for interactions? Are safe area insets handled? "
                "Are there CupertinoSwitch candidates?\n"
                "Android: Is DynamicColorBuilder used for Material You theming? "
                "Is predictive back gesture registered?\n"
                "Web: Are hover states handled with MouseRegion? Are cursor changes applied? "
                "Are responsive breakpoints defined?\n"
                "Desktop: Are dense layout variants available? Is MenuBar implemented? "
                "Are pointer-specific interactions handled?\n"
                "Priority per platform feature."
            )
        else:
            section_instructions.append(
                "## Section 5: Platform & Responsive Design\n"
                "Review responsive breakpoints and platform-specific adaptations. "
                "Are touch targets appropriately sized? Is the design accessible? "
                "Identify missing dark mode support or reduced-motion support. Priority per finding."
            )

    sections_block = "\n\n".join(section_instructions)
    sections_str = ", ".join(sections)

    skipped_note = ""
    if skipped:
        skipped_note = (
            f"\n\nNote: {len(skipped)} file(s) were skipped due to budget limits: "
            + ", ".join(skipped[:5])
            + ("..." if len(skipped) > 5 else "")
        )

    prompt = (
        f"[System: {REDESIGN_SYSTEM_INSTRUCTION}]\n\n"
        f"## Redesign Analysis Request\n\n"
        f"Framework: {framework}\n"
        f"Date: {today}\n"
        f"Sections to analyze: {sections_str}\n\n"
        f"Produce a REDESIGN.md report with these exact sections in order:\n\n"
        f"```\n"
        f"# Redesign Report — {framework} — {today}\n"
        f"## Executive Summary\n"
        + "\n".join(f"## {i+1}. {s.replace('_', ' ').title()}" for i, s in enumerate(
            [s for s in ["M3 Theme & Color System", "Navigation & Transitions",
                         "Icon Migration (Lucide)", "Animation Opportunities",
                         "Platform-Specific Features"] if True]
        ))
        + f"\n## Implementation Priority\n```\n\n"
        f"For Implementation Priority, summarize all findings in a table:\n"
        f"| Finding | Section | Priority | File |\n\n"
        f"Now analyze these sections in detail:\n\n"
        f"{sections_block}\n\n"
        f"## Codebase to Analyze\n\n"
        f"{code_context}"
        f"{skipped_note}"
    )
    return prompt


@mcp.tool()
async def gemini_redesign(
    path: str | None = None,
    paths: list[str] | None = None,
    sections: list[str] | None = None,
    model: str | None = None,
    output: str | None = None,
) -> str:
    """Scan a frontend codebase and produce a structured REDESIGN.md spec using Gemini's large context window. Analyzes theme, icons, navigation, animations, and platform features. Never generates code — writes a design spec for Claude to implement separately.

    Args:
        path: Root of the project to scan (default: PROJECT_ROOT).
        paths: Optional scope narrowing — specific dirs or files within the project.
        sections: Filter to specific sections: "theme", "icons", "navigation", "animations", "platform".
        model: Optional Gemini model ID override.
        output: Override output file path (default: CWD/REDESIGN.md).
    """
    # Validate sections
    if sections:
        invalid = set(sections) - VALID_REDESIGN_SECTIONS
        if invalid:
            return (
                f"Error: invalid section(s): {', '.join(sorted(invalid))}. "
                f"Valid: {', '.join(sorted(VALID_REDESIGN_SECTIONS))}"
            )
    active_sections = sections or DEFAULT_REDESIGN_SECTIONS

    # Resolve scan root
    scan_root = Path(path).resolve() if path else PROJECT_ROOT
    if not scan_root.exists():
        return f"Error: path not found: {path}"

    # Detect framework
    framework = _detect_framework(scan_root)

    # Collect files
    code_context, skipped = _collect_redesign_files(scan_root, paths, framework)
    if not code_context.strip():
        return "Error: no source files found to analyze."

    # Build prompt
    full_prompt = _build_redesign_prompt(framework, active_sections, code_context, skipped)

    # Call Gemini
    report = await _gemini(full_prompt, model=model)

    # Write output
    output_path = Path(output).resolve() if output else Path.cwd() / "REDESIGN.md"
    output_path.write_text(report, encoding="utf-8")

    file_count = code_context.count("### ")
    section_count = len(active_sections)
    return (
        f"REDESIGN.md written ({section_count} sections, ~{file_count} files scanned). "
        f"Framework detected: {framework}. "
        f"Review it and implement with Claude."
    )


# ---------------------------------------------------------------------------
# SQLite project management constants and helpers
# ---------------------------------------------------------------------------

EPICS_DB = Path.home() / ".claude" / ".claude" / "epics.db"

STORY_STATES = {"draft", "ready", "in-progress", "in-review", "approved", "done", "blocked", "shipped"}
TASK_STATES = {"todo", "in-progress", "done", "blocked", "skipped"}
TERMINAL_STATES = {"done", "closed", "shipped"}
EPIC_STATES = {"active", "done", "shipped"}

VALID_STORY_TRANSITIONS = {
    "draft": {"ready", "in-progress"},
    "ready": {"in-progress", "draft"},
    "in-progress": {"in-review", "approved", "done", "blocked"},
    "in-review": {"in-progress", "approved"},
    "approved": {"done", "shipped", "in-progress"},
    "blocked": {"in-progress", "draft"},
}

VALID_EPIC_TRANSITIONS = {
    "active": {"done"},
    "done": {"shipped", "active"},
}


def _get_db(db_path: Path | None = None) -> sqlite3.Connection:
    """Open the epics SQLite database with WAL mode and row factory."""
    path = db_path or EPICS_DB
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _next_id(conn: sqlite3.Connection, table: str, prefix: str) -> str:
    """Generate the next sequential ID for a table (e.g., 'story-186')."""
    prefix_len = len(prefix)
    row = conn.execute(
        f"SELECT MAX(CAST(SUBSTR(id, {prefix_len + 1}) AS INTEGER)) FROM {table}"
    ).fetchone()
    next_num = (row[0] or 0) + 1
    return f"{prefix}{next_num}"


def _validate_transition(
    current: str, target: str, valid_map: dict[str, set[str]], force: bool = False
) -> str | None:
    """Return error message if transition is invalid, None if ok."""
    if force:
        return None
    # "any → blocked" and "any → draft" are always valid for stories
    if target in ("blocked", "draft"):
        return None
    allowed = valid_map.get(current, set())
    if target not in allowed:
        return f"Invalid transition: '{current}' → '{target}'. Allowed from '{current}': {sorted(allowed)}"
    return None


def _story_to_dict(row: sqlite3.Row) -> dict:
    """Convert a story Row to a dict, parsing JSON fields."""
    d = dict(row)
    for field in ("write_files", "depends_on"):
        val = d.get(field)
        if val and isinstance(val, str):
            try:
                d[field] = json.loads(val)
            except json.JSONDecodeError:
                d[field] = []
    # Convert integer booleans to bool
    for field in ("needs_testing", "needs_review", "auto_merge", "archived"):
        if field in d:
            d[field] = bool(d[field])
    return d


def _epic_to_dict(row: sqlite3.Row) -> dict:
    """Convert an epic Row to a dict."""
    d = dict(row)
    if "persistent" in d:
        d["persistent"] = bool(d["persistent"])
    return d


def _ensure_order_idx_column(conn: sqlite3.Connection) -> None:
    """Lazily add order_idx to stories table if it doesn't exist yet."""
    try:
        conn.execute("ALTER TABLE stories ADD COLUMN order_idx INTEGER")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Already exists


# ---------------------------------------------------------------------------
# PM Read/Query MCP tools (6 tools)
# ---------------------------------------------------------------------------

@mcp.tool()
async def pm_list_epics(
    state: str | None = None,
    include_stories: bool = False,
) -> str:
    """List all epics, optionally filtered by state. Returns epic summaries with optional story counts.

    Args:
        state: Filter by epic state ('active', 'done', 'shipped'). Omit for all.
        include_stories: If true, include inline story counts per state.
    """
    conn = _get_db()
    try:
        if state:
            if state not in EPIC_STATES:
                return f"Invalid state '{state}'. Valid: {sorted(EPIC_STATES)}"
            epics = conn.execute("SELECT * FROM epics WHERE state = ?", (state,)).fetchall()
        else:
            epics = conn.execute("SELECT * FROM epics").fetchall()

        result = []
        for epic in epics:
            ed = _epic_to_dict(epic)
            if include_stories:
                counts = conn.execute(
                    "SELECT state, COUNT(*) as cnt FROM stories "
                    "WHERE epic_id = ? AND archived = 0 GROUP BY state",
                    (ed["id"],)
                ).fetchall()
                ed["story_counts"] = {r["state"]: r["cnt"] for r in counts}
                total = conn.execute(
                    "SELECT COUNT(*) FROM stories WHERE epic_id = ? AND archived = 0",
                    (ed["id"],)
                ).fetchone()[0]
                ed["total_active_stories"] = total
            result.append(ed)
        return json.dumps(result, indent=2)
    finally:
        conn.close()


@mcp.tool()
async def pm_get_epic(epic_id: str) -> str:
    """Get a single epic with all its active stories and their tasks.

    Args:
        epic_id: The epic ID (e.g., 'epic-022').
    """
    conn = _get_db()
    try:
        epic = conn.execute("SELECT * FROM epics WHERE id = ?", (epic_id,)).fetchone()
        if not epic:
            return f"Epic '{epic_id}' not found."
        ed = _epic_to_dict(epic)

        _ensure_order_idx_column(conn)
        stories = conn.execute(
            "SELECT * FROM stories WHERE epic_id = ? AND archived = 0 ORDER BY COALESCE(order_idx, 2147483647), id",
            (epic_id,)
        ).fetchall()

        story_list = []
        for story in stories:
            sd = _story_to_dict(story)
            tasks = conn.execute(
                "SELECT * FROM tasks WHERE story_id = ? ORDER BY id",
                (sd["id"],)
            ).fetchall()
            sd["tasks"] = [dict(t) for t in tasks]
            story_list.append(sd)

        ed["stories"] = story_list
        return json.dumps(ed, indent=2)
    finally:
        conn.close()


@mcp.tool()
async def pm_list_stories(
    epic_id: str | None = None,
    state: str | None = None,
    agent: str | None = None,
    include_archived: bool = False,
) -> str:
    """List stories with optional filters. Archived stories excluded by default.

    Args:
        epic_id: Filter by epic ID.
        state: Filter by story state.
        agent: Filter by agent type ('quick-fixer', 'architect', etc.).
        include_archived: If true, include archived stories (default false).
    """
    conn = _get_db()
    try:
        conditions = []
        params: list = []

        if not include_archived:
            conditions.append("archived = 0")

        if epic_id:
            conditions.append("epic_id = ?")
            params.append(epic_id)

        if state:
            if state not in STORY_STATES:
                return f"Invalid state '{state}'. Valid: {sorted(STORY_STATES)}"
            conditions.append("state = ?")
            params.append(state)

        if agent:
            conditions.append("agent = ?")
            params.append(agent)

        where = " AND ".join(conditions) if conditions else "1=1"
        _ensure_order_idx_column(conn)
        stories = conn.execute(
            f"SELECT * FROM stories WHERE {where} ORDER BY COALESCE(order_idx, 2147483647), id", params
        ).fetchall()

        return json.dumps([_story_to_dict(s) for s in stories], indent=2)
    finally:
        conn.close()


@mcp.tool()
async def pm_get_story(story_id: str) -> str:
    """Get a single story with its tasks and reverse dependency info.

    Args:
        story_id: The story ID (e.g., 'story-185').
    """
    conn = _get_db()
    try:
        story = conn.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()
        if not story:
            return f"Story '{story_id}' not found."
        sd = _story_to_dict(story)

        tasks = conn.execute(
            "SELECT * FROM tasks WHERE story_id = ? ORDER BY id", (story_id,)
        ).fetchall()
        sd["tasks"] = [dict(t) for t in tasks]

        # Reverse dependencies: stories that depend on this one
        blocked_by_me = conn.execute(
            "SELECT id, title, state FROM stories WHERE depends_on LIKE ? AND archived = 0",
            (f'%"{story_id}"%',)
        ).fetchall()
        if blocked_by_me:
            sd["blocks"] = [{"id": r["id"], "title": r["title"], "state": r["state"]} for r in blocked_by_me]

        return json.dumps(sd, indent=2)
    finally:
        conn.close()


@mcp.tool()
async def pm_board(epic_id: str | None = None) -> str:
    """Show a Kanban board view grouped by story state. Only active (non-archived) stories.

    Args:
        epic_id: Optional epic ID to scope the board to a single epic.
    """
    conn = _get_db()
    try:
        _ensure_order_idx_column(conn)
        if epic_id:
            stories = conn.execute(
                "SELECT * FROM stories WHERE epic_id = ? AND archived = 0 ORDER BY COALESCE(order_idx, 2147483647), id",
                (epic_id,)
            ).fetchall()
        else:
            stories = conn.execute(
                "SELECT * FROM stories WHERE archived = 0 ORDER BY COALESCE(order_idx, 2147483647), id"
            ).fetchall()

        board: dict[str, list] = {}
        for story in stories:
            sd = _story_to_dict(story)
            state = sd["state"]
            if state not in board:
                board[state] = []
            board[state].append({
                "id": sd["id"],
                "title": sd["title"],
                "epic_id": sd["epic_id"],
                "agent": sd.get("agent"),
                "branch": sd.get("branch"),
            })

        # Add WIP counts
        summary = {
            "columns": board,
            "wip": {state: len(items) for state, items in board.items()},
            "total": sum(len(items) for items in board.values()),
        }

        # Blocked items detail
        blocked = board.get("blocked", [])
        if blocked:
            summary["blocked_items"] = blocked

        return json.dumps(summary, indent=2)
    finally:
        conn.close()


@mcp.tool()
async def pm_search(query: str, scope: str | None = None) -> str:
    """Search across epics, stories, and tasks by title or ID substring.

    Args:
        query: Search term (matched as substring against titles and IDs).
        scope: Limit search to 'epics', 'stories', or 'tasks'. Omit to search all.
    """
    conn = _get_db()
    try:
        results = []
        pattern = f"%{query}%"

        if scope in (None, "epics"):
            epics = conn.execute(
                "SELECT * FROM epics WHERE id LIKE ? OR title LIKE ?",
                (pattern, pattern)
            ).fetchall()
            for e in epics:
                results.append({"type": "epic", **_epic_to_dict(e)})

        if scope in (None, "stories"):
            stories = conn.execute(
                "SELECT * FROM stories WHERE (id LIKE ? OR title LIKE ?) AND archived = 0",
                (pattern, pattern)
            ).fetchall()
            for s in stories:
                results.append({"type": "story", **_story_to_dict(s)})

        if scope in (None, "tasks"):
            tasks = conn.execute(
                "SELECT t.*, s.title as story_title FROM tasks t "
                "JOIN stories s ON t.story_id = s.id "
                "WHERE t.id LIKE ? OR t.title LIKE ?",
                (pattern, pattern)
            ).fetchall()
            for t in tasks:
                results.append({"type": "task", **dict(t)})

        return json.dumps(results, indent=2)
    finally:
        conn.close()


@mcp.tool()
async def pm_view(
    epic_id: str | None = None,
    include_archived: bool = False,
) -> str:
    """Combined dashboard: active epic summaries, Kanban board, WIP metrics, and callouts.

    Args:
        epic_id: Scope to a single epic. Omit for all active epics.
        include_archived: Include archived story counts in epic progress summaries.
    """
    conn = _get_db()
    try:
        _ensure_order_idx_column(conn)

        # --- 1. Fetch epics ------------------------------------------------
        if epic_id:
            epic_rows = conn.execute(
                "SELECT * FROM epics WHERE id = ?", (epic_id,)
            ).fetchall()
            if not epic_rows:
                return json.dumps({"error": f"Epic '{epic_id}' not found."})
        else:
            epic_rows = conn.execute(
                "SELECT * FROM epics WHERE state = 'active'"
            ).fetchall()

        # --- 2. Epic progress summaries ------------------------------------
        epics_out = []
        for epic in epic_rows:
            ed = _epic_to_dict(epic)
            archived_filter = "" if include_archived else " AND archived = 0"
            counts = conn.execute(
                f"SELECT state, COUNT(*) as cnt FROM stories "
                f"WHERE epic_id = ?{archived_filter} GROUP BY state",
                (ed["id"],)
            ).fetchall()
            by_state = {r["state"]: r["cnt"] for r in counts}
            total = sum(by_state.values())
            done_count = by_state.get("done", 0) + by_state.get("shipped", 0)
            pct_done = round(done_count / total * 100) if total else 0
            epics_out.append({
                "id": ed["id"],
                "title": ed["title"],
                "state": ed["state"],
                "persistent": ed.get("persistent", False),
                "progress": {
                    "total": total,
                    "by_state": by_state,
                    "pct_done": pct_done,
                },
            })

        # --- 3. Board columns ----------------------------------------------
        epic_filter = ""
        story_params: list = []
        if epic_id:
            epic_filter = " AND epic_id = ?"
            story_params.append(epic_id)

        stories = conn.execute(
            f"SELECT * FROM stories WHERE archived = 0{epic_filter} "
            f"ORDER BY COALESCE(order_idx, 2147483647), id",
            story_params
        ).fetchall()

        board: dict[str, list] = {}
        for story in stories:
            sd = _story_to_dict(story)
            state = sd["state"]
            if state not in board:
                board[state] = []
            board[state].append({
                "id": sd["id"],
                "title": sd["title"],
                "epic_id": sd["epic_id"],
                "agent": sd.get("agent"),
                "branch": sd.get("branch"),
            })

        # --- 4. WIP stats --------------------------------------------------
        by_state_rows = conn.execute(
            f"SELECT state, COUNT(*) as cnt FROM stories WHERE archived = 0{epic_filter} "
            f"GROUP BY state ORDER BY cnt DESC",
            story_params
        ).fetchall()
        by_agent_rows = conn.execute(
            f"SELECT COALESCE(agent, 'unassigned') as agent, COUNT(*) as cnt "
            f"FROM stories WHERE archived = 0{epic_filter} GROUP BY agent ORDER BY cnt DESC",
            story_params
        ).fetchall()
        wip = {
            "total_active": sum(r["cnt"] for r in by_state_rows),
            "by_state": {r["state"]: r["cnt"] for r in by_state_rows},
            "by_agent": {r["agent"]: r["cnt"] for r in by_agent_rows},
        }

        # --- 5. Callouts ---------------------------------------------------
        blocked_rows = conn.execute(
            f"SELECT id, title, epic_id FROM stories "
            f"WHERE state = 'blocked' AND archived = 0{epic_filter}",
            story_params
        ).fetchall()

        stale_cutoff = (datetime.utcnow() - timedelta(days=14)).isoformat()

        stale_rows = conn.execute(
            f"SELECT id, title, epic_id, started_at FROM stories "
            f"WHERE state = 'in-progress' AND archived = 0 "
            f"AND started_at IS NOT NULL AND started_at < ?{epic_filter}",
            [stale_cutoff] + story_params
        ).fetchall()

        callouts = {
            "blocked": [
                {"id": r["id"], "title": r["title"], "epic_id": r["epic_id"]}
                for r in blocked_rows
            ],
            "stale": [
                {"id": r["id"], "title": r["title"], "epic_id": r["epic_id"],
                 "started_at": r["started_at"]}
                for r in stale_rows
            ],
        }

        result = {
            "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
            "scope": epic_id or "all",
            "epics": epics_out,
            "board": board,
            "wip": wip,
            "callouts": callouts,
        }
        return json.dumps(result, indent=2)
    finally:
        conn.close()


PLAN_SYSTEM_INSTRUCTION = (
    "You are a senior software engineer. Given the project context and codebase, "
    "produce a concrete implementation plan for the given stories/epics.\n\n"
    "For each story, return:\n"
    '- "agent": one of "quick-fixer" (small fixes/styling), "architect" (new features/refactors), "unit-tester" (tests only)\n'
    '- "write_files": list of file paths this story will modify\n'
    '- "tasks": ordered list of implementation steps as strings\n'
    '- "parallel_group": integer (1=first, 2=after group 1 finishes, etc.)\n'
    '- "depends_on": list of story IDs that must complete first\n\n'
    "Return ONLY valid JSON. No prose, no markdown, no code blocks."
)


def _build_plan_prompt(subject: str, context_block: str, code_block: str) -> str:
    """Build a Gemini prompt for planning epics/stories. Returns valid-JSON-only prompt."""
    parts = [f"[System: {PLAN_SYSTEM_INSTRUCTION}]"]
    if context_block:
        parts.append(f"## Project Context\n\n{context_block}")
    if code_block:
        parts.append(f"## Codebase\n\n{code_block}")
    parts.append(f"## Planning Subject\n\n{subject}")
    return "\n\n".join(parts)


@mcp.tool()
async def pm_plan(
    epic_id: str | None = None,
    story_id: str | None = None,
    paths: list[str] | None = None,
) -> str:
    """AI-powered planning tool that reads the codebase and generates task breakdowns, agent assignments, and execution order for epics and stories.

    Three modes:
    - Story mode (story_id set): generate tasks + agent + write_files for one story
    - Epic mode (epic_id set, no story_id): plan all draft stories in an epic
    - Bulk mode (neither set): return full roadmap JSON for all active epics/stories

    Args:
        epic_id: Scope planning to one epic (epic mode).
        story_id: Scope planning to one story (story mode). Takes priority over epic_id.
        paths: Source file paths to pass as codebase context (default: PROJECT_ROOT).
    """
    conn = _get_db()
    try:
        # Load shared context (codebase + project docs)
        audit_context = _load_audit_context()
        files = _discover_files(paths)
        code_content, _ = _read_files_within_budget(files, MAX_CODE_BYTES)

        # ---------------------------------------------------------------
        # Story mode
        # ---------------------------------------------------------------
        if story_id:
            story = conn.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()
            if not story:
                return json.dumps({"error": f"Story '{story_id}' not found."})
            sd = _story_to_dict(story)

            # Gather existing open stories for dependency context
            open_stories = conn.execute(
                "SELECT id, title, state FROM stories WHERE state NOT IN ('done','shipped') AND archived = 0 AND id != ?",
                (story_id,)
            ).fetchall()
            open_stories_text = "\n".join(
                f"- {r['id']}: {r['title']} [{r['state']}]" for r in open_stories
            ) or "(none)"

            subject = (
                f"Story ID: {sd['id']}\n"
                f"Title: {sd['title']}\n"
                f"Current agent: {sd.get('agent') or 'unassigned'}\n"
                f"Current write_files: {sd.get('write_files') or []}\n\n"
                f"Other open stories (for dependency awareness):\n{open_stories_text}\n\n"
                "Return a single JSON object (not an array) with fields: "
                "agent, write_files, tasks, parallel_group, depends_on."
            )

            prompt = _build_plan_prompt(subject, audit_context, code_content)
            plan_file = Path(tempfile.mktemp(suffix=".md", prefix="pm_plan_"))
            raw = await _gemini(prompt)
            plan_file.write_text(raw, encoding="utf-8")

            try:
                plan_data = json.loads(plan_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                return json.dumps({
                    "error": "Gemini returned malformed JSON.",
                    "plan_file": str(plan_file),
                })

            # Write tasks to DB
            for task_title in plan_data.get("tasks", []):
                row = conn.execute(
                    "SELECT MAX(CAST(SUBSTR(id, 2) AS INTEGER)) FROM tasks WHERE story_id = ?",
                    (story_id,)
                ).fetchone()
                next_num = (row[0] or 0) + 1
                conn.execute(
                    "INSERT INTO tasks (id, story_id, title, state, blocked_by) VALUES (?, ?, ?, 'todo', NULL)",
                    (f"t{next_num}", story_id, task_title)
                )
            # Update story agent and write_files
            conn.execute(
                "UPDATE stories SET agent = ?, write_files = ? WHERE id = ?",
                (
                    plan_data.get("agent"),
                    json.dumps(plan_data.get("write_files", [])),
                    story_id,
                )
            )
            conn.commit()
            return json.dumps({
                "mode": "story",
                "story_id": story_id,
                "title": sd["title"],
                "agent": plan_data.get("agent"),
                "write_files": plan_data.get("write_files", []),
                "tasks_created": len(plan_data.get("tasks", [])),
            })

        # ---------------------------------------------------------------
        # Epic mode
        # ---------------------------------------------------------------
        if epic_id:
            epic = conn.execute("SELECT * FROM epics WHERE id = ?", (epic_id,)).fetchone()
            if not epic:
                return json.dumps({"error": f"Epic '{epic_id}' not found."})

            draft_stories = conn.execute(
                "SELECT * FROM stories WHERE epic_id = ? AND state IN ('draft','ready') AND archived = 0",
                (epic_id,)
            ).fetchall()

            if not draft_stories:
                return json.dumps({
                    "mode": "epic",
                    "epic_id": epic_id,
                    "message": "No draft/ready stories found in this epic.",
                })

            story_list = [_story_to_dict(s) for s in draft_stories]
            subject_lines = [
                f"- Story {s['id']}: {s['title']}" for s in story_list
            ]
            subject = (
                f"Epic ID: {epic_id}\n"
                f"Epic title: {dict(epic)['title']}\n\n"
                "Stories to plan (return a JSON array, one object per story in the same order):\n"
                + "\n".join(subject_lines)
                + "\n\nEach array element must have: story_id, agent, write_files, tasks, parallel_group, depends_on."
            )

            prompt = _build_plan_prompt(subject, audit_context, code_content)
            plan_file = Path(tempfile.mktemp(suffix=".md", prefix="pm_plan_"))
            raw = await _gemini(prompt)
            plan_file.write_text(raw, encoding="utf-8")

            try:
                plans = json.loads(plan_file.read_text(encoding="utf-8"))
                if not isinstance(plans, list):
                    plans = [plans]
            except (json.JSONDecodeError, ValueError):
                return json.dumps({
                    "error": "Gemini returned malformed JSON.",
                    "plan_file": str(plan_file),
                })

            summary = []
            for s, plan_data in zip(story_list, plans):
                sid = s["id"]
                for task_title in plan_data.get("tasks", []):
                    row = conn.execute(
                        "SELECT MAX(CAST(SUBSTR(id, 2) AS INTEGER)) FROM tasks WHERE story_id = ?",
                        (sid,)
                    ).fetchone()
                    next_num = (row[0] or 0) + 1
                    conn.execute(
                        "INSERT INTO tasks (id, story_id, title, state, blocked_by) VALUES (?, ?, ?, 'todo', NULL)",
                        (f"t{next_num}", sid, task_title)
                    )
                conn.execute(
                    "UPDATE stories SET agent = ?, write_files = ? WHERE id = ?",
                    (
                        plan_data.get("agent"),
                        json.dumps(plan_data.get("write_files", [])),
                        sid,
                    )
                )
                summary.append({
                    "story_id": sid,
                    "title": s["title"],
                    "agent": plan_data.get("agent"),
                    "tasks_created": len(plan_data.get("tasks", [])),
                    "parallel_group": plan_data.get("parallel_group", 1),
                    "depends_on": plan_data.get("depends_on", []),
                })

            conn.commit()

            return json.dumps({
                "mode": "epic",
                "epic_id": epic_id,
                "stories": summary,
            }, indent=2)

        # ---------------------------------------------------------------
        # Bulk mode
        # ---------------------------------------------------------------
        active_epics = conn.execute(
            "SELECT * FROM epics WHERE state = 'active'"
        ).fetchall()

        all_stories = conn.execute(
            "SELECT * FROM stories WHERE state NOT IN ('done','shipped','archived') AND archived = 0 "
            "ORDER BY epic_id, id"
        ).fetchall()

        epic_map: dict[str, dict] = {}
        for epic in active_epics:
            ed = _epic_to_dict(epic)
            epic_map[ed["id"]] = {**ed, "stories": []}

        for story in all_stories:
            sd = _story_to_dict(story)
            eid = sd.get("epic_id", "")
            if eid in epic_map:
                epic_map[eid]["stories"].append(sd)

        # Build subject listing all epics and stories
        subject_parts = []
        for eid, edata in epic_map.items():
            subject_parts.append(f"Epic {eid}: {edata['title']}")
            for s in edata["stories"]:
                subject_parts.append(f"  - Story {s['id']}: {s['title']} [{s['state']}]")

        subject = (
            "Produce a full roadmap JSON with this structure:\n"
            '{"epics": [{"id": ..., "title": ..., "stories": [{"id": ..., "title": ..., '
            '"agent": ..., "parallel_group": ..., "depends_on": [...], "tasks": [...]}]}], '
            '"execution_plan": {"parallel_groups": [{"group": 1, "stories": [...], '
            '"can_run_simultaneously": true}], "total_stories": N}}\n\n'
            "Stories to plan:\n" + "\n".join(subject_parts)
        )

        prompt = _build_plan_prompt(subject, audit_context, code_content)
        plan_file = Path(tempfile.mktemp(suffix=".md", prefix="pm_plan_"))
        raw = await _gemini(prompt)
        plan_file.write_text(raw, encoding="utf-8")

        try:
            roadmap = json.loads(plan_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            return json.dumps({
                "error": "Gemini returned malformed JSON.",
                "plan_file": str(plan_file),
            })

        roadmap["generated_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        roadmap["mode"] = "bulk"
        return json.dumps(roadmap, indent=2)

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# PM Write MCP tools (6 tools)
# ---------------------------------------------------------------------------

@mcp.tool()
async def pm_create_epic(
    title: str,
    branch: str | None = None,
    persistent: bool = False,
) -> str:
    """Create a new epic with an auto-generated ID.

    Args:
        title: Epic title.
        branch: Optional git branch name (e.g., 'epic/023').
        persistent: If true, epic stays active even when all stories are done.
    """
    conn = _get_db()
    try:
        epic_id = _next_id(conn, "epics", "epic-")
        conn.execute(
            "INSERT INTO epics (id, title, branch, persistent, state) VALUES (?, ?, ?, ?, 'active')",
            (epic_id, title, branch, int(persistent))
        )
        conn.commit()
        return json.dumps({
            "id": epic_id, "title": title, "branch": branch, "persistent": persistent, "state": "active",
            "suggestions": ["Call pm_plan_items with your story titles to auto-group them into stories and tasks"],
        })
    finally:
        conn.close()


@mcp.tool()
async def pm_create_story(
    title: str,
    epic_id: str | None = None,
    write_files: list[str] | None = None,
    agent: str | None = None,
    model: str | None = None,
    depends_on: list[str] | None = None,
    needs_testing: bool = False,
    needs_review: bool = False,
    tasks: list[str] | None = None,
) -> str:
    """Create a new story with an auto-generated ID. Defaults to 'backlog' epic if none specified.

    Args:
        title: Story title.
        epic_id: Epic to add the story to. Creates 'epic-backlog' if omitted.
        write_files: List of files this story will modify.
        agent: Agent type ('quick-fixer', 'architect', 'manual').
        model: Model to use ('haiku', 'sonnet', 'opus').
        depends_on: List of story IDs this story depends on.
        needs_testing: Whether the story needs testing before merge.
        needs_review: Whether the story needs review before merge.
        tasks: Optional list of task titles to create immediately under this story.
    """
    conn = _get_db()
    try:
        target_epic = epic_id or "epic-backlog"

        # Ensure epic exists
        existing = conn.execute("SELECT id FROM epics WHERE id = ?", (target_epic,)).fetchone()
        if not existing:
            if target_epic == "epic-backlog":
                conn.execute(
                    "INSERT INTO epics (id, title, persistent, state) VALUES ('epic-backlog', 'Backlog', 1, 'active')"
                )
            else:
                return f"Epic '{target_epic}' not found. Create it first with pm_create_epic."

        story_id = _next_id(conn, "stories", "story-")
        conn.execute(
            """INSERT INTO stories (id, epic_id, title, state, write_files, agent, model,
               depends_on, needs_testing, needs_review)
               VALUES (?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?)""",
            (
                story_id, target_epic, title,
                json.dumps(write_files or []),
                agent, model,
                json.dumps(depends_on or []),
                int(needs_testing), int(needs_review),
            )
        )

        # Inline task creation
        created_tasks = []
        for i, task_title in enumerate(tasks or [], start=1):
            task_id = f"t{i}"
            conn.execute(
                "INSERT INTO tasks (id, story_id, title, state, blocked_by) VALUES (?, ?, ?, 'todo', NULL)",
                (task_id, story_id, task_title)
            )
            created_tasks.append({"id": task_id, "title": task_title, "state": "todo"})

        conn.commit()
        result = {
            "id": story_id, "epic_id": target_epic, "title": title,
            "state": "draft", "write_files": write_files or [],
            "agent": agent, "model": model,
        }
        if created_tasks:
            result["tasks"] = created_tasks
        return json.dumps(result)
    finally:
        conn.close()


def _tokenize(text: str) -> set[str]:
    """Tokenize text into lowercase keyword set, stripping punctuation."""
    import re
    return set(re.sub(r"[^\w\s]", "", text.lower()).split())


def _jaccard(a: set[str], b: set[str]) -> float:
    """Compute Jaccard similarity between two sets."""
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def _find_best_story_match(conn: sqlite3.Connection, title: str, write_files: list[str] | None) -> tuple[str | None, list[dict]]:
    """Find the best matching open story for a task title.

    Returns (story_id, candidates) where:
    - story_id is set if exactly 1 clear match (jaccard > 0.3)
    - candidates is a list of dicts if 2+ plausible matches
    - Both None/empty if no match found
    """
    title_kw = _tokenize(title)
    open_stories = conn.execute(
        "SELECT id, title, write_files FROM stories WHERE state NOT IN ('done', 'shipped', 'archived')"
    ).fetchall()

    matches: list[tuple[float, str, str]] = []  # (score, story_id, story_title)
    for row in open_stories:
        story_kw = _tokenize(row["title"])
        score = _jaccard(title_kw, story_kw)
        if score > 0.3:
            matches.append((score, row["id"], row["title"]))

    # Sort by score descending
    matches.sort(key=lambda x: x[0], reverse=True)

    if not matches:
        return None, []
    if len(matches) == 1:
        return matches[0][1], []
    # Multiple plausible matches — return as candidates
    candidates = [{"story_id": m[1], "title": m[2], "score": round(m[0], 2)} for m in matches[:5]]
    return None, candidates


def _add_task_to_story(conn: sqlite3.Connection, story_id: str, title: str, blocked_by: str | None) -> dict:
    """Insert a task into a story and return the task dict."""
    row = conn.execute(
        "SELECT MAX(CAST(SUBSTR(id, 2) AS INTEGER)) FROM tasks WHERE story_id = ?",
        (story_id,)
    ).fetchone()
    next_num = (row[0] or 0) + 1
    task_id = f"t{next_num}"
    conn.execute(
        "INSERT INTO tasks (id, story_id, title, state, blocked_by) VALUES (?, ?, ?, 'todo', ?)",
        (task_id, story_id, title, blocked_by)
    )
    return {"id": task_id, "story_id": story_id, "title": title, "state": "todo", "blocked_by": blocked_by}


def _create_story_for_task(conn: sqlite3.Connection, title: str, write_files: list[str] | None) -> str:
    """Create a new draft story (in epic-backlog) and return its ID."""
    target_epic = "epic-backlog"
    existing = conn.execute("SELECT id FROM epics WHERE id = ?", (target_epic,)).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO epics (id, title, persistent, state) VALUES ('epic-backlog', 'Backlog', 1, 'active')"
        )
    story_id = _next_id(conn, "stories", "story-")
    conn.execute(
        """INSERT INTO stories (id, epic_id, title, state, write_files, agent, model,
           depends_on, needs_testing, needs_review)
           VALUES (?, 'epic-backlog', ?, 'draft', ?, NULL, NULL, '[]', 0, 0)""",
        (story_id, title, json.dumps(write_files or []))
    )
    return story_id


@mcp.tool()
async def pm_add_task(
    title: str | None = None,
    story_id: str | None = None,
    write_files: list[str] | None = None,
    items: list[str] | None = None,
    blocked_by: str | None = None,
) -> str:
    """Add a task (or tasks) to a story with auto-generated IDs.

    story_id is optional — if omitted the tool searches open stories by keyword
    similarity. If 1 clear match is found the task is added there; if no match,
    a new story is created; if 2+ matches, candidates are returned for Claude to
    ask the user.

    Args:
        title: Single task title (omit if using items).
        story_id: Story to add the task to. Auto-detected from title if omitted.
        write_files: File paths hinting which story to target.
        items: Bulk list of task title strings (alternative to title).
        blocked_by: Optional task ID within the same story that blocks this one.
    """
    if not title and not items:
        return "Provide either 'title' for a single task or 'items' for bulk tasks."

    all_titles = items if items else [title]  # type: ignore[list-item]

    conn = _get_db()
    try:
        results = []
        for task_title in all_titles:
            target_story = story_id

            if not target_story:
                matched, candidates = _find_best_story_match(conn, task_title, write_files)
                if candidates:
                    return json.dumps({
                        "action": "needs_clarification",
                        "task": task_title,
                        "message": "Multiple plausible stories found. Specify story_id.",
                        "candidates": candidates,
                    })
                if matched:
                    target_story = matched
                else:
                    # Create a new story for this task
                    target_story = _create_story_for_task(conn, task_title, write_files)
                    results.append({"created_story": target_story})

            story = conn.execute("SELECT id FROM stories WHERE id = ?", (target_story,)).fetchone()
            if not story:
                return f"Story '{target_story}' not found."

            task = _add_task_to_story(conn, target_story, task_title, blocked_by)
            results.append(task)

        conn.commit()
        if len(results) == 1:
            return json.dumps(results[0])
        return json.dumps({"created": results, "count": len(results)})
    finally:
        conn.close()


def _group_items(items: list[str], existing_stories: list[dict]) -> dict:
    """Group raw todo items into story clusters using Jaccard similarity + union-find.

    Returns a proposal dict with proposed_epics, proposed_stories, questions, warnings.
    """
    # Tokenize each item
    tokens = [_tokenize(item) for item in items]

    # Union-find helpers
    parent = list(range(len(items)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        parent[find(x)] = find(y)

    # Build clusters: unite items with Jaccard > 0.3
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if _jaccard(tokens[i], tokens[j]) > 0.3:
                union(i, j)

    # Collect clusters
    from collections import defaultdict
    clusters: dict[int, list[int]] = defaultdict(list)
    for idx in range(len(items)):
        clusters[find(idx)].append(idx)

    # Build proposed stories
    proposed_stories = []
    warnings = []
    existing_titles_kw = [(_tokenize(s["title"]), s["id"]) for s in existing_stories]

    for root, indices in clusters.items():
        cluster_items = [items[i] for i in indices]
        if len(cluster_items) == 1:
            story_title = cluster_items[0]
            tasks: list[str] = []
        else:
            # Use the longest item as story title heuristic
            story_title = max(cluster_items, key=len)
            tasks = [item for item in cluster_items if item != story_title]

        # Duplicate check against existing open stories
        story_kw = _tokenize(story_title)
        for ex_kw, ex_id in existing_titles_kw:
            if story_kw & ex_kw and _jaccard(story_kw, ex_kw) > 0.3:
                warnings.append(
                    f"'{story_title}' may duplicate existing story {ex_id} — review before committing."
                )

        proposed_stories.append({
            "title": story_title,
            "tasks": tasks,
            "write_files": [],
            "epic_id": None,
        })

    # If >2 distinct clusters with no cross-cluster keyword overlap → suggest separate epics
    all_tokens = [_tokenize(s["title"]) for s in proposed_stories]
    questions: list[str] = []
    if len(proposed_stories) > 2:
        has_overlap = any(
            _jaccard(all_tokens[i], all_tokens[j]) > 0.0
            for i in range(len(all_tokens))
            for j in range(i + 1, len(all_tokens))
        )
        if not has_overlap:
            questions.append(
                "The items span multiple unrelated themes. Should they be grouped into separate epics? "
                "If yes, reply with epic names and which stories belong to each."
            )

    return {
        "proposed_epics": [],
        "proposed_stories": proposed_stories,
        "questions": questions,
        "warnings": warnings,
    }


@mcp.tool()
async def pm_plan_items(
    items: list[str],
    epic_id: str | None = None,
    confirmed: bool = False,
    proposal: dict | None = None,
) -> str:
    """Bulk planning tool for unstructured todos. Groups items into stories and tasks.

    Two-phase flow:
    1. Phase 1 — Propose (confirmed=False): groups items and returns a JSON proposal.
    2. Phase 2 — Commit (confirmed=True, proposal=<from phase 1>): creates epics/stories/tasks.

    Args:
        items: Raw todo strings to plan.
        epic_id: Optional target epic for all proposed stories.
        confirmed: If True, commit the proposal to the DB.
        proposal: The proposal dict returned by a prior Phase 1 call (required when confirmed=True).
    """
    if confirmed and not proposal:
        return "Pass the 'proposal' dict from the Phase 1 call when confirmed=True."

    conn = _get_db()
    try:
        if not confirmed:
            # Phase 1 — generate proposal
            open_stories = conn.execute(
                "SELECT id, title FROM stories WHERE state NOT IN ('done', 'shipped', 'archived')"
            ).fetchall()
            existing = [{"id": r["id"], "title": r["title"]} for r in open_stories]
            prop = _group_items(items, existing)

            # Attach epic_id hint if provided
            if epic_id:
                for s in prop["proposed_stories"]:
                    s["epic_id"] = epic_id

            return json.dumps({
                "phase": "proposal",
                "item_count": len(items),
                "story_count": len(prop["proposed_stories"]),
                "proposal": prop,
                "instructions": (
                    "Review the proposal. Answer any questions, then call pm_plan_items again "
                    "with confirmed=True and this proposal (optionally modified) to commit."
                ),
            }, indent=2)

        # Phase 2 — commit
        prop = proposal
        created_epics: list[dict] = []
        created_stories: list[dict] = []
        created_tasks: list[dict] = []

        # Create new epics
        for ep in prop.get("proposed_epics", []):
            ep_id = _next_id(conn, "epics", "epic-")
            conn.execute(
                "INSERT INTO epics (id, title, branch, persistent, state) VALUES (?, ?, NULL, 0, 'active')",
                (ep_id, ep["title"])
            )
            created_epics.append({"id": ep_id, "title": ep["title"]})
            # Update story references to use new epic ID
            for s in prop.get("proposed_stories", []):
                if s.get("epic_id") == ep.get("temp_id"):
                    s["epic_id"] = ep_id

        # Create stories + tasks
        target_epic = epic_id or "epic-backlog"
        existing_epic = conn.execute("SELECT id FROM epics WHERE id = ?", (target_epic,)).fetchone()
        if not existing_epic and target_epic == "epic-backlog":
            conn.execute(
                "INSERT INTO epics (id, title, persistent, state) VALUES ('epic-backlog', 'Backlog', 1, 'active')"
            )

        for s in prop.get("proposed_stories", []):
            story_epic = s.get("epic_id") or target_epic
            # Ensure story epic exists
            ep_exists = conn.execute("SELECT id FROM epics WHERE id = ?", (story_epic,)).fetchone()
            if not ep_exists:
                story_epic = target_epic

            story_id = _next_id(conn, "stories", "story-")
            conn.execute(
                """INSERT INTO stories (id, epic_id, title, state, write_files, agent, model,
                   depends_on, needs_testing, needs_review)
                   VALUES (?, ?, ?, 'draft', ?, NULL, NULL, '[]', 0, 0)""",
                (story_id, story_epic, s["title"], json.dumps(s.get("write_files") or []))
            )
            created_stories.append({"id": story_id, "title": s["title"], "epic_id": story_epic})

            # Create tasks
            for i, task_title in enumerate(s.get("tasks") or [], start=1):
                task_id = f"t{i}"
                conn.execute(
                    "INSERT INTO tasks (id, story_id, title, state, blocked_by) VALUES (?, ?, ?, 'todo', NULL)",
                    (task_id, story_id, task_title)
                )
                created_tasks.append({"id": task_id, "story_id": story_id, "title": task_title})

        conn.commit()
        return json.dumps({
            "phase": "committed",
            "created_epics": created_epics,
            "created_stories": created_stories,
            "created_tasks": created_tasks,
            "summary": (
                f"Created {len(created_epics)} epic(s), "
                f"{len(created_stories)} story(ies), "
                f"{len(created_tasks)} task(s)."
            ),
        }, indent=2)
    finally:
        conn.close()


@mcp.tool()
async def pm_update_story(
    story_id: str,
    state: str | None = None,
    title: str | None = None,
    agent: str | None = None,
    model: str | None = None,
    write_files: list[str] | None = None,
    branch: str | None = None,
    move_to_epic: str | None = None,
    force: bool = False,
) -> str:
    """Update story fields. Validates state transitions. Auto-timestamps on state changes.

    Args:
        story_id: Story to update.
        state: New state. Validates transition unless force=True.
        title: New title.
        agent: New agent type.
        model: New model.
        write_files: New list of write files.
        branch: New branch name.
        move_to_epic: Epic ID to move the story to.
        force: Skip state transition validation.
    """
    conn = _get_db()
    try:
        story = conn.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()
        if not story:
            return f"Story '{story_id}' not found."

        sd = _story_to_dict(story)
        updates = []
        params: list = []

        if state is not None:
            if state not in STORY_STATES:
                return f"Invalid state '{state}'. Valid: {sorted(STORY_STATES)}"
            err = _validate_transition(sd["state"], state, VALID_STORY_TRANSITIONS, force)
            if err:
                return err
            updates.append("state = ?")
            params.append(state)

            # Auto-set started_at on → in-progress
            if state == "in-progress" and not sd.get("started_at"):
                updates.append("started_at = ?")
                params.append(datetime.utcnow().isoformat())

            # Auto-set completed_at and archived on → terminal
            if state in TERMINAL_STATES:
                updates.append("completed_at = ?")
                params.append(datetime.utcnow().isoformat())
                updates.append("archived = 1")

        if title is not None:
            updates.append("title = ?")
            params.append(title)

        if agent is not None:
            updates.append("agent = ?")
            params.append(agent)

        if model is not None:
            updates.append("model = ?")
            params.append(model)

        if write_files is not None:
            updates.append("write_files = ?")
            params.append(json.dumps(write_files))

        if branch is not None:
            updates.append("branch = ?")
            params.append(branch)

        if move_to_epic is not None:
            epic = conn.execute("SELECT id FROM epics WHERE id = ?", (move_to_epic,)).fetchone()
            if not epic:
                return f"Epic '{move_to_epic}' not found."
            updates.append("epic_id = ?")
            params.append(move_to_epic)

        if not updates:
            return "No fields to update."

        params.append(story_id)
        conn.execute(
            f"UPDATE stories SET {', '.join(updates)} WHERE id = ?", params
        )
        conn.commit()

        # Return updated story
        updated = conn.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()
        return json.dumps(_story_to_dict(updated), indent=2)
    finally:
        conn.close()


@mcp.tool()
async def pm_update_epic(
    epic_id: str,
    title: str | None = None,
    state: str | None = None,
    branch: str | None = None,
    pr_number: int | None = None,
    persistent: bool | None = None,
) -> str:
    """Update epic fields. Validates state transitions.

    Args:
        epic_id: Epic to update.
        title: New title.
        state: New state ('active', 'done', 'shipped').
        branch: New branch name.
        pr_number: PR number.
        persistent: Whether the epic is persistent.
    """
    conn = _get_db()
    try:
        epic = conn.execute("SELECT * FROM epics WHERE id = ?", (epic_id,)).fetchone()
        if not epic:
            return f"Epic '{epic_id}' not found."

        ed = _epic_to_dict(epic)
        updates = []
        params: list = []

        if state is not None:
            if state not in EPIC_STATES:
                return f"Invalid state '{state}'. Valid: {sorted(EPIC_STATES)}"
            err = _validate_transition(ed["state"], state, VALID_EPIC_TRANSITIONS)
            if err:
                return err
            updates.append("state = ?")
            params.append(state)

        if title is not None:
            updates.append("title = ?")
            params.append(title)

        if branch is not None:
            updates.append("branch = ?")
            params.append(branch)

        if pr_number is not None:
            updates.append("pr_number = ?")
            params.append(pr_number)

        if persistent is not None:
            updates.append("persistent = ?")
            params.append(int(persistent))

        if not updates:
            return "No fields to update."

        params.append(epic_id)
        conn.execute(
            f"UPDATE epics SET {', '.join(updates)} WHERE id = ?", params
        )
        conn.commit()

        updated = conn.execute("SELECT * FROM epics WHERE id = ?", (epic_id,)).fetchone()
        return json.dumps(_epic_to_dict(updated), indent=2)
    finally:
        conn.close()


@mcp.tool()
async def pm_update_task(
    story_id: str,
    task_id: str,
    state: str | None = None,
    title: str | None = None,
    force: bool = False,
) -> str:
    """Update a task's state or title within a story.

    Args:
        story_id: The story containing the task.
        task_id: The task ID (e.g., 't1').
        state: New task state ('todo', 'in-progress', 'done', 'blocked', 'skipped').
        title: New task title.
        force: Skip state validation.
    """
    conn = _get_db()
    try:
        task = conn.execute(
            "SELECT * FROM tasks WHERE story_id = ? AND id = ?", (story_id, task_id)
        ).fetchone()
        if not task:
            return f"Task '{task_id}' not found in story '{story_id}'."

        updates = []
        params: list = []

        if state is not None:
            if state not in TASK_STATES:
                return f"Invalid state '{state}'. Valid: {sorted(TASK_STATES)}"
            updates.append("state = ?")
            params.append(state)

        if title is not None:
            updates.append("title = ?")
            params.append(title)

        if not updates:
            return "No fields to update."

        params.extend([story_id, task_id])
        conn.execute(
            f"UPDATE tasks SET {', '.join(updates)} WHERE story_id = ? AND id = ?", params
        )
        conn.commit()

        updated = conn.execute(
            "SELECT * FROM tasks WHERE story_id = ? AND id = ?", (story_id, task_id)
        ).fetchone()
        return json.dumps(dict(updated), indent=2)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# PM Organize MCP tool
# ---------------------------------------------------------------------------

def _renumber_epic_stories(conn: sqlite3.Connection, epic_id: str) -> None:
    """Assign sequential order_idx values (1, 2, 3...) to all non-archived stories in an epic."""
    rows = conn.execute(
        "SELECT id FROM stories WHERE epic_id = ? AND archived = 0 ORDER BY COALESCE(order_idx, 2147483647), id",
        (epic_id,)
    ).fetchall()
    for i, row in enumerate(rows, start=1):
        conn.execute("UPDATE stories SET order_idx = ? WHERE id = ?", (i, row["id"]))


@mcp.tool()
async def pm_organize(
    mode: str,
    # --- reorder ---
    story_id: str | None = None,
    before_story_id: str | None = None,
    after_story_id: str | None = None,
    ranked: list[str] | None = None,
    # --- cleanup ---
    archive_days: int = 30,
    stale_days: int = 14,
    confirmed: bool = False,
    # --- regroup ---
    proposal: dict | None = None,
    # --- shared ---
    epic_id: str | None = None,
) -> str:
    """Housekeeping tool for backlog management: reorder stories, triage unorganized work, cleanup done items, or regroup stories across epics.

    Args:
        mode: One of 'reorder', 'triage', 'cleanup', 'regroup'.
        story_id: (reorder) The story to move.
        before_story_id: (reorder) Place story_id immediately before this story.
        after_story_id: (reorder) Place story_id immediately after this story.
        ranked: (reorder) Full ordered list of story IDs for bulk ranking.
        archive_days: (cleanup) Archive done stories older than N days (default 30).
        stale_days: (cleanup) Surface in-progress stories older than N days (default 14).
        confirmed: (cleanup/regroup) If True, commit destructive changes.
        proposal: (regroup Phase 2) The proposal dict returned by Phase 1.
        epic_id: Scope triage/regroup to a single epic; required for reorder when using anchor params.
    """
    valid_modes = {"reorder", "triage", "cleanup", "regroup"}
    if mode not in valid_modes:
        return f"Invalid mode '{mode}'. Valid modes: {sorted(valid_modes)}"

    conn = _get_db()
    try:
        _ensure_order_idx_column(conn)

        # ---------------------------------------------------------------
        # Mode: reorder
        # ---------------------------------------------------------------
        if mode == "reorder":
            # Bulk ranking
            if ranked is not None:
                if not ranked:
                    return "ranked list is empty."
                unknowns = []
                for i, sid in enumerate(ranked, start=1):
                    row = conn.execute("SELECT id FROM stories WHERE id = ?", (sid,)).fetchone()
                    if not row:
                        unknowns.append(sid)
                        continue
                    conn.execute("UPDATE stories SET order_idx = ? WHERE id = ?", (i, sid))
                conn.commit()
                warnings = [f"Unknown story IDs skipped: {unknowns}"] if unknowns else []
                # Return affected epic's stories
                first_known = next((sid for sid in ranked if sid not in unknowns), None)
                if first_known:
                    epic_row = conn.execute("SELECT epic_id FROM stories WHERE id = ?", (first_known,)).fetchone()
                    target_epic = epic_row["epic_id"] if epic_row else None
                else:
                    target_epic = None
                result_stories = []
                if target_epic:
                    rows = conn.execute(
                        "SELECT id, title, state, order_idx FROM stories WHERE epic_id = ? AND archived = 0 ORDER BY COALESCE(order_idx, 2147483647), id",
                        (target_epic,)
                    ).fetchall()
                    result_stories = [dict(r) for r in rows]
                return json.dumps({"mode": "reorder", "warnings": warnings, "stories": result_stories}, indent=2)

            # Single-story placement
            if not story_id:
                return "Provide story_id (with before_story_id or after_story_id) or ranked."
            if before_story_id and after_story_id:
                return "Provide either before_story_id or after_story_id, not both."
            if not before_story_id and not after_story_id:
                return "Provide before_story_id or after_story_id when using story_id."

            anchor_id = before_story_id or after_story_id
            story = conn.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()
            if not story:
                return f"Story '{story_id}' not found."
            anchor = conn.execute("SELECT * FROM stories WHERE id = ?", (anchor_id,)).fetchone()
            if not anchor:
                return f"Anchor story '{anchor_id}' not found."
            if story["epic_id"] != anchor["epic_id"]:
                return f"story_id and anchor must be in the same epic (got '{story['epic_id']}' and '{anchor['epic_id']}')."

            target_epic = story["epic_id"]

            # Ensure all stories in epic have order_idx assigned
            has_nulls = conn.execute(
                "SELECT COUNT(*) FROM stories WHERE epic_id = ? AND archived = 0 AND order_idx IS NULL",
                (target_epic,)
            ).fetchone()[0]
            if has_nulls:
                _renumber_epic_stories(conn, target_epic)
                conn.commit()

            anchor_row = conn.execute("SELECT order_idx FROM stories WHERE id = ?", (anchor_id,)).fetchone()
            anchor_idx = anchor_row["order_idx"]

            if before_story_id:
                new_idx = anchor_idx - 1
            else:
                new_idx = anchor_idx + 1

            conn.execute("UPDATE stories SET order_idx = ? WHERE id = ?", (new_idx, story_id))
            conn.commit()

            # Check for collision (another story has the same order_idx)
            collision = conn.execute(
                "SELECT COUNT(*) FROM stories WHERE epic_id = ? AND archived = 0 AND order_idx = ? AND id != ?",
                (target_epic, new_idx, story_id)
            ).fetchone()[0]
            if collision:
                _renumber_epic_stories(conn, target_epic)
                conn.commit()

            rows = conn.execute(
                "SELECT id, title, state, order_idx FROM stories WHERE epic_id = ? AND archived = 0 ORDER BY COALESCE(order_idx, 2147483647), id",
                (target_epic,)
            ).fetchall()
            return json.dumps({"mode": "reorder", "epic_id": target_epic, "stories": [dict(r) for r in rows]}, indent=2)

        # ---------------------------------------------------------------
        # Mode: triage
        # ---------------------------------------------------------------
        if mode == "triage":
            epic_filter = " AND s.epic_id = ?" if epic_id else ""
            params_epic: list = [epic_id] if epic_id else []

            # Backlog stories
            backlog_rows = conn.execute(
                f"SELECT id, title, state, agent FROM stories s WHERE s.epic_id = 'epic-backlog' AND s.archived = 0{' AND s.epic_id = ?' if epic_id else ''}",
                [epic_id] if epic_id else []
            ).fetchall()
            backlog_stories = [dict(r) for r in backlog_rows]

            # Unassigned stories (no agent)
            unassigned_rows = conn.execute(
                f"SELECT id, title, state, epic_id FROM stories s WHERE s.agent IS NULL AND s.archived = 0{epic_filter}",
                params_epic
            ).fetchall()
            unassigned_stories = [dict(r) for r in unassigned_rows]

            # Draft stories with no tasks
            draft_rows = conn.execute(
                f"SELECT s.id, s.title, s.epic_id FROM stories s WHERE s.state = 'draft' AND s.archived = 0{epic_filter}",
                params_epic
            ).fetchall()
            draft_without_tasks = []
            for row in draft_rows:
                task_count = conn.execute(
                    "SELECT COUNT(*) FROM tasks WHERE story_id = ?", (row["id"],)
                ).fetchone()[0]
                if task_count == 0:
                    draft_without_tasks.append(dict(row))

            # Clustering proposal for backlog stories
            backlog_titles = [s["title"] for s in backlog_stories]
            clustering_proposal: dict = {}
            if backlog_titles:
                open_stories_rows = conn.execute(
                    "SELECT id, title FROM stories WHERE state NOT IN ('done', 'shipped') AND archived = 0"
                ).fetchall()
                existing = [{"id": r["id"], "title": r["title"]} for r in open_stories_rows]
                clustering_proposal = _group_items(backlog_titles, existing)

            # Suggested moves: compare backlog story keywords against non-backlog epic titles
            suggested_moves = []
            non_backlog_epics = conn.execute(
                "SELECT id, title FROM epics WHERE id != 'epic-backlog' AND state = 'active'"
            ).fetchall()
            for story in backlog_stories:
                story_kw = _tokenize(story["title"])
                best_score = 0.0
                best_epic = None
                for epic_row in non_backlog_epics:
                    epic_kw = _tokenize(epic_row["title"])
                    score = _jaccard(story_kw, epic_kw)
                    if score > 0.3 and score > best_score:
                        best_score = score
                        best_epic = epic_row["id"]
                if best_epic:
                    suggested_moves.append({
                        "story_id": story["id"],
                        "story_title": story["title"],
                        "suggested_epic_id": best_epic,
                        "score": round(best_score, 2),
                        "reason": "keyword match",
                    })

            return json.dumps({
                "mode": "triage",
                "backlog_stories": backlog_stories,
                "unassigned_stories": unassigned_stories,
                "draft_without_tasks": draft_without_tasks,
                "clustering_proposal": clustering_proposal,
                "suggested_moves": suggested_moves,
                "instructions": "Use pm_update_story(move_to_epic=...) or pm_plan_items to act on these.",
            }, indent=2)

        # ---------------------------------------------------------------
        # Mode: cleanup
        # ---------------------------------------------------------------
        if mode == "cleanup":
            if archive_days < 1:
                return "archive_days must be >= 1."
            if stale_days < 1:
                return "stale_days must be >= 1."

            now = datetime.utcnow()

            # Compute cutoff timestamps
            from datetime import timedelta
            archive_cutoff = (now - timedelta(days=archive_days)).isoformat()
            stale_cutoff = (now - timedelta(days=stale_days)).isoformat()

            # Stories to archive: terminal state, not yet archived, completed before cutoff
            would_archive_rows = conn.execute(
                """SELECT id, title, state, epic_id, completed_at
                   FROM stories
                   WHERE state IN ('done', 'shipped') AND archived = 0
                   AND completed_at IS NOT NULL AND completed_at < ?""",
                (archive_cutoff,)
            ).fetchall()
            would_archive = [dict(r) for r in would_archive_rows]

            # Epics to close: active, non-persistent, all stories archived
            active_non_persistent = conn.execute(
                "SELECT id, title FROM epics WHERE state = 'active' AND persistent = 0"
            ).fetchall()
            would_close = []
            for ep in active_non_persistent:
                active_count = conn.execute(
                    "SELECT COUNT(*) FROM stories WHERE epic_id = ? AND archived = 0",
                    (ep["id"],)
                ).fetchone()[0]
                if active_count == 0:
                    would_close.append({"id": ep["id"], "title": ep["title"]})

            # Stale in-progress stories (read-only)
            stale_rows = conn.execute(
                """SELECT id, title, epic_id, started_at
                   FROM stories
                   WHERE state = 'in-progress' AND archived = 0
                   AND started_at IS NOT NULL AND started_at < ?""",
                (stale_cutoff,)
            ).fetchall()
            stale_stories = [dict(r) for r in stale_rows]

            # Task/story mismatches: task in-progress but story not in-progress (read-only)
            mismatch_rows = conn.execute(
                """SELECT t.id as task_id, t.story_id, t.title as task_title,
                          s.state as story_state, s.title as story_title
                   FROM tasks t
                   JOIN stories s ON t.story_id = s.id
                   WHERE t.state = 'in-progress' AND s.state != 'in-progress' AND s.archived = 0"""
            ).fetchall()
            task_mismatches = [dict(r) for r in mismatch_rows]

            if not confirmed:
                return json.dumps({
                    "mode": "cleanup",
                    "dry_run": True,
                    "would_archive_stories": would_archive,
                    "would_close_epics": would_close,
                    "stale_stories": stale_stories,
                    "task_mismatches": task_mismatches,
                }, indent=2)

            # Commit
            archived_ids = [r["id"] for r in would_archive]
            for sid in archived_ids:
                conn.execute("UPDATE stories SET archived = 1 WHERE id = ?", (sid,))

            closed_epic_ids = [ep["id"] for ep in would_close]
            for eid in closed_epic_ids:
                # Re-check all stories still archived before closing
                remaining = conn.execute(
                    "SELECT COUNT(*) FROM stories WHERE epic_id = ? AND archived = 0", (eid,)
                ).fetchone()[0]
                if remaining == 0:
                    conn.execute("UPDATE epics SET state = 'done' WHERE id = ?", (eid,))

            conn.commit()
            return json.dumps({
                "mode": "cleanup",
                "dry_run": False,
                "archived_stories": archived_ids,
                "closed_epics": closed_epic_ids,
                "stale_stories": stale_stories,
                "task_mismatches": task_mismatches,
            }, indent=2)

        # ---------------------------------------------------------------
        # Mode: regroup
        # ---------------------------------------------------------------
        if mode == "regroup":
            if not confirmed:
                # Phase 1: analyze and propose
                epic_filter_sql = " AND s.epic_id = ?" if epic_id else ""
                params_r: list = [epic_id] if epic_id else []

                active_stories = conn.execute(
                    f"SELECT id, title, epic_id FROM stories s WHERE s.archived = 0{epic_filter_sql}",
                    params_r
                ).fetchall()

                titles = [r["title"] for r in active_stories]
                story_map = {r["title"]: r for r in active_stories}

                if not titles:
                    return json.dumps({"mode": "regroup", "phase": "proposal", "moves": [], "new_epics": [], "no_change": []})

                open_stories_list = [{"id": r["id"], "title": r["title"]} for r in active_stories]
                clustering = _group_items(titles, open_stories_list)

                existing_epics = conn.execute(
                    "SELECT id, title FROM epics WHERE state = 'active'"
                ).fetchall()

                moves = []
                new_epics_proposal = []
                no_change = []

                for cluster in clustering.get("proposed_stories", []):
                    cluster_title = cluster["title"]
                    cluster_kw = _tokenize(cluster_title)

                    # Find all story IDs in this cluster (title + tasks collapsed back)
                    cluster_story_ids = []
                    all_cluster_titles = [cluster_title] + cluster.get("tasks", [])
                    for ctitle in all_cluster_titles:
                        row = story_map.get(ctitle)
                        if row:
                            cluster_story_ids.append(row["id"])

                    if not cluster_story_ids:
                        continue

                    # Compare against existing epic titles
                    best_score = 0.0
                    best_epic_id = None
                    best_epic_title = None
                    for ep in existing_epics:
                        ep_kw = _tokenize(ep["title"])
                        score = _jaccard(cluster_kw, ep_kw)
                        if score > 0.3 and score > best_score:
                            best_score = score
                            best_epic_id = ep["id"]
                            best_epic_title = ep["title"]

                    for sid in cluster_story_ids:
                        story_row = conn.execute("SELECT id, epic_id FROM stories WHERE id = ?", (sid,)).fetchone()
                        if not story_row:
                            continue
                        current_epic = story_row["epic_id"]

                        if best_epic_id and best_epic_id != current_epic:
                            moves.append({
                                "story_id": sid,
                                "from_epic": current_epic,
                                "to_epic": best_epic_id,
                                "to_epic_title": best_epic_title,
                                "score": round(best_score, 2),
                            })
                        elif not best_epic_id:
                            # Propose new epic
                            existing_new = next(
                                (ne for ne in new_epics_proposal if ne.get("_cluster_title") == cluster_title),
                                None
                            )
                            if not existing_new:
                                new_epics_proposal.append({
                                    "_cluster_title": cluster_title,
                                    "title": cluster_title,
                                    "story_ids": cluster_story_ids,
                                })
                        else:
                            no_change.append({"story_id": sid, "epic_id": current_epic})

                # Clean internal field from new_epics_proposal
                clean_new_epics = [
                    {"title": ne["title"], "story_ids": ne["story_ids"]}
                    for ne in new_epics_proposal
                ]

                return json.dumps({
                    "mode": "regroup",
                    "phase": "proposal",
                    "moves": moves,
                    "new_epics": clean_new_epics,
                    "no_change": no_change,
                    "instructions": (
                        "Review the proposal, then call pm_organize(mode='regroup', confirmed=True, proposal=<this>) "
                        "to commit. You may modify the proposal before passing it back."
                    ),
                }, indent=2)

            # Phase 2: commit
            if not proposal:
                return "Pass the proposal dict from Phase 1 when confirmed=True."

            moved = []
            skipped = []
            created_epics = []

            # Create new epics first
            new_epic_id_map: dict[str, str] = {}  # title → new epic id
            for ne in proposal.get("new_epics", []):
                new_title = ne.get("title", "")
                if not new_title:
                    continue
                new_eid = _next_id(conn, "epics", "epic-")
                conn.execute(
                    "INSERT INTO epics (id, title, branch, persistent, state) VALUES (?, ?, NULL, 0, 'active')",
                    (new_eid, new_title)
                )
                created_epics.append({"id": new_eid, "title": new_title})
                new_epic_id_map[new_title] = new_eid

                # Move stories from this new_epic entry
                for sid in ne.get("story_ids", []):
                    story_row = conn.execute("SELECT id FROM stories WHERE id = ?", (sid,)).fetchone()
                    if not story_row:
                        skipped.append({"story_id": sid, "reason": "story no longer exists"})
                        continue
                    conn.execute("UPDATE stories SET epic_id = ? WHERE id = ?", (new_eid, sid))
                    moved.append({"story_id": sid, "to_epic": new_eid})

            # Apply existing-epic moves
            for move in proposal.get("moves", []):
                sid = move.get("story_id")
                from_epic = move.get("from_epic")
                to_epic = move.get("to_epic")
                if not sid or not to_epic:
                    continue
                story_row = conn.execute("SELECT id, epic_id FROM stories WHERE id = ?", (sid,)).fetchone()
                if not story_row:
                    skipped.append({"story_id": sid, "reason": "story no longer exists"})
                    continue
                if story_row["epic_id"] != from_epic:
                    skipped.append({"story_id": sid, "reason": f"epic changed (now {story_row['epic_id']})"})
                    continue
                epic_exists = conn.execute("SELECT id FROM epics WHERE id = ?", (to_epic,)).fetchone()
                if not epic_exists:
                    skipped.append({"story_id": sid, "reason": f"target epic '{to_epic}' not found"})
                    continue
                conn.execute("UPDATE stories SET epic_id = ? WHERE id = ?", (to_epic, sid))
                moved.append({"story_id": sid, "to_epic": to_epic})

            conn.commit()
            return json.dumps({
                "mode": "regroup",
                "phase": "committed",
                "moved": moved,
                "created_epics": created_epics,
                "skipped": skipped,
            }, indent=2)

        return f"Unhandled mode '{mode}'."
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# PM Analytics MCP tools (3 tools)
# ---------------------------------------------------------------------------

@mcp.tool()
async def pm_wip(epic_id: str | None = None) -> str:
    """Show work-in-progress: story counts by state, blocked items, and agent distribution.

    Args:
        epic_id: Optional epic ID to scope WIP to a single epic.
    """
    conn = _get_db()
    try:
        epic_filter = ""
        params: list = []
        if epic_id:
            epic_filter = " AND epic_id = ?"
            params.append(epic_id)

        # Stories by state
        by_state = conn.execute(
            f"SELECT state, COUNT(*) as cnt FROM stories WHERE archived = 0{epic_filter} GROUP BY state ORDER BY cnt DESC",
            params
        ).fetchall()

        # Agent distribution
        by_agent = conn.execute(
            f"SELECT COALESCE(agent, 'unassigned') as agent, COUNT(*) as cnt FROM stories WHERE archived = 0{epic_filter} GROUP BY agent ORDER BY cnt DESC",
            params
        ).fetchall()

        # Blocked items
        blocked = conn.execute(
            f"SELECT id, title, epic_id FROM stories WHERE state = 'blocked' AND archived = 0{epic_filter}",
            params
        ).fetchall()

        result = {
            "by_state": {r["state"]: r["cnt"] for r in by_state},
            "by_agent": {r["agent"]: r["cnt"] for r in by_agent},
            "total_active": sum(r["cnt"] for r in by_state),
            "blocked": [{"id": r["id"], "title": r["title"], "epic_id": r["epic_id"]} for r in blocked],
        }
        return json.dumps(result, indent=2)
    finally:
        conn.close()


@mcp.tool()
async def pm_cycle_time(epic_id: str | None = None, since: str | None = None) -> str:
    """Show cycle time for completed stories (time from in-progress to done).

    Args:
        epic_id: Optional epic ID filter.
        since: ISO date string to filter stories completed after this date.
    """
    conn = _get_db()
    try:
        conditions = ["archived = 1", "started_at IS NOT NULL", "completed_at IS NOT NULL"]
        params: list = []

        if epic_id:
            conditions.append("epic_id = ?")
            params.append(epic_id)

        if since:
            conditions.append("completed_at >= ?")
            params.append(since)

        where = " AND ".join(conditions)
        stories = conn.execute(
            f"SELECT id, title, started_at, completed_at FROM stories WHERE {where} ORDER BY completed_at DESC",
            params
        ).fetchall()

        items = []
        total_hours = 0
        for s in stories:
            try:
                started = datetime.fromisoformat(s["started_at"])
                completed = datetime.fromisoformat(s["completed_at"])
                delta = completed - started
                hours = delta.total_seconds() / 3600
                items.append({
                    "id": s["id"], "title": s["title"],
                    "started_at": s["started_at"], "completed_at": s["completed_at"],
                    "cycle_hours": round(hours, 1),
                })
                total_hours += hours
            except (ValueError, TypeError):
                items.append({
                    "id": s["id"], "title": s["title"],
                    "started_at": s["started_at"], "completed_at": s["completed_at"],
                    "cycle_hours": "N/A",
                })

        avg_hours = round(total_hours / len(items), 1) if items else 0

        result = {
            "stories": items,
            "count": len(items),
            "average_cycle_hours": avg_hours,
        }
        return json.dumps(result, indent=2)
    finally:
        conn.close()


@mcp.tool()
async def pm_throughput(period: str = "week", lookback: int = 4) -> str:
    """Show completed story throughput over time.

    Args:
        period: Grouping period — 'day', 'week', or 'month' (default: 'week').
        lookback: Number of periods to look back (default: 4).
    """
    conn = _get_db()
    try:
        if period == "day":
            group_expr = "DATE(completed_at)"
            date_format = "%Y-%m-%d"
        elif period == "week":
            group_expr = "strftime('%Y-W%W', completed_at)"
            date_format = "%Y-W%W"
        elif period == "month":
            group_expr = "strftime('%Y-%m', completed_at)"
            date_format = "%Y-%m"
        else:
            return f"Invalid period '{period}'. Valid: day, week, month."

        rows = conn.execute(
            f"""SELECT {group_expr} as period, COUNT(*) as completed
                FROM stories
                WHERE archived = 1 AND completed_at IS NOT NULL
                GROUP BY {group_expr}
                ORDER BY period DESC
                LIMIT ?""",
            (lookback,)
        ).fetchall()

        items = [{"period": r["period"], "completed": r["completed"]} for r in rows]
        total = sum(r["completed"] for r in rows)
        avg = round(total / len(items), 1) if items else 0

        result = {
            "period_type": period,
            "data": items,
            "total": total,
            "average_per_period": avg,
        }
        return json.dumps(result, indent=2)
    finally:
        conn.close()


if __name__ == "__main__":
    import sys

    if "--http" in sys.argv:
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
