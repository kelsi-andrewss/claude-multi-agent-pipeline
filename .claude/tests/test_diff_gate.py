"""Integration tests for diff-gate.sh."""
import json
import os
import subprocess

import pytest

SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "diff-gate.sh")


def git(*args, cwd=None):
    result = subprocess.run(
        ["git"] + list(args),
        capture_output=True, text=True, cwd=cwd,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}\n{result.stdout}")
    return result.stdout.strip()


@pytest.fixture
def git_worktree(tmp_path):
    """Set up a git repo with dev branch and a story worktree with changed files."""
    repo = str(tmp_path / "repo")
    os.makedirs(repo)
    git("init", "-b", "main", cwd=repo)
    git("config", "user.email", "t@t.com", cwd=repo)
    git("config", "user.name", "T", cwd=repo)

    # Initial commit on main
    with open(os.path.join(repo, "src.py"), "w") as f:
        f.write("def hello(): pass\n")
    with open(os.path.join(repo, "utils.py"), "w") as f:
        f.write("def util(): pass\n")
    git("add", "src.py", "utils.py", cwd=repo)
    git("commit", "-m", "initial", cwd=repo)

    # Create dev branch
    git("checkout", "-b", "dev", cwd=repo)
    git("checkout", "main", cwd=repo)

    # Create story branch with changes to src.py and an unexpected file
    git("checkout", "-b", "story-1", "dev", cwd=repo)
    with open(os.path.join(repo, "src.py"), "w") as f:
        f.write("def hello(): return 'world'\n")
    with open(os.path.join(repo, "extra.py"), "w") as f:
        f.write("# unexpected file\n")
    git("add", "src.py", "extra.py", cwd=repo)
    git("commit", "-m", "story changes", cwd=repo)

    # Go back to main so we can create a worktree on story-1
    git("checkout", "main", cwd=repo)

    # Create worktree
    wt_path = str(tmp_path / "wt")
    git("worktree", "add", wt_path, "story-1", cwd=repo)

    yield {"repo": repo, "worktree": wt_path}

    # Cleanup
    try:
        git("worktree", "remove", "--force", wt_path, cwd=repo)
    except Exception:
        pass


def run_diff_gate(worktree_path, dev_branch, write_files):
    result = subprocess.run(
        ["bash", SCRIPT_PATH,
         "--worktree-path", worktree_path,
         "--dev-branch", dev_branch,
         "--write-files", write_files],
        capture_output=True, text=True,
    )
    return result


class TestDiffGateBasic:
    def test_no_unexpected_files(self, git_worktree):
        result = run_diff_gate(git_worktree["worktree"], "dev", "src.py,extra.py")
        assert result.returncode == 0
        output = json.loads(result.stdout.strip())
        assert output["status"] == "success"
        assert output["unexpected_files"] == []

    def test_unexpected_files_detected(self, git_worktree):
        result = run_diff_gate(git_worktree["worktree"], "dev", "src.py")
        assert result.returncode == 0
        output = json.loads(result.stdout.strip())
        assert output["status"] == "success"
        assert "extra.py" in output["unexpected_files"]

    def test_all_files_unexpected(self, git_worktree):
        result = run_diff_gate(git_worktree["worktree"], "dev", "nonexistent.py")
        assert result.returncode == 0
        output = json.loads(result.stdout.strip())
        assert "src.py" in output["unexpected_files"]
        assert "extra.py" in output["unexpected_files"]


class TestDiffGateSymbolStripping:
    def test_symbol_suffix_stripped(self, git_worktree):
        result = run_diff_gate(git_worktree["worktree"], "dev", "src.py:hello,extra.py:something")
        assert result.returncode == 0
        output = json.loads(result.stdout.strip())
        assert output["unexpected_files"] == []

    def test_mixed_with_and_without_symbols(self, git_worktree):
        result = run_diff_gate(git_worktree["worktree"], "dev", "src.py:hello,extra.py")
        assert result.returncode == 0
        output = json.loads(result.stdout.strip())
        assert output["unexpected_files"] == []


class TestDiffGateEdgeCases:
    def test_nonexistent_worktree(self, tmp_path):
        fake_path = str(tmp_path / "nonexistent")
        result = run_diff_gate(fake_path, "dev", "src.py")
        assert result.returncode == 2
        output = json.loads(result.stdout.strip())
        assert output["status"] == "error"

    def test_missing_arguments(self):
        result = subprocess.run(
            ["bash", SCRIPT_PATH, "--worktree-path", "/tmp/x"],
            capture_output=True, text=True,
        )
        assert result.returncode == 2

    def test_changed_files_list(self, git_worktree):
        result = run_diff_gate(git_worktree["worktree"], "dev", "src.py,extra.py")
        output = json.loads(result.stdout.strip())
        assert set(output["changed_files"]) == {"src.py", "extra.py"}

    def test_expected_files_list(self, git_worktree):
        result = run_diff_gate(git_worktree["worktree"], "dev", "src.py:foo,extra.py")
        output = json.loads(result.stdout.strip())
        assert set(output["expected_files"]) == {"src.py", "extra.py"}

    def test_duplicate_write_files_deduped(self, git_worktree):
        result = run_diff_gate(git_worktree["worktree"], "dev", "src.py,src.py:bar,extra.py")
        output = json.loads(result.stdout.strip())
        assert output["expected_files"].count("src.py") == 1
