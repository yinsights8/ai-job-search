"""Three-pass matching: Sent-thread → Domain → Subject.

For each tracker row, the matcher queries Gmail and produces Match
records. The three passes dedup by Message-ID.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from .classify import Classification, classify, apply_classification
from .gmail import GmailClient
from .models import Direction, EmailMessage, Match, MatchMethod, TrackerRow
from .redactor import safe_log_message

log = logging.getLogger("email_scanner.match")


# Job-board alert/digest senders. These are marketing-style job
# suggestions that keyword-match tracker rows but are never genuine
# application correspondence, so the matcher drops them outright.
ALERT_DIGEST_DOMAINS: frozenset[str] = frozenset(
    {
        "jobalert.indeed.com",
        "match.indeed.com",
        "lensa.com",
        "jobleads.com",
        "spelljob.com",
        "hirist.tech",
        "vaia.com",
        "glassdoor.com",
        "artificialintelligencejobs.co.uk",
        "m.teksystems.com",
        "twinehq.com",
    }
)


def _is_alert_digest(msg: EmailMessage) -> bool:
    email = (msg.from_.email or "").lower()
    domain = email.split("@")[-1] if "@" in email else ""
    return domain in ALERT_DIGEST_DOMAINS


@dataclass
class MatcherConfig:
    """Per-run configuration for the matcher."""

    use_llm: bool = True
    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "llama3.2:3b"
    llm_api_key: Optional[str] = None
    llm_timeout: int = 120
    max_results_per_query: int = 100
    since: Optional[datetime] = None  # only consider messages after this


@dataclass
class MatchResult:
    matches: list[Match] = field(default_factory=list)
    unmatched: list[EmailMessage] = field(default_factory=list)
    seen_message_ids: set[str] = field(default_factory=set)
    first_contact_warnings: list[str] = field(default_factory=list)


# ---------- Entry point -----------------------------------------------------


def match_tracker(
    rows: list[TrackerRow],
    gmail: GmailClient,
    config: MatcherConfig,
) -> MatchResult:
    """Run all three passes for every tracker row. Returns a MatchResult
    aggregating the matches and the messages that couldn't be assigned."""
    result = MatchResult()
    seen_domains_per_app: dict[str, set[str]] = {}

    for row in rows:
        # Per-application state for the "first contact from this domain" warning
        seen_domains_per_app.setdefault(row.folder_key, set())
        candidates: list[EmailMessage] = []

        # Pass 1: Sent-thread
        try:
            candidates.extend(_pass_sent_thread(row, gmail, config))
        except Exception as e:
            log.warning("Sent-thread pass failed for %s: %s", row.folder_key, safe_log_message(e))

        # Pass 2: Domain
        try:
            candidates.extend(_pass_domain(row, gmail, config))
        except Exception as e:
            log.warning("Domain pass failed for %s: %s", row.folder_key, safe_log_message(e))

        # Pass 3: Subject
        try:
            candidates.extend(_pass_subject(row, gmail, config))
        except Exception as e:
            log.warning("Subject pass failed for %s: %s", row.folder_key, safe_log_message(e))

        # Dedup and assign
        for msg in candidates:
            if msg.message_id in result.seen_message_ids:
                continue
            result.seen_message_ids.add(msg.message_id)
            if _is_alert_digest(msg):
                log.info("dropping alert digest from %s", msg.from_.email)
                continue

            match = _build_match(msg, row, seen_domains_per_app[row.folder_key])
            if match.first_contact_from_domain:
                result.first_contact_warnings.append(
                    f"{row.folder_key}: first contact from {match.message.from_.email}"
                )

            # Classify
            cls_result = classify(
                match.message,
                use_llm=config.use_llm,
                llm_base_url=config.llm_base_url,
                llm_model=config.llm_model,
                llm_api_key=config.llm_api_key,
                llm_timeout=config.llm_timeout,
            )
            apply_classification(match, cls_result)

            result.matches.append(match)

    return result


# ---------- Per-pass logic --------------------------------------------------


