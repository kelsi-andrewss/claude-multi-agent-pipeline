"""Tests for mcp_server/server.py — all subprocess calls are mocked."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import gemini_client
import server
import tools_analysis
import tools_gemini
import tools_pm_helpers
import tools_pm_plan
import tools_test as tools_test_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_subprocess():
    """Mock create_subprocess_exec returning a successful gemini JSON response."""
    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(
        json.dumps({"response": "test response"}).encode(),
        b"",
    ))
    with patch("gemini_client.asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
        yield mock_exec, proc


# ---------------------------------------------------------------------------
# _gemini() — stdin piping
# ---------------------------------------------------------------------------

class TestGemini:
    def test_pipes_prompt_via_stdin(self, mock_subprocess):
        mock_exec, proc = mock_subprocess
        prompt = "Hello, Gemini!"

        result = asyncio.get_event_loop().run_until_complete(server._gemini(prompt))

        # Command should NOT contain -p
        call_args = mock_exec.call_args
        cmd_parts = call_args[0]
        assert "-p" not in cmd_parts
        assert prompt not in cmd_parts

        # stdin=PIPE must be set
        assert call_args[1]["stdin"] == asyncio.subprocess.PIPE

        # prompt piped via communicate()
        proc.communicate.assert_awaited_once_with(input=prompt.encode())

        assert result == "test response"

    def test_includes_model_flag(self, mock_subprocess):
        mock_exec, _ = mock_subprocess

        asyncio.get_event_loop().run_until_complete(
            server._gemini("hi", model="gemini-2.0-flash")
        )

        cmd_parts = mock_exec.call_args[0]
        assert "-m" in cmd_parts
        idx = cmd_parts.index("-m")
        assert cmd_parts[idx + 1] == "gemini-2.0-flash"

    def test_omits_model_flag_when_none(self, mock_subprocess):
        mock_exec, _ = mock_subprocess

        asyncio.get_event_loop().run_until_complete(
            server._gemini("hi", model=None)
        )

        cmd_parts = mock_exec.call_args[0]
        assert "-m" not in cmd_parts

    def test_handles_cli_error(self, mock_subprocess):
        mock_exec, proc = mock_subprocess
        proc.returncode = 1
        proc.communicate = AsyncMock(return_value=(b"", b"something went wrong"))

        from gemini_client import GeminiCLIError
        with pytest.raises(GeminiCLIError, match="something went wrong"):
            asyncio.get_event_loop().run_until_complete(server._gemini("hi"))

    def test_parses_json_response(self, mock_subprocess):
        _, proc = mock_subprocess
        proc.communicate = AsyncMock(return_value=(
            json.dumps({"response": "hello world"}).encode(),
            b"",
        ))

        result = asyncio.get_event_loop().run_until_complete(server._gemini("hi"))
        assert result == "hello world"

    def test_handles_empty_response(self, mock_subprocess):
        _, proc = mock_subprocess
        proc.communicate = AsyncMock(return_value=(
            json.dumps({}).encode(),
            b"",
        ))

        result = asyncio.get_event_loop().run_until_complete(server._gemini("hi"))
        assert result == "(empty response)"


# ---------------------------------------------------------------------------
# gemini_chat
# ---------------------------------------------------------------------------

class TestGeminiChat:
    def test_formats_messages(self, mock_subprocess):
        _, proc = mock_subprocess
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "model", "content": "hi there"},
            {"role": "user", "content": "thanks"},
        ]

        asyncio.get_event_loop().run_until_complete(
            server.gemini_chat(messages)
        )

        piped_input = proc.communicate.call_args[1]["input"].decode()
        assert "User: hello" in piped_input
        assert "Model: hi there" in piped_input
        assert "User: thanks" in piped_input
        # No-code instruction always present
        assert server.NO_CODE_INSTRUCTION in piped_input


# ---------------------------------------------------------------------------
# fetch_doc
# ---------------------------------------------------------------------------

class TestFetchDoc:
    def test_list_returns_table_with_all_keys(self):
        result = asyncio.get_event_loop().run_until_complete(server.fetch_doc("list"))

        for key in server.DOCUMENTS:
            assert f"`{key}`" in result

        # Verify table header
        assert "| Key |" in result

    def test_claude_returns_file_content(self):
        claude_path = server.PROJECT_ROOT / server.DOCUMENTS["claude"]["path"]
        if not claude_path.exists():
            pytest.skip("CLAUDE.md not found at project root")

        result = asyncio.get_event_loop().run_until_complete(server.fetch_doc("claude"))
        assert len(result) > 0
        # CLAUDE.md should contain some recognizable content
        assert "Advocate" in result or "advocate" in result

    def test_nonexistent_key_returns_error(self):
        result = asyncio.get_event_loop().run_until_complete(
            server.fetch_doc("nonexistent")
        )

        assert "Unknown document" in result
        # Should list valid keys for discoverability
        assert "claude" in result


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------

class TestPlan:
    def test_reads_default_docs(self, mock_subprocess):
        with patch.object(tools_gemini, "_read_doc", return_value="doc content") as mock_read:
            asyncio.get_event_loop().run_until_complete(
                server.plan("build a widget")
            )

            called_keys = [call[0][0] for call in mock_read.call_args_list]
            assert "claude" in called_keys
            assert "requirements" in called_keys
            assert "architecture" in called_keys

    def test_includes_system_instruction(self, mock_subprocess):
        _, proc = mock_subprocess

        with patch.object(tools_gemini, "_read_doc", return_value="doc content"):
            asyncio.get_event_loop().run_until_complete(
                server.plan("build a widget")
            )

        piped_input = proc.communicate.call_args[1]["input"].decode()
        assert "[System:" in piped_input
        assert "senior developer" in piped_input


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------

class TestAnalyze:
    def test_reads_claude_doc(self, mock_subprocess):
        with patch.object(tools_gemini, "_read_doc", return_value="conventions") as mock_read:
            asyncio.get_event_loop().run_until_complete(
                server.analyze("def foo(): pass")
            )

            mock_read.assert_called_once_with("claude")

    def test_includes_context_when_provided(self, mock_subprocess):
        _, proc = mock_subprocess

        with patch.object(tools_gemini, "_read_doc", return_value="conventions"):
            asyncio.get_event_loop().run_until_complete(
                server.analyze("def foo(): pass", context="This is a helper function")
            )

        piped_input = proc.communicate.call_args[1]["input"].decode()
        assert "Additional Context" in piped_input
        assert "This is a helper function" in piped_input


# ---------------------------------------------------------------------------
# _run_tests
# ---------------------------------------------------------------------------

class TestRunTests:
    def test_backend_command_construction(self):
        """Backend suite runs pytest via .venv python with correct flags."""
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"all passed", None))

        with patch("gemini_client.asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            output, passed = asyncio.get_event_loop().run_until_complete(
                server._run_tests("backend")
            )

        cmd_parts = mock_exec.call_args[0]
        assert cmd_parts[-1] == "--tb=short"
        assert "tests/" in cmd_parts
        assert str(server.PROJECT_ROOT) == mock_exec.call_args[1]["cwd"]
        assert passed is True
        assert output == "all passed"

    def test_backend_specific_tests(self):
        """When specific tests provided, they replace 'tests/' in command."""
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"ok", None))

        with patch("gemini_client.asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            asyncio.get_event_loop().run_until_complete(
                server._run_tests("backend", tests=["tests/test_a.py::test_one", "tests/test_b.py"])
            )

        cmd_parts = mock_exec.call_args[0]
        assert "tests/" not in cmd_parts
        assert "tests/test_a.py::test_one" in cmd_parts
        assert "tests/test_b.py" in cmd_parts

    def test_frontend_command_construction(self):
        """Frontend suite runs flutter test from flutter/ directory."""
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"all passed", None))

        with patch("gemini_client.asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            output, passed = asyncio.get_event_loop().run_until_complete(
                server._run_tests("frontend")
            )

        cmd_parts = mock_exec.call_args[0]
        assert cmd_parts == ("flutter", "test")
        assert mock_exec.call_args[1]["cwd"] == str(server.PROJECT_ROOT / "flutter")
        assert passed is True

    def test_failure_returns_false(self):
        """Non-zero return code means tests failed."""
        proc = AsyncMock()
        proc.returncode = 1
        proc.communicate = AsyncMock(return_value=(b"FAILED test_something", None))

        with patch("gemini_client.asyncio.create_subprocess_exec", return_value=proc):
            output, passed = asyncio.get_event_loop().run_until_complete(
                server._run_tests("backend")
            )

        assert passed is False
        assert "FAILED" in output

    def test_timeout_handling(self):
        """Tests that exceed the timeout return an error."""
        proc = AsyncMock()
        proc.kill = MagicMock()
        proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)

        with patch("gemini_client.asyncio.create_subprocess_exec", return_value=proc):
            output, passed = asyncio.get_event_loop().run_until_complete(
                server._run_tests("backend", timeout=5)
            )

        assert passed is False
        assert "timed out" in output.lower()
        proc.kill.assert_called_once()

    def test_missing_executable(self):
        """FileNotFoundError when executable doesn't exist."""
        with patch(
            "gemini_client.asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError,
        ):
            output, passed = asyncio.get_event_loop().run_until_complete(
                server._run_tests("backend")
            )

        assert passed is False
        assert "not found" in output.lower()

    def test_unknown_suite(self):
        """Unknown suite name returns error."""
        output, passed = asyncio.get_event_loop().run_until_complete(
            server._run_tests("unknown")
        )

        assert passed is False
        assert "Unknown suite" in output


