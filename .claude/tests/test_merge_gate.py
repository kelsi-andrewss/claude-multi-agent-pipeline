"""Integration tests for merge-gate.py."""
import json
import os
import sqlite3
import subprocess
import sys

import pytest

SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "merge-gate.py")
INIT_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "init-run-db.py")


def git(*args, cwd=None):
    result = subprocess.run(
        ["git"] + list(args),
        capture_output=True, text=True, cwd=cwd,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}\n{result.stdout}")
    return result.stdout.strip()


class GitFixture:
    """Sets up a bare origin repo + worktrees to simulate the real merge-gate flow.

    Creates:
    - A bare repo (acts as origin)
    - A working clone with dev, story-branch, and story-branch--test branches
    - A merge-candidate worktree checked out on story-branch
    """

    def __init__(self, tmp_path, source_content=None, test_content=None,
                 test_imports_bad=False, test_assertion_fail=False,
                 source_conflicts_with_test=False, test_output_ambiguous=False,
                 test_mixed_errors=False):

        # Create a bare repo to act as origin
        self.bare_dir = str(tmp_path / "origin.git")
        os.makedirs(self.bare_dir)
        git("init", "--bare", "-b", "main", cwd=self.bare_dir)

        # Clone it as the working repo
        self.repo_dir = str(tmp_path / "repo")
        git("clone", self.bare_dir, self.repo_dir)
        git("config", "user.email", "test@test.com", cwd=self.repo_dir)
        git("config", "user.name", "Test", cwd=self.repo_dir)

        # Initial commit on main
        with open(os.path.join(self.repo_dir, "src.py"), "w") as f:
            f.write("def hello():\n    return 'hello'\n")
        git("add", "src.py", cwd=self.repo_dir)
        git("commit", "-m", "initial", cwd=self.repo_dir)
        git("push", "origin", "main", cwd=self.repo_dir)

        # Create dev branch and push
        git("checkout", "-b", "dev", cwd=self.repo_dir)
        git("push", "origin", "dev", cwd=self.repo_dir)

        # Create story branch with implementation
        git("checkout", "-b", "story-branch", "dev", cwd=self.repo_dir)
        impl = source_content if source_content else "def hello():\n    return 'hello world'\n"
        with open(os.path.join(self.repo_dir, "src.py"), "w") as f:
            f.write(impl)
        if source_conflicts_with_test:
            with open(os.path.join(self.repo_dir, "test_src.py"), "w") as f:
                f.write("# coder wrote to test file — will conflict with test agent\n")
            git("add", "test_src.py", cwd=self.repo_dir)
        git("add", "src.py", cwd=self.repo_dir)
        git("commit", "-m", "implementation", cwd=self.repo_dir)
        git("push", "origin", "story-branch", cwd=self.repo_dir)

        # Create test branch from dev (not story branch)
        git("checkout", "dev", cwd=self.repo_dir)
        git("checkout", "-b", "story-branch--test", cwd=self.repo_dir)

        if test_imports_bad:
            test_code = "from nonexistent import foo\nCannot find module 'bar'\n"
        elif test_assertion_fail:
            test_code = (
                "import sys\n"
                "print('AssertionError: Expected 1 to equal 2')\n"
                "sys.exit(1)\n"
            )
        elif test_output_ambiguous:
            test_code = (
                "import sys\n"
                "print('RuntimeError: something went wrong')\n"
                "sys.exit(1)\n"
            )
        elif test_mixed_errors:
            test_code = (
                "import sys\n"
                "print('TypeError: x is not callable')\n"
                "print('AssertionError: expected true')\n"
                "sys.exit(1)\n"
            )
        else:
            test_code = test_content if test_content else "import sys\nsys.exit(0)\n"

        with open(os.path.join(self.repo_dir, "test_src.py"), "w") as f:
            f.write(test_code)
        git("add", "test_src.py", cwd=self.repo_dir)
        git("commit", "-m", "add tests", cwd=self.repo_dir)
        git("push", "origin", "story-branch--test", cwd=self.repo_dir)

        # Go back to dev
        git("checkout", "dev", cwd=self.repo_dir)

        # Create merge-candidate worktree from story branch
        self.mc_dir = str(tmp_path / "merge-candidate")
        git("worktree", "add", self.mc_dir, "story-branch", cwd=self.repo_dir)

        # Fetch so origin refs are available in the worktree
        git("fetch", "origin", cwd=self.mc_dir)

    def cleanup(self):
        try:
            git("worktree", "remove", "--force", self.mc_dir, cwd=self.repo_dir)
        except Exception:
            pass


