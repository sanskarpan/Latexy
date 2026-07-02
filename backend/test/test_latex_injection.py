"""
LaTeX injection filter tests for LaTeXService.validate_latex_content.

Covers the hardened validator that rejects shell-escape primitives and
absolute-path / traversal file reads while still accepting legitimate
relative multi-file includes.
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
    ],
)
def test_malicious_content_rejected(body):
    assert latex_service.validate_latex_content(_DOC % body) is False


def test_missing_structure_rejected():
    assert latex_service.validate_latex_content("no latex here") is False
