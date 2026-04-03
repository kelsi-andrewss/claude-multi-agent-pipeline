"""Tests for _gemini timeout/retry behavior and audit two-pass flow."""

from __future__ import annotations

import asyncio
import json
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

import sys
from pathlib import Path

# Ensure the gemini server package is importable
sys.path.insert(0, str(Path(__file__).parent))

from gemini_client import (
    _gemini,
    GeminiTimeoutError,
    GeminiCLIError,
    GeminiParseError,
)
from constants import TIMEOUT_MEDIUM, TIMEOUT_HEAVY
from tools_analysis import _extract_signatures, _do_audit


@pytest.fixture
def mock_proc():
    """Create a mock subprocess that returns valid JSON."""
    proc = AsyncMock()
    proc.communicate = AsyncMock(
        return_value=(json.dumps({"response": "ok"}).encode(), b"")
    )
    proc.returncode = 0
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


@pytest.mark.asyncio
async def test_gemini_default_timeout(mock_proc):
    """_gemini without explicit timeout uses TIMEOUT_MEDIUM (180s)."""
    with patch("gemini_client.asyncio.create_subprocess_exec", return_value=mock_proc):
        with patch("gemini_client.asyncio.wait_for", wraps=asyncio.wait_for) as mock_wait:
            # wait_for will call proc.communicate which returns our mock data
            await _gemini("hi")
            mock_wait.assert_called_once()
            _, kwargs = mock_wait.call_args
            assert kwargs["timeout"] == TIMEOUT_MEDIUM


@pytest.mark.asyncio
async def test_gemini_custom_timeout(mock_proc):
    """_gemini with explicit timeout=60 passes 60 to wait_for."""
    with patch("gemini_client.asyncio.create_subprocess_exec", return_value=mock_proc):
        with patch("gemini_client.asyncio.wait_for", wraps=asyncio.wait_for) as mock_wait:
            await _gemini("hi", timeout=60)
            mock_wait.assert_called_once()
            _, kwargs = mock_wait.call_args
            assert kwargs["timeout"] == 60


@pytest.mark.asyncio
async def test_gemini_timeout_error_message(mock_proc):
    """Timeout error message includes the actual timeout value passed."""
    with patch("gemini_client.asyncio.create_subprocess_exec", return_value=mock_proc):
        with patch("gemini_client.asyncio.wait_for", side_effect=asyncio.TimeoutError):
            with pytest.raises(GeminiTimeoutError, match="42s"):
                await _gemini("hi", timeout=42, max_retries=0)


# --- Retry / backoff tests ---


def _make_proc(*, returncode=0, stdout=None, stderr=b""):
    """Build a mock subprocess with the given outcome."""
    proc = AsyncMock()
    if stdout is None:
        stdout = json.dumps({"response": "ok"}).encode()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