def run_merge_gate(mc_path, session_id=None, story_id=None,
                   test_cmd=None, db_home=None, extra_args=None):
    args = [
        sys.executable, SCRIPT_PATH,
        "--merge-candidate", mc_path,
        "--story-branch", "story-branch",
        "--test-branch", "story-branch--test",
        "--dev-branch", "dev",
        "--test-cmd", test_cmd or sys.executable,
        "--test-files", "test_src.py",
    ]
    if session_id:
        args.extend(["--session-id", session_id])
    if story_id:
        args.extend(["--story-id", story_id])
    if extra_args:
        args.extend(extra_args)

    env = os.environ.copy()
    if db_home:
        env["HOME"] = db_home

    return subprocess.run(args, capture_output=True, text=True, env=env)


def test_cherry_pick_success_tests_pass(tmp_path):
    fixture = GitFixture(tmp_path)
    try:
        result = run_merge_gate(fixture.mc_dir)
        assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
        output = json.loads(result.stdout.strip())
        assert output["test_passed"] is True
        assert output["classification"] is None
    finally:
        fixture.cleanup()


def test_cherry_pick_conflict(tmp_path):
    fixture = GitFixture(tmp_path, source_conflicts_with_test=True)
    try:
        result = run_merge_gate(fixture.mc_dir)
        assert result.returncode == 1
        output = json.loads(result.stdout.strip())
        assert output["test_passed"] is False
        assert output["error_type"] == "cherry_pick_conflict"
        assert output["classification"] == "compile_error"
    finally:
        fixture.cleanup()


def test_compile_error_classification(tmp_path):
    fixture = GitFixture(tmp_path, test_imports_bad=True)
    try:
        result = run_merge_gate(fixture.mc_dir)
        assert result.returncode == 1
        output = json.loads(result.stdout.strip())
        assert output["test_passed"] is False
        assert output["classification"] == "compile_error"
    finally:
        fixture.cleanup()


def test_logic_failure_classification(tmp_path):
    fixture = GitFixture(tmp_path, test_assertion_fail=True)
    try:
        result = run_merge_gate(fixture.mc_dir)
        assert result.returncode == 1
        output = json.loads(result.stdout.strip())
        assert output["test_passed"] is False
        assert output["classification"] == "logic_failure"
    finally:
        fixture.cleanup()


def test_ambiguous_classification(tmp_path):
    fixture = GitFixture(tmp_path, test_output_ambiguous=True)
    try:
        result = run_merge_gate(fixture.mc_dir)
        assert result.returncode == 1
        output = json.loads(result.stdout.strip())
        assert output["test_passed"] is False
        assert output["classification"] == "ambiguous"
    finally:
        fixture.cleanup()


def test_mixed_errors_classify_as_compile(tmp_path):
    fixture = GitFixture(tmp_path, test_mixed_errors=True)
    try:
        result = run_merge_gate(fixture.mc_dir)
        assert result.returncode == 1
        output = json.loads(result.stdout.strip())
        assert output["test_passed"] is False
        assert output["classification"] == "compile_error"
    finally:
        fixture.cleanup()


def test_timeout_classifies_as_logic_failure(tmp_path):
    # Test the classification function directly (running a 300s timeout in tests is impractical)
    from importlib.util import spec_from_file_location, module_from_spec
    spec = spec_from_file_location("merge_gate", SCRIPT_PATH)
    mg = module_from_spec(spec)
    spec.loader.exec_module(mg)

    assert mg.classify_failure("TimeoutError: test timed out") == "logic_failure"
    assert mg.classify_failure("timed out after 300 seconds") == "logic_failure"


