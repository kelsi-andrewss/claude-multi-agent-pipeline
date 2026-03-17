#!/usr/bin/env python3
"""Generate a CLAUDE.md conventions file from scout bootstrap JSON output.

Reads explore agent JSON from stdin, emits markdown to stdout.
"""
from __future__ import annotations

import json
import sys


def generate(data: dict) -> str:
    lines: list[str] = []
    project_name = data.get("project_name", "Project")
    lines.append(f"# {project_name} — Conventions")
    lines.append("")

    _emit_languages(lines, data)
    _emit_structure(lines, data)
    _emit_naming(lines, data)
    _emit_error_handling(lines, data)
    _emit_testing(lines, data)
    _emit_imports(lines, data)
    _emit_api(lines, data)
    _emit_database(lines, data)
    _emit_ci_cd(lines, data)

    return "\n".join(lines)


def _emit_languages(lines: list[str], data: dict) -> None:
    languages = data.get("languages", [])
    frameworks = data.get("frameworks", [])
    if not languages and not frameworks:
        return

    lines.append("## Language & Framework")
    lines.append("")

    for lang in languages:
        name = lang.get("name", "Unknown")
        version = lang.get("version")
        primary = lang.get("primary", False)
        suffix = " (primary)" if primary else ""
        ver = f" {version}" if version else ""
        lines.append(f"- {name}{ver}{suffix}")

    for fw in frameworks:
        name = fw.get("name", "Unknown")
        version = fw.get("version", "")
        purpose = fw.get("purpose", "")
        ver = f" {version}" if version else ""
        purp = f" — {purpose}" if purpose else ""
        lines.append(f"- {name}{ver}{purp}")

    lines.append("")


def _emit_structure(lines: list[str], data: dict) -> None:
    structure = data.get("structure")
    if not structure:
        return

    lines.append("## Project Structure")
    lines.append("")

    layout = structure.get("layout")
    pattern = structure.get("pattern")
    if layout:
        lines.append(f"- Layout: {layout}")
    if pattern:
        lines.append(f"- Organization: {pattern}")

    for d in structure.get("key_directories", []):
        path = d.get("path", "")
        purpose = d.get("purpose", "")
        lines.append(f"- `{path}/` — {purpose}")

    lines.append("")


def _emit_naming(lines: list[str], data: dict) -> None:
    naming = data.get("naming")
    if not naming:
        return

    lines.append("## Naming Conventions")
    lines.append("")

    if naming.get("files"):
        lines.append(f"- Files: {naming['files']}")
    if naming.get("functions"):
        lines.append(f"- Functions/methods: {naming['functions']}")
    if naming.get("components"):
        lines.append(f"- Components: {naming['components']}")
    if naming.get("tests"):
        lines.append(f"- Tests: {naming['tests']}")

    lines.append("")


def _emit_error_handling(lines: list[str], data: dict) -> None:
    eh = data.get("error_handling")
    if not eh:
        return

    lines.append("## Error Handling")
    lines.append("")

    pattern = eh.get("pattern")
    details = eh.get("details")
    if pattern:
        lines.append(f"- Pattern: {pattern}")
    if details:
        lines.append(f"- {details}")

    for ex in eh.get("examples", []):
        f = ex.get("file", "")
        p = ex.get("pattern", "")
        lines.append(f"- Example in `{f}`: {p}")

    lines.append("")


def _emit_testing(lines: list[str], data: dict) -> None:
    testing = data.get("testing")
    if not testing:
        return

    lines.append("## Testing")
    lines.append("")

    if testing.get("framework"):
        lines.append(f"- Framework: {testing['framework']}")
    if testing.get("assertion_style"):
        lines.append(f"- Assertions: {testing['assertion_style']}")
    if testing.get("file_pattern"):
        lines.append(f"- File pattern: {testing['file_pattern']}")
    if testing.get("fixture_pattern"):
        lines.append(f"- Fixtures: {testing['fixture_pattern']}")
    if testing.get("coverage_tool"):
        lines.append(f"- Coverage: {testing['coverage_tool']}")

    lines.append("")


def _emit_imports(lines: list[str], data: dict) -> None:
    imports = data.get("imports")
    if not imports:
        return

    lines.append("## Import Patterns")
    lines.append("")

    style = imports.get("style")
    if style:
        lines.append(f"- Style: {style}")

    aliases = imports.get("aliases", {})
    if aliases:
        for alias, target in aliases.items():
            lines.append(f"- Alias: `{alias}` -> `{target}`")

    for pat in imports.get("notable_patterns", []):
        lines.append(f"- {pat}")

    lines.append("")


def _emit_api(lines: list[str], data: dict) -> None:
    api = data.get("api")
    if not api or not api.get("detected"):
        return

    lines.append("## API Patterns")
    lines.append("")

    if api.get("framework"):
        lines.append(f"- Framework: {api['framework']}")
    if api.get("route_pattern"):
        lines.append(f"- Route pattern: {api['route_pattern']}")
    if api.get("auth_pattern"):
        lines.append(f"- Auth: {api['auth_pattern']}")

    for ex in api.get("examples", []):
        f = ex.get("file", "")
        p = ex.get("pattern", "")
        lines.append(f"- Example in `{f}`: {p}")

    lines.append("")


def _emit_database(lines: list[str], data: dict) -> None:
    db = data.get("database")
    if not db or not db.get("detected"):
        return

    lines.append("## Database Patterns")
    lines.append("")

    if db.get("engine"):
        lines.append(f"- Engine: {db['engine']}")
    if db.get("orm"):
        lines.append(f"- ORM: {db['orm']}")
    if db.get("migration_tool"):
        lines.append(f"- Migrations: {db['migration_tool']}")

    lines.append("")


def _emit_ci_cd(lines: list[str], data: dict) -> None:
    ci = data.get("ci_cd")
    if not ci or not ci.get("detected"):
        return

    lines.append("## CI/CD")
    lines.append("")

    if ci.get("platform"):
        lines.append(f"- Platform: {ci['platform']}")
    for tool in ci.get("lint_tools", []):
        lines.append(f"- Lint: {tool}")
    if ci.get("build_tool"):
        lines.append(f"- Build: {ci['build_tool']}")

    lines.append("")


if __name__ == "__main__":
    data = json.load(sys.stdin)
    print(generate(data))