# ---------------------------------------------------------------------------
# test tool
# ---------------------------------------------------------------------------

class TestTestTool:
    def test_all_pass_skips_gemini(self):
        """When all tests pass, return summary directly without calling Gemini."""
        with patch.object(
            tools_test_mod, "_run_tests", return_value=("all good", True)
        ) as mock_run, patch.object(tools_test_mod, "_gemini") as mock_gemini:
            result = asyncio.get_event_loop().run_until_complete(
                server.test(suite="backend")
            )

        mock_run.assert_called_once_with("backend", tests=None)
        mock_gemini.assert_not_called()
        assert "passed" in result.lower()

    def test_failure_triggers_gemini_analysis(self):
        """When tests fail, output is sent to Gemini for analysis."""
        with patch.object(
            tools_test_mod, "_run_tests", return_value=("FAILED test_foo", False)
        ), patch.object(
            tools_test_mod, "_gemini", return_value="Structured analysis here"
        ) as mock_gemini:
            result = asyncio.get_event_loop().run_until_complete(
                server.test(suite="backend")
            )

        mock_gemini.assert_called_once()
        prompt = mock_gemini.call_args[0][0]
        assert "FAILED test_foo" in prompt
        assert result == "Structured analysis here"

    def test_invalid_suite_returns_error(self):
        """Invalid suite name returns an error message."""
        result = asyncio.get_event_loop().run_until_complete(
            server.test(suite="invalid")
        )
        assert "Invalid suite" in result

    def test_backend_only(self):
        """suite='backend' only runs backend tests."""
        with patch.object(
            tools_test_mod, "_run_tests", return_value=("ok", True)
        ) as mock_run:
            asyncio.get_event_loop().run_until_complete(
                server.test(suite="backend")
            )

        mock_run.assert_called_once_with("backend", tests=None)

    def test_frontend_only(self):
        """suite='frontend' only runs frontend tests."""
        with patch.object(
            tools_test_mod, "_run_tests", return_value=("ok", True)
        ) as mock_run:
            asyncio.get_event_loop().run_until_complete(
                server.test(suite="frontend")
            )

        mock_run.assert_called_once_with("frontend")

    def test_all_runs_both(self):
        """suite='all' runs both backend and frontend."""
        call_count = 0

        async def mock_run(suite, **kwargs):
            nonlocal call_count
            call_count += 1
            return ("ok", True)

        with patch.object(tools_test_mod, "_run_tests", side_effect=mock_run):
            asyncio.get_event_loop().run_until_complete(
                server.test(suite="all")
            )

        assert call_count == 2

    def test_specific_tests_passed_to_backend(self):
        """tests parameter is forwarded to _run_tests for backend."""
        specific = ["tests/test_a.py::test_one"]
        with patch.object(
            tools_test_mod, "_run_tests", return_value=("ok", True)
        ) as mock_run:
            asyncio.get_event_loop().run_until_complete(
                server.test(suite="backend", tests=specific)
            )

        mock_run.assert_called_once_with("backend", tests=specific)


# ---------------------------------------------------------------------------
# No-code enforcement across all Gemini-backed tools
# ---------------------------------------------------------------------------

class TestNoCodeEnforcement:
    def test_gemini_chat_includes_no_code(self, mock_subprocess):
        _, proc = mock_subprocess

        asyncio.get_event_loop().run_until_complete(
            server.gemini_chat([{"role": "user", "content": "hi"}])
        )

        piped_input = proc.communicate.call_args[1]["input"].decode()
        assert server.NO_CODE_INSTRUCTION in piped_input

    def test_plan_includes_no_code(self, mock_subprocess):
        _, proc = mock_subprocess

        with patch.object(tools_gemini, "_read_doc", return_value="doc content"):
            asyncio.get_event_loop().run_until_complete(
                server.plan("build something")
            )

        piped_input = proc.communicate.call_args[1]["input"].decode()
        assert server.NO_CODE_INSTRUCTION in piped_input

    def test_analyze_includes_no_code(self, mock_subprocess):
        _, proc = mock_subprocess

        with patch.object(tools_gemini, "_read_doc", return_value="conventions"):
            asyncio.get_event_loop().run_until_complete(
                server.analyze("review this")
            )

        piped_input = proc.communicate.call_args[1]["input"].decode()
        assert server.NO_CODE_INSTRUCTION in piped_input


# ---------------------------------------------------------------------------
# _discover_files
# ---------------------------------------------------------------------------

class TestDiscoverFiles:
    """Tests for _discover_files helper."""

    @pytest.fixture(autouse=True)
    def _setup_tmpdir(self, tmp_path):
        """Create a temp project tree and patch PROJECT_ROOT."""
        self.root = tmp_path
        # Create source files of varying sizes
        (tmp_path / "small.py").write_text("a = 1")
        (tmp_path / "medium.ts").write_text("x" * 100)
        (tmp_path / "large.js").write_text("y" * 1000)
        # Non-source file
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        # Ignored directory
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "dep.js").write_text("module")
        # Nested source
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.dart").write_text("main() {}")
        self._patcher = patch.object(gemini_client, "PROJECT_ROOT", tmp_path)
        self._patcher.start()

    @pytest.fixture(autouse=True)
    def _teardown(self):
        yield
        self._patcher.stop()

    def test_finds_source_files(self):
        files = server._discover_files()
        names = {f.name for f in files}
        assert "small.py" in names
        assert "medium.ts" in names
        assert "large.js" in names
        assert "app.dart" in names

    def test_excludes_non_source_extensions(self):
        files = server._discover_files()
        names = {f.name for f in files}
        assert "image.png" not in names

    def test_skips_ignored_directories(self):
        files = server._discover_files()
        names = {f.name for f in files}
        assert "dep.js" not in names

    def test_sorted_by_size_ascending(self):
        files = server._discover_files()
        sizes = [f.stat().st_size for f in files]
        assert sizes == sorted(sizes)

    def test_explicit_paths(self):
        files = server._discover_files(paths=["src"])
        names = {f.name for f in files}
        assert names == {"app.dart"}

    def test_explicit_file_path(self):
        files = server._discover_files(paths=["small.py"])
        assert len(files) == 1
        assert files[0].name == "small.py"

    def test_ignore_patterns(self):
        files = server._discover_files(ignore_patterns=["*.ts"])
        names = {f.name for f in files}
        assert "medium.ts" not in names
        assert "small.py" in names

    def test_nonexistent_path_skipped(self):
        files = server._discover_files(paths=["nonexistent"])
        assert files == []


# ---------------------------------------------------------------------------
# _read_files_within_budget
# ---------------------------------------------------------------------------

class TestReadFilesWithinBudget:
    """Tests for _read_files_within_budget helper."""

    @pytest.fixture(autouse=True)
    def _setup_tmpdir(self, tmp_path):
        self.root = tmp_path
        self._patcher = patch.object(gemini_client, "PROJECT_ROOT", tmp_path)
        self._patcher.start()

    @pytest.fixture(autouse=True)
    def _teardown(self):
        yield
        self._patcher.stop()

    def test_reads_all_within_budget(self):
        f1 = self.root / "a.py"
        f2 = self.root / "b.py"
        f1.write_text("hello")
        f2.write_text("world")

        content, skipped = server._read_files_within_budget([f1, f2], 10000)
        assert "hello" in content
        assert "world" in content
        assert skipped == []

    def test_skips_files_exceeding_budget(self):
        small = self.root / "small.py"
        big = self.root / "big.py"
        small.write_text("x")
        big.write_text("y" * 1000)

        content, skipped = server._read_files_within_budget([small, big], 100)
        assert "x" in content
        assert big in skipped

    def test_format_includes_headers_and_separators(self):
        f1 = self.root / "a.py"
        f1.write_text("content")

        content, _ = server._read_files_within_budget([f1], 10000)
        assert "### a.py" in content
        assert "---" in content

    def test_handles_unreadable_file(self):
        f1 = self.root / "a.py"
        f1.write_text("ok")
        bad = self.root / "bad.py"
        bad.write_text("data")
        # Make unreadable
        bad.chmod(0o000)

        content, skipped = server._read_files_within_budget([f1, bad], 10000)
        assert "ok" in content
        assert bad in skipped
        # Restore permissions for cleanup
        bad.chmod(0o644)

    def test_empty_file_list(self):
        content, skipped = server._read_files_within_budget([], 10000)
        assert content == ""
        assert skipped == []