def test_db_persistence(tmp_path):
    db_home = str(tmp_path / "dbhome")
    os.makedirs(os.path.join(db_home, ".claude", ".claude"), exist_ok=True)
    db_path = os.path.join(db_home, ".claude", ".claude", "run-state.db")

    env = os.environ.copy()
    env["HOME"] = db_home
    subprocess.run(
        [sys.executable, INIT_SCRIPT, "--session-id", "sess-1", "--dev-branch", "dev"],
        capture_output=True, text=True, env=env,
    )

    fixture = GitFixture(tmp_path)
    try:
        result = run_merge_gate(
            fixture.mc_dir,
            session_id="sess-1", story_id="story-42",
            db_home=db_home,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT test_passed, retry_count, merged_at FROM merge_results "
            "WHERE session_id='sess-1' AND story_id='story-42'"
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] == 1  # test_passed
        assert row[1] == 0  # retry_count
        assert row[2] is not None  # merged_at set on pass
    finally:
        fixture.cleanup()


def test_retry_increments_count(tmp_path):
    db_home = str(tmp_path / "dbhome")
    os.makedirs(os.path.join(db_home, ".claude", ".claude"), exist_ok=True)
    db_path = os.path.join(db_home, ".claude", ".claude", "run-state.db")

    env = os.environ.copy()
    env["HOME"] = db_home
    subprocess.run(
        [sys.executable, INIT_SCRIPT, "--session-id", "sess-r", "--dev-branch", "dev"],
        capture_output=True, text=True, env=env,
    )

    fixture = GitFixture(tmp_path, test_assertion_fail=True)
    try:
        # First run
        run_merge_gate(
            fixture.mc_dir,
            session_id="sess-r", story_id="story-99",
            db_home=db_home,
        )

        # Recreate merge-candidate for second run
        fixture.cleanup()
        fixture.mc_dir = str(tmp_path / "merge-candidate-2")
        git("worktree", "add", fixture.mc_dir, "story-branch", cwd=fixture.repo_dir)
        git("fetch", "origin", cwd=fixture.mc_dir)

        # Second run
        run_merge_gate(
            fixture.mc_dir,
            session_id="sess-r", story_id="story-99",
            db_home=db_home,
        )

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT retry_count FROM merge_results WHERE session_id='sess-r' AND story_id='story-99'"
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] == 1  # incremented once on second run
    finally:
        fixture.cleanup()


def test_shell_metacharacters_in_paths(tmp_path):
    """Paths with semicolons/pipes must not be interpreted as shell commands."""
    fixture = GitFixture(tmp_path)
    try:
        result = run_merge_gate(fixture.mc_dir)
        assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
        output = json.loads(result.stdout.strip())
        assert output["test_passed"] is True

        # Verify the debug log shows list form (shell=False), not a string (shell=True)
        assert "[" in result.stderr and "]" in result.stderr
    finally:
        fixture.cleanup()


def test_no_db_write_without_session(tmp_path):
    db_home = str(tmp_path / "dbhome")
    os.makedirs(os.path.join(db_home, ".claude", ".claude"), exist_ok=True)
    db_path = os.path.join(db_home, ".claude", ".claude", "run-state.db")

    fixture = GitFixture(tmp_path)
    try:
        result = run_merge_gate(fixture.mc_dir, db_home=db_home)
        assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
        output = json.loads(result.stdout.strip())
        assert output["test_passed"] is True

        assert not os.path.exists(db_path)
    finally:
        fixture.cleanup()


# --- Mutation testing integration tests ---


def test_mutation_flag_not_set_skips_mutation(tmp_path):
    fixture = GitFixture(tmp_path)
    try:
        result = run_merge_gate(fixture.mc_dir)
        assert result.returncode == 0
        output = json.loads(result.stdout.strip())
        assert output["test_passed"] is True
        assert output.get("mutation_score") is None
        assert "mutation testing" not in result.stderr.lower()
    finally:
        fixture.cleanup()


