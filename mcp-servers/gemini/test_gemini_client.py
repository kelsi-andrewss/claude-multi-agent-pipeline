"""Tests for _gemini timeout behavior."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import sys
from pathlib import Path

# Ensure the gemini server package is importable
sys.path.insert(0, str(Path(__file__).parent))

from gemini_client import _gemini, GeminiTimeoutError
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
                await _gemini("hi", timeout=42)