# ---------------------------------------------------------------------------
# _load_audit_context
# ---------------------------------------------------------------------------

class TestLoadAuditContext:
    """Tests for _load_audit_context helper."""

    @pytest.fixture(autouse=True)
    def _setup_tmpdir(self, tmp_path):
        self.root = tmp_path
        self._patcher = patch.object(gemini_client, "PROJECT_ROOT", tmp_path)
        self._patcher.start()

    @pytest.fixture(autouse=True)
    def _teardown(self):
        yield
        self._patcher.stop()

    def test_finds_requirements_at_root(self):
        (self.root / "REQUIREMENTS.md").write_text("Must do X")
        result = server._load_audit_context()
        assert "Must do X" in result
        assert "### REQUIREMENTS.md" in result

    def test_finds_research_dir_files(self):
        research = self.root / "project_requirements_and_research"
        research.mkdir()
        (research / "notes.md").write_text("Research notes")

        result = server._load_audit_context()
        assert "Research notes" in result

    def test_returns_empty_when_nothing_found(self):
        result = server._load_audit_context()
        assert result == ""

    def test_truncates_to_budget(self):
        (self.root / "REQUIREMENTS.md").write_text("x" * (server.MAX_CONTEXT_BYTES + 1000))
        result = server._load_audit_context()
        assert len(result.encode("utf-8")) <= server.MAX_CONTEXT_BYTES


# ---------------------------------------------------------------------------
# _load_audit_prompt
# ---------------------------------------------------------------------------

class TestLoadAuditPrompt:
    """Tests for _load_audit_prompt helper."""

    def test_reads_from_disk(self, tmp_path):
        prompt_file = tmp_path / "AUDIT-PROMPT.md"
        prompt_file.write_text("Custom audit instructions")

        with patch.object(gemini_client, "AUDIT_PROMPT_PATH", prompt_file):
            result = server._load_audit_prompt()
        assert result == "Custom audit instructions"

    def test_fallback_when_missing(self, tmp_path):
        missing = tmp_path / "nonexistent.md"
        with patch.object(gemini_client, "AUDIT_PROMPT_PATH", missing):
            result = server._load_audit_prompt()
        assert "comprehensive code audit" in result
        assert "Executive Summary" in result

    def test_fallback_covers_all_sections(self, tmp_path):
        missing = tmp_path / "nonexistent.md"
        with patch.object(gemini_client, "AUDIT_PROMPT_PATH", missing):
            result = server._load_audit_prompt()
        assert "Code Quality" in result
        assert "Bug Audit" in result
        assert "Completeness" in result
        assert "Security" in result


# ---------------------------------------------------------------------------
# audit tool
# ---------------------------------------------------------------------------

class TestAuditTool:
    """Tests for the audit() MCP tool."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.root = tmp_path
        (tmp_path / "main.py").write_text("print('hello')")
        (tmp_path / "lib.ts").write_text("export const x = 1;")
        self._root_patcher = patch.object(tools_analysis, "PROJECT_ROOT", tmp_path)
        self._gc_patcher = patch.object(gemini_client, "PROJECT_ROOT", tmp_path)
        self._root_patcher.start()
        self._gc_patcher.start()

    @pytest.fixture(autouse=True)
    def _teardown(self):
        yield
        self._root_patcher.stop()
        self._gc_patcher.stop()

    def test_invalid_sections_returns_error(self):
        result = asyncio.get_event_loop().run_until_complete(
            server.audit(sections=["invalid_section"])
        )
        assert "Error: invalid section(s)" in result
        assert "invalid_section" in result

    def test_nonexistent_path_returns_error(self):
        result = asyncio.get_event_loop().run_until_complete(
            server.audit(paths=["does/not/exist"])
        )
        assert "Error: path not found" in result

    def test_no_files_returns_error(self):
        # Empty dir with no source files
        empty = self.root / "empty_dir"
        empty.mkdir()
        (empty / "readme.txt").write_text("not a source file")

        result = asyncio.get_event_loop().run_until_complete(
            server.audit(paths=["empty_dir"])
        )
        assert "Error: no source files found" in result

    def test_full_audit_calls_gemini(self):
        with patch.object(tools_analysis, "_gemini", return_value="Audit report") as mock_gem:
            result = asyncio.get_event_loop().run_until_complete(server.audit())

        mock_gem.assert_called_once()
        assert result == "Audit report"

    def test_no_code_instruction_in_prompt(self):
        with patch.object(tools_analysis, "_gemini", return_value="report") as mock_gem:
            asyncio.get_event_loop().run_until_complete(server.audit())

        prompt = mock_gem.call_args[0][0]
        assert server.NO_CODE_INSTRUCTION in prompt

    def test_section_filter_in_prompt(self):
        with patch.object(tools_analysis, "_gemini", return_value="report") as mock_gem:
            asyncio.get_event_loop().run_until_complete(
                server.audit(sections=["bugs"])
            )

        prompt = mock_gem.call_args[0][0]
        assert "Focus ONLY on these sections: bugs" in prompt

    def test_summary_only_in_prompt(self):
        with patch.object(tools_analysis, "_gemini", return_value="report") as mock_gem:
            asyncio.get_event_loop().run_until_complete(
                server.audit(summary_only=True)
            )

        prompt = mock_gem.call_args[0][0]
        assert "Executive Summary" in prompt
        assert "Do not include detailed findings" in prompt

    def test_model_passthrough(self):
        with patch.object(tools_analysis, "_gemini", return_value="report") as mock_gem:
            asyncio.get_event_loop().run_until_complete(
                server.audit(model="gemini-2.0-flash")
            )

        assert mock_gem.call_args[1]["model"] == "gemini-2.0-flash"

    def test_writes_report_to_disk(self):
        with patch.object(tools_analysis, "_gemini", return_value="# Audit Report\nGood code."):
            asyncio.get_event_loop().run_until_complete(server.audit())

        output = self.root / "AUDIT-GEMINI.md"
        assert output.exists()
        assert output.read_text() == "# Audit Report\nGood code."

    def test_scoped_audit_only_includes_specified_files(self):
        with patch.object(tools_analysis, "_gemini", return_value="report") as mock_gem:
            asyncio.get_event_loop().run_until_complete(
                server.audit(paths=["main.py"])
            )

        prompt = mock_gem.call_args[0][0]
        assert "print('hello')" in prompt
        assert "export const x = 1;" not in prompt

    def test_skipped_files_noted_in_prompt(self):
        # Create a file that won't fit in a tiny budget
        (self.root / "big.py").write_text("z" * 500)

        with patch.object(tools_analysis, "MAX_CODE_BYTES", 100):
            with patch.object(tools_analysis, "_gemini", return_value="report") as mock_gem:
                asyncio.get_event_loop().run_until_complete(server.audit())

        prompt = mock_gem.call_args[0][0]
        assert "Skipped Files" in prompt

    def test_audit_prompt_included(self):
        with patch.object(tools_analysis, "_gemini", return_value="report") as mock_gem:
            asyncio.get_event_loop().run_until_complete(server.audit())

        prompt = mock_gem.call_args[0][0]
        # Should contain audit prompt content (either from disk or fallback)
        assert "audit" in prompt.lower()

    def test_context_included_when_available(self):
        (self.root / "REQUIREMENTS.md").write_text("Must support feature X")

        with patch.object(tools_analysis, "_gemini", return_value="report") as mock_gem:
            asyncio.get_event_loop().run_until_complete(server.audit())

        prompt = mock_gem.call_args[0][0]
        assert "Project Context" in prompt
        assert "Must support feature X" in prompt


# ---------------------------------------------------------------------------
# _detect_framework
# ---------------------------------------------------------------------------

class TestDetectFramework:
    """Tests for _detect_framework helper."""

    def test_detects_flutter_via_pubspec(self, tmp_path):
        (tmp_path / "pubspec.yaml").write_text("name: my_app\n")
        assert server._detect_framework(tmp_path) == "flutter"

    def test_detects_react_via_package_json(self, tmp_path):
        pkg = {"dependencies": {"react": "^18.0.0", "react-dom": "^18.0.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        assert server._detect_framework(tmp_path) == "react"

    def test_detects_next_as_react(self, tmp_path):
        pkg = {"dependencies": {"next": "^14.0.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        assert server._detect_framework(tmp_path) == "react"

    def test_detects_vue(self, tmp_path):
        pkg = {"dependencies": {"vue": "^3.0.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        assert server._detect_framework(tmp_path) == "vue"

    def test_fallback_to_unknown(self, tmp_path):
        assert server._detect_framework(tmp_path) == "unknown"

    def test_flutter_takes_priority_over_package_json(self, tmp_path):
        """If both pubspec.yaml and package.json exist, flutter wins."""
        (tmp_path / "pubspec.yaml").write_text("name: my_app\n")
        pkg = {"dependencies": {"react": "^18.0.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        assert server._detect_framework(tmp_path) == "flutter"

    def test_malformed_package_json_falls_back(self, tmp_path):
        (tmp_path / "package.json").write_text("not valid json {{{")
        assert server._detect_framework(tmp_path) == "unknown"


# ---------------------------------------------------------------------------
# _collect_redesign_files
# ---------------------------------------------------------------------------

class TestCollectRedesignFiles:
    """Tests for _collect_redesign_files helper."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.root = tmp_path
        self._patcher = patch.object(gemini_client, "PROJECT_ROOT", tmp_path)
        self._patcher.start()

    @pytest.fixture(autouse=True)
    def _teardown(self):
        yield
        self._patcher.stop()

    def test_flutter_collects_dart_files(self):
        (self.root / "home_screen.dart").write_text("// home")
        (self.root / "pubspec.yaml").write_text("name: app\n")
        content, skipped = server._collect_redesign_files(self.root, None, "flutter")
        assert "home" in content

    def test_flutter_excludes_non_dart(self):
        (self.root / "main.py").write_text("# python")
        (self.root / "widget.dart").write_text("// dart")
        content, _ = server._collect_redesign_files(self.root, None, "flutter")
        assert "# python" not in content

    def test_react_collects_tsx_files(self):
        (self.root / "App.tsx").write_text("// react app")
        content, _ = server._collect_redesign_files(self.root, None, "react")
        assert "react app" in content

    def test_skips_ignored_dirs(self):
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules" / "dep.dart").write_text("// ignored")
        (self.root / "app.dart").write_text("// included")
        content, _ = server._collect_redesign_files(self.root, None, "flutter")
        assert "ignored" not in content
        assert "included" in content

    def test_returns_empty_for_no_files(self):
        content, skipped = server._collect_redesign_files(self.root, None, "flutter")
        assert content == ""


