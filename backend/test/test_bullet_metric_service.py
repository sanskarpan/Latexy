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
