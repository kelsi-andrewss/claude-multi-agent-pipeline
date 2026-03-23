#!/usr/bin/env python3
"""Validate hook paths in settings.json — warn about dead references.

Usage: python3 -m hooks.lib.session_reconcile <settings_json_path>
"""
import json, os, sys


def reconcile_hooks(settings_path):
    with open(settings_path) as f:
        cfg = json.load(f)
    hooks = cfg.get("hooks", {})
    home = os.path.expanduser("~")
    dead = []
    for event, entries in hooks.items():
        for entry in entries:
            for hook in entry.get("hooks", []):
                cmd = hook.get("command", "")
                resolved = cmd.replace("~", home, 1) if cmd.startswith("~") else cmd
                if resolved and not os.path.isfile(resolved):
                    dead.append(cmd)
    return dead


def main():
    try:
        settings_path = sys.argv[1]
        dead = reconcile_hooks(settings_path)
        if dead:
            print("=== DEAD HOOK REFERENCES IN settings.json ===")
            for d in dead:
                print(f"  WARN: {d} does not exist on disk")
            print("  Run story cleanup to remove these entries.")
            print("")
    except Exception:
        pass


if __name__ == "__main__":
    main()
