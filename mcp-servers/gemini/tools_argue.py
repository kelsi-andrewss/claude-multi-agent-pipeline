"""Argue tool: adversarial Claude vs Gemini debate loop."""

from __future__ import annotations

import json
from pathlib import Path

from constants import ARGUE_SYSTEM_INSTRUCTION, CONVERGENCE_PROMPT, NO_CODE_INSTRUCTION
from gemini_client import _gemini


def _argue_build_context_block(
    context_paths: list[str] | None,
    context_docs: list[str] | None,
) -> tuple[str, list[str]]:
    """Read context_paths (300-line truncation) and context_docs (verbatim). Returns (block, skipped)."""
    parts: list[str] = []
    skipped: list[str] = []

    if context_paths:
        for raw_path in context_paths:
            p = Path(raw_path).expanduser()
            if not p.exists():
                skipped.append(raw_path)
                continue
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
                truncated = "\n".join(lines[:300])
                if len(lines) > 300:
                    truncated += f"\n[...truncated at 300/{len(lines)} lines]"
                parts.append(f"### {p.name}\n\n{truncated}")
            except OSError:
                skipped.append(raw_path)

    if context_docs:
        for raw_path in context_docs:
            p = Path(raw_path).expanduser()
            if not p.exists():
                skipped.append(raw_path)
                continue
            try:
                parts.append(f"### {p.name}\n\n{p.read_text(encoding='utf-8', errors='replace')}")
            except OSError:
                skipped.append(raw_path)

    return "\n\n---\n\n".join(parts), skipped


def _argue_extract_challenge(response: str) -> str:
    """Extract the single strongest claim and form a targeted challenge."""
    claim_keywords = ["should", "must", "always", "never", "better", "worse", "superior",
                      "inferior", "recommend", "avoid", "prefer", "requires", "guarantees"]
    lines = [l.strip() for l in response.splitlines() if l.strip()]
    best_line = ""
    for line in lines:
        lower = line.lower()
        if any(kw in lower for kw in claim_keywords):
            best_line = line
            break
    if not best_line and lines:
        for line in lines:
            if len(line) > 40:
                best_line = line
                break
    if not best_line:
        best_line = response[:200]

    return (
        f"Challenge this specific claim: \"{best_line[:300]}\"\n\n"
        "Provide one focused counter-argument only. Be specific and avoid restating prior points."
    )


def register(mcp, seed_tools=None):
    seed_tools = seed_tools or {}

    @mcp.tool()
    async def argue(
        topic: str,
        topic_type: str = "general",
        context_paths: list[str] | None = None,
        context_docs: list[str] | None = None,
        seed_tool: str | None = None,
        seed_tool_args: dict | None = None,
        max_rounds: int = 4,
        model: str | None = None,
    ) -> str:
        """Adversarial debate loop: Claude vs Gemini challenge each other until convergence or round cap.

        Args:
            topic: The question, decision, or plan to debate.
            topic_type: One of plan | audit | bug | tech | general (default: general).
            context_paths: File paths to include as context (truncated to 300 lines each).
            context_docs: Markdown files to include verbatim.
            seed_tool: Optional tool to pre-seed context: "find_bug", "plan", or "audit".
            seed_tool_args: Arguments for the seed tool (passed as keyword args).
            max_rounds: Number of debate rounds, 1-8 (default: 4).
            model: Optional Gemini model ID override.
        """
        max_rounds = max(1, min(8, max_rounds))
        skipped: list[str] = []

        context_block, path_skipped = _argue_build_context_block(context_paths, context_docs)
        skipped.extend(path_skipped)

        seed_output = ""
        if seed_tool:
            tool_fn = seed_tools.get(seed_tool)
            if tool_fn:
                try:
                    args = seed_tool_args or {}
                    seed_output = await tool_fn(**args)
                except Exception as exc:
                    skipped.append(f"seed_tool '{seed_tool}' failed: {exc}")
                    seed_output = ""
            else:
                skipped.append(f"unknown seed_tool: {seed_tool}")

        opening_parts: list[str] = []
        if seed_output:
            opening_parts.append(f"## Seed Analysis\n\n{seed_output}")
        if context_block:
            opening_parts.append(f"## Context\n\n{context_block}")
        opening_parts.append(f"## Topic\n\n{topic}")
        if topic_type != "general":
            opening_parts[0] = f"Topic type: {topic_type}\n\n" + opening_parts[0]

        opening_turn = "\n\n---\n\n".join(opening_parts)

        messages: list[dict[str, str]] = [{"role": "user", "content": opening_turn}]
        converged = False
        tension_summary = ""
        consecutive_converged = 0

        for round_num in range(1, max_rounds + 1):
            # Fix: call _gemini directly with ARGUE_SYSTEM_INSTRUCTION to avoid
            # double NO_CODE_INSTRUCTION that gemini_chat() would add
            conversation_lines = []
            for msg in messages:
                role = msg.get("role", "user").capitalize()
                conversation_lines.append(f"{role}: {msg.get('content', '')}")
            conversation = "\n".join(conversation_lines)

            gemini_prompt = f"[System: {ARGUE_SYSTEM_INSTRUCTION}]\n\n{conversation}"
            gemini_response = await _gemini(gemini_prompt, model=model)

            if gemini_response.startswith("[gemini error"):
                return json.dumps({
                    "error": f"Gemini unreachable on round {round_num}: {gemini_response}",
                    "topic": topic,
                    "topic_type": topic_type,
                    "rounds_run": round_num - 1,
                    "converged": False,
                    "skipped_paths": skipped,
                })

            messages.append({"role": "model", "content": gemini_response})

            if max_rounds == 1:
                tension_summary = "Single round — no convergence probe."
                break

            challenge = _argue_extract_challenge(gemini_response)
            messages.append({"role": "user", "content": challenge})

            exchange_so_far = "\n\n".join(
                f"{m['role'].upper()}: {m['content']}" for m in messages
            )
            convergence_input = f"{CONVERGENCE_PROMPT}{exchange_so_far}"
            verdict_raw = await _gemini(convergence_input, model=model)

            first_line = verdict_raw.strip().splitlines()[0].strip().upper() if verdict_raw.strip() else ""
            remaining_lines = verdict_raw.strip().splitlines()[1:] if verdict_raw.strip().count("\n") else []
            tension_summary = " ".join(remaining_lines).strip() or "none"

            if first_line.startswith("YES"):
                consecutive_converged += 1
            else:
                consecutive_converged = 0

            if consecutive_converged >= 2:
                converged = True
                break

        result = {
            "topic": topic,
            "topic_type": topic_type,
            "rounds_run": len([m for m in messages if m["role"] == "model"]),
            "converged": converged,
            "tension_summary": tension_summary,
            "messages": messages,
        }
        if skipped:
            result["skipped_paths"] = skipped

        return json.dumps(result)
