"""Analysis tools: audit, find_bug, gemini_redesign, pm_consistency_check."""

from __future__ import annotations

import json
import os
from pathlib import Path

from constants import (
    DEFAULT_IGNORE_DIRS,
    DEFAULT_REDESIGN_SECTIONS,
    MAX_CODE_BYTES,
    NO_CODE_INSTRUCTION,
    PROJECT_ROOT,
    REDESIGN_SYSTEM_INSTRUCTION,
    VALID_AUDIT_SECTIONS,
    VALID_REDESIGN_SECTIONS,
)
from gemini_client import (
    _discover_files,
    _gemini,
    _load_audit_context,
    _load_audit_prompt,
    _read_files_within_budget,
)


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
    all_files: list[Path] = []

    if paths:
        search_roots = [root / p for p in paths if (root / p).exists()]
    else:
        search_roots = [root]

    if framework == "flutter":
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
        all_files = _discover_files(paths, root=root)

    all_files.sort(key=lambda f: f.stat().st_size if f.exists() else 0)

    content, skipped_paths = _read_files_within_budget(all_files, MAX_CODE_BYTES, root=root)
    skipped_names = [
        str(p.relative_to(root)) if p.is_relative_to(root) else str(p)
        for p in skipped_paths if p.is_absolute()
    ]
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
            ["M3 Theme & Color System", "Navigation & Transitions",
             "Icon Migration (Lucide)", "Animation Opportunities",
             "Platform-Specific Features"]
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


