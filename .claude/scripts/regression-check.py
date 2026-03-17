#!/usr/bin/env python3
"""Post-merge regression check: re-verify acceptance criteria from previously merged stories.

Usage:
    python3 regression-check.py \
      --epic-id <epic_id> \
      --just-merged-story-id <story_id> \
      --just-merged-write-files <comma-separated paths> \
      --project-root <path> \
      --dev-branch <branch> \
      --session-id <uuid> \
      --story-manifest '<JSON string>'

The story manifest is a JSON object mapping story IDs to their metadata:
    {
        "story-801": {
            "write_files": ["src/foo.ts", "src/bar.ts"],
            "plan_file": "/path/to/plan.md",
            "acceptance_criteria": "raw text of ## Acceptance criteria section"
        }
    }

Exit codes: 0 = all criteria passed (or only manual skips), 1 = regression detected, 2 = system error.
Emits JSON to stdout.
"""
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys

DB_PATH = os.path.expanduser("~/.claude/.claude/run-state.db")

CRITERION_API = re.compile(
    r"(GET|POST|PUT|DELETE|PATCH)\s+\S+|endpoint|route|returns?\s+\d{3}", re.IGNORECASE
)
CRITERION_CLI = re.compile(r"run\b|execute\b|command.line|^\$\s", re.IGNORECASE | re.MULTILINE)
CRITERION_FILE = re.compile(r"file\s+exists?|generates?\b|creates?\s+.*file", re.IGNORECASE)
CRITERION_MANUAL = re.compile(r"displays?|renders?|shows?|UI|visual", re.IGNORECASE)

CASE_INSENSITIVE_FS = sys.platform == "darwin"


def emit(obj):
    print(json.dumps(obj))


def normalize_path(p):
    p = p.split(":")[0]
    p = p.lstrip("./")
    if CASE_INSENSITIVE_FS:
        p = p.lower()
    return p


def compute_overlap(merged_files, story_files):
    merged_set = {normalize_path(f) for f in merged_files}
    story_set = {normalize_path(f) for f in story_files}
    return merged_set & story_set


def classify_criterion(text):
    if CRITERION_API.search(text):
        return "api"
    if CRITERION_CLI.search(text):
        return "cli"
    if CRITERION_FILE.search(text):
        return "file"
    if CRITERION_MANUAL.search(text):
        return "manual"
    return "manual"


def extract_url(text):
    m = re.search(r"(https?://\S+)", text)
    if m:
        return m.group(1)
    m = re.search(r"(GET|POST|PUT|DELETE|PATCH)\s+(/\S+)", text, re.IGNORECASE)
    if m:
        return f"http://localhost:3000{m.group(2)}"
    return None


def extract_file_path(text, project_root):
    m = re.search(r"file\s+exists?:?\s*(\S+)", text, re.IGNORECASE)
    if m:
        path = m.group(1)
        if not os.path.isabs(path):
            path = os.path.join(project_root, path)
        return path
    m = re.search(r"(?:generates?|creates?)\s+(?:a\s+)?(?:file\s+)?(\S+)", text, re.IGNORECASE)
    if m:
        path = m.group(1)
        if not os.path.isabs(path):
            path = os.path.join(project_root, path)
        return path
    return None


def extract_command(text):
    m = re.search(r"^\$\s+(.+)$", text, re.MULTILINE)
    if m:
        return m.group(1).strip()
    m = re.search(r"(?:run|execute)\s+`([^`]+)`", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def verify_criterion(text, kind, project_root):
    if kind == "manual":
        return "skip_manual", None

    if kind == "api":
        url = extract_url(text)
        if not url:
            return "skip_manual", "Could not extract URL from criterion"
        try:
            result = subprocess.run(
                ["curl", "-sf", "-o", "/dev/null", "-w", "%{http_code}", url],
                capture_output=True, text=True, timeout=30, cwd=project_root,
            )
            status_code = result.stdout.strip()
            if result.returncode == 0 and status_code.startswith("2"):
                return "pass", None
            return "fail", f"curl returned {status_code}"
        except subprocess.TimeoutExpired:
            return "timeout", "curl timed out after 30s"
        except FileNotFoundError:
            return "error", "curl not available"

    if kind == "file":
        path = extract_file_path(text, project_root)
        if not path:
            return "skip_manual", "Could not extract file path from criterion"
        if os.path.exists(path):
            return "pass", None
        return "fail", f"File not found: {path}"

    if kind == "cli":
        cmd = extract_command(text)
        if not cmd:
            return "skip_manual", "Could not extract command from criterion"
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=30, cwd=project_root,
            )
            if result.returncode == 0:
                return "pass", None
            output = (result.stdout + result.stderr).strip()
            return "fail", output[:500] if output else f"exit code {result.returncode}"
        except subprocess.TimeoutExpired:
            return "timeout", "Command timed out after 30s"

    return "skip_manual", None