@pytest.mark.asyncio
async def test_retries_on_timeout():
    """GeminiTimeoutError triggers retry; success on 2nd attempt returns normally."""
    good_proc = _make_proc()
    timeout_proc = _make_proc()
    # wait_for is called 3 times:
    #   1) proc.communicate — raises TimeoutError
    #   2) proc.wait inside terminate handler — succeeds (returns None)
    #   3) proc.communicate on retry — returns good data
    with patch("gemini_client.asyncio.create_subprocess_exec", side_effect=[timeout_proc, good_proc]):
        with patch("gemini_client.asyncio.wait_for") as mock_wf:
            mock_wf.side_effect = [
                asyncio.TimeoutError,   # 1st attempt communicate — timeout
                None,                   # terminate handler proc.wait
                (json.dumps({"response": "ok"}).encode(), b""),  # 2nd attempt — success
            ]
            with patch("gemini_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                result = await _gemini("hi", max_retries=2)
    assert result == "ok"
    mock_sleep.assert_called_once()


@pytest.mark.asyncio
async def test_retries_on_cli_error():
    """GeminiCLIError triggers retry; success on 2nd attempt returns normally."""
    fail_proc = _make_proc(returncode=1, stderr=b"rate limited")
    good_proc = _make_proc()
    with patch("gemini_client.asyncio.create_subprocess_exec", side_effect=[fail_proc, good_proc]):
        with patch("gemini_client.asyncio.wait_for") as mock_wf:
            mock_wf.side_effect = [
                (b"", b"rate limited"),  # first attempt — CLI error
                (json.dumps({"response": "ok"}).encode(), b""),  # second attempt
            ]
            # Override returncode per call
            fail_proc.returncode = 1
            good_proc.returncode = 0
            with patch("gemini_client.asyncio.sleep", new_callable=AsyncMock):
                result = await _gemini("hi", max_retries=2)
    assert result == "ok"


@pytest.mark.asyncio
async def test_no_retry_on_parse_error():
    """GeminiParseError is raised immediately with no retry."""
    bad_proc = _make_proc(stdout=b"not json at all")
    with patch("gemini_client.asyncio.create_subprocess_exec", return_value=bad_proc):
        with patch("gemini_client.asyncio.wait_for", return_value=(b"not json at all", b"")):
            with patch("gemini_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                with pytest.raises(GeminiParseError):
                    await _gemini("hi", max_retries=3)
    mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_max_retries_zero_no_retry():
    """max_retries=0 means a single attempt with no retry."""
    timeout_proc = _make_proc()
    with patch("gemini_client.asyncio.create_subprocess_exec", return_value=timeout_proc):
        with patch("gemini_client.asyncio.wait_for", side_effect=asyncio.TimeoutError):
            with patch("gemini_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                with pytest.raises(GeminiTimeoutError):
                    await _gemini("hi", max_retries=0)
    mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_backoff_intervals():
    """Backoff delays follow 2^attempt pattern (jitter adds 0-1s)."""
    timeout_proc = _make_proc()
    # All 4 attempts (1 initial + 3 retries) timeout
    with patch("gemini_client.asyncio.create_subprocess_exec", return_value=timeout_proc):
        with patch("gemini_client.asyncio.wait_for", side_effect=asyncio.TimeoutError):
            with patch("gemini_client.random.uniform", return_value=0.5):
                with patch("gemini_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                    with pytest.raises(GeminiTimeoutError):
                        await _gemini("hi", max_retries=3)
    # 3 retries => 3 sleep calls: 2^1+0.5=2.5, 2^2+0.5=4.5, 2^3+0.5=8.5
    assert mock_sleep.call_count == 3
    delays = [c.args[0] for c in mock_sleep.call_args_list]
    assert delays == [2.5, 4.5, 8.5]


@pytest.mark.asyncio
async def test_final_exception_propagated():
    """After exhausting retries the last exception is raised, not a wrapper."""
    fail_proc = _make_proc(returncode=1, stderr=b"server error")
    with patch("gemini_client.asyncio.create_subprocess_exec", return_value=fail_proc):
        with patch("gemini_client.asyncio.wait_for", return_value=(b"", b"server error")):
            with patch("gemini_client.asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(GeminiCLIError, match="server error"):
                    await _gemini("hi", max_retries=2)


# --- Two-pass audit tests ---


@pytest.mark.asyncio
async def test_two_pass_audit_calls_gemini_twice():
    """Two-pass audit calls _gemini exactly twice: triage then deep dive."""
    triage_json = json.dumps({
        "flagged_files": ["src/app.py"],
        "dead_code_candidates": [],
    })

    gemini_calls = []

    async def mock_gemini(prompt, *, model=None, timeout=TIMEOUT_MEDIUM, max_retries=3):
        gemini_calls.append({"prompt": prompt, "timeout": timeout})
        if len(gemini_calls) == 1:
            return triage_json
        return "Audit report content"

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        src = root / "src"
        src.mkdir()
        (src / "app.py").write_text("def main():\n    pass\n")
        (root / "AUDIT-GEMINI.md").touch()

        with patch("tools_analysis._gemini", side_effect=mock_gemini):
            with patch("tools_analysis._load_audit_context", return_value=""):
                with patch("tools_analysis._load_audit_prompt", return_value="Audit prompt"):
                    result = await _do_audit(project_root=str(root))

    assert len(gemini_calls) == 2
    assert "triage" in gemini_calls[0]["prompt"].lower()
    assert gemini_calls[0]["timeout"] == TIMEOUT_MEDIUM
    assert gemini_calls[1]["timeout"] == TIMEOUT_HEAVY
    assert result == "Audit report content"


@pytest.mark.asyncio
async def test_triage_failure_falls_back_to_single_pass():
    """When triage returns a Gemini error, falls back to single-pass with all files."""
    gemini_calls = []

    async def mock_gemini(prompt, *, model=None, timeout=TIMEOUT_MEDIUM, max_retries=3):
        gemini_calls.append({"prompt": prompt, "timeout": timeout})
        if len(gemini_calls) == 1:
            raise GeminiTimeoutError("No response after 180s")
        return "Fallback report"

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "a.py").write_text("def foo():\n    pass\n")
        (root / "b.py").write_text("def bar():\n    pass\n")

        with patch("tools_analysis._gemini", side_effect=mock_gemini):
            with patch("tools_analysis._load_audit_context", return_value=""):
                with patch("tools_analysis._load_audit_prompt", return_value="Audit prompt"):
                    result = await _do_audit(project_root=str(root))

    assert result == "Fallback report"
    assert len(gemini_calls) == 2
    # Second call (deep dive) should contain both files since triage failed
    deep_prompt = gemini_calls[1]["prompt"]
    assert "a.py" in deep_prompt
    assert "b.py" in deep_prompt


@pytest.mark.asyncio
async def test_dead_code_candidates_in_deep_dive_prompt():
    """Dead code candidates from triage appear in the deep dive prompt."""
    triage_json = json.dumps({
        "flagged_files": ["mod.py"],
        "dead_code_candidates": [
            {"file": "mod.py", "name": "orphaned_helper", "type": "function"},
            {"file": "mod.py", "name": "OldWidget", "type": "class"},
        ],
    })

    gemini_calls = []

    async def mock_gemini(prompt, *, model=None, timeout=TIMEOUT_MEDIUM, max_retries=3):
        gemini_calls.append(prompt)
        if len(gemini_calls) == 1:
            return triage_json
        return "Report with dead code"

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "mod.py").write_text("def orphaned_helper():\n    pass\n\nclass OldWidget:\n    pass\n")

        with patch("tools_analysis._gemini", side_effect=mock_gemini):
            with patch("tools_analysis._load_audit_context", return_value=""):
                with patch("tools_analysis._load_audit_prompt", return_value="Audit prompt"):
                    await _do_audit(project_root=str(root))

    deep_prompt = gemini_calls[1]
    assert "Dead Code Candidates" in deep_prompt
    assert "orphaned_helper" in deep_prompt
    assert "OldWidget" in deep_prompt


def test_extract_signatures_extracts_defs_and_imports():
    """_extract_signatures returns only signature lines, not function bodies."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "sample.py").write_text(
            "import os\n"
            "from pathlib import Path\n"
            "\n"
            "SECRET = 'should_not_appear'\n"
            "\n"
            "def process_data(x):\n"
            "    return x * 2\n"
            "\n"
            "class MyHandler:\n"
            "    def handle(self):\n"
            "        pass\n"
        )
        (root / "utils.js").write_text(
            "export function fetchData() {\n"
            "  return null;\n"
            "}\n"
            "const internal = 42;\n"
            "export default class ApiClient {\n"
            "  constructor() {}\n"
            "}\n"
        )

        files = sorted(root.glob("*.*"))
        result = _extract_signatures(files, root=root)

    assert "import os" in result
    assert "from pathlib import Path" in result
    assert "def process_data(x):" in result
    assert "class MyHandler:" in result
    assert "export function fetchData()" in result
    assert "export default class ApiClient" in result
    # Body lines and non-signature constants must NOT appear
    assert "should_not_appear" not in result
    assert "return x * 2" not in result
    assert "const internal" not in result
