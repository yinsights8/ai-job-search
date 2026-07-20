"""Tests for the matcher: three-pass dedup, ordering, and flags."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from tools.email_scanner.match import (
    MatcherConfig,
    _same_registrable,
    match_tracker,
)
from tools.email_scanner.models import Direction, EmailMessage
from tests.conftest import make_message


class FakeGmail:
    """Mock GmailClient with deterministic search and fetch behaviour.

    Configure via:
        fake.search_responses[query] = [message_id, ...]
        fake.messages[message_id] = EmailMessage(...)
        fake.threads[thread_id] = [EmailMessage, ...]
    """

    def __init__(self):
        self.search_responses: dict[str, list[str]] = {}
        self.messages: dict[str, EmailMessage] = {}
        self.threads: dict[str, list[EmailMessage]] = {}

    def search(self, query: str, max_results: int = 100):
        return list(self.search_responses.get(query, []))[:max_results]

    def get_message(self, message_id: str, fmt: str = "full"):
        return self.messages[message_id]

    def get_thread(self, thread_id: str):
        return list(self.threads.get(thread_id, []))


class TestMatchTracker:
    def test_domain_pass_matches(self, sample_tracker_rows):
        gmail = FakeGmail()
        # Abound tracker row has source https://jobs.getabound.com/... so
        # the matcher queries "from:getabound.com" (careers prefix stripped).
        gmail.search_responses["from:getabound.com"] = ["m1"]
        gmail.messages["m1"] = make_message(
            message_id="<m1@mail.gmail.com>",
            sender="recruiter@jobs.getabound.com",
            subject="Update on your application",
        )

        config = MatcherConfig(use_llm=False)
        result = match_tracker(sample_tracker_rows, gmail, config)
        assert len(result.matches) == 1
        assert result.matches[0].matched_application == "abound_graduate_ai_engineer"
        assert result.matches[0].match_method.value == "domain"

    def test_alert_digest_senders_are_dropped(self, sample_tracker_rows):
        gmail = FakeGmail()
        gmail.search_responses["from:getabound.com"] = ["m1", "m2"]
        gmail.messages["m1"] = make_message(
            message_id="<m1@mail.gmail.com>",
            sender="donotreply@jobalert.indeed.com",
            subject="10 new Graduate AI Engineer jobs for you",
        )
        gmail.messages["m2"] = make_message(
            message_id="<m2@mail.gmail.com>",
            sender="recruiter@jobs.getabound.com",
            subject="Update on your application",
        )

        config = MatcherConfig(use_llm=False)
        result = match_tracker(sample_tracker_rows, gmail, config)
        assert len(result.matches) == 1
        assert result.matches[0].message.message_id == "<m2@mail.gmail.com>"

    def test_sent_thread_pass(self, sample_tracker_rows):
        gmail = FakeGmail()
        # User sent an email to jobs.getabound.com, Abound replied
        sent_msg = make_message(
            message_id="<sent@mail.gmail.com>",
            thread_id="t1",
            direction=Direction.OUTBOUND,
            sender="candidate@example.com",
            subject="Application — Graduate AI Engineer",
        )
        inbound_msg = make_message(
            message_id="<in@mail.gmail.com>",
            thread_id="t1",
            direction=Direction.INBOUND,
            sender="recruiter@jobs.getabound.com",
            subject="Re: Application — Graduate AI Engineer",
        )
        # The matcher uses _build_company_queries which produces
        # "in:sent (\"Abound\")" and (when include_domain) an
        # "in:sent (to:getabound.com OR from:getabound.com)" query
        gmail.search_responses['in:sent ("Abound")'] = ["sent-msg-id"]
        gmail.search_responses["in:sent (to:getabound.com OR from:getabound.com)"] = ["sent-msg-id"]
        gmail.messages["sent-msg-id"] = sent_msg
        gmail.threads["t1"] = [sent_msg, inbound_msg]

        config = MatcherConfig(use_llm=False)
        result = match_tracker(sample_tracker_rows, gmail, config)
        # Both sent and inbound should appear
        assert len(result.matches) == 2
        directions = {m.message.direction for m in result.matches}
        assert directions == {Direction.INBOUND, Direction.OUTBOUND}

    def test_dedup_by_message_id(self, sample_tracker_rows):
        """The same message appearing in two passes should be deduped."""
        gmail = FakeGmail()
        msg = make_message(
            message_id="<dup@mail.gmail.com>",
            sender="recruiter@jobs.getabound.com",
            subject="Update on your application",
        )
        # Appears in both domain and subject passes
        gmail.search_responses["from:getabound.com"] = ["m1"]
        gmail.search_responses['subject:("Abound" OR "Graduate AI Engineer")'] = ["m1"]
        gmail.messages["m1"] = msg

        config = MatcherConfig(use_llm=False)
        result = match_tracker(sample_tracker_rows, gmail, config)
        assert len(result.matches) == 1

    def test_domain_mismatch_flag(self, sample_tracker_rows):
        """If the From-domain is unrelated to the company's known
        domain, set `domain_mismatch=True`."""
        gmail = FakeGmail()
        gmail.search_responses["from:getabound.com"] = ["m1"]
        gmail.messages["m1"] = make_message(
            message_id="<m1@mail.gmail.com>",
            sender="someone@totally-different.com",
            subject="Update on your application",
        )
        config = MatcherConfig(use_llm=False)
        result = match_tracker(sample_tracker_rows, gmail, config)
        assert result.matches[0].domain_mismatch is True

    def test_first_contact_warning(self, sample_tracker_rows):
        """The first time we see a From-domain, the first_contact flag
        is True; subsequent messages from the same domain set it to False."""
        gmail = FakeGmail()
        gmail.search_responses["from:getabound.com"] = ["m1", "m2"]
        gmail.messages["m1"] = make_message(
            message_id="<m1@mail.gmail.com>",
            sender="recruiter@jobs.getabound.com",
        )
        gmail.messages["m2"] = make_message(
            message_id="<m2@mail.gmail.com>",
            sender="hr@jobs.getabound.com",
        )
        config = MatcherConfig(use_llm=False)
        result = match_tracker(sample_tracker_rows, gmail, config)
        first_contact_flags = [m.first_contact_from_domain for m in result.matches]
        # m1 is the first message from jobs.getabound.com → True
        # m2 is also from jobs.getabound.com (after @) → False
        assert first_contact_flags[0] is True
        assert first_contact_flags[1] is False
        assert len(result.first_contact_warnings) == 1

    def test_no_results(self, sample_tracker_rows):
        gmail = FakeGmail()
        config = MatcherConfig(use_llm=False)
        result = match_tracker(sample_tracker_rows, gmail, config)
        assert result.matches == []


class TestSameRegistrable:
    def test_same(self):
        assert _same_registrable("example.com", "example.com") is True

    def test_subdomain_matches(self):
        assert _same_registrable("mail.example.com", "example.com") is True

    def test_different(self):
        assert _same_registrable("example.com", "different.com") is False

    def test_different_tld(self):
        assert _same_registrable("example.com", "example.org") is False
