"""UI codegen tools: gemini_ui_code, gemini_plan_library."""

from __future__ import annotations

import json
import re
from pathlib import Path

from constants import UI_CODEGEN_SYSTEM_INSTRUCTION, PROJECT_ROOT
from gemini_client import _gemini
from tools_analysis import _collect_redesign_files, _detect_framework

_DEFAULT_COMPONENT_TYPES = [
    "button", "card", "form", "input", "modal", "layout",
    "nav", "data-table", "sidebar", "header", "footer",
]

_FRAMEWORK_EXT = {
    "react": ".tsx",
    "vue": ".vue",
    "flutter": ".dart",
    "unknown": ".tsx",
}

_COMPONENT_CATEGORIES = {
    "button": "action",
    "card": "display",
    "form": "input",
    "input": "input",
    "modal": "overlay",
    "layout": "layout",
    "nav": "navigation",
    "data-table": "display",
    "sidebar": "navigation",
    "header": "layout",
    "footer": "layout",
}


def _type_to_component_name(component_type: str) -> str:
    """Convert a component type slug to PascalCase component name."""
    return "".join(part.capitalize() for part in component_type.split("-"))


def _extract_props_contract(code: str, component_name: str) -> str:
    """Extract props interface/type from generated code. Returns empty string if not found."""
    patterns = [
        rf"(interface\s+{component_name}Props\s*\{{[^}}]*\}})",
        rf"(type\s+{component_name}Props\s*=\s*\{{[^}}]*\}})",
        rf"(interface\s+\w*Props\s*\{{[^}}]*\}})",
    ]
    for pattern in patterns:
        match = re.search(pattern, code, re.DOTALL)
        if match:
            return match.group(1).strip()
    return ""


def _extract_code_block(response: str) -> str:
    """Extract code from a fenced code block if present, otherwise return raw."""
    match = re.search(r"```\w*\n(.*?)```", response, re.DOTALL)
    if match:
        return match.group(1).strip()
    return response.strip()


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

    @mcp.tool()
    async def gemini_plan_library(
        design_spec: str,
        component_types: list[str] | None = None,
        color_palette: str | None = None,
        typography: str | None = None,
        project_root: str | None = None,
        model: str | None = None,
    ) -> str:
        """Plan a component library: generate specs (names, typed props contracts, categories) for each component type. Writes specs to /tmp/gemini/library-plan.json. Use gemini_ui_code to generate the actual component code from these specs.

        Args:
            design_spec: Design specification describing the visual language, spacing, component behavior.
            component_types: Component types to plan. Defaults to: button, card, form, input, modal, layout, nav, data-table, sidebar, header, footer.
            color_palette: Color palette description (e.g. "primary: #3B82F6, secondary: #10B981, ...").
            typography: Typography spec (e.g. "font-family: Inter, heading sizes, body size").
            project_root: Absolute path to the project root (for framework detection).
            model: Optional Gemini model ID override.
        """
        _root = Path(project_root).resolve() if project_root else None
        scan_root = _root or PROJECT_ROOT
        types = component_types or list(_DEFAULT_COMPONENT_TYPES)

        framework = _detect_framework(scan_root)

        design_context_parts = [f"Framework: {framework}", f"Design Spec:\n{design_spec}"]
        if color_palette:
            design_context_parts.append(f"Color Palette: {color_palette}")
        if typography:
            design_context_parts.append(f"Typography: {typography}")
        design_context = "\n\n".join(design_context_parts)

        plan_prompt = (
            "You are a senior frontend engineer planning a component library.\n\n"
            f"## Design Context\n\n{design_context}\n\n"
            "## Task\n\n"
            f"For each of the following component types, produce a JSON array of specs.\n"
            f"Component types: {', '.join(types)}\n\n"
            "Each element must have exactly these keys:\n"
            '- "name": PascalCase component name (e.g. "DataTable")\n'
            '- "props_contract": full typed interface for the component props\n'
            '- "category": one of action, display, input, overlay, layout, navigation, general\n\n'
            "Return ONLY a JSON array. No prose, no markdown, no code blocks."
        )

        response = await _gemini(plan_prompt, model=model)

        try:
            specs = json.loads(response)
            if not (isinstance(specs, list) and all(isinstance(s, dict) and "name" in s for s in specs)):
                raise ValueError("Invalid spec format")
        except (json.JSONDecodeError, TypeError, ValueError):
            specs = [
                {
                    "name": _type_to_component_name(ct),
                    "props_contract": f"interface {_type_to_component_name(ct)}Props {{}}",
                    "category": _COMPONENT_CATEGORIES.get(ct, "general"),
                }
                for ct in types
            ]

        ext = _FRAMEWORK_EXT.get(framework, ".tsx")
        for spec in specs:
            spec["framework"] = framework
            spec["file_ext"] = ext

        out_dir = Path("/tmp/gemini")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "library-plan.json"
        out_path.write_text(json.dumps(specs, indent=2), encoding="utf-8")

        return f"Library plan: {len(specs)} components -> {out_path}"

    return {
        "gemini_ui_code": gemini_ui_code,
        "gemini_plan_library": gemini_plan_library,
    }
