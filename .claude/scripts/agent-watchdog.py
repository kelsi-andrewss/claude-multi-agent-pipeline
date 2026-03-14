#!/usr/bin/env python3
"""Agent watchdog: dual-gate health monitor for background coder agents.

Monitors running agents for stuck patterns (Gate 1) and resource budget
overruns (Gate 2). Both gates must trigger before killing an agent.

Usage:
    python3 agent-watchdog.py \
      --session-id <uuid> \
      --story-ids <comma-separated story IDs> \
      --agent-pids <comma-separated PIDs, same order as story-ids> \
      [--poll-interval 15] \
      [--agent-types <comma-separated: quick-fixer|architect, same order>]

Exit codes: 0 = all normal, 1 = at least one killed, 2 = system error.
Emits JSON to stdout on exit. Logs to stderr during operation.
"""
import argparse
import hashlib
import json
import os
import signal
import sqlite3
import sys
import time
from datetime import datetime

DB_PATH = os.path.expanduser("~/.claude/.claude/run-state.db")

# Gate 1: Pattern detection
REPEAT_THRESHOLD = 5
OSCILLATION_WINDOW = 10
OSCILLATION_THRESHOLD = 3

# Gate 2: Soft budgets (keyed by agent type)
BUDGETS = {
    "quick-fixer": {"max_minutes": 30, "max_tokens": 100_000},
    "architect": {"max_minutes": 90, "max_tokens": 300_000},
}
DEFAULT_BUDGET = BUDGETS["quick-fixer"]

POLL_INTERVAL = 15


def log(msg):
    print(f"WATCHDOG: {msg}", file=sys.stderr)


def emit(obj):
    print(json.dumps(obj))


