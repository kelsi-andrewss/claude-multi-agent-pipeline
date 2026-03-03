"""Test runner tool: run project tests and analyze failures with Gemini."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from constants import NO_CODE_INSTRUCTION, PROJECT_ROOT, TEST_ANALYSIS_PROMPT
from gemini_client import _gemini


async def _run_tests(
    suite: str, tests: list[str] | None = None, timeout: int = 300
) -> tuple[str, bool]:
    """Run project tests and return (output_text, all_passed)."""
    if suite == "backend":
        venv_python = str(PROJECT_ROOT / ".venv" / "bin" / "python3")
        cmd = [venv_python, "-m", "pytest"]
        if tests:
            cmd.extend(tests)
        else:
            cmd.append("tests/")
        cmd.append("--tb=short")
        cwd = str(PROJECT_ROOT)
        env = {**os.environ, "PYTHONPATH": "."}
    elif suite == "frontend":
        cmd = ["flutter", "test"]
        cwd = str(PROJECT_ROOT / "flutter")
        env = None
    else:
        return (f"Unknown suite: {suite}", False)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
            env=env,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = stdout.decode(errors="replace")
        passed = proc.returncode == 0
        return (output, passed)
    except FileNotFoundError:
        executable = cmd[0]
        return (f"Executable not found: {executable}", False)
    except asyncio.TimeoutError:
        proc.kill()
        return (f"Tests timed out after {timeout}s", False)


def register(mcp):
    @mcp.tool()
    async def test(suite: str = "all", tests: list[str] | None = None) -> str:
        """Run project tests and analyze failures with Gemini. Returns a brief summary if all pass, or a structured failure analysis if any fail.

        Args:
            suite: Which test suite to run — "backend", "frontend", or "all" (default).
            tests: Optional specific test paths or pytest node IDs (backend only).
        """
        if suite not in ("backend", "frontend", "all"):
            return f"Invalid suite '{suite}'. Must be 'backend', 'frontend', or 'all'."

        results: list[tuple[str, str, bool]] = []

        if suite in ("backend", "all"):
            output, passed = await _run_tests("backend", tests=tests)
            results.append(("backend", output, passed))

        if suite in ("frontend", "all"):
            output, passed = await _run_tests("frontend")
            results.append(("frontend", output, passed))

        all_passed = all(passed for _, _, passed in results)

        combined_output = ""
        for name, output, passed in results:
            status = "PASSED" if passed else "FAILED"
            combined_output += f"=== {name.upper()} ({status}) ===\n{output}\n\n"

        if all_passed:
            summary_lines = []
            for name, _, passed in results:
                summary_lines.append(f"{name}: all tests passed")
            return "\n".join(summary_lines)

        max_bytes = 50_000
        if len(combined_output) > max_bytes:
            combined_output = (
                f"[...truncated {len(combined_output) - max_bytes} bytes from start...]\n"
                + combined_output[-max_bytes:]
            )

        full_prompt = (
            f"[System: {TEST_ANALYSIS_PROMPT}]\n\n"
            f"## Test Output\n\n{combined_output}"
        )
        return await _gemini(full_prompt)
