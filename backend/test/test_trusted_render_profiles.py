"""Trusted formats must be exact, immutable, optional and cache-distinct."""
import hashlib
import json

import pytest

from app.services.render_engine import trusted_profiles as profiles
from app.services.render_engine.managed_preamble import MANAGED_ENGLISH_FORMAT_ID, MANAGED_ENGLISH_PREAMBLE
from app.services.resume_builder_service import resume_builder_service
from scripts.benchmark_trusted_format import FIXTURE


def test_preamble_extraction_preserves_builder_source():
    source = resume_builder_service.render(FIXTURE, "professional").latex_content
    assert hashlib.sha256(source.encode()).hexdigest() == "cdd4a6d58032584057c44b07133dd7a19e386c9c147a901569a9ab718175d580"
    assert source.startswith(MANAGED_ENGLISH_PREAMBLE + r"\begin{document}")


@pytest.fixture
def trusted_profile(tmp_path, monkeypatch):
    fmt = tmp_path / (MANAGED_ENGLISH_FORMAT_ID + ".fmt")
    fmt.write_bytes(b"owned-format" * 200)
    binary = tmp_path / "pdflatex"
    binary.write_bytes(b"owned-compiler")
    binary.chmod(0o555)
    metadata = tmp_path / "formats.json"
    profile = {"profile_id": MANAGED_ENGLISH_FORMAT_ID, "compiler": "pdflatex", "format_path": str(fmt),
        "format_size": fmt.stat().st_size, "format_sha256": hashlib.sha256(fmt.read_bytes()).hexdigest(),
        "preamble_sha256": hashlib.sha256(MANAGED_ENGLISH_PREAMBLE.encode()).hexdigest(),
        "compiler_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(), "compiler_version": "owned-version",
        "dependencies_sha256": "a" * 64}
    def save():
        material = {key: value for key, value in profile.items() if key != "identity_sha256"}
        profile["identity_sha256"] = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        metadata.write_text(json.dumps({"schema_version": 1, "profiles": [profile]}))
        profiles._verified.cache_clear()
    save()
    monkeypatch.setattr(profiles, "MANIFEST_PATH", metadata)
    monkeypatch.setattr(profiles, "FORMAT_PATH", fmt)
    monkeypatch.setattr(profiles.shutil, "which", lambda name: str(binary) if name == "pdflatex" else None)
    # Fixtures are user-owned in nonroot test containers. The real image smoke
    # checks root-owned readonly assets; these tests isolate identity handling.
    monkeypatch.setattr(profiles, "_immutable", lambda path, maximum: path.read_bytes())
    original_stat = profiles.Path.stat
    def root_stat(path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        if path == binary:
            import os
            values = list(result)
            values[4] = 0
            return os.stat_result(values)
        return result
    monkeypatch.setattr(profiles.Path, "stat", root_stat)
    yield profile, save, fmt, binary
    profiles._verified.cache_clear()


def test_exact_profile_and_ordinary_fallbacks(trusted_profile, monkeypatch):
    source = MANAGED_ENGLISH_PREAMBLE + r"\begin{document}Hello\end{document}"
    assert profiles.trusted_format_flags(source, "pdflatex") == ["-fmt=" + MANAGED_ENGLISH_FORMAT_ID]
    assert profiles.trusted_format_identity(source, "pdflatex")["identity_sha256"] == trusted_profile[0]["identity_sha256"]
    for compiler in ("xelatex", "lualatex"):
        assert profiles.trusted_format_identity(source, compiler) is None
    assert profiles.trusted_format_identity(source.replace("11pt", "10pt"), "pdflatex") is None
    assert profiles.trusted_format_identity("%&userformat\n" + source, "pdflatex") is None
    monkeypatch.setattr(profiles.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else str(trusted_profile[3]))
    assert profiles.trusted_format_identity(source, "pdflatex") is None


@pytest.mark.parametrize("field,value", [
    ("format_sha256", "f" * 64), ("compiler_binary_sha256", "f" * 64),
    ("preamble_sha256", "f" * 64), ("format_size", True), ("format_size", 100_000_000),
    ("profile_id", "untrusted-user-format"), ("extra", "unexpected"),
])
def test_profile_mismatch_falls_back(trusted_profile, field, value):
    profile, save, _, _ = trusted_profile
    profile[field] = value
    save()
    source = MANAGED_ENGLISH_PREAMBLE + r"\begin{document}Hello\end{document}"
    assert profiles.trusted_format_flags(source, "pdflatex") == []


def test_profile_identity_changes_exact_cache_key(monkeypatch):
    from app.workers.latex_worker import compile_cache_key
    source = MANAGED_ENGLISH_PREAMBLE + r"\begin{document}Hello\end{document}"
    monkeypatch.setattr(profiles, "trusted_format_identity", lambda source, compiler: {"identity_sha256": "a" * 64})
    first = compile_cache_key(source, "pdflatex", {}, "user:test")
    monkeypatch.setattr(profiles, "trusted_format_identity", lambda source, compiler: {"identity_sha256": "b" * 64})
    assert compile_cache_key(source, "pdflatex", {}, "user:test") != first
    monkeypatch.setattr(profiles, "trusted_format_identity", lambda source, compiler: None)
    assert compile_cache_key(source, "pdflatex", {}, "user:test") != first


def test_replaced_asset_invalidates_memoized_verification(trusted_profile):
    _, _, fmt, _ = trusted_profile
    source = MANAGED_ENGLISH_PREAMBLE + r"\begin{document}Hello\end{document}"
    assert profiles.trusted_format_flags(source, "pdflatex")
    # Keep the same size and manifest: cache invalidation must observe the
    # actual immutable asset replacement rather than metadata changes alone.
    old = fmt.read_bytes()
    fmt.write_bytes(b"X" + old[1:])
    assert profiles.trusted_format_flags(source, "pdflatex") == []
