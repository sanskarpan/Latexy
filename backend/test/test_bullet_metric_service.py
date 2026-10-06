import random
import re

from app.services.bullet_metric_service import replace_unverified_metrics


def test_replaces_unsupported_counts_percentages_currency_and_scale():
    result = replace_unverified_metrics(r"Led 12 engineers, cut latency 40\%, served 10M users, and saved $2.5M.")

    assert result == (r"Led [X] engineers, cut latency [X]\%, served [X]M users, and saved $[X]M.")


def test_preserves_only_metrics_present_in_user_evidence():
    result = replace_unverified_metrics(
        r"Led 12 engineers and improved throughput 40\% across 3 teams.",
        "I led 12 engineers and throughput improved by 40%.",
    )

    assert result == r"Led 12 engineers and improved throughput 40\% across [X] teams."


def test_does_not_rewrite_existing_placeholders_or_ordinary_text():
    text = r"Improved conversion by [X]\% while mentoring [X] engineers."

    assert replace_unverified_metrics(text) == text


def test_linear_candidate_scan_preserves_original_boundary_and_evidence_semantics():
    original = re.compile(
        r"(?<![\w\[])(?P<prefix>[$£€₹])?(?P<number>\d+(?:[.,]\d+)*)"
        r"(?P<suffix>[kKmMbB](?:\+)?|\+|\\?%)?(?![\w\]])"
    )
    rng = random.Random(1750)
    for _ in range(2_000):
        text = "".join(rng.choice("012345abc [],.$₹kM+%\\") for _ in range(40))
        evidence = "12 3.5 40%"
        allowed = {match.group("number") for match in original.finditer(evidence)}

        def replace(match):
            if match.group("number") in allowed:
                return match.group(0)
            return f"{match.group('prefix') or ''}[X]{match.group('suffix') or ''}"

        assert replace_unverified_metrics(text, evidence) == original.sub(replace, text)
