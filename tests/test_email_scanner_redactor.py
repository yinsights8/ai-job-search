"""Tests for the redactor helpers."""

from __future__ import annotations

from tools.email_scanner.redactor import (
    domain_of,
    redacted_body_snippet,
    safe_log_message,
    strip_email_addresses,
)


class TestDomainOf:
    def test_extracts_domain(self):
        assert domain_of("recruiter@example.com") == "example.com"

    def test_lowercases(self):
        assert domain_of("Recruiter@Example.COM") == "example.com"

    def test_empty(self):
        assert domain_of("") == ""

    def test_no_at_sign(self):
        assert domain_of("not-an-email") == ""


class TestStripEmailAddresses:
    def test_replaces_simple_address(self):
        out = strip_email_addresses("Contact me at recruiter@example.com today")
        assert "recruiter@example.com" not in out
        assert "<redacted>" in out

    def test_replaces_multiple(self):
        out = strip_email_addresses("a@x.com and b@y.com")
        assert out == "<redacted> and <redacted>"

    def test_empty(self):
        assert strip_email_addresses("") == ""

    def test_no_addresses_unchanged(self):
        text = "Just some plain text without any emails."
        assert strip_email_addresses(text) == text


class TestRedactedBodySnippet:
    def test_short_body_returned_as_is(self):
        snippet = redacted_body_snippet("Just a short message.")
        assert "Just a short message" in snippet

    def test_long_body_truncated(self):
        body = "word " * 200
        snippet = redacted_body_snippet(body, max_chars=50)
        assert len(snippet) <= 53  # 50 + "..."
        assert snippet.endswith("...")

    def test_email_addresses_stripped(self):
        body = "Contact recruiter@example.com for details"
        snippet = redacted_body_snippet(body)
        assert "recruiter@example.com" not in snippet

    def test_newlines_collapsed(self):
        body = "Line 1\nLine 2\nLine 3"
        snippet = redacted_body_snippet(body)
        assert "\n" not in snippet
        assert "Line 1 Line 2 Line 3" in snippet

    def test_empty_body(self):
        assert redacted_body_snippet("") == ""


class TestSafeLogMessage:
    def test_exception_format(self):
        try:
            raise ValueError("test error with recruiter@example.com")
        except ValueError as e:
            msg = safe_log_message(e)
        assert "ValueError" in msg
        assert "recruiter@example.com" not in msg
        assert "<redacted>" in msg

    def test_string_passthrough(self):
        assert safe_log_message("just a string") == "just a string"