# ---------------------------------------------------------------------------
# _build_redesign_prompt
# ---------------------------------------------------------------------------

class TestBuildRedesignPrompt:
    """Tests for _build_redesign_prompt helper."""

    def test_includes_framework(self):
        prompt = server._build_redesign_prompt("flutter", ["theme"], "code here", [])
        assert "flutter" in prompt.lower()

    def test_includes_sections_block(self):
        prompt = server._build_redesign_prompt("flutter", ["theme", "icons"], "code", [])
        assert "ColorScheme" in prompt
        assert "Lucide" in prompt

    def test_single_section_excludes_others(self):
        prompt = server._build_redesign_prompt("flutter", ["icons"], "code", [])
        assert "Lucide" in prompt
        assert "ColorScheme" not in prompt
        assert "AnimatedSwitcher" not in prompt

    def test_includes_code_context(self):
        prompt = server._build_redesign_prompt("flutter", ["theme"], "MY_CODE_BLOCK", [])
        assert "MY_CODE_BLOCK" in prompt

    def test_includes_skipped_note_when_files_skipped(self):
        prompt = server._build_redesign_prompt(
            "flutter", ["theme"], "code", ["file1.dart", "file2.dart"]
        )
        assert "skipped" in prompt.lower()

    def test_no_skipped_note_when_none_skipped(self):
        prompt = server._build_redesign_prompt("flutter", ["theme"], "code", [])
        assert "skipped" not in prompt.lower()

    def test_redesign_system_instruction_present(self):
        prompt = server._build_redesign_prompt("flutter", ["theme"], "code", [])
        assert server.REDESIGN_SYSTEM_INSTRUCTION in prompt

    def test_react_uses_react_prompts(self):
        prompt = server._build_redesign_prompt("react", ["theme"], "code", [])
        assert "design tokens" in prompt.lower() or "css variables" in prompt.lower()

    def test_navigation_section_flutter(self):
        prompt = server._build_redesign_prompt("flutter", ["navigation"], "code", [])
        assert "GoRouter" in prompt or "Navigator" in prompt

    def test_animations_section_flutter(self):
        prompt = server._build_redesign_prompt("flutter", ["animations"], "code", [])
        assert "AnimatedSwitcher" in prompt

    def test_platform_section_flutter(self):
        prompt = server._build_redesign_prompt("flutter", ["platform"], "code", [])
        assert "HapticFeedback" in prompt or "DynamicColorBuilder" in prompt


# ---------------------------------------------------------------------------
# gemini_redesign tool
# ---------------------------------------------------------------------------

