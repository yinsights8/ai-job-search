"""Shared pytest fixtures and helpers for the email_scanner test suite."""

from __future__ import annotations

import json
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pytest

# Make the tools/ package importable from tests/
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.email_scanner import paths  # noqa: E402
from tools.email_scanner.models import (  # noqa: E402
    Direction,
    EmailAddress,
    EmailMessage,
    TrackerRow,
)


# ---------- Repo-isolation helpers -----------------------------------------


@pytest.fixture
def tmp_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run tests against a temporary copy of the repo skeleton.

    Sets EMAIL_SCANNER_ROOT (read by paths) to `tmp_path` and creates
    a minimal `auth/`, `documents/applications/`, and
    `job_search_tracker.csv`."""
    monkeypatch.setenv("EMAIL_SCANNER_ROOT", str(tmp_path))
    (tmp_path / "auth").mkdir()
    (tmp_path / "documents" / "applications").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def tracker_csv(tmp_workspace: Path) -> Path:
    """Write a small tracker CSV with three example applications."""
    p = tmp_workspace / "job_search_tracker.csv"
    p.write_text(
        textwrap.dedent(
            """\
            date,company,role,location,salary,source,status,notes,domain
            2026-07-14,Abound,Graduate AI Engineer,London,GBP 35000-45000,https://jobs.getabound.com/post/123,applied,Strong fit,
            2026-07-17,The AA,AI Engineer,UK,,https://theaacareers.co.uk/job/123,applied,Strong fit,
            2026-07-18,FD Intelligence,AI Graduate Scientist,Edinburgh,,https://uk.linkedin.com/jobs/view/4440041652,applied,Strong fit,
            """
        ),
        encoding="utf-8",
    )
    return p


@pytest.fixture
def gmail_config_json(tmp_workspace: Path) -> Path:
    p = tmp_workspace / "auth" / "gmail-config.json"
    p.write_text(
        json.dumps(
            {
                "client_id": "test.apps.googleusercontent.com",
                "project_id": "test-project",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_secret": "test-secret",
                "redirect_uris": ["http://localhost:3000/oauth2callback"],
                "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
            }
        ),
        encoding="utf-8",
    )
    return p


@pytest.fixture
def oauth_client_json(tmp_workspace: Path) -> Path:
    p = tmp_workspace / "auth" / "oauth-client.json"
    p.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "test.apps.googleusercontent.com",
                    "project_id": "test-project",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "client_secret": "test-secret",
                    "redirect_uris": ["http://localhost:3000/oauth2callback"],
                }
            }
        ),
        encoding="utf-8",
    )
    return p


# ---------- Email fixtures -------------------------------------------------


def make_message(
    *,
    message_id: str = "<abc@mail.gmail.com>",
    thread_id: str = "thread-1",
    direction: Direction = Direction.INBOUND,
    sender: str = "recruiter@example.com",
    sender_name: Optional[str] = "Test Recruiter",
    to: list[str] | None = None,
    cc: list[str] | None = None,
    subject: str = "Update on your application",
    body: str = "Hi,\n\nWe received your application.\n\nThanks",
    headers: dict[str, str] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    raw_bytes: bytes | None = None,
    date: datetime | None = None,
) -> EmailMessage:
    """Build a test EmailMessage. Default sender is recruiter@example.com
    so tests can pass through the Domain pass."""
    if to is None:
        to = ["candidate@example.com"]
    if date is None:
        date = datetime(2026, 7, 18, 9, 42, tzinfo=timezone.utc)
    base_headers = {
        "From": f"{sender_name} <{sender}>" if sender_name else sender,
        "To": ", ".join(to),
        "Subject": subject,
        "Date": date.strftime("%a, %d %b %Y %H:%M:%S %z"),
        "Message-ID": message_id,
        "MIME-Version": "1.0",
    }
    if cc:
        base_headers["Cc"] = ", ".join(cc)
    if headers:
        base_headers.update(headers)

    def _addr(s: str) -> EmailAddress:
        if "<" in s:
            name, _, addr = s.partition("<")
            return EmailAddress(name=name.strip() or None, email=addr.rstrip(">").strip().lower())
        return EmailAddress(name=None, email=s.lower())

    return EmailMessage(
        message_id=message_id,
        thread_id=thread_id,
        direction=direction,
        date_received=date,
        **{"from": _addr(sender)},
        to=[_addr(t) for t in to],
        cc=[_addr(c) for c in (cc or [])],
        subject=subject,
        body_text=body,
        headers=base_headers,
        attachments=attachments or [],
        raw_bytes=raw_bytes,
    )


@pytest.fixture
def make_email():
    """Factory fixture so tests can do `make_email(subject=...)`."""
    return make_message


# ---------- Tracker fixtures -----------------------------------------------


@pytest.fixture
def sample_tracker_rows() -> list[TrackerRow]:
    return [
        TrackerRow(
            date="2026-07-14",
            company="Abound",
            role="Graduate AI Engineer",
            source="https://jobs.getabound.com/post/123",
        ),
        TrackerRow(
            date="2026-07-17",
            company="The AA",
            role="AI Engineer",
            source="https://theaacareers.co.uk/job/123",
        ),
        TrackerRow(
            date="2026-07-18",
            company="FD Intelligence",
            role="AI Graduate Scientist",
            source="https://uk.linkedin.com/jobs/view/4440041652",
        ),
    ]
