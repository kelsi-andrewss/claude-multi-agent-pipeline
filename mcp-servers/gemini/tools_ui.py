"""UI codegen tools: gemini_ui_code."""

from __future__ import annotations

from pathlib import Path

from constants import UI_CODEGEN_SYSTEM_INSTRUCTION, PROJECT_ROOT
from gemini_client import _gemini
from tools_analysis import _collect_redesign_files, _detect_framework


def register(mcp):
    @mcp.tool()
    async def gemini_ui_code(
        component_name: str,
        props_contract: str,
        requirements: str,
        exemplar_paths: list[str] | None = None,
        error_feedback: str | None = None,
        project_root: str | None = None,
        model: str | None = None,
        output_path: str | None = None,
    ) -> str:
        """Generate production-ready UI component code using Gemini.
        Produces markup and styles only — no state management, no data fetching,
        no business logic. Event handlers call props. Matches the project's
        framework and existing component patterns.

        Args:
            component_name: Name of the component to generate (e.g. "UserProfileCard", "SettingsPage").
            props_contract: TypeScript-style interface or description of props the component receives (data shape + callbacks).
            requirements: What the component should render, look like, and behave like.
            exemplar_paths: Optional list of 1-2 existing component file paths to match patterns from.
            error_feedback: Build/lint errors from a previous attempt — Gemini will fix only these errors without restructuring.
            project_root: Absolute path to the project root. Defaults to the server's working directory.
            model: Optional Gemini model ID override.
            output_path: If provided, write generated code directly to this file path and return a summary instead of the full source. Saves disk/transcript space.
        """
        _root = Path(project_root).resolve() if project_root else None
        scan_root = _root or PROJECT_ROOT

        framework = _detect_framework(scan_root)
        code_context, skipped = _collect_redesign_files(scan_root, exemplar_paths, framework)

        skipped_note = ""
        if skipped:
            skipped_note = (
                f"\n\nNote: {len(skipped)} file(s) were skipped due to budget limits: "
                + ", ".join(skipped[:5])
                + ("..." if len(skipped) > 5 else "")
            )

        full_prompt = (
            f"[System: {UI_CODEGEN_SYSTEM_INSTRUCTION}]\n\n"
            f"## Code Generation Request\n\n"
            f"Component: {component_name}\n"
            f"Framework: {framework}\n\n"
            f"## Props Contract\n\n"
            f"{props_contract}\n\n"
            f"## Requirements\n\n"
            f"{requirements}\n\n"
            f"## Exemplar Code\n\n"
            f"{code_context}"
            f"{skipped_note}"
        )

        if error_feedback:
            full_prompt += (
                f"\n\n## Previous Attempt Errors\n\n"
                f"{error_feedback}\n\n"
                f"Fix ONLY these errors. Do not restructure the component."
            )

        response = await _gemini(full_prompt, model=model)

        if output_path:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(response)
            line_count = response.count("\n") + 1
            return f"Wrote {component_name} to {output_path} ({line_count} lines, {len(response)} bytes)"

        return response

    return {
        "gemini_ui_code": gemini_ui_code,
    }