def register(mcp):
    @mcp.tool()
    async def audit(
        paths: list[str] | None = None,
        sections: list[str] | None = None,
        summary_only: bool = False,
        ignore_patterns: list[str] | None = None,
        model: str | None = None,
        project_root: str | None = None,
    ) -> str:
        """Audit source code with Gemini and produce a structured markdown report. Auto-discovers requirements/research docs for completeness checking. Never generates code.

        Args:
            paths: Specific files or directories to audit (default: full project).
            sections: Filter report to specific sections: "quality", "bugs", "completeness", "security".
            summary_only: If True, return only an executive summary.
            ignore_patterns: Glob patterns to exclude files (e.g. "tests/*", "*.generated.*").
            model: Optional Gemini model ID override.
            project_root: Absolute path to the project root to read files from. Defaults to the server's working directory. Pass a worktree path to scope file reads to that worktree.
        """
        _root = Path(project_root).resolve() if project_root else None

        if sections:
            invalid = set(sections) - VALID_AUDIT_SECTIONS
            if invalid:
                return f"Error: invalid section(s): {', '.join(sorted(invalid))}. Valid: {', '.join(sorted(VALID_AUDIT_SECTIONS))}"

        if paths:
            for p in paths:
                resolved = ((_root or PROJECT_ROOT) / p).resolve()
                if not resolved.exists():
                    return f"Error: path not found: {p}"

        files = _discover_files(paths, ignore_patterns, root=_root)
        if not files:
            return "Error: no source files found to audit."

        code_content, skipped = _read_files_within_budget(files, MAX_CODE_BYTES, root=_root)

        audit_context = _load_audit_context(root=_root)
        audit_prompt = _load_audit_prompt()

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

        system_block = (
            f"{NO_CODE_INSTRUCTION}\n\n{audit_prompt}"
            f"{section_instruction}{summary_instruction}"
        )

        prompt_parts = [f"[System: {system_block}]"]

        if audit_context:
            prompt_parts.append(f"## Project Context\n\n{audit_context}")

        prompt_parts.append(f"## Files Under Audit\n\n{code_content}")

        if skipped:
            _display_root = _root or PROJECT_ROOT
            skipped_list = "\n".join(
                f"- {p.relative_to(_display_root)}" if p.is_relative_to(_display_root) else f"- {p}"
                for p in skipped
            )
            prompt_parts.append(f"## Skipped Files (exceeded budget)\n\n{skipped_list}")

        full_prompt = "\n\n".join(prompt_parts)

        report = await _gemini(full_prompt, model=model)

        # Fix: don't write error strings to disk
        if report.startswith("[gemini error") or report.startswith("[gemini parse error"):
            return report

        output_path = (_root or PROJECT_ROOT) / "AUDIT-GEMINI.md"
        output_path.write_text(report, encoding="utf-8")

        return report

    @mcp.tool()
    async def find_bug(
        symptom: str,
        paths: list[str] | None = None,
        model: str | None = None,
        project_root: str | None = None,
    ) -> str:
        """Find the root cause of a bug using Gemini's large context window. Returns a structured diagnosis: root cause, contributing factors, how to confirm, and fix direction. Never generates code.

        Args:
            symptom: Description of the observed bug behavior or error.
            paths: Optional list of files or directories to scope the search. If provided, skips the hypothesis pass and loads only these files.
            model: Optional Gemini model ID override.
            project_root: Absolute path to the project root to read files from. Defaults to the server's working directory. Pass a worktree path to scope file reads to that worktree.
        """
        _root = Path(project_root).resolve() if project_root else None

        FIND_BUG_SYSTEM = (
            "You are a senior debugging engineer performing root cause analysis. "
            + NO_CODE_INSTRUCTION
        )

        audit_context = _load_audit_context(root=_root)
        candidate_paths = paths
        pass1_response = ""

        if not candidate_paths:
            hypothesis_prompt = (
                f"[System: {FIND_BUG_SYSTEM}]\n\n"
                "## Task\n\n"
                "Given the symptom below, identify which source files are most likely involved "
                "and provide a one-sentence root cause hypothesis. "
                "List the file paths relative to the project root, one per line, preceded by '- '.\n\n"
                f"## Symptom\n\n{symptom}"
            )
            if audit_context:
                hypothesis_prompt += f"\n\n## Project Context\n\n{audit_context}"

            pass1_response = await _gemini(hypothesis_prompt, model=model)

            if not pass1_response.startswith("[gemini error"):
                candidate_paths = []
                for line in pass1_response.splitlines():
                    line = line.strip()
                    if line.startswith("- "):
                        candidate = line[2:].strip()
                        if candidate and not candidate.startswith("["):
                            candidate_paths.append(candidate)
                if not candidate_paths:
                    candidate_paths = None

        files = _discover_files(candidate_paths, root=_root)
        if not files:
            files = _discover_files(None, root=_root)

        code_content, skipped = _read_files_within_budget(files, MAX_CODE_BYTES, root=_root)

        diagnosis_system = (
            f"{FIND_BUG_SYSTEM}\n\n"
            "Structure your diagnosis with exactly these four sections:\n"
            "1. **Root cause** — most likely location (file + function/area)\n"
            "2. **Contributing factors** — conditions that make this fail\n"
            "3. **How to confirm** — minimal reproduction step or log to look for\n"
            "4. **Fix direction** — natural language description of the fix"
        )

        prompt_parts = [f"[System: {diagnosis_system}]"]
        prompt_parts.append(f"## Symptom\n\n{symptom}")

        if pass1_response and not pass1_response.startswith("[gemini error"):
            prompt_parts.append(f"## Hypothesis (from initial analysis)\n\n{pass1_response}")

        if audit_context:
            prompt_parts.append(f"## Project Context\n\n{audit_context}")

        prompt_parts.append(f"## Candidate Source Files\n\n{code_content}")

        if skipped:
            _display_root = _root or PROJECT_ROOT
            skipped_list = "\n".join(
                f"- {p.relative_to(_display_root)}" if p.is_relative_to(_display_root) else f"- {p}"
                for p in skipped
            )
            prompt_parts.append(f"## Skipped Files (exceeded budget)\n\n{skipped_list}")

        full_prompt = "\n\n".join(prompt_parts)
        return await _gemini(full_prompt, model=model)

    @mcp.tool()
    async def gemini_redesign(
        path: str | None = None,
        paths: list[str] | None = None,
        sections: list[str] | None = None,
        model: str | None = None,
        output: str | None = None,
        project_root: str | None = None,
    ) -> str:
        """Scan a frontend codebase and produce a structured REDESIGN.md spec using Gemini's large context window. Analyzes theme, icons, navigation, animations, and platform features. Never generates code — writes a design spec for Claude to implement separately.

        Args:
            path: Root of the project to scan (default: PROJECT_ROOT).
            paths: Optional scope narrowing — specific dirs or files within the project.
            sections: Filter to specific sections: "theme", "icons", "navigation", "animations", "platform".
            model: Optional Gemini model ID override.
            output: Override output file path (default: CWD/REDESIGN.md).
            project_root: Absolute path to the project root to read files from. Defaults to the server's working directory. Pass a worktree path to scope file reads to that worktree.
        """
        _root = Path(project_root).resolve() if project_root else None

        if sections:
            invalid = set(sections) - VALID_REDESIGN_SECTIONS
            if invalid:
                return (
                    f"Error: invalid section(s): {', '.join(sorted(invalid))}. "
                    f"Valid: {', '.join(sorted(VALID_REDESIGN_SECTIONS))}"
                )
        active_sections = sections or DEFAULT_REDESIGN_SECTIONS

        scan_root = Path(path).resolve() if path else (_root or PROJECT_ROOT)
        if not scan_root.exists():
            return f"Error: path not found: {path}"

        framework = _detect_framework(scan_root)

        code_context, skipped = _collect_redesign_files(scan_root, paths, framework)
        if not code_context.strip():
            return "Error: no source files found to analyze."

        full_prompt = _build_redesign_prompt(framework, active_sections, code_context, skipped)

        report = await _gemini(full_prompt, model=model)

        # Fix: don't write error strings to disk
        if report.startswith("[gemini error") or report.startswith("[gemini parse error"):
            return report

        output_path = Path(output).resolve() if output else Path.cwd() / "REDESIGN.md"
        output_path.write_text(report, encoding="utf-8")

        file_count = code_context.count("### ")
        section_count = len(active_sections)
        return (
            f"REDESIGN.md written ({section_count} sections, ~{file_count} files scanned). "
            f"Framework detected: {framework}. "
            f"Review it and implement with Claude."
        )

    @mcp.tool()
    async def pm_consistency_check(
        pattern: str,
        paths: list[str] | None = None,
        project_root: str | None = None,
        model: str | None = None,
    ) -> str:
        """Check codebase for violations of a natural-language pattern or convention. Returns structured findings.

        Args:
            pattern: Natural-language description of the convention to check (e.g. "all Firestore writes use writeBatch when touching >1 document").
            paths: Optional scope — specific files or directories to check.
            project_root: Absolute path to the project root. Defaults to the server's working directory.
            model: Optional Gemini model ID override.
        """
        _root = Path(project_root).resolve() if project_root else None

        files = _discover_files(paths, root=_root)
        if not files:
            return json.dumps({"pattern": pattern, "violations": [], "files_checked": 0, "error": "No source files found."})

        code_content, skipped = _read_files_within_budget(files, MAX_CODE_BYTES, root=_root)
        files_checked = code_content.count("### ")

        system_instruction = (
            f"{NO_CODE_INSTRUCTION}\n\n"
            "You are a senior code reviewer checking for violations of a specific pattern or convention. "
            "For each violation found, return a JSON array of objects with these fields:\n"
            '- "file": relative file path\n'
            '- "location": function/class/line area where the violation occurs\n'
            '- "description": what specifically violates the pattern\n'
            '- "fix_direction": how to fix it (in natural language, no code)\n\n'
            "If no violations are found, return an empty JSON array: []\n"
            "Return ONLY valid JSON. No prose, no markdown, no code blocks."
        )

        full_prompt = (
            f"[System: {system_instruction}]\n\n"
            f"## Pattern to Check\n\n{pattern}\n\n"
            f"## Codebase\n\n{code_content}"
        )

        raw = await _gemini(full_prompt, model=model)

        if raw.startswith("[gemini error") or raw.startswith("[gemini parse error"):
            return json.dumps({"pattern": pattern, "violations": [], "files_checked": files_checked, "error": raw})

        try:
            violations = json.loads(raw)
            if not isinstance(violations, list):
                violations = [violations]
        except json.JSONDecodeError:
            return json.dumps({"pattern": pattern, "violations": [], "files_checked": files_checked, "raw_response": raw[:2000]})

        return json.dumps({
            "pattern": pattern,
            "violations": violations,
            "files_checked": files_checked,
        })

    return {
        "audit": audit,
        "find_bug": find_bug,
    }