def parse_criteria(text):
    if not text or not text.strip():
        return []
    lines = text.strip().splitlines()
    criteria = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        cleaned = re.sub(r"^\d+[\.\)]\s*", "", line)
        cleaned = re.sub(r"^[-*]\s*", "", cleaned)
        if cleaned:
            criteria.append(cleaned)
    return criteria


def record_event(conn, session_id, trigger_story, affected_story, epic_id,
                 criterion, result, error_output, overlapping_files):
    conn.execute(
        """INSERT INTO regression_events
           (session_id, trigger_story_id, affected_story_id, epic_id,
            criterion, result, error_output, overlapping_files)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (session_id, trigger_story, affected_story, epic_id,
         criterion, result, error_output, json.dumps(list(overlapping_files))),
    )


def main():
    parser = argparse.ArgumentParser(
        description="Post-merge regression check: re-verify acceptance criteria"
    )
    parser.add_argument("--epic-id", required=True, help="Epic ID")
    parser.add_argument("--just-merged-story-id", required=True, help="Story that just merged")
    parser.add_argument("--just-merged-write-files", required=True,
                        help="Comma-separated write files of the just-merged story")
    parser.add_argument("--project-root", required=True, help="Path to project root")
    parser.add_argument("--dev-branch", required=True, help="Dev branch name")
    parser.add_argument("--session-id", required=True, help="Session UUID for DB writes")
    parser.add_argument("--story-manifest", required=True,
                        help="JSON string: {story_id: {write_files, plan_file, acceptance_criteria}}")
    args = parser.parse_args()

    try:
        manifest = json.loads(args.story_manifest)
    except json.JSONDecodeError as e:
        emit({"status": "error", "error": f"Invalid story manifest JSON: {e}"})
        sys.exit(2)

    merged_files = [f.strip() for f in args.just_merged_write_files.split(",") if f.strip()]

    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
    except sqlite3.Error as e:
        emit({"status": "error", "error": f"Cannot open run-state.db: {e}"})
        sys.exit(2)

    stories_checked = 0
    stories_skipped = 0
    criteria_verified = 0
    criteria_failed = 0
    criteria_manual = 0
    failures = []

    for story_id, data in manifest.items():
        if story_id == args.just_merged_story_id:
            continue

        story_write_files = data.get("write_files", [])
        overlap = compute_overlap(merged_files, story_write_files)

        if not overlap:
            stories_skipped += 1
            continue

        stories_checked += 1
        ac_text = data.get("acceptance_criteria", "")
        criteria = parse_criteria(ac_text)

        if not criteria:
            continue

        for criterion_text in criteria:
            kind = classify_criterion(criterion_text)
            result, error = verify_criterion(criterion_text, kind, args.project_root)

            record_event(conn, args.session_id, args.just_merged_story_id,
                         story_id, args.epic_id, criterion_text, result, error, overlap)

            if result == "pass":
                criteria_verified += 1
            elif result == "skip_manual":
                criteria_manual += 1
            elif result in ("fail", "timeout", "error"):
                criteria_failed += 1
                failures.append({
                    "story_id": story_id,
                    "criterion": criterion_text,
                    "error": error or result,
                    "overlapping_files": sorted(overlap),
                })

    conn.commit()
    conn.close()

    summary = {
        "status": "success",
        "stories_checked": stories_checked,
        "stories_skipped": stories_skipped,
        "criteria_verified": criteria_verified,
        "criteria_failed": criteria_failed,
        "criteria_manual": criteria_manual,
        "failures": failures,
        "regressions_logged": len(failures),
    }

    emit(summary)
    sys.exit(1 if criteria_failed > 0 else 0)


if __name__ == "__main__":
    main()
