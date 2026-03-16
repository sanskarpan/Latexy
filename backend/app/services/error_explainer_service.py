"""
AI-powered LaTeX error explainer service.

Two tiers:
1. Instant pattern matching for 20+ known errors (no API needed)
2. LLM call for complex/unknown errors (cached 24h in Redis)
"""

import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Optional

from ..core.config import settings
from ..core.logging import get_logger
from ..core.redis import cache_manager

logger = get_logger(__name__)


@dataclass
class PatternMatch:
    explanation: str
    suggested_fix: str
    corrected_code: Optional[str] = None


# ── Pattern fallback dictionary ─────────────────────────────────────────────

_PATTERNS: list[tuple[re.Pattern, PatternMatch]] = [
    (
        re.compile(r"Undefined control sequence", re.IGNORECASE),
        PatternMatch(
            explanation="The command you used doesn't exist or requires a package that isn't loaded.",
            suggested_fix="Check the command spelling. If it's from a package, add \\usepackage{package_name} to your preamble.",
        ),
    ),
    (
        re.compile(r"Missing \$ inserted", re.IGNORECASE),
        PatternMatch(
            explanation="You used a math symbol (like _ or ^) outside of math mode.",
            suggested_fix="Wrap the expression in dollar signs: $...$ for inline math, or use \\textsubscript{}/\\textsuperscript{} for text.",
        ),
    ),
    (
        re.compile(r"Extra \}", re.IGNORECASE),
        PatternMatch(
            explanation="There's an extra closing brace } that doesn't match any opening brace.",
            suggested_fix="Remove the extra closing brace, or add a matching opening brace {.",
        ),
    ),
    (
        re.compile(r"Too many \}'s", re.IGNORECASE),
        PatternMatch(
            explanation="There are more closing braces } than opening braces {.",
            suggested_fix="Count your braces and remove the extra closing brace(s).",
        ),
    ),
    (
        re.compile(r"Missing \} inserted", re.IGNORECASE),
        PatternMatch(
            explanation="An opening brace { was never closed.",
            suggested_fix="Add the missing closing brace } at the appropriate position.",
        ),
    ),
    (
        re.compile(r"Runaway argument", re.IGNORECASE),
        PatternMatch(
            explanation="A command argument is missing its closing brace, causing LaTeX to consume too much text.",
            suggested_fix="Find the command with an unclosed brace and add the missing }.",
        ),
    ),
    (
        re.compile(r"\\begin\{(\w+)\}.*ended by \\end\{(\w+)\}", re.IGNORECASE),
        PatternMatch(
            explanation="An environment was opened with one name but closed with a different name.",
            suggested_fix="Make sure the \\begin{...} and \\end{...} names match exactly.",
        ),
    ),
    (
        re.compile(r"Overfull \\hbox", re.IGNORECASE),
        PatternMatch(
            explanation="A line of text is wider than the available space (text overflows the margin).",
            suggested_fix="Rephrase the text, add hyphenation hints (\\-), or allow more flexible spacing with \\sloppy.",
        ),
    ),
    (
        re.compile(r"Underfull \\hbox", re.IGNORECASE),
        PatternMatch(
            explanation="A line of text has too much white space — usually harmless.",
            suggested_fix="This is typically a cosmetic warning. You can usually ignore it, or rephrase the text.",
        ),
    ),
    (
        re.compile(r"File .* not found", re.IGNORECASE),
        PatternMatch(
            explanation="LaTeX can't find a file it needs (a package, class, or included file).",
            suggested_fix="Check the filename spelling. If it's a package, install it or remove the \\usepackage line.",
        ),
    ),
    (
        re.compile(r"Emergency stop", re.IGNORECASE),
        PatternMatch(
            explanation="A critical error caused LaTeX to halt compilation entirely.",
            suggested_fix="Fix the first error in the log — Emergency stop is always caused by an earlier error.",
        ),
    ),
    (
        re.compile(r"Option clash for package", re.IGNORECASE),
        PatternMatch(
            explanation="A package is loaded twice with different options.",
            suggested_fix="Load the package only once, or use \\PassOptionsToPackage before \\documentclass.",
        ),
    ),
    (
        re.compile(r"Missing number, treated as zero", re.IGNORECASE),
        PatternMatch(
            explanation="LaTeX expected a number but found something else.",
            suggested_fix="Check commands that require numeric arguments (like \\hspace, \\vspace, lengths).",
        ),
    ),
    (
        re.compile(r"Illegal unit of measure", re.IGNORECASE),
        PatternMatch(
            explanation="A length value is missing its unit or uses an invalid unit.",
            suggested_fix="Add a valid unit: pt, em, cm, mm, in, ex, etc. Example: \\hspace{1em}.",
        ),
    ),
    (
        re.compile(r"Command .* already defined", re.IGNORECASE),
        PatternMatch(
            explanation="You're defining a command that already exists.",
            suggested_fix="Use \\renewcommand instead of \\newcommand, or choose a different name.",
        ),
    ),
    (
        re.compile(r"Paragraph ended before .* was complete", re.IGNORECASE),
        PatternMatch(
            explanation="A blank line appeared inside a command argument, which isn't allowed.",
            suggested_fix="Remove the blank line from inside the command, or close the command before the blank line.",
        ),
    ),
    (
        re.compile(r"Missing \\begin\{document\}", re.IGNORECASE),
        PatternMatch(
            explanation="LaTeX couldn't find \\begin{document} in your file.",
            suggested_fix="Make sure your document has \\begin{document} after the preamble.",
        ),
    ),
    (
        re.compile(r"Font .* not found", re.IGNORECASE),
        PatternMatch(
            explanation="The requested font is not installed on this system.",
            suggested_fix="Use a different font, or remove the font specification to use the default.",
        ),
    ),
    (
        re.compile(r"No room for a new", re.IGNORECASE),
        PatternMatch(
            explanation="LaTeX has run out of internal registers (too many floats, counters, or similar).",
            suggested_fix="Add \\usepackage{morefloats} or reduce the number of pending floats with \\clearpage.",
        ),
    ),
    (
        re.compile(r"Package hyperref Error", re.IGNORECASE),
        PatternMatch(
            explanation="The hyperref package encountered an error — it's sensitive to load order.",
            suggested_fix="Load hyperref as the last package in your preamble (before \\begin{document}).",
        ),
    ),
    (
        re.compile(r"Counter too large", re.IGNORECASE),
        PatternMatch(
            explanation="A counter has exceeded its maximum value.",
            suggested_fix="Check for infinite loops in numbering, or reset the counter with \\setcounter.",
        ),
    ),
    (
        re.compile(r"LaTeX Error: Environment .* undefined", re.IGNORECASE),
        PatternMatch(
            explanation="You're using an environment that hasn't been defined.",
            suggested_fix="Check the environment name spelling. You may need to load a package that defines it.",
        ),
    ),
    (
        re.compile(r"Misplaced \\noalign", re.IGNORECASE),
        PatternMatch(
            explanation="A command like \\hline or \\noalign is in the wrong position inside a table.",
            suggested_fix="Make sure \\hline appears right after \\\\ (row end) with no space or text between.",
        ),
    ),
    (
        re.compile(r"Extra alignment tab", re.IGNORECASE),
        PatternMatch(
            explanation="A table row has more columns (& separators) than the column specification allows.",
            suggested_fix="Remove the extra & or add more columns to the table specification.",
        ),
    ),
]