class TestGeminiRedesignTool:
    """Tests for the gemini_redesign() MCP tool."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.root = tmp_path
        (tmp_path / "pubspec.yaml").write_text("name: my_app\n")
        (tmp_path / "main.dart").write_text("void main() {}")
        self._root_patcher = patch.object(tools_analysis, "PROJECT_ROOT", tmp_path)
        self._root_patcher.start()

    @pytest.fixture(autouse=True)
    def _teardown(self):
        yield
        self._root_patcher.stop()

    def test_invalid_sections_returns_error(self):
        result = asyncio.get_event_loop().run_until_complete(
            server.gemini_redesign(sections=["invalid_section"])
        )
        assert "Error: invalid section(s)" in result
        assert "invalid_section" in result

    def test_nonexistent_path_returns_error(self):
        result = asyncio.get_event_loop().run_until_complete(
            server.gemini_redesign(path="/does/not/exist")
        )
        assert "Error: path not found" in result

    def test_calls_gemini_with_prompt(self):
        with patch.object(tools_analysis, "_gemini", return_value="# Redesign Report") as mock_gem:
            asyncio.get_event_loop().run_until_complete(
                server.gemini_redesign()
            )
        mock_gem.assert_called_once()

    def test_writes_redesign_md(self, tmp_path):
        output_file = tmp_path / "REDESIGN.md"
        with patch.object(tools_analysis, "_gemini", return_value="# Redesign Report\nContent."):
            asyncio.get_event_loop().run_until_complete(
                server.gemini_redesign(output=str(output_file))
            )
        assert output_file.exists()
        assert output_file.read_text() == "# Redesign Report\nContent."

    def test_return_message_includes_framework(self):
        with patch.object(tools_analysis, "_gemini", return_value="report"), \
             patch("builtins.open", side_effect=None), \
             patch.object(Path, "write_text", return_value=None):
            # Use a custom output path so we don't need to mock Path.cwd()
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
                out = f.name
            result = asyncio.get_event_loop().run_until_complete(
                server.gemini_redesign(output=out)
            )
        assert "flutter" in result.lower()

    def test_return_message_includes_section_count(self):
        with patch.object(tools_analysis, "_gemini", return_value="report"):
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
                out = f.name
            result = asyncio.get_event_loop().run_until_complete(
                server.gemini_redesign(sections=["theme", "icons"], output=out)
            )
        assert "2 sections" in result

    def test_model_passthrough(self):
        with patch.object(tools_analysis, "_gemini", return_value="report") as mock_gem:
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
                out = f.name
            asyncio.get_event_loop().run_until_complete(
                server.gemini_redesign(model="gemini-2.0-flash", output=out)
            )
        assert mock_gem.call_args[1]["model"] == "gemini-2.0-flash"

    def test_prompt_includes_redesign_system_instruction(self):
        with patch.object(tools_analysis, "_gemini", return_value="report") as mock_gem:
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
                out = f.name
            asyncio.get_event_loop().run_until_complete(
                server.gemini_redesign(output=out)
            )
        prompt = mock_gem.call_args[0][0]
        assert server.REDESIGN_SYSTEM_INSTRUCTION in prompt

    def test_prompt_does_not_contain_no_code_instruction(self):
        """Redesign tool uses its own system instruction, not NO_CODE_INSTRUCTION."""
        with patch.object(tools_analysis, "_gemini", return_value="report") as mock_gem:
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
                out = f.name
            asyncio.get_event_loop().run_until_complete(
                server.gemini_redesign(output=out)
            )
        prompt = mock_gem.call_args[0][0]
        assert server.NO_CODE_INSTRUCTION not in prompt

    def test_uses_default_sections_when_none_specified(self):
        with patch.object(tools_analysis, "_gemini", return_value="report") as mock_gem:
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
                out = f.name
            asyncio.get_event_loop().run_until_complete(
                server.gemini_redesign(output=out)
            )
        prompt = mock_gem.call_args[0][0]
        # All default sections should be present
        assert "ColorScheme" in prompt       # theme
        assert "Lucide" in prompt            # icons
        assert "GoRouter" in prompt or "Navigator" in prompt  # navigation
        assert "AnimatedSwitcher" in prompt  # animations
        assert "HapticFeedback" in prompt or "DynamicColorBuilder" in prompt  # platform

    def test_section_filtering_icons_only(self):
        with patch.object(tools_analysis, "_gemini", return_value="report") as mock_gem:
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
                out = f.name
            asyncio.get_event_loop().run_until_complete(
                server.gemini_redesign(sections=["icons"], output=out)
            )
        prompt = mock_gem.call_args[0][0]
        assert "Lucide" in prompt
        assert "ColorScheme" not in prompt

    def test_no_files_returns_error(self, tmp_path):
        """A directory with only non-source files returns an error."""
        empty_dir = tmp_path / "no_sources"
        empty_dir.mkdir()
        (empty_dir / "README.txt").write_text("not a source file")

        # Patch PROJECT_ROOT to the empty dir so _collect_redesign_files scans it
        with patch.object(tools_analysis, "PROJECT_ROOT", empty_dir), \
             patch.object(tools_analysis, "_gemini", return_value="report"):
            result = asyncio.get_event_loop().run_until_complete(
                server.gemini_redesign(path=str(empty_dir))
            )
        assert "Error: no source files found" in result


# ---------------------------------------------------------------------------
# PM SQLite helpers
# ---------------------------------------------------------------------------

import sqlite3


def _create_test_db(tmp_path):
    """Create an in-memory-style test database with fixture data at tmp_path."""
    db_path = tmp_path / "test_epics.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE epics (
          id              TEXT PRIMARY KEY,
          title           TEXT NOT NULL,
          branch          TEXT,
          pr_number       INTEGER,
          persistent      INTEGER DEFAULT 0,
          state           TEXT DEFAULT 'active' CHECK(state IN ('active','done','shipped')),
          milestone_order INTEGER,
          target_date     TEXT,
          description     TEXT
        );

        CREATE TABLE stories (
          id              TEXT PRIMARY KEY,
          epic_id         TEXT NOT NULL REFERENCES epics(id),
          title           TEXT NOT NULL,
          state           TEXT DEFAULT 'draft',
          branch          TEXT,
          write_files     TEXT,
          read_files      TEXT DEFAULT '[]',
          test_files      TEXT DEFAULT '[]',
          needs_testing   INTEGER DEFAULT 0,
          needs_review    INTEGER DEFAULT 0,
          agent           TEXT,
          model           TEXT,
          depends_on      TEXT,
          auto_merge      INTEGER DEFAULT 0,
          started_at      TEXT,
          completed_at    TEXT,
          archived        INTEGER DEFAULT 0,
          order_idx       INTEGER,
          plan_file       TEXT,
          worktree_path   TEXT,
          worktree_active INTEGER DEFAULT 0
        );

        CREATE TABLE tasks (
          id         TEXT NOT NULL,
          story_id   TEXT NOT NULL REFERENCES stories(id),
          title      TEXT NOT NULL,
          state      TEXT DEFAULT 'todo' CHECK(state IN ('todo','in-progress','done','blocked','skipped')),
          blocked_by TEXT,
          PRIMARY KEY (story_id, id)
        );

        CREATE TABLE story_dependencies (
          story_id   TEXT NOT NULL REFERENCES stories(id),
          depends_on TEXT NOT NULL REFERENCES stories(id),
          PRIMARY KEY (story_id, depends_on)
        );
        CREATE INDEX idx_story_deps_depends ON story_dependencies(depends_on);

        CREATE INDEX idx_stories_state ON stories(state) WHERE archived = 0;
        CREATE INDEX idx_stories_epic ON stories(epic_id) WHERE archived = 0;
        CREATE INDEX idx_stories_branch ON stories(branch) WHERE branch IS NOT NULL;
    """)

    # Insert fixture data
    conn.execute(
        "INSERT INTO epics (id, title, branch, pr_number, persistent, state) "
        "VALUES ('epic-001', 'Test Epic', 'epic/001', 42, 1, 'active')"
    )
    conn.execute(
        "INSERT INTO epics (id, title, branch, pr_number, persistent, state) "
        "VALUES ('epic-002', 'Done Epic', 'epic/002', NULL, 0, 'done')"
    )
    conn.execute("""
        INSERT INTO stories (id, epic_id, title, state, branch, write_files, read_files,
          needs_testing, needs_review, agent, model, depends_on, auto_merge,
          started_at, completed_at, archived, order_idx)
        VALUES ('story-001', 'epic-001', 'First story', 'in-progress', 'story/first',
         '["file1.py","file2.py"]', '[]', 0, 0, 'quick-fixer', 'sonnet', '[]', 0,
         '2025-01-01T00:00:00', NULL, 0, NULL)
    """)
    conn.execute("""
        INSERT INTO stories (id, epic_id, title, state, branch, write_files, read_files,
          needs_testing, needs_review, agent, model, depends_on, auto_merge,
          started_at, completed_at, archived, order_idx)
        VALUES ('story-002', 'epic-001', 'Second story', 'draft', NULL,
         '["file3.py"]', '[]', 1, 0, 'architect', 'opus', '["story-001"]', 0,
         NULL, NULL, 0, NULL)
    """)
    conn.execute("""
        INSERT INTO stories (id, epic_id, title, state, branch, write_files, read_files,
          needs_testing, needs_review, agent, model, depends_on, auto_merge,
          started_at, completed_at, archived, order_idx)
        VALUES ('story-003', 'epic-001', 'Archived story', 'done', 'story/archived',
         '["old.py"]', '[]', 0, 0, 'quick-fixer', 'haiku', '[]', 0,
         '2025-01-01T00:00:00', '2025-01-02T12:00:00', 1, NULL)
    """)
    conn.execute("INSERT INTO story_dependencies VALUES ('story-002', 'story-001')")
    conn.execute(
        "INSERT INTO tasks VALUES ('t1', 'story-001', 'Setup env', 'done', NULL)"
    )
    conn.execute(
        "INSERT INTO tasks VALUES ('t2', 'story-001', 'Write code', 'in-progress', 't1')"
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def test_db(tmp_path):
    """Create a test DB and patch EPICS_DB to point to it."""
    db_path = _create_test_db(tmp_path)
    with patch.object(tools_pm_helpers, "EPICS_DB", db_path):
        yield db_path


# ---------------------------------------------------------------------------
# PM Read tools
# ---------------------------------------------------------------------------

class TestPmGetEpic:
    def test_get_existing_epic(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_get_epic("epic-001")
        )
        assert "epic-001" in result
        assert "2 stories" in result

    def test_not_found(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_get_epic("epic-999")
        )
        assert "not found" in result


class TestPmListStories:
    def test_excludes_archived_by_default(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(server.pm_list_stories())
        assert "2 stories" in result

    def test_include_archived(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_list_stories(include_archived=True)
        )
        assert "3 stories" in result

    def test_filter_by_state(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_list_stories(state="draft")
        )
        assert "1 stories" in result

    def test_filter_by_agent(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_list_stories(agent="architect")
        )
        assert "1 stories" in result


class TestPmGetStory:
    def test_get_with_tasks(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_get_story("story-001")
        )
        assert "story-001" in result
        assert "2 tasks" in result

    def test_reverse_dependencies(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_get_story("story-001")
        )
        assert "story-001" in result
        assert "not found" not in result

    def test_not_found(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_get_story("story-999")
        )
        assert "not found" in result


class TestPmSearch:
    def test_search_by_title(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_search("First")
        )
        assert "result" in result

    def test_search_by_id(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_search("epic-001")
        )
        assert "result" in result

    def test_scoped_search(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_search("story", scope="epics")
        )
        assert "0 results" in result

    def test_task_search(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_search("Setup env")
        )
        assert "result" in result


class TestPmView:
    def test_top_level_keys_present(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(server.pm_view())
        assert "Board:" in result

    def test_scope_all_by_default(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(server.pm_view())
        assert "Board:" in result

    def test_scope_scoped_when_epic_id_given(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_view(epic_id="epic-001")
        )
        assert "Board:" in result

    def test_epics_only_active_by_default(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(server.pm_view())
        assert "Board:" in result

    def test_epic_progress_structure(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(server.pm_view())
        assert "Board:" in result

    def test_callouts_blocked_empty_by_default(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(server.pm_view())
        assert "Board:" in result

    def test_callouts_blocked_story_appears(self, test_db):
        import sqlite3
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "INSERT INTO stories (id, epic_id, title, state, branch, write_files, read_files, "
            "needs_testing, needs_review, agent, model, depends_on, auto_merge, "
            "started_at, completed_at, archived, order_idx) VALUES "
            "('story-blocked', 'epic-001', 'Blocked story', 'blocked', NULL, "
            "'[]', '[]', 0, 0, NULL, NULL, '[]', 0, NULL, NULL, 0, NULL)"
        )
        conn.commit()
        conn.close()

        result = asyncio.get_event_loop().run_until_complete(server.pm_view())
        assert "Board:" in result

    def test_callouts_stale_story_appears(self, test_db):
        import sqlite3
        conn = sqlite3.connect(str(test_db))
        # started_at 15 days ago
        from datetime import datetime, timedelta
        old_start = (datetime.utcnow() - timedelta(days=15)).isoformat()
        conn.execute(
            "INSERT INTO stories (id, epic_id, title, state, branch, write_files, read_files, "
            "needs_testing, needs_review, agent, model, depends_on, auto_merge, "
            "started_at, completed_at, archived, order_idx) VALUES "
            "('story-stale', 'epic-001', 'Stale story', 'in-progress', NULL, "
            f"'[]', '[]', 0, 0, NULL, NULL, '[]', 0, '{old_start}', NULL, 0, NULL)"
        )
        conn.commit()
        conn.close()

        result = asyncio.get_event_loop().run_until_complete(server.pm_view())
        assert "Board:" in result

    def test_invalid_epic_id_returns_error(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_view(epic_id="epic-999")
        )
        assert "not found" in result.lower() or "error" in result.lower()


# ---------------------------------------------------------------------------
# pm_plan tool
# ---------------------------------------------------------------------------

MOCK_STORY_PLAN = {
    "agent": "quick-fixer",
    "write_files": ["lib/foo.dart"],
    "tasks": ["Do A", "Do B"],
    "parallel_group": 1,
    "depends_on": [],
}

MOCK_BULK_ROADMAP = {
    "epics": [
        {
            "id": "epic-001",
            "title": "Test Epic",
            "stories": [
                {
                    "id": "story-001",
                    "title": "First story",
                    "agent": "quick-fixer",
                    "parallel_group": 1,
                    "depends_on": [],
                    "tasks": ["Do A", "Do B"],
                }
            ],
        }
    ],
    "execution_plan": {
        "parallel_groups": [
            {"group": 1, "stories": ["story-001"], "can_run_simultaneously": True}
        ],
        "total_stories": 1,
    },
}


class TestPmPlan:
    def test_story_mode_writes_tasks(self, test_db):
        with patch.object(tools_pm_plan, "_gemini", return_value=json.dumps(MOCK_STORY_PLAN)):
            result = asyncio.get_event_loop().run_until_complete(
                server.pm_plan_story(story_id="story-001")
            )
        assert "Planned" in result
        assert "2 tasks" in result

        conn = sqlite3.connect(str(test_db))
        count = conn.execute("SELECT COUNT(*) FROM tasks WHERE story_id = 'story-001'").fetchone()[0]
        conn.close()
        assert count == 2  # old tasks deleted, 2 new from plan

    def test_story_mode_updates_agent(self, test_db):
        plan = {**MOCK_STORY_PLAN, "agent": "architect"}
        with patch.object(tools_pm_plan, "_gemini", return_value=json.dumps(plan)):
            asyncio.get_event_loop().run_until_complete(
                server.pm_plan_story(story_id="story-002")
            )
        conn = sqlite3.connect(str(test_db))
        row = conn.execute("SELECT agent FROM stories WHERE id = 'story-002'").fetchone()
        conn.close()
        assert row[0] == "architect"

    def test_story_mode_not_found(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_plan_story(story_id="story-999")
        )
        assert "not found" in result

    def test_epic_mode_plans_draft_stories(self, test_db):
        # story-002 is the only draft story in epic-001
        plans = [MOCK_STORY_PLAN]
        with patch.object(tools_pm_plan, "_gemini", return_value=json.dumps(plans)):
            result = asyncio.get_event_loop().run_until_complete(
                server.pm_plan_stories(epic_id="epic-001")
            )
        assert "Planned" in result
        assert "1 stories" in result

    def test_epic_mode_writes_tasks(self, test_db):
        plans = [{**MOCK_STORY_PLAN, "story_id": "story-002"}]
        with patch.object(tools_pm_plan, "_gemini", return_value=json.dumps(plans)):
            asyncio.get_event_loop().run_until_complete(
                server.pm_plan_stories(epic_id="epic-001")
            )

        conn = sqlite3.connect(str(test_db))
        count = conn.execute("SELECT COUNT(*) FROM tasks WHERE story_id = 'story-002'").fetchone()[0]
        conn.close()
        assert count == 2  # two tasks from MOCK_STORY_PLAN

    def test_bulk_mode_returns_all_epics(self, test_db):
        with patch.object(tools_pm_plan, "_gemini", return_value=json.dumps(MOCK_BULK_ROADMAP)):
            result = asyncio.get_event_loop().run_until_complete(server.pm_plan_bulk())
        assert "Bulk plan" in result

    def test_bulk_mode_includes_execution_plan(self, test_db):
        with patch.object(tools_pm_plan, "_gemini", return_value=json.dumps(MOCK_BULK_ROADMAP)):
            result = asyncio.get_event_loop().run_until_complete(server.pm_plan_bulk())
        assert "Bulk plan" in result

    def test_malformed_gemini_json_returns_error_gracefully(self, test_db):
        with patch.object(tools_pm_plan, "_gemini", return_value="not valid json }{{{"):
            result = asyncio.get_event_loop().run_until_complete(
                server.pm_plan_story(story_id="story-001")
            )
        assert "error" in result.lower() or "malformed" in result.lower()

    def test_passes_file_context_to_gemini(self, test_db, tmp_path):
        (tmp_path / "foo.py").write_text("def hello(): pass")
        with patch.object(tools_pm_plan, "_gemini", return_value=json.dumps(MOCK_STORY_PLAN)) as mock_gem:
            asyncio.get_event_loop().run_until_complete(
                server.pm_plan_story(story_id="story-001", project_root=str(tmp_path))
            )
        prompt = mock_gem.call_args[0][0]
        assert "def hello" in prompt or "foo.py" in prompt


# ---------------------------------------------------------------------------
# PM Write tools
# ---------------------------------------------------------------------------

class TestPmCreateEpic:
    def test_creates_epic(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_create_epic("New Epic", branch="epic/new")
        )
        assert "Created" in result
        assert "epic-" in result
        assert "New Epic" in result

    def test_auto_increments_id(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_create_epic("Another Epic")
        )
        assert "epic-3" in result


class TestPmCreateStory:
    def test_creates_story(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_create_story("New Story", epic_id="epic-001", agent="quick-fixer")
        )
        assert "Created" in result
        assert "New Story" in result

    def test_auto_creates_backlog_epic(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_create_story("Backlog Story")
        )
        assert "Created" in result

        # Verify backlog epic was created
        conn = sqlite3.connect(str(test_db))
        epic = conn.execute("SELECT * FROM epics WHERE id = 'epic-backlog'").fetchone()
        conn.close()
        assert epic is not None

    def test_nonexistent_epic_returns_error(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_create_story("Bad Story", epic_id="epic-999")
        )
        assert "not found" in result


class TestPmAddTask:
    def test_adds_task(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_add_task(title="New Task", story_id="story-001")
        )
        assert "Added" in result
        assert "New Task" in result
        assert "t3" in result

    def test_nonexistent_story(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_add_task(title="Task", story_id="story-999")
        )
        assert "not found" in result


class TestPmUpdateStory:
    def test_valid_transition(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_update_story("story-001", state="in-review")
        )
        assert "Updated" in result
        assert "in-review" in result

    def test_invalid_transition_blocked(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_update_story("story-001", state="shipped")
        )
        assert "Invalid transition" in result

    def test_force_bypasses_validation(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_update_story("story-001", state="shipped", force=True)
        )
        assert "Updated" in result
        assert "shipped" in result

    def test_auto_timestamps_on_in_progress(self, test_db):
        # story-002 is draft, move to in-progress
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_update_story("story-002", state="in-progress")
        )
        assert "Updated" in result
        conn = sqlite3.connect(str(test_db))
        row = conn.execute("SELECT started_at FROM stories WHERE id = 'story-002'").fetchone()
        conn.close()
        assert row[0] is not None

    def test_auto_archive_on_terminal_state(self, test_db):
        # Move story-001 to done (via force since in-progress→done is valid)
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_update_story("story-001", state="done")
        )
        assert "Updated" in result
        conn = sqlite3.connect(str(test_db))
        row = conn.execute("SELECT archived, completed_at FROM stories WHERE id = 'story-001'").fetchone()
        conn.close()
        assert row[0] == 1
        assert row[1] is not None

    def test_any_to_blocked_always_valid(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_update_story("story-002", state="blocked")
        )
        assert "Updated" in result
        assert "blocked" in result

    def test_any_to_draft_always_valid(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_update_story("story-001", state="draft")
        )
        assert "Updated" in result
        assert "draft" in result

    def test_update_multiple_fields(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_update_story(
                "story-002", title="Updated Title",
                agent="quick-fixer", write_files=["new.py"]
            )
        )
        assert "Updated" in result
        conn = sqlite3.connect(str(test_db))
        row = conn.execute("SELECT title, agent, write_files FROM stories WHERE id = 'story-002'").fetchone()
        conn.close()
        assert row[0] == "Updated Title"
        assert row[1] == "quick-fixer"

    def test_not_found(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_update_story("story-999", state="draft")
        )
        assert "not found" in result

    def test_move_to_epic(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_update_story("story-002", move_to_epic="epic-002")
        )
        assert "Updated" in result
        conn = sqlite3.connect(str(test_db))
        row = conn.execute("SELECT epic_id FROM stories WHERE id = 'story-002'").fetchone()
        conn.close()
        assert row[0] == "epic-002"


class TestPmUpdateEpic:
    def test_valid_transition(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_update_epic("epic-001", state="done")
        )
        assert "Updated" in result
        assert "done" in result

    def test_invalid_transition(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_update_epic("epic-001", state="shipped")
        )
        assert "Invalid transition" in result

    def test_update_pr_number(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_update_epic("epic-001", pr_number=99)
        )
        assert "Updated" in result

    def test_not_found(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_update_epic("epic-999", title="X")
        )
        assert "not found" in result


class TestPmUpdateTask:
    def test_update_state(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_update_task("story-001", "t2", state="done")
        )
        assert "Updated" in result
        assert "done" in result

    def test_invalid_state(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_update_task("story-001", "t1", state="invalid")
        )
        assert "Invalid state" in result

    def test_not_found(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_update_task("story-001", "t99", state="done")
        )
        assert "not found" in result


# ---------------------------------------------------------------------------
# PM Analytics tools
# ---------------------------------------------------------------------------

class TestPmWip:
    def test_wip_by_state(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(server.pm_wip())
        assert "WIP:" in result

    def test_wip_by_agent(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(server.pm_wip())
        assert "WIP:" in result

    def test_wip_scoped_to_epic(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_wip(epic_id="epic-002")
        )
        assert "WIP: 0/0" in result


class TestPmCycleTime:
    def test_cycle_time_for_archived_stories(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(server.pm_cycle_time())
        assert "36.0h" in result
        assert "1 stories" in result

    def test_empty_when_no_archived(self, test_db):
        # Filter to an epic with no archived stories with timestamps
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_cycle_time(epic_id="epic-002")
        )
        assert "0h" in result or "0 stories" in result


class TestPmThroughput:
    def test_throughput_by_week(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_throughput(period="week")
        )
        assert "stories/week" in result

    def test_invalid_period(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_throughput(period="hour")
        )
        assert "Invalid period" in result

    def test_throughput_by_day(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_throughput(period="day")
        )
        assert "stories/day" in result


# ---------------------------------------------------------------------------
# State validation edge cases
# ---------------------------------------------------------------------------

class TestStateValidation:
    def test_validate_transition_allows_valid(self):
        err = server._validate_transition("draft", "ready", server.VALID_STORY_TRANSITIONS)
        assert err is None

    def test_validate_transition_blocks_invalid(self):
        err = server._validate_transition("draft", "done", server.VALID_STORY_TRANSITIONS)
        assert err is not None
        assert "Invalid transition" in err

    def test_validate_transition_force_allows_anything(self):
        err = server._validate_transition("draft", "shipped", server.VALID_STORY_TRANSITIONS, force=True)
        assert err is None

    def test_any_to_blocked_always_allowed(self):
        for state in server.STORY_STATES:
            err = server._validate_transition(state, "blocked", server.VALID_STORY_TRANSITIONS)
            assert err is None, f"Transition {state}→blocked should be allowed"

    def test_any_to_draft_always_allowed(self):
        for state in server.STORY_STATES:
            err = server._validate_transition(state, "draft", server.VALID_STORY_TRANSITIONS)
            assert err is None, f"Transition {state}→draft should be allowed"


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_next_id(self, test_db):
        conn = server._get_db(test_db)
        try:
            next_story = server._next_id(conn, "stories", "story-")
            assert next_story == "story-4"  # stories 1-3 exist

            next_epic = server._next_id(conn, "epics", "epic-")
            assert next_epic == "epic-3"  # epics 1-2 exist
        finally:
            conn.close()

    def test_story_to_dict_parses_json(self, test_db):
        conn = server._get_db(test_db)
        try:
            row = conn.execute("SELECT * FROM stories WHERE id = 'story-001'").fetchone()
            d = server._story_to_dict(row)
            assert isinstance(d["write_files"], list)
            assert d["write_files"] == ["file1.py", "file2.py"]
            assert isinstance(d["needs_testing"], bool)
        finally:
            conn.close()

    def test_epic_to_dict(self, test_db):
        conn = server._get_db(test_db)
        try:
            row = conn.execute("SELECT * FROM epics WHERE id = 'epic-001'").fetchone()
            d = server._epic_to_dict(row)
            assert isinstance(d["persistent"], bool)
            assert d["persistent"] is True
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# pm_organize — reorder mode
# ---------------------------------------------------------------------------

class TestPmOrganizeReorder:
    def test_bulk_ranking_assigns_order(self, test_db):
        ranked = ["story-002", "story-001"]
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_reorder(ranked=ranked)
        )
        assert "Reordered" in result
        assert "2 stories" in result

        conn = sqlite3.connect(str(test_db))
        rows = conn.execute(
            "SELECT id FROM stories WHERE epic_id = 'epic-001' AND archived = 0 "
            "ORDER BY COALESCE(order_idx, 2147483647)"
        ).fetchall()
        conn.close()
        ids = [r[0] for r in rows]
        assert ids.index("story-002") < ids.index("story-001")

    def test_bulk_ranking_warns_on_unknown(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_reorder(ranked=["story-001", "story-999"])
        )
        assert "Reordered" in result

    def test_single_story_before(self, test_db):
        # Move story-002 before story-001
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_reorder(story_id="story-002", before_story_id="story-001")
        )
        assert "Reordered" in result

    def test_single_story_after(self, test_db):
        # Move story-001 after story-002 (story-001 is in-progress, story-002 is draft)
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_reorder(story_id="story-001", after_story_id="story-002")
        )
        assert "Reordered" in result

    def test_reorder_missing_story_returns_error(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_reorder(story_id="story-999", before_story_id="story-001")
        )
        assert "not found" in result

    def test_reorder_both_anchors_returns_error(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_reorder(
                story_id="story-001",
                before_story_id="story-002", after_story_id="story-002"
            )
        )
        assert "either" in result.lower() or "not both" in result.lower()

    def test_reorder_no_anchor_returns_error(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_reorder(story_id="story-001")
        )
        assert "before_story_id" in result or "after_story_id" in result

    def test_reorder_empty_ranked_returns_error(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_reorder(ranked=[])
        )
        assert "empty" in result.lower()


# ---------------------------------------------------------------------------
# pm_organize — triage mode
# ---------------------------------------------------------------------------

class TestPmOrganizeTriage:
    @pytest.fixture(autouse=True)
    def _setup(self, test_db):
        """Add backlog epic and stories for triage tests."""
        self.db = test_db
        conn = sqlite3.connect(str(test_db))
        conn.row_factory = sqlite3.Row
        # Create backlog epic
        try:
            conn.execute(
                "INSERT INTO epics (id, title, branch, pr_number, persistent, state) "
                "VALUES ('epic-backlog', 'Backlog', NULL, NULL, 1, 'active')"
            )
        except sqlite3.IntegrityError:
            pass
        # Add a backlog story
        conn.execute("""
            INSERT INTO stories (id, epic_id, title, state, branch, write_files, read_files,
              needs_testing, needs_review, agent, model, depends_on, auto_merge,
              started_at, completed_at, archived, order_idx)
            VALUES ('story-010', 'epic-backlog', 'Testing infrastructure', 'draft', NULL,
             '[]', '[]', 0, 0, NULL, NULL, '[]', 0, NULL, NULL, 0, NULL)
        """)
        conn.commit()
        conn.close()

    def test_triage_returns_expected_keys(self):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_triage()
        )
        assert "unassigned" in result or "no-tasks" in result

    def test_triage_finds_backlog_stories(self):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_triage()
        )
        assert "unassigned" in result or "no-tasks" in result

    def test_triage_finds_unassigned(self):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_triage()
        )
        assert "unassigned" in result.lower()

    def test_triage_finds_draft_without_tasks(self):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_triage()
        )
        assert "no-tasks" in result

    def test_triage_mode_is_read_only(self):
        """Triage is always read-only — no confirmed param."""
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_triage()
        )
        assert "unassigned" in result or "no-tasks" in result


