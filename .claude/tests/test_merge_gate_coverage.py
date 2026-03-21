"""Extended integration tests for merge-gate.py — covers edge cases beyond test_merge_gate.py."""
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
    """Minimal git fixture for merge-gate tests."""

    def __init__(self, tmp_path, test_content=None):
        self.bare_dir = str(tmp_path / "origin.git")
        os.makedirs(self.bare_dir)
        git("init", "--bare", "-b", "main", cwd=self.bare_dir)

        self.repo_dir = str(tmp_path / "repo")
        git("clone", self.bare_dir, self.repo_dir)
        git("config", "user.email", "test@test.com", cwd=self.repo_dir)
        git("config", "user.name", "Test", cwd=self.repo_dir)

        with open(os.path.join(self.repo_dir, "src.py"), "w") as f:
            f.write("def hello():\n    return 'hello'\n")
        git("add", "src.py", cwd=self.repo_dir)
        git("commit", "-m", "initial", cwd=self.repo_dir)
        git("push", "origin", "main", cwd=self.repo_dir)

        git("checkout", "-b", "dev", cwd=self.repo_dir)
        git("push", "origin", "dev", cwd=self.repo_dir)

        git("checkout", "-b", "story-branch", "dev", cwd=self.repo_dir)
        with open(os.path.join(self.repo_dir, "src.py"), "w") as f:
            f.write("def hello():\n    return 'hello world'\n")
        git("add", "src.py", cwd=self.repo_dir)
        git("commit", "-m", "implementation", cwd=self.repo_dir)
        git("push", "origin", "story-branch", cwd=self.repo_dir)

        git("checkout", "dev", cwd=self.repo_dir)
        git("checkout", "-b", "story-branch--test", cwd=self.repo_dir)

        test_code = test_content if test_content else "import sys\nsys.exit(0)\n"
        with open(os.path.join(self.repo_dir, "test_src.py"), "w") as f:
            f.write(test_code)
        git("add", "test_src.py", cwd=self.repo_dir)
        git("commit", "-m", "add tests", cwd=self.repo_dir)
        git("push", "origin", "story-branch--test", cwd=self.repo_dir)

        git("checkout", "dev", cwd=self.repo_dir)
        self.mc_dir = str(tmp_path / "merge-candidate")
        git("worktree", "add", self.mc_dir, "story-branch", cwd=self.repo_dir)
        git("fetch", "origin", cwd=self.mc_dir)

    def cleanup(self):
        try:
            git("worktree", "remove", "--force", self.mc_dir, cwd=self.repo_dir)
        except Exception:
            pass


def run_merge_gate(mc_path, session_id=None, story_id=None,
                   test_cmd=None, test_files=None, db_home=None):
    args = [
        sys.executable, SCRIPT_PATH,
        "--merge-candidate", mc_path,
        "--story-branch", "story-branch",
        "--test-branch", "story-branch--test",
        "--dev-branch", "dev",
        "--test-cmd", test_cmd or sys.executable,
        "--test-files", test_files or "test_src.py",
    ]
    if session_id:
        args.extend(["--session-id", session_id])
    if story_id:
        args.extend(["--story-id", story_id])

    env = os.environ.copy()
    if db_home:
        env["HOME"] = db_home

    return subprocess.run(args, capture_output=True, text=True, env=env)


class TestMergeGateOutputFormat:
    def test_output_is_valid_json(self, tmp_path):
        fixture = GitFixture(tmp_path)
        try:
            result = run_merge_gate(fixture.mc_dir)
            output = json.loads(result.stdout.strip())
            assert "status" in output
            assert "test_passed" in output
        finally:
            fixture.cleanup()

    def test_success_fields_on_pass(self, tmp_path):
        fixture = GitFixture(tmp_path)
        try:
            result = run_merge_gate(fixture.mc_dir)
            output = json.loads(result.stdout.strip())
            assert output["status"] == "success"
            assert output["test_passed"] is True
            assert output["error_type"] is None
            assert output["error_output"] is None
            assert output["classification"] is None
        finally:
            fixture.cleanup()

    def test_failure_has_error_output(self, tmp_path):
        test_code = "import sys\nprint('FAIL assert x == y')\nsys.exit(1)\n"
        fixture = GitFixture(tmp_path, test_content=test_code)
        try:
            result = run_merge_gate(fixture.mc_dir)
            assert result.returncode == 1
            output = json.loads(result.stdout.strip())
            assert output["test_passed"] is False
            assert output["error_output"] is not None
            assert output["error_type"] == "test_failure"
        finally:
            fixture.cleanup()


