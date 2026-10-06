"""Focused tests for the privacy-minimized forwarded-email parser."""

from __future__ import annotations

from email.message import EmailMessage

import pytest

from app.services.email_status_parser_service import (
    MAX_EMAIL_BYTES,
    EmailStatusParseError,
    parse_forwarded_application_email,
)


def _message(
    *,
    subject: str = "Application update",
    sender: str = "Acme Recruiting <jobs@acme.example>",
    body: str = "Thank you for contacting us.",
    html: str | None = None,
) -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "forwarder@example.test"
    message["Subject"] = subject
    if html is None:
        message.set_content(body)
    else:
        message.set_content(body)
        message.add_alternative(html, subtype="html")
    return message.as_bytes()


def test_rejection_is_high_confidence_and_review_only() -> None:
    result = parse_forwarded_application_email(
        _message(
            subject="Your application for Senior Software Engineer",
            body="Thank you for applying. We regret to inform you that we will not be moving forward.",
        )
    )

    assert result.status == "rejected"
    assert result.confidence >= 0.95
    assert result.company == "Acme"
    assert result.role == "Senior Software Engineer"
    assert result.requires_review is True
    assert result.suggested_status == "rejected"
    assert any(item.signal == "application not selected" for item in result.evidence)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("We are pleased to offer you the position.", "offer"),
        ("We would like to invite you to a phone screen.", "phone_screen"),
        ("Please select a time for your technical interview.", "technical"),
        ("Your final round interview will be onsite.", "onsite"),
        ("Your application has been withdrawn as requested.", "withdrawn"),
        ("We have received your application successfully.", "applied"),
    ],
)
def test_only_specific_status_signals_are_classified(body: str, expected: str) -> None:
    result = parse_forwarded_application_email(_message(body=body))
    assert result.status == expected
    assert result.requires_review


def test_generic_interview_language_is_not_assigned_to_a_tracker_stage() -> None:
    result = parse_forwarded_application_email(_message(body="We would like to invite you to an interview."))
    assert result.status is None
    assert result.confidence == 0.0


def test_html_is_stripped_without_fetching_links_or_retaining_scripts() -> None:
    result = parse_forwarded_application_email(
        _message(
            body="",
            html=(
                '<html><body><p>We are pleased to offer you a role.</p>'
                '<a href="https://tracking.invalid/secret">details</a>'
                '<img src="https://tracking.invalid/pixel">'
                '<script>"We regret to inform you"</script></body></html>'
            ),
        )
    )
    assert result.status == "offer"
    assert all(item.signal != "application not selected" for item in result.evidence)


def test_multipart_alternative_forwarded_message_is_selected_once() -> None:
    forwarded_plain = (
        "---------- Forwarded message ---------\n"
        "From: Acme Recruiting <jobs@acme.example>\n"
        "Subject: Your application for Data Analyst\n"
        "\n"
        "We have received your application."
    )
    forwarded_html = (
        "<p>---------- Forwarded message ---------</p>"
        "<p>From: Acme Recruiting &lt;jobs@acme.example&gt;</p>"
        "<p>Subject: Your application for Data Analyst</p>"
        "<p>We have received your application.</p>"
    )
    result = parse_forwarded_application_email(
        _message(subject="Fwd: Application update", sender="User <user@example.test>", body=forwarded_plain, html=forwarded_html)
    )

    assert result.status == "applied"
    assert result.company == "Acme"
    assert result.role == "Data Analyst"
    assert len(result.evidence) == 1


def test_encoded_headers_and_text_are_decoded_safely() -> None:
    result = parse_forwarded_application_email(
        _message(
            subject="=?utf-8?b?WW91ciBhcHBsaWNhdGlvbiBmb3IgU8OpcmlvciBFbmdpbmVlcg==?=",
            body="Wir haben Ihre Bewerbung erhalten.",
        )
    )
    # The status phrase is intentionally English-only; identity extraction is
    # still bounded and does not expose the sender address.
    assert result.status is None
    assert result.company == "Acme"


