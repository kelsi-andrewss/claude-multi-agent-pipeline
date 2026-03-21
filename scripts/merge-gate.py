#!/usr/bin/env python3
"""Merge gate: cherry-pick test commits, run tests, classify failures.

Usage:
    python3 merge-gate.py \\
      --merge-candidate <worktree-path> \\
      --story-branch <name> \\
      --test-branch <name> \\
      --dev-branch <name> \\
      --test-cmd <command> \\
      --test-files <comma-separated-paths> \\
      [--session-id <uuid>] \\
      [--story-id <story-id>]

Exit codes: 0 = test passed, 1 = test failed, 2 = system error.
Emits a single JSON object on stdout. Debug logging on stderr.
"""
import argparse
import hashlib
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import time

DB_PATH = os.path.expanduser("~/.claude/.claude/run-state.db")

COMPILE_ERROR_PATTERNS = [
    re.compile(r"Cannot find module"),
    re.compile(r"is not a function"),
    re.compile(r"has no exported member"),
    re.compile(r"ImportError"),
    re.compile(r"ModuleNotFoundError"),
    re.compile(r"undefined is not"),
    re.compile(r"TypeError:"),
    re.compile(r"SyntaxError:"),
]

LOGIC_FAILURE_PATTERNS = [
    re.compile(r"Assert(?:ion|tion)Error"),
    re.compile(r"Expected .* to equal"),
    re.compile(r"expected .* but got", re.IGNORECASE),
    re.compile(r"FAIL.*assert", re.IGNORECASE),
    re.compile(r"TimeoutError"),
    re.compile(r"timed out", re.IGNORECASE),
]


def emit(obj):
    print(json.dumps(obj))


def truncate_output(text, max_lines=50):
    if not text:
        return None
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    return "\n".join(lines)


def classify_failure(output):
    has_compile = any(p.search(output) for p in COMPILE_ERROR_PATTERNS)
    has_logic = any(p.search(output) for p in LOGIC_FAILURE_PATTERNS)

    if has_compile:
        return "compile_error"
    if has_logic:
        return "logic_failure"
    return "ambiguous"


