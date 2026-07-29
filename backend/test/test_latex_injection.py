r"""
LaTeX injection filter tests for LaTeXService.validate_latex_content.

Covers the hardened validator that rejects shell-escape primitives and
absolute-path / traversal file reads — including the obfuscated spellings
(\@@input, \csname input\endcsname, "\write 18", "\openin1=") — while still
accepting legitimate relative multi-file includes.

This validator is defence in depth; the primary control is the sandboxed
engine invocation covered by test_latex_sandbox.py.
"""

import pytest

from app.services.latex_service import latex_service

_DOC = r"\documentclass{article}\begin{document}%s\end{document}"


@pytest.mark.parametrize(
    "body",
    [
        "Plain resume content",
        r"\input{sections/education.tex}",   # relative include — allowed
        r"\input{./skills}",                  # single-dot relative — allowed
        r"\include{experience}",              # relative include — allowed
    ],
)
def test_valid_content_accepted(body):
    assert latex_service.validate_latex_content(_DOC % body) is True


@pytest.mark.parametrize(
    "body",
    [
        r"\write18{rm -rf /}",
        r"\openout\myfile=/tmp/x",
        r"\input{/etc/passwd}",
        r"\input {/etc/passwd}",            # whitespace before brace
        r"\input /etc/passwd",              # no braces, space-delimited
        r"\include{/etc/shadow}",
        r"\input{../../secret.txt}",        # parent traversal
        r"\lstinputlisting{/etc/hosts}",
        r"\InputIfFileExists{/etc/passwd}{}{}",
        r"\input{~/.ssh/id_rsa}",           # home-dir expansion
        r"\makeatletter\@@input /etc/passwd",  # \@@input internal
        r"\csname input\endcsname{/etc/passwd}",  # \csname-built \input
        r"\immediate\write 18{id}",         # space between \write and 18
        r"\newread\r \openin1=/etc/passwd",  # stream number defeats \b
        r"\openout15=/tmp/x",                # stream number defeats \b
        r"\directlua{os.execute('id')}",     # lualatex io/os access
    ],
)
def test_malicious_content_rejected(body):
    assert latex_service.validate_latex_content(_DOC % body) is False


def test_missing_structure_rejected():
    assert latex_service.validate_latex_content("no latex here") is False


def test_commented_out_directive_is_inert():
    r"""A % -commented \input never reaches the engine, so it must not fail the doc."""
    body = "% " + r"\input{/etc/passwd}" + "\nPlain resume content"
    assert latex_service.validate_latex_content(_DOC % body) is True
