"""Log and UI redaction helpers.

Used by every other module to ensure the body of an email and the
content of attachments never reach logs, tracebacks, or LLM prompts.

The rule is simple: a log line may contain message-id, subject,
sender-domain, classification, and matched application key. Nothing
else from the email.
"""

from __future__ import annotations

import re
from typing import Any

# Email address pattern, for stripping from log lines.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def domain_of(email_or_addr: str) -> str:
    """Extract the domain from an email address. Returns '' if no match."""
    if not email_or_addr:
        return ""
    m = re.search(r"@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})", email_or_addr)
    return m.group(1).lower() if m else ""


def strip_email_addresses(text: str) -> str:
    """Replace email addresses with `<redacted>`."""
    if not text:
        return text
    return _EMAIL_RE.sub("<redacted>", text)


def redacted_body_snippet(body: str, max_chars: int = 200) -> str:
    """Return a redacted snippet of the email body suitable for sending
    to a hosted LLM for classification.

    The body is stripped of email addresses and truncated to
    `max_chars`. The full body is never sent."""
    if not body:
        return ""
    cleaned = strip_email_addresses(body)
    cleaned = cleaned.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars] + "..."
    return cleaned


def safe_log_message(msg: Any) -> str:
    """Format any object for log output. If the object is an exception,
    format only the type and a redacted message — never the body."""
    if isinstance(msg, Exception):
        text = str(msg)
        text = strip_email_addresses(text)
        return f"{type(msg).__name__}: {text[:200]}"
    return str(msg)
