#!/usr/bin/env python3
"""Trust calibration formatting for session start.

Usage: python3 -m hooks.lib.session_trust <run_state_db_path>
"""
import os, sys


def format_trust(db_path):
    sys.path.insert(0, os.path.expanduser("~/.claude"))
    from hooks.lib.signal_processor import compute_trust_scores, get_trust_level
    report = compute_trust_scores(db_path)
    level = get_trust_level(report)
    overrides = {k: v for k, v in report["domains"].items() if v.get("override")}
    print(
        f"  Trust: {level} (global: {report['global']:.2f}, "
        f"{len(report['domains'])} domains, {len(overrides)} overrides)"
    )
    if overrides:
        for domain, info in overrides.items():
            print(
                f"    Override: {domain}: {info['score']:.2f} "
                f"({info['count']} samples)"
            )
    return level


def main():
    db_path = sys.argv[1]
    try:
        level = format_trust(db_path)
    except Exception as e:
        print(f"  Trust: medium (default — {e})")
        level = "medium"
    print(f"CLAUDE_TRUST_LEVEL={level}")


if __name__ == "__main__":
    main()
