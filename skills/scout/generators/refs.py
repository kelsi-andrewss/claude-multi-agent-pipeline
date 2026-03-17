#!/usr/bin/env python3
"""Generate .claude/refs/ markdown files from scout bootstrap JSON output.

Reads explore agent JSON from stdin.
Writes ref files to the directory specified as the first CLI argument.
Prints the list of generated filenames to stdout.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def generate(data: dict, output_dir: Path) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[str] = []

    for pitfall_group in data.get("pitfalls", []):
        category = pitfall_group.get("category", "").strip()
        items = pitfall_group.get("items", [])
        if not category or len(items) < 3:
            continue

        slug = _slugify(category)
        filename = f"pitfalls-{slug}.md"
        filepath = output_dir / filename

        if filepath.exists():
            continue

        lines = [f"# Pitfalls: {category}", ""]
        for item in items:
            lines.append(f"- {item}")
        lines.append("")

        filepath.write_text("\n".join(lines), encoding="utf-8")
        generated.append(filename)

    for pattern_group in data.get("patterns", []):
        category = pattern_group.get("category", "").strip()
        items = pattern_group.get("items", [])
        if not category or len(items) < 2:
            continue

        slug = _slugify(category)
        filename = f"patterns-{slug}.md"
        filepath = output_dir / filename

        if filepath.exists():
            continue

        lines = [f"# Patterns: {category}", ""]
        for item in items:
            name = item.get("name", "")
            desc = item.get("description", "")
            example = item.get("example_file", "")
            lines.append(f"### {name}")
            lines.append("")
            if desc:
                lines.append(desc)
                lines.append("")
            if example:
                lines.append(f"Example: `{example}`")
                lines.append("")

        filepath.write_text("\n".join(lines), encoding="utf-8")
        generated.append(filename)

    return generated


def _slugify(text: str) -> str:
    slug = text.lower().replace(" ", "-").replace("/", "-")
    return "".join(c for c in slug if c.isalnum() or c == "-")[:40]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: refs.py <output_dir>", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(sys.argv[1])
    data = json.load(sys.stdin)
    generated = generate(data, output_dir)
    for f in generated:
        print(f)
