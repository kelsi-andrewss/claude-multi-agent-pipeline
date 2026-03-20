"""Structured event log for system-level telemetry.

Appends JSON events to daily rolling JSONL files in tracking/events/.
Analogous to friction.json and skill-telemetry.jsonl — telemetry output,
not a persistence surface under decision-6.
"""
import json, os, sys
from datetime import datetime, timezone

EVENTS_DIR = os.path.expanduser("~/.claude/tracking/events")

_dir_created = False


def _events_dir():
    global _dir_created
    if not _dir_created:
        os.makedirs(EVENTS_DIR, exist_ok=True)
        _dir_created = True
    return EVENTS_DIR


def _today_file():
    return os.path.join(
        _events_dir(),
        datetime.now(timezone.utc).strftime("%Y-%m-%d") + ".jsonl",
    )


def emit_event(event_type, actor="unknown", ref="", payload=None, session_id=None):
    """Append a structured event to today's JSONL file in tracking/events/.

    Returns the absolute path to the file written, or None on error.
    Never raises -- all errors caught and logged to stderr.
    """
    try:
        event = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "type": event_type,
            "actor": actor,
            "ref": ref,
            "session": session_id if session_id is not None else os.environ.get("CLAUDE_SESSION_ID", ""),
            "payload": payload if payload is not None else {},
        }
        path = _today_file()
        with open(path, "a") as f:
            f.write(json.dumps(event, separators=(",", ":")) + "\n")
        return path
    except Exception as e:
        print(f"event_log: emit_error — {e}", file=sys.stderr)
        return None
