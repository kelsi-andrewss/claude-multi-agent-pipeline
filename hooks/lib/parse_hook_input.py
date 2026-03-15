#!/usr/bin/env python3
"""Extract fields from Claude Code hook JSON input.

Usage: echo "$INPUT" | python3 hooks/lib/parse_hook_input.py <field>
Fields: file_path, path, prompt, transcript_path, session_id, cwd, command
"""
import json, sys


def main():
    field = sys.argv[1] if len(sys.argv) > 1 else "file_path"
    try:
        d = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    if field in ("file_path", "path"):
        path = d.get("tool_input", {}).get("file_path", "")
        if not path:
            path = d.get("tool_input", {}).get("path", "")
        print(path)
    elif field == "prompt":
        print(d.get("prompt", ""))
    elif field == "command":
        print(d.get("tool_input", {}).get("command", ""))
    else:
        print(d.get(field, ""))


if __name__ == "__main__":
    main()
