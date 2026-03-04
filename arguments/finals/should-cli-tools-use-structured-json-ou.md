# Argue: Should CLI tools use structured JSON output by default, or human-readable text with optional --json flags?
**Type**: general  **Rounds**: 2  **Converged**: yes
**Date**: 2026-03-04

## Synthesis

**Agreed position:** CLI tools should default to human-readable text with an opt-in `--json` flag. The case rests purely on interactive ergonomics: humans scan spatial patterns, operate in discovery loops where curated views beat raw data, and sometimes work in minimal environments without `jq`. The arguments for stability, composition, and error handling actually favor JSON — which is why the `--json` flag must be robust and well-documented. The trade-off is maintaining two output layers, but that's the cost of a professional tool serving both pilots and autopilots. Script writers pay a one-time `--json` flag; interactive users shouldn't pay per-invocation friction.

### Key arguments that held up

**For human-readable default (decided):**
- Spatial mapping and passive pattern recognition — humans scan tables by position, JSON requires active search-and-extract
- Discovery phase vs execution phase — interactive CLI use is exploratory; curated views beat raw data dumps
- Zero-dependency accessibility — recovery shells, distroless containers, serial consoles may lack jq
- Burden of intent asymmetry — script writers add `--json` once; interactive users would need `| jq` on every invocation

**For JSON (acknowledged but not decisive):**
- Versioned JSON schemas are more stable than text for programmatic consumers
- Structured data composes better than regex-parsed text (jq, yq, nushell)
- Error visibility is implementation quality, not format property — both formats can hide errors

### Trade-off accepted

Maintaining two output layers (text + JSON) is the "Hidden API tax." It's the cost of serving both humans and machines well. Collapsing to one format serves neither.
