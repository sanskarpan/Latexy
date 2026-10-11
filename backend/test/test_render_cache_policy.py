"""Volatile source remains compilable but bypasses exact-output reuse."""
import pytest

from app.services.render_engine.cache_policy import supports_exact_cache
from app.workers.latex_worker import compile_cache_key


@pytest.mark.parametrize("primitive", [r"\today", r"\time", r"\pdfuniformdeviate100", r"\includegraphics{x}", r"\input{x}", r"\csname today\endcsname", r"\csname to\string day\endcsname", "^^74oday"])
def test_volatile_sources_disable_exact_cache(primitive):
    source = r"\documentclass{article}\begin{document}" + primitive + r"\end{document}"
    assert not supports_exact_cache(source)
    assert compile_cache_key(source, "pdflatex", {}, "user:test") is None


def test_static_source_and_comment_dependencies_can_reuse():
    assert supports_exact_cache("\\documentclass{article}\n% \\today\n\\begin{document}Hello\\end{document}")
