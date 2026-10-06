"""Deployment build contexts must exclude local credentials and environments."""

from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("pattern", [".env", ".env.*", "**/.env", "**/.env.*", ".venv/"])
def test_backend_build_context_excludes_sensitive_local_files(pattern):
    patterns = {
        line.strip() for line in (BACKEND / ".dockerignore").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert pattern in patterns
    assert not any(line.startswith("!.env") for line in patterns)


@pytest.mark.parametrize("filename", ["Dockerfile", "Dockerfile.prod"])
def test_backend_images_install_every_supported_tex_engine(filename):
    source = (BACKEND / filename).read_text()
    assert "texlive-xetex" in source
    assert "texlive-luatex" in source
    assert "texlive-latex-base" in source


def test_local_engine_cache_is_normalized_before_warming_without_application_copy():
    source = (BACKEND / "Dockerfile.tex-engine").read_text()
    instructions = [line.lstrip() for line in source.splitlines() if not line.lstrip().startswith("#")]
    assert not any(line.startswith(("COPY ", "ADD ")) for line in instructions)
    assert source.index("touch -m -d '@1704067200'") < source.index("fc-cache --force --system-only")


def test_local_sandbox_has_multilingual_system_fonts_and_lua_lookup_cache():
    source = (BACKEND / "Dockerfile.tex-engine").read_text()
    for package in ("fonts-lohit-deva", "fonts-noto-core", "fonts-noto-cjk"):
        assert package in source
    assert source.index("fonts-lohit-deva") < source.index("fc-cache --force --system-only")
    assert "luaotfload-tool --update --force" in source


def test_local_sandbox_precompiles_the_pinned_devanagari_shapes_for_readonly_cache():
    source = (BACKEND / "Dockerfile.tex-engine").read_text()
    assert "Noto Sans Devanagari Bold" in source
    assert "ItalicFeatures={FakeSlant=0.15}" in source
    assert "BoldItalicFeatures={FakeSlant=0.15}" in source
    assert "luatexja-fontspec" in source
    assert "Noto Sans CJK JP" in source
    assert "polyglossia" in source
    assert "Noto Naskh Arabic" in source
    assert "Noto Sans Hebrew" in source
    assert r"\textenglish{email@example.com •}" in source
    assert "TEXMFVAR" in source and "TEXMFCACHE" in source
    assert "-no-shell-escape -recorder -interaction=batchmode -halt-on-error" in source
    assert "sleep 125" in source
    assert "Some font shapes were not available" in source
    assert source.index("luaotfload-tool --update --force") < source.index("lualatex -no-shell-escape")


def test_local_sandbox_rebuilds_when_its_source_changes():
    source = (BACKEND.parent / "scripts/dev.sh").read_text()
    assert 'shasum -a 256 "$PROJECT_ROOT/backend/Dockerfile.tex-engine"' in source
    assert '[[ "$DEV_TEX_BUILT_HASH" != "$DEV_TEX_SOURCE_HASH" ]]' in source
    assert 'docker build --label "xyz.latexy.local-tex-source=$DEV_TEX_SOURCE_HASH"' in source