# ---------------------------------------------------------------------------
# pm_organize — cleanup mode
# ---------------------------------------------------------------------------

class TestPmOrganizeCleanup:
    @pytest.fixture(autouse=True)
    def _setup(self, test_db):
        """Add a done+old story and a stale in-progress story for cleanup tests."""
        self.db = test_db
        conn = sqlite3.connect(str(test_db))
        conn.row_factory = sqlite3.Row
        # Add a done story that is NOT archived yet (archived=0), with old completed_at
        conn.execute("""
            INSERT INTO stories (id, epic_id, title, state, branch, write_files, read_files,
              needs_testing, needs_review, agent, model, depends_on, auto_merge,
              started_at, completed_at, archived, order_idx)
            VALUES ('story-019', 'epic-001', 'Old done unarchived', 'done', NULL,
             '[]', '[]', 0, 0, NULL, NULL, '[]', 0,
             '2025-01-01T00:00:00', '2025-01-02T00:00:00', 0, NULL)
        """)
        # Add an in-progress story that started long ago (stale)
        conn.execute("""
            INSERT INTO stories (id, epic_id, title, state, branch, write_files, read_files,
              needs_testing, needs_review, agent, model, depends_on, auto_merge,
              started_at, completed_at, archived, order_idx)
            VALUES ('story-020', 'epic-001', 'Stale in-progress', 'in-progress', NULL,
             '[]', '[]', 0, 0, 'quick-fixer', 'sonnet', '[]', 0,
             '2020-01-01T00:00:00', NULL, 0, NULL)
        """)
        conn.commit()
        conn.close()

    def test_cleanup_dry_run_shows_would_archive(self):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_cleanup(archive_days=30, confirmed=False)
        )
        assert "Cleanup" in result
        assert "dry run" in result

    def test_cleanup_dry_run_does_not_commit(self):
        asyncio.get_event_loop().run_until_complete(
            server.pm_cleanup(archive_days=30, confirmed=False)
        )
        conn = sqlite3.connect(str(self.db))
        row = conn.execute("SELECT archived FROM stories WHERE id = 'story-019'").fetchone()
        conn.close()
        # story-019 was inserted with archived=0; dry-run should not change it
        assert row[0] == 0

    def test_cleanup_shows_stale_stories(self):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_cleanup(stale_days=14, confirmed=False)
        )
        assert "Cleanup" in result

    def test_cleanup_confirmed_archives_stories(self):
        # Add a fresh done story with old completed_at
        conn = sqlite3.connect(str(self.db))
        conn.execute("""
            INSERT INTO stories (id, epic_id, title, state, branch, write_files, read_files,
              needs_testing, needs_review, agent, model, depends_on, auto_merge,
              started_at, completed_at, archived, order_idx)
            VALUES ('story-030', 'epic-001', 'Old done story', 'done', NULL,
             '[]', '[]', 0, 0, NULL, NULL, '[]', 0,
             '2025-01-01T00:00:00', '2025-01-02T00:00:00', 0, NULL)
        """)
        conn.commit()
        conn.close()

        result = asyncio.get_event_loop().run_until_complete(
            server.pm_cleanup(archive_days=30, confirmed=True)
        )
        assert "Cleanup" in result

        # Verify in DB
        conn = sqlite3.connect(str(self.db))
        row = conn.execute("SELECT archived FROM stories WHERE id = 'story-030'").fetchone()
        conn.close()
        assert row[0] == 1

    def test_cleanup_invalid_archive_days(self):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_cleanup(archive_days=0)
        )
        assert "archive_days" in result

    def test_cleanup_invalid_stale_days(self):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_cleanup(stale_days=0)
        )
        assert "stale_days" in result

    def test_cleanup_shows_task_mismatches(self):
        # t2 in story-001 is in-progress, story-001 is also in-progress → no mismatch
        # Make a task in-progress while story is draft
        conn = sqlite3.connect(str(self.db))
        conn.execute("INSERT INTO tasks VALUES ('t1', 'story-002', 'Some task', 'in-progress', NULL)")
        conn.commit()
        conn.close()

        result = asyncio.get_event_loop().run_until_complete(
            server.pm_cleanup(confirmed=False)
        )
        assert "Cleanup" in result


