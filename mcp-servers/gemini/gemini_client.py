"""Gemini CLI wrapper and file discovery/reading helpers."""

from __future__ import annotations

import asyncio
import fnmatch
import json
import os
from pathlib import Path

from constants import (
    DEFAULT_IGNORE_DIRS,
    DEFAULT_IGNORE_EXTENSIONS,
    DEFAULT_MODEL,
    GEMINI_TIMEOUT,
    SOURCE_EXTENSIONS,
    MAX_CONTEXT_BYTES,
    PROJECT_ROOT,
    AUDIT_PROMPT_PATH,
    DOCUMENTS,
)


class GeminiError(Exception):
    """Base exception for Gemini CLI failures."""


class GeminiTimeoutError(GeminiError):
    """Gemini CLI did not respond within timeout."""


class GeminiCLIError(GeminiError):
    """Gemini CLI exited with non-zero status."""


class GeminiParseError(GeminiError):
    """Gemini CLI returned invalid JSON."""


async def _gemini(prompt: str, *, model: str | None = DEFAULT_MODEL, system_instruction: str | None = None) -> str:
    """Call gemini CLI in headless mode and return the response text."""
    if system_instruction:
        prompt = f"[System: {system_instruction}]\n\n{prompt}"
    cmd: list[str] = ["gemini"]
    if model:
        cmd.extend(["-m", model])
    cmd.extend(["-o", "json"])
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=prompt.encode()), timeout=GEMINI_TIMEOUT
        )
    except asyncio.TimeoutError:
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=3)
        except (ProcessLookupError, asyncio.TimeoutError):
            proc.kill()
            await proc.wait()
        raise GeminiTimeoutError(f"No response after {GEMINI_TIMEOUT}s")
    if proc.returncode != 0:
        err = stderr.decode().strip()
        raise GeminiCLIError(f"Exit {proc.returncode}: {err}")
    try:
        data = json.loads(stdout.decode())
    except json.JSONDecodeError:
        raw = stdout.decode()
        raise GeminiParseError(f"Invalid JSON: {raw[:500]}")
    return data.get("response", "(empty response)")


def _read_doc(key: str) -> str:
    """Read a project document by DOCUMENTS key. Returns content or error note."""
    if key not in DOCUMENTS:
        return f"[Document '{key}' not found]"
    file_path = (PROJECT_ROOT / DOCUMENTS[key]["path"]).resolve()
    if not file_path.is_relative_to(PROJECT_ROOT.resolve()):
        return f"[Document '{key}' outside project root]"
    if not file_path.exists():
        return f"[File not found: {DOCUMENTS[key]['path']}]"
    return file_path.read_text(encoding="utf-8")


def _discover_files(
    paths: list[str] | None = None,
    ignore_patterns: list[str] | None = None,
    root: Path | None = None,
) -> list[Path]:
    """Walk source tree and return matching files sorted by size ascending."""
    _root = root or PROJECT_ROOT
    ignore_patterns = ignore_patterns or []
    roots: list[Path] = []

    if paths:
        for p in paths:
            resolved = (_root / p).resolve()
            if not resolved.exists():
                continue
            if not resolved.is_relative_to(_root.resolve()):
                continue
            roots.append(resolved)
    else:
        roots = [_root]

    found: list[Path] = []
    for walk_root in roots:
        if walk_root.is_file():
            if walk_root.suffix in SOURCE_EXTENSIONS:
                found.append(walk_root)
            continue
        for dirpath, dirnames, filenames in os.walk(walk_root):
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
                rel = str(fpath.relative_to(_root))
                if any(fnmatch.fnmatch(rel, pat) for pat in ignore_patterns):
                    continue
                found.append(fpath)

    # Sort by file size ascending to maximize file count within budget
    found.sort(key=lambda f: f.stat().st_size)
    return found


def _read_files_within_budget(
    file_list: list[Path], budget: int, root: Path | None = None
) -> tuple[str, list[Path]]:
    """Read files until budget is exhausted. Returns (content, skipped_paths)."""
    _root = root or PROJECT_ROOT
    parts: list[str] = []
    total = 0
    skipped: list[Path] = []

    for fpath in file_list:
        try:
            try:
                text = fpath.read_text(encoding="utf-8", errors="strict")
            except UnicodeDecodeError:
                text = "[warning: file contains non-UTF8 bytes]\n" + fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            skipped.append(fpath)
            continue
        size = len(text.encode("utf-8"))
        if total + size > budget:
            skipped.append(fpath)
            continue
        try:
            rel = fpath.relative_to(_root)
        except ValueError:
            rel = fpath
        parts.append(f"### {rel}\n\n{text}\n\n---")
        total += size

    return "\n\n".join(parts), skipped


def _load_audit_context(root: Path | None = None) -> str:
    """Scan project root for requirements/research docs and return concatenated content."""
    _root = root or PROJECT_ROOT
    context_parts: list[str] = []

    for name in ("REQUIREMENTS.md", "ARCHITECTURE.md", "BOUNTY.md"):
        fpath = _root / name
        if fpath.exists():
            context_parts.append(f"### {name}\n\n{fpath.read_text(encoding='utf-8')}")

    research_dir = _root / "project_requirements_and_research"
    if research_dir.is_dir():
        for md_file in sorted(research_dir.glob("*.md")):
            context_parts.append(
                f"### {md_file.relative_to(_root)}\n\n"
                f"{md_file.read_text(encoding='utf-8')}"
            )

    full = "\n\n---\n\n".join(context_parts)
    if len(full.encode("utf-8")) > MAX_CONTEXT_BYTES:
        truncated = full.encode("utf-8")[:MAX_CONTEXT_BYTES].decode("utf-8", errors="ignore")
        last_nl = truncated.rfind("\n")
        if last_nl > 0:
            truncated = truncated[:last_nl]
        full = truncated
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
