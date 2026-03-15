"""Design tools: gemini_design."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from constants import DESIGN_SYSTEM_INSTRUCTION, PROJECT_ROOT
from format_response import fmt_design
from gemini_client import _gemini
from tools_analysis import _collect_redesign_files, _detect_framework


def register(mcp):
    @mcp.tool()
    async def gemini_design(
        component_name: str,
        requirements: str,
        paths: list[str] | None = None,
        project_root: str | None = None,
        model: str | None = None,
    ) -> str:
        """Generate a structural UI design specification for a component using Gemini.
        Produces a design spec with widget tree, layout hierarchy, visual properties,
        and interaction patterns. Does not generate implementation code.

        Args:
            component_name: Name of the component to design (e.g. "UserProfileCard", "SettingsPage").
            requirements: Natural language description of what the component should do, look like, and how it should behave.
            paths: Optional list of files/directories to scope codebase context (existing code the design should integrate with).
            project_root: Absolute path to the project root. Defaults to the server's working directory.
            model: Optional Gemini model ID override.
        """
        _root = Path(project_root).resolve() if project_root else None
        scan_root = _root or PROJECT_ROOT

        framework = _detect_framework(scan_root)
        code_context, skipped = _collect_redesign_files(scan_root, paths, framework)

        today = date.today().isoformat()

        skipped_note = ""
        if skipped:
            skipped_note = (
                f"\n\nNote: {len(skipped)} file(s) were skipped due to budget limits: "
                + ", ".join(skipped[:5])
                + ("..." if len(skipped) > 5 else "")
            )

        full_prompt = (
            f"[System: {DESIGN_SYSTEM_INSTRUCTION}]\n\n"
            f"## Design Request\n\n"
            f"Component: {component_name}\n"
            f"Framework: {framework}\n"
            f"Date: {today}\n\n"
            f"## Requirements\n\n"
            f"{requirements}\n\n"
            f"## Existing Codebase\n\n"
            f"{code_context}"
            f"{skipped_note}"
        )

        response = await _gemini(full_prompt, model=model)
        return fmt_design(response, component_name)

    return {
        "gemini_design": gemini_design,
    }
