"""Pydantic models for the email-scanner pipeline.

These models are the canonical shape of the data the CLI passes between
subcommands. The `plan` subcommand produces a `PlanFile` (written to
stdout as JSON); the `apply` subcommand reads it from stdin and writes
the archive. Every other module accepts and returns these types so
they're easy to mock in tests.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from .domains import derive_domain_from_url


# ---------- Enumerations ----------------------------------------------------


class Direction(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class Classification(str, Enum):
    OUTBOUND_APPLICATION = "outbound-application"
    ACKNOWLEDGEMENT = "acknowledgement"
    INTERVIEW_INVITE = "interview-invite"
    INTERVIEW_RESCHEDULE = "interview-reschedule"
    TASK_ASSIGNMENT = "task-assignment"
    INFO_REQUEST = "info-request"
    OFFER = "offer"
    REJECTION = "rejection"
    WITHDRAWN_BY_THEM = "withdrawn-by-them"
    PORTAL_ACK = "portal-ack"
    OUT_OF_OFFICE = "out-of-office"
    SUSPICIOUS = "suspicious"
    OTHER = "other"
    NEEDS_REVIEW = "needs-review"


class MatchMethod(str, Enum):
    SENT_THREAD = "sent-thread"
    DOMAIN = "domain"
    SUBJECT = "subject"
    UNTRACKED = "untracked"


# ---------- Attachment ------------------------------------------------------


class AttachmentRef(BaseModel):
    """A single attachment as it appears in the email body and frontmatter."""

    filename: str
    mime_type: str
    size_bytes: int
    saved_to: Optional[str] = None  # relative path under emails/ once written
    saved: bool = True
    reason: Optional[str] = None  # set when saved=False
    deduplicated_to: Optional[str] = None  # set when this attachment is a dup


# ---------- Tracker ---------------------------------------------------------


class TrackerRow(BaseModel):
    """A single row from `job_search_tracker.csv`.

    Canonical column order (the Go dashboard parses the first 8
    positionally — never reorder them; new columns append at the end):
    `date,company,role,location,salary,source,status,notes,domain`.
    Unknown columns from older CSVs are ignored."""

    date: str
    company: str
    role: str
    location: Optional[str] = None
    salary: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    # Explicit primary email-sending domain for the company. Preferred over
    # URL-derived domain when set. Use when the company sends from a domain
    # that cannot be inferred from the source URL (e.g. ATS-hosted
    # applications, multi-domain companies, or any case where the careers
    # URL host differs from the email-sending host).
    domain: Optional[str] = None

    @property
    def folder_key(self) -> str:
        """`<company>_<role>` lowercased with underscores, matching the
        per-application folder convention in `documents/README.md`."""
        company = re.sub(r"[^a-z0-9]+", "_", self.company.lower()).strip("_")
        role = re.sub(r"[^a-z0-9]+", "_", self.role.lower()).strip("_")
        return f"{company}_{role}"

    @property
    def company_domain(self) -> Optional[str]:
        """Primary email-sending domain for the company.

        Resolution order:
        1. Explicit `domain` column if set.
        2. Hostname of the `source` URL, with a leading careers-portal
           prefix (jobs., careers., apply., boards., talent.) stripped.

        Returns None if neither yields a usable host.
        """
        if self.domain:
            d = self.domain.strip().lower()
            return d or None
        return derive_domain_from_url(self.source or "")


# ---------- Email message ---------------------------------------------------


class EmailAddress(BaseModel):
    name: Optional[str] = None
    email: str


class EmailMessage(BaseModel):
    """A single Gmail message in a normalised shape the rest of the
    pipeline operates on. Source-agnostic — populated either from a
    live `googleapiclient` call or from a fixture in tests."""

    message_id: str  # RFC822 Message-ID
    # Gmail API id — required for raw/attachment fetches (the RFC822
    # Message-ID is not a valid `messages.get` id)
    gmail_id: str = ""
    thread_id: str
    direction: Direction
    date_received: datetime
    from_: EmailAddress = Field(alias="from")
    to: list[EmailAddress] = Field(default_factory=list)
    cc: list[EmailAddress] = Field(default_factory=list)
    subject: str = ""
    # Full body as plain text. Quoted/forwarded chains preserved verbatim.
    body_text: str = ""
    # All headers in original order, for the .md extract
    headers: dict[str, str] = Field(default_factory=dict)
    # Attachments as Gmail returns them (filename, mimeType, size, attachmentId)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    # Raw RFC-822 bytes for the .eml file
    raw_bytes: Optional[bytes] = None

    model_config = {"populate_by_name": True}

    @field_validator("date_received", mode="before")
    @classmethod
    def _coerce_datetime(cls, v: Any) -> datetime:
        if isinstance(v, datetime):
            return v
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(v / 1000.0)
        if isinstance(v, str):
            # Try ISO 8601 first (model_dump(mode="json") produces this shape)
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                pass
            # Fall back to RFC 2822 (Gmail Date header)
            from email.utils import parsedate_to_datetime

            try:
                return parsedate_to_datetime(v)
            except (TypeError, ValueError) as e:
                raise ValueError(f"Cannot parse date: {v!r}") from e
        raise ValueError(f"Cannot coerce to datetime: {v!r}")


# ---------- Match + classification ------------------------------------------


class Match(BaseModel):
    """The result of matching an EmailMessage to a tracker row."""

    message: EmailMessage
    matched_application: Optional[str]  # folder_key, or None if untracked
    match_method: MatchMethod
    domain_mismatch: bool = False  # True if From-domain != company known domain
    first_contact_from_domain: bool = False  # True if this is the first time
    #                                        # we've seen a message from this
    #                                        # From-domain for this application
    classification: Classification = Classification.NEEDS_REVIEW
    classification_confidence: float = 0.0
    classifier_source: str = "regex"  # "regex" | "llm"
    classification_signals: list[str] = Field(default_factory=list)
    classification_notes: str = ""
    needs_review: bool = False  # True if classification is ambiguous

    @property
    def file_stem(self) -> str:
        """`<YYYY-MM-DDTHHmm>_<direction>_<slug>` suitable for both .eml and .md."""
        dt = self.message.date_received.strftime("%Y-%m-%dT%H%M")
        slug = self.classification.value
        return f"{dt}_{self.message.direction.value}_{slug}"


# ---------- Plan (output of `plan`, input to `apply`) ----------------------


class PlanFile(BaseModel):
    """The JSON shape passed from `plan` to `apply` over stdout/stdin."""

    matches: list[Match] = Field(default_factory=list)
    unmatched: list[EmailMessage] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.now)
    since: Optional[str] = None  # ISO date — for idempotency and logging

    def dump_json(self) -> str:
        """Serialise to JSON. `raw_bytes` is base64-encoded so the JSON
        stays text-only and the file can be passed over stdin."""
        import base64
        import json

        def _encode(m: EmailMessage) -> dict[str, Any]:
            data = m.model_dump(by_alias=True, mode="json")
            if m.raw_bytes is not None:
                data["raw_bytes_b64"] = base64.b64encode(m.raw_bytes).decode("ascii")
                data.pop("raw_bytes", None)
            return data

        return json.dumps(
            {
                "matches": [
                    {
                        **m.model_dump(mode="json"),
                        "message": _encode(m.message),
                    }
                    for m in self.matches
                ],
                "unmatched": [_encode(m) for m in self.unmatched],
                "generated_at": self.generated_at.isoformat(),
                "since": self.since,
            },
            indent=2,
        )

    @classmethod
    def load_json(cls, payload: str) -> "PlanFile":
        import base64
        import json

        data = json.loads(payload)
        matches = []
        for m in data.get("matches", []):
            msg = m["message"]
            if "raw_bytes_b64" in msg:
                msg["raw_bytes"] = base64.b64decode(msg["raw_bytes_b64"])
                msg.pop("raw_bytes_b64", None)
            matches.append(Match(message=EmailMessage.model_validate(msg), **{k: v for k, v in m.items() if k != "message"}))
        unmatched = []
        for msg in data.get("unmatched", []):
            if "raw_bytes_b64" in msg:
                msg["raw_bytes"] = base64.b64decode(msg["raw_bytes_b64"])
                msg.pop("raw_bytes_b64", None)
            unmatched.append(EmailMessage.model_validate(msg))
        return cls(
            matches=matches,
            unmatched=unmatched,
            generated_at=datetime.fromisoformat(data["generated_at"]) if data.get("generated_at") else datetime.now(),
            since=data.get("since"),
        )