def _pass_sent_thread(
    row: TrackerRow, gmail: GmailClient, config: MatcherConfig
) -> list[EmailMessage]:
    """Find Sent-mail messages to this company, then expand to the thread
    in the Inbox. Captures both outbound (your application) and inbound
    (their replies) in the same thread."""
    out: list[EmailMessage] = []
    queries = _build_company_queries(row, include_domain=True, since=config.since)
    seen_thread_ids: set[str] = set()

    for q in queries:
        ids = gmail.search(q, max_results=config.max_results_per_query)
        for mid in ids:
            try:
                msg = gmail.get_message(mid)
            except Exception:
                continue
            if msg.thread_id in seen_thread_ids:
                continue
            seen_thread_ids.add(msg.thread_id)
            # Fetch the entire thread to capture the full chain
            try:
                thread = gmail.get_thread(msg.thread_id)
                out.extend(thread)
            except Exception:
                out.append(msg)
    return out


def _pass_domain(
    row: TrackerRow, gmail: GmailClient, config: MatcherConfig
) -> list[EmailMessage]:
    """Inbox messages from the company's known domain. Catches ATS and
    portal responses even when the user never sent an email directly."""
    out: list[EmailMessage] = []
    if not row.company_domain:
        return out
    query = f"from:{row.company_domain}"
    if config.since:
        query += f" after:{config.since.strftime('%Y/%m/%d')}"
    ids = gmail.search(query, max_results=config.max_results_per_query)
    for mid in ids:
        try:
            out.append(gmail.get_message(mid))
        except Exception:
            continue
    return out


def _pass_subject(
    row: TrackerRow, gmail: GmailClient, config: MatcherConfig
) -> list[EmailMessage]:
    """Subject-keyword last-resort pass."""
    out: list[EmailMessage] = []
    company = _escape_gmail_query(row.company)
    role = _escape_gmail_query(row.role)
    if company:
        q = f'subject:("{company}" OR "{role}")'
        if config.since:
            q += f" after:{config.since.strftime('%Y/%m/%d')}"
        ids = gmail.search(q, max_results=config.max_results_per_query)
        for mid in ids:
            try:
                out.append(gmail.get_message(mid))
            except Exception:
                continue
    return out


def _build_company_queries(
    row: TrackerRow, include_domain: bool = True, since: Optional[datetime] = None
) -> list[str]:
    """Build Gmail search queries that target Sent mail related to a
    tracker row. Multiple variants increase recall."""
    company = _escape_gmail_query(row.company)
    base_qualifiers = []
    if since:
        base_qualifiers.append(f"after:{since.strftime('%Y/%m/%d')}")
    qs: list[str] = []
    if company:
        qs.append(f"in:sent ({company}) {' '.join(base_qualifiers)}".strip())
    if include_domain and row.company_domain:
        qs.append(f"in:sent (to:{row.company_domain} OR from:{row.company_domain}) {' '.join(base_qualifiers)}".strip())
    return qs


def _escape_gmail_query(s: str) -> str:
    """Wrap a phrase in quotes so Gmail treats it as a phrase match.
    Strip quotes from the input to avoid breaking out of the wrap."""
    s = (s or "").strip().replace('"', "")
    if not s:
        return ""
    return f'"{s}"'


# ---------- Per-message -----------------------------------------------------


def _build_match(
    msg: EmailMessage, row: TrackerRow, seen_domains: set[str]
) -> Match:
    """Construct a Match record with first-contact / domain-mismatch flags."""
    sender_domain = msg.from_.email.split("@")[-1].lower() if msg.from_.email and "@" in msg.from_.email else ""
    company_domain = (row.company_domain or "").lower()
    domain_mismatch = bool(
        company_domain and sender_domain and not _same_registrable(sender_domain, company_domain)
    )
    first_contact = bool(sender_domain and sender_domain not in seen_domains)
    if sender_domain:
        seen_domains.add(sender_domain)

    # Choose the match method based on the original direction + how we found it
    method = (
        MatchMethod.SENT_THREAD
        if msg.direction == Direction.OUTBOUND
        else MatchMethod.DOMAIN
        if company_domain and _same_registrable(sender_domain, company_domain)
        else MatchMethod.SUBJECT
    )

    return Match(
        message=msg,
        matched_application=row.folder_key,
        match_method=method,
        domain_mismatch=domain_mismatch,
        first_contact_from_domain=first_contact,
    )


def _same_registrable(a: str, b: str) -> bool:
    """Loose match: same registrable domain. Handles e.g. `mail.company.com`
    vs `company.com` by checking the last two labels."""
    def base(d: str) -> str:
        parts = d.lower().split(".")
        if len(parts) >= 2:
            return ".".join(parts[-2:])
        return d.lower()

    return base(a) == base(b)
