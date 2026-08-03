"""Contact extraction, with the international phone cases the old regex missed.

The previous ``PHONE_RE`` matched the NANP layout only, so every resume that
wrote its number with a non-US country code produced ``phone: None`` — silently,
on every format, not just PDF. These tests pin that class of input.
"""

from __future__ import annotations

import pytest

from app.utils.contact import find_email, find_phone

# (raw text, region hint, expected E.164-ish international form)
INTERNATIONAL_CASES = [
    ("Bangalore, India | priya@example.com | +91 98765 43210", "US", "+91 98765 43210"),
    ("Mumbai | +91-98765-43210", "US", "+91 98765 43210"),
    ("London | +44 20 7946 0958", "US", "+44 20 7946 0958"),
    ("Sydney | +61 2 9374 4000", "US", "+61 2 9374 4000"),
    ("Singapore | +65 6123 4567", "US", "+65 6123 4567"),
    ("Berlin | +49 30 901820", "US", "+49 30 901820"),
    ("Toronto | +1 416 555 0199", "US", "+1 416-555-0199"),
    ("SF, CA | (415) 555-2671", "US", "+1 415-555-2671"),
]


@pytest.mark.parametrize("text,region,expected", INTERNATIONAL_CASES)
def test_international_numbers_are_found(text, region, expected):
    """A country code makes the number unambiguous — region must not matter."""
    assert find_phone(text, region) == expected


def test_bare_local_number_needs_the_matching_region():
    """A number with no country code is meaningless without one.

    The important half is the second assertion: parsing a bare Indian number
    under a US default returns *nothing* rather than inventing a US number, so a
    misconfigured region can never produce a wrong phone number on a resume.
    """
    assert find_phone("Chennai | 98765 43210", "IN") == "+91 98765 43210"
    assert find_phone("Chennai | 98765 43210", "US") is None


@pytest.mark.parametrize(
    "noise",
    [
        "Reduced p95 checkout latency from 380ms to 140ms via query batching.",
        "Designed idempotency layer handling 40M req/day with p99 under 25ms.",
        "CGPA: 9.1/10  |  2015 - 2019",
        "Scaled the pipeline to 1,200,000 events daily",
        "AWS certified 2023-2026, credential id 4519827364",
        "Bangalore 560001",
    ],
)
def test_resume_digit_noise_is_not_a_phone_number(noise):
    """Resumes are full of digits; none of these are phone numbers.

    This is why the implementation scans with PhoneNumberMatcher rather than a
    permissive regex — a looser pattern matches the credential id and the pin
    code, which is worse than the US-only bug it replaced.
    """
    for region in ("US", "IN", "GB"):
        assert find_phone(noise, region) is None


def test_no_phone_present_returns_none():
    assert find_phone("Priya Raman\nBackend engineer", "US") is None
    assert find_phone("", "US") is None


def test_email_extraction():
    assert find_email("reach me at priya.raman@example.com today") == "priya.raman@example.com"
    assert find_email("no address here") is None


def test_parser_contact_uses_the_international_path():
    """The parser base class must go through find_phone, not the old regex."""
    from app.parsers.text_parser import TextParser

    contact = TextParser()._extract_contact_info(
        "Priya Raman\nBangalore, India\npriya.raman@example.com\n+91 98765 43210\n"
        "github.com/priyaraman"
    )
    assert contact.phone == "+91 98765 43210"
    assert contact.email == "priya.raman@example.com"
    assert contact.github == "github.com/priyaraman"