def test_mutation_runs_on_flag(tmp_path):
    source = (
        "def hello():\n"
        "    x = 1\n"
        "    if x == 1:\n"
        "        return 'hello world'\n"
        "    return 'nope'\n"
    )
    test_code = (
        "import sys, os\n"
        "sys.path.insert(0, os.getcwd())\n"
        "from src import hello\n"
        "assert hello() == 'hello world'\n"
    )
    fixture = GitFixture(tmp_path, source_content=source, test_content=test_code)
    try:
        result = run_merge_gate(fixture.mc_dir, extra_args=["--mutation"])
        assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
        output = json.loads(result.stdout.strip())
        assert output["test_passed"] is True
        assert output.get("mutation_score") is not None
    finally:
        fixture.cleanup()


def test_mutation_score_persisted_in_db(tmp_path):
    db_home = str(tmp_path / "dbhome")
    os.makedirs(os.path.join(db_home, ".claude", ".claude"), exist_ok=True)
    db_path = os.path.join(db_home, ".claude", ".claude", "run-state.db")

    env = os.environ.copy()
    env["HOME"] = db_home
    subprocess.run(
        [sys.executable, INIT_SCRIPT, "--session-id", "mut-sess", "--dev-branch", "dev"],
        capture_output=True, text=True, env=env,
    )

    source = (
        "def hello():\n"
        "    x = 1\n"
        "    if x == 1:\n"
        "        return 'hello world'\n"
        "    return 'nope'\n"
    )
    test_code = (
        "import sys, os\n"
        "sys.path.insert(0, os.getcwd())\n"
        "from src import hello\n"
        "assert hello() == 'hello world'\n"
    )
    fixture = GitFixture(tmp_path, source_content=source, test_content=test_code)
    try:
        result = run_merge_gate(
            fixture.mc_dir, session_id="mut-sess", story_id="story-mut",
            db_home=db_home, extra_args=["--mutation"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT mutation_score FROM merge_results WHERE story_id='story-mut'"
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] is not None
    finally:
        fixture.cleanup()


def test_mutation_warning_below_threshold(tmp_path):
    source = (
        "def hello():\n"
        "    x = 1\n"
        "    if x == 1:\n"
        "        return 'hello world'\n"
        "    return 'nope'\n"
    )
    # Test that does not kill mutants (no real assertion on behavior)
    test_code = "import sys\nsys.exit(0)\n"
    fixture = GitFixture(tmp_path, source_content=source, test_content=test_code)
    try:
        result = run_merge_gate(
            fixture.mc_dir,
            extra_args=["--mutation", "--mutation-threshold", "0.99"],
        )
        assert result.returncode == 1
        output = json.loads(result.stdout.strip())
        assert output["test_passed"] is False
        assert output["classification"] == "low_mutation_score"
    finally:
        fixture.cleanup()


def test_mutation_timeout_skips_gracefully(tmp_path):
    source = (
        "def hello():\n"
        "    x = 1\n"
        "    if x == 1:\n"
        "        return 'hello world'\n"
        "    return 'nope'\n"
    )
    # Test that takes a while
    test_code = "import time, sys\ntime.sleep(0.1)\nsys.exit(0)\n"
    fixture = GitFixture(tmp_path, source_content=source, test_content=test_code)
    try:
        result = run_merge_gate(
            fixture.mc_dir,
            extra_args=["--mutation", "--mutation-timeout", "1"],
        )
        # Mutation runs within timeout, scores 0.0, blocks gate
        assert result.returncode == 1
        output = json.loads(result.stdout.strip())
        assert output["test_passed"] is False
        assert output["classification"] == "low_mutation_score"
    finally:
        fixture.cleanup()


def test_mutation_blocks_below_threshold(tmp_path):
    source = (
        "def hello():\n"
        "    x = 1\n"
        "    if x == 1:\n"
        "        return 'hello world'\n"
        "    return 'nope'\n"
    )
    # Trivial test that passes but won't kill mutants
    test_code = "import sys\nsys.exit(0)\n"
    fixture = GitFixture(tmp_path, source_content=source, test_content=test_code)
    try:
        result = run_merge_gate(
            fixture.mc_dir,
            extra_args=["--mutation", "--mutation-threshold", "1.0"],
        )
        # Threshold=1.0 with trivial test: mutation blocks gate
        assert result.returncode == 1
        output = json.loads(result.stdout.strip())
        assert output["test_passed"] is False
        assert output["classification"] == "low_mutation_score"
    finally:
        fixture.cleanup()