_GENERIC_FALLBACK = PatternMatch(
    explanation="This LaTeX error is not in our known patterns database.",
    suggested_fix="Check the error message and the line indicated. Look for typos, missing braces, or incorrect commands.",
)


class ErrorExplainerService:
    """Service for explaining LaTeX compilation errors."""

    def explain_from_patterns(self, error_message: str) -> PatternMatch:
        """Match error against known patterns. Always returns a result."""
        for pattern, match in _PATTERNS:
            if pattern.search(error_message):
                return match
        return _GENERIC_FALLBACK

    async def explain_with_llm(
        self,
        error_message: str,
        surrounding_latex: str,
        error_line: int,
        api_key: str,
    ) -> dict:
        """Use LLM to explain an error. Returns {explanation, suggested_fix, corrected_code}."""
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=api_key)

            system_prompt = (
                "You are a LaTeX expert. The user has a LaTeX compilation error. "
                "Explain the error in plain English for someone who is not a LaTeX expert. "
                "If possible, provide the corrected version of the surrounding code. "
                "Respond with JSON: {\"explanation\": \"...\", \"suggested_fix\": \"...\", \"corrected_code\": \"...\" or null}"
            )

            user_prompt = (
                f"Error message: {error_message}\n"
                f"Error line: {error_line}\n"
                f"Surrounding LaTeX code:\n```\n{surrounding_latex}\n```"
            )

            response = await client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=800,
            )

            content = response.choices[0].message.content
            if not content:
                raise ValueError("Empty LLM response")

            result = json.loads(content)
            return {
                "explanation": result.get("explanation", ""),
                "suggested_fix": result.get("suggested_fix", ""),
                "corrected_code": result.get("corrected_code"),
            }

        except Exception as e:
            logger.error(f"LLM error explanation failed: {e}")
            raise

    async def explain(
        self,
        error_message: str,
        surrounding_latex: str = "",
        error_line: int = 0,
        api_key: str | None = None,
    ) -> dict:
        """
        Full explanation flow: pattern → cache → LLM → fallback.
        Returns dict with explanation, suggested_fix, corrected_code, source, cached.
        """
        start = time.monotonic()

        # 1. Pattern match first
        pattern_result = self.explain_from_patterns(error_message)

        # 2. If no API key, return pattern result
        if not api_key:
            return {
                "explanation": pattern_result.explanation,
                "suggested_fix": pattern_result.suggested_fix,
                "corrected_code": pattern_result.corrected_code,
                "source": "pattern",
                "cached": False,
                "processing_time": round(time.monotonic() - start, 3),
            }

        # 3. Check Redis cache
        cache_key = f"ai:explain:{_make_cache_key(error_message, surrounding_latex)}"
        try:
            cached = await cache_manager.get(cache_key)
            if cached and isinstance(cached, dict):
                cached["cached"] = True
                cached["processing_time"] = round(time.monotonic() - start, 3)
                return cached
        except Exception:
            pass  # cache miss or Redis down

        # 4. LLM call
        try:
            llm_result = await self.explain_with_llm(
                error_message, surrounding_latex, error_line, api_key
            )
            result = {
                "explanation": llm_result["explanation"],
                "suggested_fix": llm_result["suggested_fix"],
                "corrected_code": llm_result.get("corrected_code"),
                "source": "llm",
                "cached": False,
                "processing_time": round(time.monotonic() - start, 3),
            }

            # Cache for 24h
            try:
                await cache_manager.set(cache_key, result, ttl=86400)
            except Exception:
                pass  # non-critical

            return result

        except Exception:
            # Fallback to pattern result
            return {
                "explanation": pattern_result.explanation,
                "suggested_fix": pattern_result.suggested_fix,
                "corrected_code": pattern_result.corrected_code,
                "source": "pattern",
                "cached": False,
                "processing_time": round(time.monotonic() - start, 3),
            }


def _make_cache_key(error_message: str, surrounding_latex: str) -> str:
    """Create a deterministic hash for caching."""
    raw = f"{error_message}::{surrounding_latex}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# Singleton
error_explainer_service = ErrorExplainerService()