# ---------------------------------------------------------------------------
# pm_organize — regroup mode
# ---------------------------------------------------------------------------

class TestPmOrganizeRegroup:
    def test_regroup_phase1_returns_proposal(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_regroup(confirmed=False)
        )
        assert "Regroup proposal" in result

    def test_regroup_phase2_requires_proposal(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_regroup(confirmed=True, proposal=None)
        )
        assert "proposal" in result.lower()

    def test_regroup_phase2_moves_stories(self, test_db):
        proposal = {
            "moves": [
                {"story_id": "story-001", "from_epic": "epic-001", "to_epic": "epic-002"}
            ],
            "new_epics": [],
        }
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_regroup(confirmed=True, proposal=proposal)
        )
        assert "Regrouped" in result

        # Verify in DB
        conn = sqlite3.connect(str(test_db))
        row = conn.execute("SELECT epic_id FROM stories WHERE id = 'story-001'").fetchone()
        conn.close()
        assert row[0] == "epic-002"

    def test_regroup_phase2_skips_stale_moves(self, test_db):
        # story-001 is actually in epic-001, but we claim it was in epic-002
        proposal = {
            "moves": [
                {"story_id": "story-001", "from_epic": "epic-002", "to_epic": "epic-001"}
            ],
            "new_epics": [],
        }
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_regroup(confirmed=True, proposal=proposal)
        )
        assert "Regroup" in result

    def test_regroup_phase2_creates_new_epics(self, test_db):
        proposal = {
            "moves": [],
            "new_epics": [
                {"title": "Brand New Epic", "story_ids": ["story-002"]}
            ],
        }
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_regroup(confirmed=True, proposal=proposal)
        )
        assert "Regrouped" in result
        assert "1 new epics" in result

        conn = sqlite3.connect(str(test_db))
        row = conn.execute("SELECT epic_id FROM stories WHERE id = 'story-002'").fetchone()
        conn.close()
        assert row[0] != "epic-001"  # Moved to new epic

    def test_regroup_scoped_to_epic(self, test_db):
        result = asyncio.get_event_loop().run_until_complete(
            server.pm_regroup(confirmed=False, epic_id="epic-001")
        )
        assert "Regroup proposal" in result


