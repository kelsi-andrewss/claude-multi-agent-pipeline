"""Shared constants, prompts, and configuration for the Gemini MCP server."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_MODEL = None  # Let gemini CLI use its own model routing

PROJECT_ROOT = Path(os.environ.get("GEMINI_MCP_PROJECT_ROOT", str(Path.cwd())))

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

_KNOWN_DOCUMENTS: dict[str, dict[str, str]] = {
    "claude": {"path": "CLAUDE.md", "description": "Project implementation guide and conventions"},
    "requirements": {"path": "REQUIREMENTS.md", "description": "Full project requirements"},
    "bounty": {"path": "BOUNTY.md", "description": "Bounty spec and deliverables"},
    "architecture": {"path": "ARCHITECTURE.md", "description": "System architecture overview"},
    "roadmap": {"path": "ROADMAP.md", "description": "Development roadmap and milestones"},
    "cost_analysis": {"path": "COST_ANALYSIS.md", "description": "AI cost analysis and token usage"},
    "firestore_schema": {"path": "FIRESTORE_SCHEMA.md", "description": "Firestore database schema"},
    "gemini": {"path": "GEMINI.md", "description": "Gemini integration notes"},
    "audit": {"path": "AUDIT.md", "description": "Codebase audit report"},
}


def _discover_documents() -> dict[str, dict[str, str]]:
    """Discover project documents by scanning PROJECT_ROOT for known files and research dirs."""
    docs: dict[str, dict[str, str]] = {}
    for key, meta in _KNOWN_DOCUMENTS.items():
        if (PROJECT_ROOT / meta["path"]).exists():
            docs[key] = meta
    research_dir = PROJECT_ROOT / "project_requirements_and_research"
    if research_dir.is_dir():
        for md_file in sorted(research_dir.glob("*.md")):
            key = md_file.stem.lower().replace(" ", "_").replace("-", "_")
            if key not in docs:
                docs[key] = {
                    "path": str(md_file.relative_to(PROJECT_ROOT)),
                    "description": f"Research doc: {md_file.stem}",
                }
    return docs


DOCUMENTS: dict[str, dict[str, str]] = _discover_documents()

# ---------------------------------------------------------------------------
# Test analysis prompt
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# PM / SQLite constants
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

# ---------------------------------------------------------------------------
# PM Plan constants
# ---------------------------------------------------------------------------
PLAN_SYSTEM_INSTRUCTION = (
    "You are a senior software engineer. Given the project context and codebase, "
    "produce a concrete implementation plan for the given stories/epics.\n\n"
    "For each story, return:\n"
    '- "story_id": the story ID exactly as given (e.g. "story-293") — required for matching\n'
    '- "agent": one of "quick-fixer" (small fixes/styling), "architect" (new features/refactors), "unit-tester" (tests only)\n'
    '- "write_files": list of file paths this story will modify\n'
    '- "tasks": ordered list of implementation steps as strings\n'
    '- "parallel_group": integer (1=first, 2=after group 1 finishes, etc.)\n'
    '- "depends_on": list of story IDs that must complete first\n\n'
    "Return ONLY valid JSON. No prose, no markdown, no code blocks."
)

# ---------------------------------------------------------------------------
# Knowledge DB constants
# ---------------------------------------------------------------------------
DECISION_STATUSES = {"active", "superseded", "reversed"}
SCOPE_TYPES = {"file", "pattern", "tech"}
PATTERN_CATEGORIES = {"react", "firebase", "css", "konva", "architecture", "general"}
PATTERN_SEVERITIES = {"must", "should", "prefer"}
PATTERN_STATUSES = {"active", "deprecated"}
PITFALLS_DIR = Path.home() / ".claude" / "refs"
PITFALLS_CATEGORY_MAP = {
    "pitfalls-react.md": "react",
    "pitfalls-firebase.md": "firebase",
    "pitfalls-css.md": "css",
    "pitfalls-konva.md": "konva",
}

# ---------------------------------------------------------------------------
# Roadmap constants
# ---------------------------------------------------------------------------
AT_RISK_DAYS_THRESHOLD = 7
AT_RISK_PCT_THRESHOLD = 80
