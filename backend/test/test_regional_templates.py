from pathlib import Path

from app.api.template_routes import CATEGORY_LABELS, VALID_CATEGORIES
from app.data.official_snippets import OFFICIAL_SNIPPETS
from app.scripts.seed_templates import CATEGORY_META

TEMPLATES_ROOT = Path(__file__).resolve().parents[1] / "app" / "data" / "templates"


def test_regional_category_is_consistent_across_api_and_seeder():
    assert "regional" in VALID_CATEGORIES
    assert CATEGORY_LABELS["regional"] == "Regional Formats"
    assert CATEGORY_META["regional"]["description"]


def test_regional_source_library_contains_requested_formats():
    regional = TEMPLATES_ROOT / "regional"
    assert {path.name for path in regional.glob("*.tex")} == {
        "europecv.tex",
        "india_government_psu_application.tex",
        "india_professional_biodata.tex",
        "polish_cv_rodo.tex",
    }


def test_polish_consent_is_specific_optional_and_reusable():
    template = (TEMPLATES_ROOT / "regional" / "polish_cv_rodo.tex").read_text()
    snippet = next(item for item in OFFICIAL_SNIPPETS if item["title"] == "Optional Polish Recruitment Consent (RODO)")

    for placeholder in ("NAZWA PRACODAWCY", "NAZWA STANOWISKA"):
        assert placeholder in template
        assert placeholder in snippet["content"]
    assert "blanket" in snippet["description"]
    assert "only when" in snippet["description"]
    assert snippet["category"] == "misc"


def test_india_formats_do_not_request_identity_or_protected_category_numbers():
    regional = TEMPLATES_ROOT / "regional"
    india_sources = "\n".join(path.read_text() for path in regional.glob("india_*.tex")).lower()
    for prohibited in ("aadhaar", "pan number", "caste", "religion"):
        assert prohibited not in india_sources