def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def kill_agent(pid):
    """Send SIGTERM, wait 5s, then SIGKILL if still alive."""
    try:
        pgid = os.getpgid(pid)
        is_group_leader = pgid == pid
    except (ProcessLookupError, PermissionError):
        return

    try:
        if is_group_leader:
            os.killpg(pgid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return

    for _ in range(10):
        time.sleep(0.5)
        if not pid_alive(pid):
            return

    try:
        if is_group_leader:
            os.killpg(pgid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def extract_tool_call(lines):
    """Extract the most recent tool call from agent output lines.

    Parses conservatively — returns None if nothing recognizable is found.
    """
    for line in reversed(lines):
        line = line.strip()
        # Look for tool use patterns in Claude Code output
        if "tool_use" in line or "Tool:" in line or "invoke" in line:
            return line
        # Look for common tool call patterns
        if line.startswith(("Read(", "Edit(", "Write(", "Bash(", "Grep(", "Glob(")):
            return line
    return None


def hash_tool_call(tool_call_str):
    """MD5 hash of tool call string, truncated to 12 chars."""
    return hashlib.md5(tool_call_str.encode()).hexdigest()[:12]


def check_oscillation(hash_history):
    """Check for A-B-A-B alternating pattern in recent hash history."""
    window = hash_history[-OSCILLATION_WINDOW:]
    if len(window) < 4:
        return False

    alternation_count = 0
    for i in range(2, len(window)):
        if window[i] == window[i - 2] and window[i] != window[i - 1]:
            alternation_count += 1

    return alternation_count >= OSCILLATION_THRESHOLD


def upsert_heartbeat(cursor, story_id, agent_id, tool_call, tool_hash, repeat_count, token_estimate):
    """Upsert a heartbeat row for this story_id."""
    existing = cursor.execute(
        "SELECT id FROM agent_heartbeats WHERE story_id=?", (story_id,)
    ).fetchone()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if existing:
        cursor.execute(
            "UPDATE agent_heartbeats SET agent_id=?, last_tool_call=?, "
            "tool_call_hash=?, repeat_count=?, token_estimate=?, last_heartbeat=? "
            "WHERE story_id=?",
            (agent_id, tool_call, tool_hash, repeat_count, token_estimate, now, story_id),
        )
    else:
        cursor.execute(
            "INSERT INTO agent_heartbeats (story_id, agent_id, last_tool_call, "
            "tool_call_hash, repeat_count, token_estimate, last_heartbeat) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (story_id, agent_id, tool_call, tool_hash, repeat_count, token_estimate, now),
        )


def record_kill(cursor, story_id, reason):
    """Mark heartbeat as killed and update story_executions if present."""
    cursor.execute(
        "UPDATE agent_heartbeats SET last_tool_call=? WHERE story_id=?",
        (f"KILLED:{reason}", story_id),
    )
    cursor.execute(
        "UPDATE story_executions SET step='blocked', result_summary=? "
        "WHERE story_id=? AND step NOT IN ('done', 'blocked')",
        (f"Watchdog killed: {reason}", story_id),
    )


def main():
    parser = argparse.ArgumentParser(description="Dual-gate agent health monitor")
    parser.add_argument("--session-id", required=True, help="Session UUID")
    parser.add_argument("--story-ids", required=True, help="Comma-separated story IDs")
    parser.add_argument("--agent-pids", required=True, help="Comma-separated PIDs")
    parser.add_argument("--poll-interval", type=int, default=POLL_INTERVAL, help="Seconds between polls")
    parser.add_argument("--agent-types", default=None, help="Comma-separated agent types")
    args = parser.parse_args()

    story_ids = [s.strip() for s in args.story_ids.split(",")]
    pids = [int(p.strip()) for p in args.agent_pids.split(",")]

    if len(story_ids) != len(pids):
        emit({"status": "error", "error": "story-ids and agent-pids must have the same count"})
        sys.exit(2)

    agent_types = None
    if args.agent_types:
        agent_types = [t.strip() for t in args.agent_types.split(",")]
        if len(agent_types) != len(story_ids):
            emit({"status": "error", "error": "agent-types must match story-ids count"})
            sys.exit(2)

    # Build tracking dict
    tracking = {}
    for i, story_id in enumerate(story_ids):
        agent_type = agent_types[i] if agent_types else "quick-fixer"
        budget = BUDGETS.get(agent_type, DEFAULT_BUDGET)
        tracking[story_id] = {
            "pid": pids[i],
            "agent_type": agent_type,
            "budget": budget,
            "start_time": time.time(),
            "hash_history": [],
            "last_hash": None,
            "repeat_count": 0,
        }

    killed_agents = {}
    completed_normally = []
    shutting_down = False

    def handle_signal(signum, frame):
        nonlocal shutting_down
        shutting_down = True
        log(f"Received signal {signum}, shutting down gracefully")

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Connect to DB
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
    except sqlite3.Error as e:
        emit({"status": "error", "error": f"Cannot open run-state.db: {e}"})
        sys.exit(2)

    poll_interval = args.poll_interval
    log(f"Monitoring {len(tracking)} agents, poll interval {poll_interval}s")

    try:
        while tracking and not shutting_down:
            dead_stories = []

            for story_id, info in tracking.items():
                pid = info["pid"]

                # Check if PID is still alive
                if not pid_alive(pid):
                    dead_stories.append(story_id)
                    if story_id not in killed_agents:
                        completed_normally.append(story_id)
                    continue

                # Read agent output file
                output_path = f"/tmp/coder-output-{story_id}.log"
                try:
                    with open(output_path, "r") as f:
                        lines = f.readlines()
                        last_lines = lines[-50:] if len(lines) > 50 else lines
                except (FileNotFoundError, PermissionError):
                    continue

                # Extract tool call
                tool_call = extract_tool_call(last_lines)
                if not tool_call:
                    # Update token estimate even without tool call
                    try:
                        file_size = os.path.getsize(output_path)
                        info["token_estimate"] = file_size // 4
                    except OSError:
                        pass
                    continue

                current_hash = hash_tool_call(tool_call)
                info["hash_history"].append(current_hash)

                # Token estimate from file size
                try:
                    file_size = os.path.getsize(output_path)
                    token_estimate = file_size // 4
                except OSError:
                    token_estimate = 0

                # Update repeat count
                if current_hash == info["last_hash"]:
                    info["repeat_count"] += 1
                else:
                    info["repeat_count"] = 1
                    info["last_hash"] = current_hash

                # Upsert heartbeat
                upsert_heartbeat(
                    cursor, story_id, None, tool_call, current_hash,
                    info["repeat_count"], token_estimate,
                )
                conn.commit()

                # Gate 1: Pattern detection
                gate1_stuck = info["repeat_count"] >= REPEAT_THRESHOLD
                gate1_oscillating = check_oscillation(info["hash_history"])
                gate1_triggered = gate1_stuck or gate1_oscillating

                # Gate 2: Resource budget
                elapsed_minutes = (time.time() - info["start_time"]) / 60
                budget = info["budget"]
                gate2_time = elapsed_minutes > budget["max_minutes"]
                gate2_tokens = token_estimate > budget["max_tokens"]
                gate2_exceeded = gate2_time or gate2_tokens
                budget_fraction = max(
                    elapsed_minutes / budget["max_minutes"],
                    token_estimate / budget["max_tokens"] if budget["max_tokens"] > 0 else 0,
                )
                gate2_half = budget_fraction >= 0.5

                # Dual-gate kill decision
                should_kill = False
                reason_parts = []

                if gate1_triggered and gate2_half:
                    should_kill = True
                    g1_detail = f"stuck ({tool_call[:40]}... x{info['repeat_count']})" if gate1_stuck else "oscillating pattern"
                    reason_parts.append(g1_detail)
                    reason_parts.append(f"{budget_fraction * 100:.0f}% budget elapsed")

                if gate2_exceeded and info["repeat_count"] >= 2:
                    should_kill = True
                    g2_detail = []
                    if gate2_time:
                        g2_detail.append(f"time {elapsed_minutes:.0f}m > {budget['max_minutes']}m")
                    if gate2_tokens:
                        g2_detail.append(f"tokens {token_estimate} > {budget['max_tokens']}")
                    reason_parts.append(" + ".join(g2_detail))
                    if info["repeat_count"] >= 2 and not gate1_triggered:
                        reason_parts.append(f"repeat_count={info['repeat_count']}")

                if should_kill:
                    reason = " + ".join(reason_parts)
                    log(f"Killing {story_id} agent (PID={pid}) -- reason: {reason}")
                    record_kill(cursor, story_id, reason)
                    conn.commit()
                    kill_agent(pid)
                    killed_agents[story_id] = reason
                    dead_stories.append(story_id)

            # Remove dead stories from tracking
            for story_id in dead_stories:
                tracking.pop(story_id, None)

            if tracking and not shutting_down:
                time.sleep(poll_interval)

    finally:
        # Clean up heartbeat rows for monitored stories
        all_stories = list(killed_agents.keys()) + completed_normally
        for story_id in all_stories:
            try:
                cursor.execute("DELETE FROM agent_heartbeats WHERE story_id=?", (story_id,))
            except sqlite3.Error:
                pass
        try:
            conn.commit()
            conn.close()
        except sqlite3.Error:
            pass

    # Emit result
    result = {
        "status": "success",
        "killed": list(killed_agents.keys()),
        "killed_reasons": killed_agents,
        "completed_normally": completed_normally,
        "total_monitored": len(killed_agents) + len(completed_normally),
    }

    emit(result)
    sys.exit(1 if killed_agents else 0)


if __name__ == "__main__":
    main()
