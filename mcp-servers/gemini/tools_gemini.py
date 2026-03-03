"""Core Gemini tools: gemini_generate, gemini_chat, fetch_doc, plan, analyze."""

from __future__ import annotations

from constants import DOCUMENTS, NO_CODE_INSTRUCTION, PROJECT_ROOT
from gemini_client import _gemini, _read_doc


async def _do_plan(task: str, documents: list[str] | None = None) -> str:
    """Core plan logic, callable directly without MCP registration."""
    if documents is None:
        documents = ["claude", "requirements", "architecture"]

    context_parts: list[str] = []
    for key in documents:
        content = _read_doc(key)
        label = DOCUMENTS.get(key, {}).get("description", key)
        context_parts.append(f"### {label}\n\n{content}")

    context_block = "\n\n---\n\n".join(context_parts)

    plan_system = (
        "You are a senior developer on this project. Given the task and project context, "
        "produce a concrete implementation plan. Include:\n"
        "1. Numbered steps with specific file paths and function names\n"
        "2. Key risks or edge cases to watch for\n"
        "3. Testing strategy (what to test, how)\n"
        "4. Dependencies or prerequisites\n"
        "Keep it actionable — no hand-waving.\n\n"
        f"{NO_CODE_INSTRUCTION}"
    )

    full_prompt = (
        f"## Task\n{task}\n\n"
        f"## Project Context\n{context_block}"
    )
    return await _gemini(full_prompt, system_instruction=plan_system)


def register(mcp):
    @mcp.tool()
    async def gemini_generate(
        prompt: str,
        model: str | None = None,
        system_instruction: str | None = None,
    ) -> str:
        """Raw Gemini prompt — no project context injected. Use plan() for implementation planning or analyze() for code/design review instead.

        Args:
            prompt: The input prompt to send to Gemini.
            model: Optional Gemini model ID. Omit to use CLI default.
            system_instruction: Optional system instruction to guide the model.
        """
        combined_instruction = NO_CODE_INSTRUCTION
        if system_instruction:
            combined_instruction = f"{NO_CODE_INSTRUCTION}\n\n{system_instruction}"
        return await _gemini(prompt, model=model, system_instruction=combined_instruction)

    @mcp.tool()
    async def gemini_chat(
        messages: list[dict[str, str]],
        model: str | None = None,
        system_instruction: str | None = None,
    ) -> str:
        """Raw multi-turn Gemini conversation — no project context injected. Use for back-and-forth dialogue only.

        Args:
            messages: List of message objects with "role" ("user" or "model") and "content" keys.
            model: Optional Gemini model ID. Omit to use CLI default.
            system_instruction: Optional system instruction to guide the model.
        """
        lines = []
        for msg in messages:
            role = msg.get("role", "user").capitalize()
            lines.append(f"{role}: {msg.get('content', '')}")
        conversation = "\n".join(lines)

        combined_instruction = NO_CODE_INSTRUCTION
        if system_instruction:
            combined_instruction = f"{NO_CODE_INSTRUCTION}\n\n{system_instruction}"
        return await _gemini(conversation, model=model, system_instruction=combined_instruction)

    @mcp.tool()
    async def fetch_doc(document: str = "list") -> str:
        """Retrieve an Advocate project document by key (CLAUDE.md, REQUIREMENTS.md, etc.).

        Args:
            document: Document key to retrieve, or "list" to see all available documents.
        """
        if document == "list":
            lines = ["| Key | File | Lines | Description |", "| --- | --- | ---: | --- |"]
            for key, info in DOCUMENTS.items():
                file_path = PROJECT_ROOT / info["path"]
                if file_path.exists():
                    line_count = len(file_path.read_text(encoding="utf-8").splitlines())
                else:
                    line_count = 0
                lines.append(f"| `{key}` | `{info['path']}` | {line_count} | {info['description']} |")
            return "\n".join(lines)

        if document not in DOCUMENTS:
            valid_keys = ", ".join(DOCUMENTS.keys())
            return f"Unknown document '{document}'. Valid keys: {valid_keys}"

        file_path = PROJECT_ROOT / DOCUMENTS[document]["path"]
        if not file_path.exists():
            return f"File not found: {DOCUMENTS[document]['path']}"

        return file_path.read_text(encoding="utf-8")

    @mcp.tool()
    async def plan(
        task: str,
        documents: list[str] | None = None,
    ) -> str:
        """Generate an implementation plan for a task. Automatically loads CLAUDE.md, REQUIREMENTS.md, and ARCHITECTURE.md as context and uses a senior-developer system prompt. Prefer this over gemini_generate for any planning task.

        Args:
            task: Description of what needs to be implemented.
            documents: Document keys to include as context (default: claude, requirements, architecture).
                Use fetch_doc(document="list") to see available keys.
        """
        return await _do_plan(task, documents)

    @mcp.tool()
    async def analyze(
        input: str,
        context: str | None = None,
    ) -> str:
        """Review code or a design proposal against project conventions. Automatically loads CLAUDE.md as context and returns a structured verdict (APPROVE/NEEDS CHANGES/REJECT for code, PROCEED/REVISE/RECONSIDER for design). Prefer this over gemini_generate for any review task.

        Args:
            input: Code snippet or design description to analyze.
            context: Optional additional context about what the input is for.
        """
        project_conventions = _read_doc("claude")

        prompt_parts = [f"## Input\n\n{input}"]
        if context:
            prompt_parts.append(f"## Additional Context\n\n{context}")
        prompt_parts.append(f"## Project Conventions\n\n{project_conventions}")

        analyze_system = (
            "You are a senior architect reviewing submissions for this project. "
            "Auto-detect whether the input is code or a design proposal.\n\n"
            "For CODE: review for correctness, style adherence, edge cases, security. "
            "Give a verdict: APPROVE, NEEDS CHANGES, or REJECT with specific line-level feedback.\n\n"
            "For DESIGN: evaluate feasibility, alignment with project architecture, trade-offs. "
            "Give a verdict: PROCEED, REVISE, or RECONSIDER with concrete reasoning.\n\n"
            "Be opinionated and direct. Reference project conventions where relevant.\n\n"
            f"{NO_CODE_INSTRUCTION}"
        )

        full_prompt = "\n\n".join(prompt_parts)
        return await _gemini(full_prompt, system_instruction=analyze_system)

    return {
        "gemini_chat": gemini_chat,
        "plan": plan,
        "analyze": analyze,
    }
