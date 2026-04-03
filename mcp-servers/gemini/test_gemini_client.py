"""Tests for _gemini timeout and retry behavior."""

from __future__ import annotations

import asyncio
import json
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
from constants import TIMEOUT_MEDIUM


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