def record_merge_result(session_id, story_id, test_passed, classification, test_output,
                        test_file_names=None, acceptance_criteria_hash=None, coverage_pct=None):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")

        for col, col_type in [
            ("test_file_names", "TEXT"),
            ("acceptance_criteria_hash", "TEXT"),
            ("coverage_pct", "REAL"),
        ]:
            try:
                cursor.execute(f"ALTER TABLE merge_results ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass

        existing = cursor.execute(
            "SELECT retry_count FROM merge_results WHERE session_id=? AND story_id=?",
            (session_id, story_id),
        ).fetchone()

        if existing:
            cursor.execute(
                "UPDATE merge_results SET test_passed=?, error_classification=?, "
                "test_output=?, retry_count=retry_count+1, test_file_names=?, "
                "acceptance_criteria_hash=?, coverage_pct=? "
                "WHERE session_id=? AND story_id=?",
                (1 if test_passed else 0, classification, test_output,
                 test_file_names, acceptance_criteria_hash, coverage_pct,
                 session_id, story_id),
            )
        else:
            cursor.execute(
                "INSERT INTO merge_results (session_id, story_id, test_passed, error_classification, "
                "test_output, retry_count, test_file_names, acceptance_criteria_hash, coverage_pct) "
                "VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)",
                (session_id, story_id, 1 if test_passed else 0, classification, test_output,
                 test_file_names, acceptance_criteria_hash, coverage_pct),
            )

        if test_passed:
            cursor.execute(
                "UPDATE merge_results SET merged_at=? WHERE session_id=? AND story_id=?",
                (int(time.time()), session_id, story_id),
            )

        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        print(f"merge-gate: DB write failed: {e}", file=sys.stderr)


COVERAGE_PATTERNS = [
    re.compile(r"Statements\s*:\s*([\d.]+)%", re.IGNORECASE),
    re.compile(r"TOTAL\s+\d+\s+\d+\s+([\d.]+)%"),
    re.compile(r"coverage:\s*([\d.]+)%\s+of\s+statements", re.IGNORECASE),
    re.compile(r"([\d.]+)%\s+coverage", re.IGNORECASE),
    re.compile(r"All files\s*\|\s*([\d.]+)"),
]


def detect_project_type(path):
    if os.path.isfile(os.path.join(path, "pubspec.yaml")):
        return "flutter"
    if os.path.isfile(os.path.join(path, "package.json")):
        return "node_ts"
    if os.path.isfile(os.path.join(path, "Cargo.toml")):
        return "rust"
    if os.path.isfile(os.path.join(path, "go.mod")):
        return "go"
    if any(os.path.isfile(os.path.join(path, f)) for f in ("pyproject.toml", "requirements.txt", "setup.py")):
        return "python"
    return "unknown"


def build_coverage_cmd(project_type, test_cmd, test_files):
    if project_type == "node_ts":
        return ["npx", "c8", "--reporter=text"] + shlex.split(test_cmd) + test_files
    if project_type == "python":
        parts = shlex.split(test_cmd)
        return parts + ["--cov", "--cov-report=term"] + test_files
    if project_type == "flutter":
        return shlex.split(test_cmd) + ["--coverage"] + test_files
    if project_type == "go":
        return shlex.split(test_cmd) + ["-cover"] + test_files
    return None


def parse_coverage_pct(output):
    for p in COVERAGE_PATTERNS:
        m = p.search(output)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                continue
    matches = re.findall(r"([\d.]+)%", output)
    if matches:
        try:
            return float(matches[-1])
        except ValueError:
            pass
    return None


def main():
    parser = argparse.ArgumentParser(description="Merge gate: cherry-pick, test, classify")
    parser.add_argument("--merge-candidate", required=True, help="Path to merge-candidate worktree")
    parser.add_argument("--story-branch", required=True, help="Story branch name")
    parser.add_argument("--test-branch", required=True, help="Test branch name")
    parser.add_argument("--dev-branch", required=True, help="Dev branch name")
    parser.add_argument("--test-cmd", required=True, help="Test command to run")
    parser.add_argument("--test-files", required=True, help="Comma-separated test file paths")
    parser.add_argument("--session-id", default=None, help="Session UUID for DB persistence")
    parser.add_argument("--story-id", default=None, help="Story ID for DB persistence")
    parser.add_argument("--coverage", action="store_true", help="Run coverage after tests pass")
    parser.add_argument("--acceptance-criteria", default=None, help="Acceptance criteria text for hashing")
    parser.add_argument("--test-file-names", default=None, help="Test file names for persistence")
    args = parser.parse_args()

    mc_path = args.merge_candidate

    ac_hash = None
    if args.acceptance_criteria:
        ac_hash = hashlib.sha256(args.acceptance_criteria.encode()).hexdigest()

    db_extras = {
        "test_file_names": args.test_file_names,
        "acceptance_criteria_hash": ac_hash,
        "coverage_pct": None,
    }

    if not os.path.isdir(mc_path):
        emit({"status": "error", "error": f"Merge candidate path does not exist: {mc_path}"})
        sys.exit(2)

    # Step 1: Cherry-pick test commits
    print(f"merge-gate: fetching test commits from origin/{args.test_branch}", file=sys.stderr)
    try:
        log_result = subprocess.run(
            ["git", "-C", mc_path, "log", "--oneline",
             f"origin/{args.test_branch}", "--not", f"origin/{args.dev_branch}",
             "--reverse", "--format=%H"],
            capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        emit({"status": "error", "error": "Timeout fetching test commit list"})
        sys.exit(2)
    except FileNotFoundError:
        emit({"status": "error", "error": "git not available"})
        sys.exit(2)

    test_commits = [h.strip() for h in log_result.stdout.strip().splitlines() if h.strip()]

    if not test_commits:
        emit({"status": "error", "error": "No test commits found on test branch"})
        sys.exit(2)

    print(f"merge-gate: cherry-picking {len(test_commits)} test commit(s)", file=sys.stderr)
    try:
        cp_result = subprocess.run(
            ["git", "-C", mc_path, "cherry-pick"] + test_commits,
            capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        subprocess.run(
            ["git", "-C", mc_path, "cherry-pick", "--abort"],
            capture_output=True, timeout=30,
        )
        emit({"status": "error", "error": "Timeout during cherry-pick"})
        sys.exit(2)

    if cp_result.returncode != 0:
        subprocess.run(
            ["git", "-C", mc_path, "cherry-pick", "--abort"],
            capture_output=True, timeout=30,
        )
        error_output = truncate_output(cp_result.stderr + cp_result.stdout)
        classification = "compile_error"
        result = {
            "status": "success",
            "test_passed": False,
            "error_type": "cherry_pick_conflict",
            "error_output": error_output,
            "classification": classification,
        }
        if args.session_id and args.story_id:
            record_merge_result(args.session_id, args.story_id, False, classification, error_output, **db_extras)
        emit(result)
        sys.exit(1)

    # Step 2: Run the test command
    test_file_list = [f.strip() for f in args.test_files.split(",") if f.strip()]
    cmd_parts = shlex.split(args.test_cmd) + test_file_list

    print(f"merge-gate: running tests: {cmd_parts}", file=sys.stderr)
    try:
        test_result = subprocess.run(
            cmd_parts,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=mc_path,
        )
    except subprocess.TimeoutExpired:
        error_output = truncate_output("Test execution timed out after 300 seconds")
        classification = "logic_failure"
        result = {
            "status": "success",
            "test_passed": False,
            "error_type": "test_failure",
            "error_output": error_output,
            "classification": classification,
        }
        if args.session_id and args.story_id:
            record_merge_result(args.session_id, args.story_id, False, classification, error_output, **db_extras)
        emit(result)
        sys.exit(1)

    combined_output = test_result.stdout + test_result.stderr

    if test_result.returncode == 0:
        result = {
            "status": "success",
            "test_passed": True,
            "error_type": None,
            "error_output": None,
            "classification": None,
            "coverage_pct": None,
        }

        # Step 2b: Run coverage if requested
        if args.coverage:
            project_type = detect_project_type(mc_path)
            cov_cmd = build_coverage_cmd(project_type, args.test_cmd, test_file_list)
            if cov_cmd:
                print(f"merge-gate: running coverage: {cov_cmd}", file=sys.stderr)
                try:
                    cov_result = subprocess.run(
                        cov_cmd, capture_output=True, text=True, timeout=300, cwd=mc_path,
                    )
                    cov_output = cov_result.stdout + cov_result.stderr
                    cov_pct = parse_coverage_pct(cov_output)
                    result["coverage_pct"] = cov_pct
                    db_extras["coverage_pct"] = cov_pct
                    if cov_pct is not None and cov_pct < 60.0:
                        result["coverage_warning"] = f"Coverage {cov_pct:.1f}% below 60% threshold"
                except subprocess.TimeoutExpired:
                    print("merge-gate: coverage collection timed out", file=sys.stderr)

        if args.session_id and args.story_id:
            record_merge_result(args.session_id, args.story_id, True, None, None, **db_extras)
        emit(result)
        sys.exit(0)

    # Step 3: Classify failure
    error_output = truncate_output(combined_output)
    classification = classify_failure(combined_output)

    result = {
        "status": "success",
        "test_passed": False,
        "error_type": "test_failure",
        "error_output": error_output,
        "classification": classification,
        "coverage_pct": None,
    }

    if args.session_id and args.story_id:
        record_merge_result(args.session_id, args.story_id, False, classification, error_output, **db_extras)

    emit(result)
    sys.exit(1)


if __name__ == "__main__":
    main()