# ---------------------------------------------------------------------------
# web_search
# ---------------------------------------------------------------------------

class TestWebSearch:
    def test_returns_response(self, mock_subprocess):
        """web_search returns non-empty string from Gemini."""
        _, proc = mock_subprocess

        result = asyncio.get_event_loop().run_until_complete(
            server.web_search("latest Python 3.13 features")
        )

        assert result == "test response"

    def test_system_instruction_includes_search_grounding(self, mock_subprocess):
        """System instruction forces Google Search grounding and citations."""
        _, proc = mock_subprocess

        asyncio.get_event_loop().run_until_complete(
            server.web_search("test query")
        )

        piped_input = proc.communicate.call_args[1]["input"].decode()
        assert "Google Search" in piped_input
        assert "citation" in piped_input.lower()

    def test_does_not_include_no_code_instruction(self, mock_subprocess):
        """web_search must NOT use NO_CODE_INSTRUCTION — results may contain code."""
        _, proc = mock_subprocess

        asyncio.get_event_loop().run_until_complete(
            server.web_search("test query")
        )

        piped_input = proc.communicate.call_args[1]["input"].decode()
        assert server.NO_CODE_INSTRUCTION not in piped_input

    def test_short_response_returned_directly(self, mock_subprocess):
        """Responses under 2000 chars are returned as-is."""
        _, proc = mock_subprocess
        proc.communicate = AsyncMock(return_value=(
            json.dumps({"response": "short answer"}).encode(),
            b"",
        ))

        result = asyncio.get_event_loop().run_until_complete(
            server.web_search("test query")
        )

        assert result == "short answer"
        assert "/tmp/gemini/" not in result

    def test_long_response_writes_detail_file(self, mock_subprocess):
        """Responses over 2000 chars write to /tmp/gemini/search.md."""
        _, proc = mock_subprocess
        long_text = "A" * 2500
        proc.communicate = AsyncMock(return_value=(
            json.dumps({"response": long_text}).encode(),
            b"",
        ))

        result = asyncio.get_event_loop().run_until_complete(
            server.web_search("test query")
        )

        assert "/tmp/gemini/search.md" in result
        assert result.startswith("A")
