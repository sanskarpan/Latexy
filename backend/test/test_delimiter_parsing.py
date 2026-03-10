"""
Tests for the delimiter-based LLM response parsing logic in orchestrator._run_llm_stage.

These tests verify the state machine that extracts LaTeX and changes JSON
from delimited LLM output without leaking JSON scaffold tokens to the frontend.
"""

import json

# ─── Helpers to simulate the state machine ───────────────────────────────────

_LS = "<<<LATEX>>>"
_LE = "<<<END_LATEX>>>"
_CS = "<<<CHANGES>>>"
_CE = "<<<END_CHANGES>>>"
_BEFORE, _IN_LATEX, _AFTER_LATEX, _IN_CHANGES = 0, 1, 2, 3


def run_state_machine(chunks: list[str]) -> tuple[str, str, list[str]]:
    """
    Simulate the delimiter state machine from orchestrator._run_llm_stage.
    Returns (latex, changes_raw, emitted_tokens).
    """
    llm_state = _BEFORE
    latex_parts: list[str] = []
    changes_parts: list[str] = []
    emitted_tokens: list[str] = []
    buf = ""

    for delta in chunks:
        buf += delta

        for _ in range(4):
            if llm_state == _BEFORE:
                if _LS in buf:
                    buf = buf.split(_LS, 1)[1]
                    llm_state = _IN_LATEX
                    continue
                else:
                    if len(buf) >= len(_LS):
                        buf = buf[-len(_LS):]
                break

            elif llm_state == _IN_LATEX:
                if _LE in buf:
                    before, _, buf = buf.partition(_LE)
                    if before:
                        latex_parts.append(before)
                        emitted_tokens.append(before)
                    llm_state = _AFTER_LATEX
                    continue
                else:
                    safe_len = len(buf) - len(_LE) + 1
                    if safe_len > 0:
                        safe = buf[:safe_len]
                        latex_parts.append(safe)
                        emitted_tokens.append(safe)
                        buf = buf[safe_len:]
                break

            elif llm_state == _AFTER_LATEX:
                if _CS in buf:
                    buf = buf.split(_CS, 1)[1]
                    llm_state = _IN_CHANGES
                    continue
                else:
                    if len(buf) >= len(_CS):
                        buf = buf[-len(_CS):]
                break

            elif llm_state == _IN_CHANGES:
                if _CE in buf:
                    before, _, _ = buf.partition(_CE)
                    changes_parts.append(before)
                    buf = ""
                else:
                    safe_len = len(buf) - len(_CE) + 1
                    if safe_len > 0:
                        changes_parts.append(buf[:safe_len])
                        buf = buf[safe_len:]
                break

    latex = "".join(latex_parts).strip()
    changes_raw = "".join(changes_parts).strip()
    return latex, changes_raw, emitted_tokens


# ─── Tests ───────────────────────────────────────────────────────────────────


def test_clean_delimiter_response():
    """Full delimiter format in a single chunk is correctly parsed."""
    sample_latex = r"""\documentclass{article}
\begin{document}
Hello World
\end{document}"""

    sample_changes = json.dumps([
        {"section": "Header", "change_type": "modified", "reason": "Improved clarity"}
    ])

    full_response = (
        f"{_LS}\n{sample_latex}\n{_LE}\n{_CS}\n{sample_changes}\n{_CE}"
    )

    latex, changes_raw, tokens = run_state_machine([full_response])

    assert "\\documentclass" in latex
    assert "Hello World" in latex
    parsed_changes = json.loads(changes_raw)
    assert len(parsed_changes) == 1
    assert parsed_changes[0]["section"] == "Header"
    # No JSON braces should appear in emitted tokens
    for tok in tokens:
        assert "{" not in tok or "\\" in tok or "\\begin" in tok  # only LaTeX braces


def test_delimiter_split_across_chunks():
    """Delimiter straddling two chunks is handled correctly without corruption."""
    sample_latex = r"\section{Experience} Worked at Acme."

    full_response = f"{_LS}\n{sample_latex}\n{_LE}\n{_CS}\n[]\n{_CE}"

    # Split at the exact boundary of <<<END_LATEX>>> across two chunks
    split_at = full_response.index(_LE) + 5  # split inside the end delimiter
    chunk1 = full_response[:split_at]
    chunk2 = full_response[split_at:]

    latex, changes_raw, tokens = run_state_machine([chunk1, chunk2])

    assert "\\section{Experience}" in latex
    assert "Worked at Acme." in latex
    # No delimiter text should appear in the latex result
    assert _LE not in latex
    assert _LS not in latex


def test_delimiter_latex_start_straddle():
    """<<<LATEX>>> delimiter spanning two chunks transitions state correctly."""
    pre_content = "Some preamble text "
    latex_body = r"\documentclass{article}\begin{document}Test\end{document}"
    changes = "[]"

    # Artificially split the opening delimiter across two chunks
    full = f"{pre_content}{_LS}{latex_body}{_LE}{_CS}{changes}{_CE}"
    split_idx = full.index(_LS) + 5
    chunk1, chunk2 = full[:split_idx], full[split_idx:]

    latex, _, _ = run_state_machine([chunk1, chunk2])

    assert "\\documentclass" in latex
    assert "Test" in latex
    # Pre-content before <<<LATEX>>> must not appear in latex output
    assert "preamble" not in latex


def test_no_delimiter_fallback():
    """When LLM ignores delimiter format, latex_parts is empty (caller falls back to JSON)."""
    raw_json = json.dumps({
        "optimized_latex": r"\documentclass{article}\begin{document}Hello\end{document}",
        "changes": []
    })

    latex, changes_raw, tokens = run_state_machine([raw_json])

    # State machine produces nothing — caller should fall back to JSON parsing
    assert latex == ""
    assert changes_raw == ""
    assert tokens == []


def test_multiple_transitions_per_chunk():
    """A single large chunk containing all delimiters transitions state correctly."""
    sample_latex = r"\documentclass{article}\begin{document}x\end{document}"
    sample_changes = '[{"section":"Summary","change_type":"modified","reason":"clearer"}]'

    # Entire response in one chunk
    full = f"{_LS}{sample_latex}{_LE}{_CS}{sample_changes}{_CE}"
    latex, changes_raw, _ = run_state_machine([full])

    assert "\\documentclass" in latex
    parsed = json.loads(changes_raw)
    assert parsed[0]["section"] == "Summary"


def test_empty_changes_section():
    """Empty changes JSON array is handled gracefully."""
    sample_latex = r"\section{Skills} Python, Rust"
    full = f"{_LS}\n{sample_latex}\n{_LE}\n{_CS}\n[]\n{_CE}"
    latex, changes_raw, _ = run_state_machine([full])

    assert "\\section{Skills}" in latex
    assert json.loads(changes_raw) == []


def test_only_latex_tokens_emitted():
    """Verify that no JSON scaffold characters appear in emitted tokens."""
    latex_body = r"\section{Experience}\item Did stuff"
    changes = '[{"section":"Experience","change_type":"modified","reason":"stronger verbs"}]'
    full = f"Some prefix {_LS}\n{latex_body}\n{_LE}\n{_CS}\n{changes}\n{_CE} Some suffix"

    # Emit token-by-token (1 char at a time) to stress-test buffering
    chars = list(full)
    latex, changes_raw, tokens = run_state_machine(chars)

    assert "\\section" in latex
    # All emitted tokens should be LaTeX content only
    combined = "".join(tokens)
    assert "<<<" not in combined
    assert '"section"' not in combined  # JSON key must not be emitted
    parsed = json.loads(changes_raw)
    assert parsed[0]["section"] == "Experience"