def test_oversized_and_malformed_messages_are_rejected() -> None:
    with pytest.raises(EmailStatusParseError, match="maximum size"):
        parse_forwarded_application_email(b"From: a@example.test\n\n" + b"x" * MAX_EMAIL_BYTES)
    with pytest.raises(EmailStatusParseError, match="separator"):
        parse_forwarded_application_email(b"From: a@example.test\nSubject: update")
    with pytest.raises(EmailStatusParseError, match="(?:headers|malformed)"):
        parse_forwarded_application_email(b"not an RFC 5322 header\n\napplication was rejected")


def test_attachment_and_archive_content_are_rejected() -> None:
    message = EmailMessage()
    message["From"] = "jobs@acme.example"
    message["Subject"] = "Application update"
    message.set_content("We have received your application.")
    message.add_attachment(b"PK\x03\x04", maintype="application", subtype="zip", filename="status.zip")

    with pytest.raises(EmailStatusParseError, match="attachments"):
        parse_forwarded_application_email(message.as_bytes())


def test_conflicting_high_confidence_statuses_require_manual_interpretation() -> None:
    result = parse_forwarded_application_email(
        _message(body="We are pleased to offer you a position, but the role has been filled and we will not be moving forward.")
    )
    assert result.status is None
    assert result.confidence == 0.0
    assert len(result.evidence) == 2


def test_raw_bytes_are_not_logged_or_returned_in_result() -> None:
    result = parse_forwarded_application_email(_message(body="We have received your application. Secret token: abc"))
    assert result.status == "applied"
    assert "Secret token" not in repr(result)
    assert "abc" not in repr(result)


def test_forwarded_block_uses_inner_sender_and_subject_not_outer_user() -> None:
    result = parse_forwarded_application_email(
        _message(
            subject="Fwd: Application update",
            sender="Sanskar Pandey <user@example.test>",
            body=(
                "---------- Forwarded message ---------\n"
                "From: Acme Recruiting <jobs@acme.example>\n"
                "Date: Mon, 14 Sep 2026 09:00:00 +0000\n"
                "Subject: Your application for Data Analyst\n"
                "To: user@example.test\n"
                "\n"
                "Thank you for applying. We regret to inform you that we will not be moving forward."
            ),
        )
    )

    assert result.status == "rejected"
    assert result.company == "Acme"
    assert result.role == "Data Analyst"
    assert "Sanskar" not in repr(result)
    assert "user@example.test" not in repr(result)


def test_fwd_subject_without_dashes_still_scopes_inner_headers() -> None:
    result = parse_forwarded_application_email(
        _message(
            subject="FW: Application update",
            sender="User Name <user@example.test>",
            body=(
                "From: Acme Recruiting <jobs@acme.example>\n"
                "Subject: Your application for Product Manager\n"
                "\n"
                "We are pleased to offer you the position."
            ),
        )
    )

    assert result.status == "offer"
    assert result.company == "Acme"
    assert result.role == "Product Manager"


def test_multiple_forwarded_blocks_are_rejected_as_ambiguous() -> None:
    body = (
        "---------- Forwarded message ---------\n"
        "From: Acme Recruiting <jobs@acme.example>\n"
        "Subject: Application update\n\n"
        "We have received your application.\n\n"
        "---------- Forwarded message ---------\n"
        "From: Other Recruiting <jobs@other.example>\n"
        "Subject: Application update\n\n"
        "Your application was rejected."
    )
    with pytest.raises(EmailStatusParseError, match="multiple forwarded"):
        parse_forwarded_application_email(
            _message(subject="Fwd: Two updates", sender="User <user@example.test>", body=body)
        )


def test_fwd_without_an_inner_header_block_fails_closed() -> None:
    with pytest.raises(EmailStatusParseError, match="header block"):
        parse_forwarded_application_email(
            _message(
                subject="Fwd: Application update",
                sender="User Name <user@example.test>",
                body="I forwarded the message below, but its headers were removed.",
            )
        )