class TestMergeGateCustomTestCmd:
    def test_custom_test_command(self, tmp_path):
        test_code = "import sys\nprint('all good')\nsys.exit(0)\n"
        fixture = GitFixture(tmp_path, test_content=test_code)
        try:
            result = run_merge_gate(fixture.mc_dir, test_cmd=f"{sys.executable} -u")
            assert result.returncode == 0
            output = json.loads(result.stdout.strip())
            assert output["test_passed"] is True
        finally:
            fixture.cleanup()

    def test_test_files_split_and_passed(self, tmp_path):
        fixture = GitFixture(tmp_path)
        try:
            # Verify test_files are split on comma and passed as separate args
            result = run_merge_gate(fixture.mc_dir, test_files="test_src.py")
            assert result.returncode == 0
            # The stderr debug line shows the command list
            assert "test_src.py" in result.stderr
        finally:
            fixture.cleanup()


class TestMergeGateNewArgs:
    """Tests for --coverage, --acceptance-criteria, --test-file-names args."""

    def test_coverage_pct_in_output_on_pass(self, tmp_path):
        """--coverage flag should add coverage_pct to JSON output."""
        # Test that outputs fake coverage data and passes
        test_code = "import sys\nprint('TOTAL 100 80 80%')\nsys.exit(0)\n"
        fixture = GitFixture(tmp_path, test_content=test_code)
        try:
            args = [
                sys.executable, SCRIPT_PATH,
                "--merge-candidate", fixture.mc_dir,
                "--story-branch", "story-branch",
                "--test-branch", "story-branch--test",
                "--dev-branch", "dev",
                "--test-cmd", sys.executable,
                "--test-files", "test_src.py",
                "--coverage",
            ]
            result = subprocess.run(args, capture_output=True, text=True)
            assert result.returncode == 0
            output = json.loads(result.stdout.strip())
            assert output["test_passed"] is True
            assert "coverage_pct" in output
        finally:
            fixture.cleanup()

    def test_no_coverage_flag_has_null_coverage(self, tmp_path):
        """Without --coverage, coverage_pct should be null."""
        fixture = GitFixture(tmp_path)
        try:
            result = run_merge_gate(fixture.mc_dir)
            assert result.returncode == 0
            output = json.loads(result.stdout.strip())
            assert output.get("coverage_pct") is None
        finally:
            fixture.cleanup()

    def test_acceptance_criteria_hash_in_db(self, tmp_path):
        """--acceptance-criteria should produce SHA-256 hash persisted in DB."""
        import hashlib
        db_home = str(tmp_path / "dbhome")
        os.makedirs(os.path.join(db_home, ".claude", ".claude"), exist_ok=True)
        db_path = os.path.join(db_home, ".claude", ".claude", "run-state.db")

        env = os.environ.copy()
        env["HOME"] = db_home
        subprocess.run(
            [sys.executable, INIT_SCRIPT, "--session-id", "cov-sess", "--dev-branch", "dev"],
            capture_output=True, text=True, env=env,
        )

        criteria = "User can log in with valid credentials"
        expected_hash = hashlib.sha256(criteria.encode()).hexdigest()

        fixture = GitFixture(tmp_path)
        try:
            args = [
                sys.executable, SCRIPT_PATH,
                "--merge-candidate", fixture.mc_dir,
                "--story-branch", "story-branch",
                "--test-branch", "story-branch--test",
                "--dev-branch", "dev",
                "--test-cmd", sys.executable,
                "--test-files", "test_src.py",
                "--session-id", "cov-sess",
                "--story-id", "story-ac",
                "--acceptance-criteria", criteria,
            ]
            result = subprocess.run(args, capture_output=True, text=True, env=env)
            assert result.returncode == 0

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT acceptance_criteria_hash FROM merge_results WHERE story_id='story-ac'"
            ).fetchone()
            conn.close()

            assert row is not None
            assert row[0] == expected_hash
        finally:
            fixture.cleanup()

    def test_test_file_names_persisted_in_db(self, tmp_path):
        """--test-file-names should be persisted in DB."""
        db_home = str(tmp_path / "dbhome")
        os.makedirs(os.path.join(db_home, ".claude", ".claude"), exist_ok=True)
        db_path = os.path.join(db_home, ".claude", ".claude", "run-state.db")

        env = os.environ.copy()
        env["HOME"] = db_home
        subprocess.run(
            [sys.executable, INIT_SCRIPT, "--session-id", "tfn-sess", "--dev-branch", "dev"],
            capture_output=True, text=True, env=env,
        )

        fixture = GitFixture(tmp_path)
        try:
            args = [
                sys.executable, SCRIPT_PATH,
                "--merge-candidate", fixture.mc_dir,
                "--story-branch", "story-branch",
                "--test-branch", "story-branch--test",
                "--dev-branch", "dev",
                "--test-cmd", sys.executable,
                "--test-files", "test_src.py",
                "--session-id", "tfn-sess",
                "--story-id", "story-tfn",
                "--test-file-names", "test_api.py,test_auth.py",
            ]
            result = subprocess.run(args, capture_output=True, text=True, env=env)
            assert result.returncode == 0

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT test_file_names FROM merge_results WHERE story_id='story-tfn'"
            ).fetchone()
            conn.close()

            assert row is not None
            assert row[0] == "test_api.py,test_auth.py"
        finally:
            fixture.cleanup()

    def test_new_db_columns_exist(self, tmp_path):
        """Idempotent ALTER TABLE should create new columns."""
        db_home = str(tmp_path / "dbhome")
        os.makedirs(os.path.join(db_home, ".claude", ".claude"), exist_ok=True)
        db_path = os.path.join(db_home, ".claude", ".claude", "run-state.db")

        env = os.environ.copy()
        env["HOME"] = db_home
        subprocess.run(
            [sys.executable, INIT_SCRIPT, "--session-id", "col-sess", "--dev-branch", "dev"],
            capture_output=True, text=True, env=env,
        )

        fixture = GitFixture(tmp_path)
        try:
            args = [
                sys.executable, SCRIPT_PATH,
                "--merge-candidate", fixture.mc_dir,
                "--story-branch", "story-branch",
                "--test-branch", "story-branch--test",
                "--dev-branch", "dev",
                "--test-cmd", sys.executable,
                "--test-files", "test_src.py",
                "--session-id", "col-sess",
                "--story-id", "story-col",
            ]
            subprocess.run(args, capture_output=True, text=True, env=env)

            conn = sqlite3.connect(db_path)
            cols = [row[1] for row in conn.execute("PRAGMA table_info(merge_results)").fetchall()]
            conn.close()

            assert "test_file_names" in cols
            assert "acceptance_criteria_hash" in cols
            assert "coverage_pct" in cols
        finally:
            fixture.cleanup()


class TestMergeGateNonexistentPath:
    def test_bad_merge_candidate_path(self, tmp_path):
        fake_path = str(tmp_path / "nonexistent")
        result = run_merge_gate(fake_path)
        assert result.returncode == 2
        output = json.loads(result.stdout.strip())
        assert output["status"] == "error"


class TestMergeGateDbEdgeCases:
    def _init_db(self, db_home):
        os.makedirs(os.path.join(db_home, ".claude", ".claude"), exist_ok=True)
        env = os.environ.copy()
        env["HOME"] = db_home
        subprocess.run(
            [sys.executable, INIT_SCRIPT, "--session-id", "test-sess", "--dev-branch", "dev"],
            capture_output=True, text=True, env=env,
        )
        return os.path.join(db_home, ".claude", ".claude", "run-state.db")

    def test_pass_sets_merged_at(self, tmp_path):
        db_home = str(tmp_path / "dbhome")
        db_path = self._init_db(db_home)
        fixture = GitFixture(tmp_path)
        try:
            result = run_merge_gate(
                fixture.mc_dir, session_id="test-sess", story_id="s-1", db_home=db_home,
            )
            assert result.returncode == 0

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT test_passed, merged_at FROM merge_results WHERE story_id='s-1'"
            ).fetchone()
            conn.close()

            assert row[0] == 1
            assert row[1] is not None
        finally:
            fixture.cleanup()

    def test_fail_does_not_set_merged_at(self, tmp_path):
        db_home = str(tmp_path / "dbhome")
        db_path = self._init_db(db_home)
        test_code = "import sys\nprint('AssertionError: bad')\nsys.exit(1)\n"
        fixture = GitFixture(tmp_path, test_content=test_code)
        try:
            result = run_merge_gate(
                fixture.mc_dir, session_id="test-sess", story_id="s-2", db_home=db_home,
            )
            assert result.returncode == 1

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT test_passed, merged_at FROM merge_results WHERE story_id='s-2'"
            ).fetchone()
            conn.close()

            assert row[0] == 0
            assert row[1] is None
        finally:
            fixture.cleanup()

    def test_retry_then_pass_sets_merged_at(self, tmp_path):
        db_home = str(tmp_path / "dbhome")
        db_path = self._init_db(db_home)

        # First run: fail
        test_code_fail = "import sys\nprint('AssertionError: bad')\nsys.exit(1)\n"
        fixture = GitFixture(tmp_path, test_content=test_code_fail)
        try:
            run_merge_gate(
                fixture.mc_dir, session_id="test-sess", story_id="s-3", db_home=db_home,
            )

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT retry_count, merged_at FROM merge_results WHERE story_id='s-3'"
            ).fetchone()
            conn.close()
            assert row[0] == 0
            assert row[1] is None
        finally:
            fixture.cleanup()

        # Second run: pass (new fixture with passing tests)
        fixture2 = GitFixture(tmp_path / "run2")
        try:
            run_merge_gate(
                fixture2.mc_dir, session_id="test-sess", story_id="s-3", db_home=db_home,
            )

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT retry_count, test_passed, merged_at FROM merge_results WHERE story_id='s-3'"
            ).fetchone()
            conn.close()
            assert row[0] == 1  # retry incremented
            assert row[1] == 1  # now passing
            assert row[2] is not None  # merged_at set
        finally:
            fixture2.cleanup()
