"""Tests for the archive writer: .eml/.md, attachments, _index.md, idempotency."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tools.email_scanner import paths
from tools.email_scanner.archive import (
    ATTACHMENT_SIZE_CAP_BYTES,
    WriteReport,
    _write_attachment,
    apply_plan,
    sanitise_filename,
)
from tools.email_scanner.models import (
    Classification,
    Direction,
    EmailMessage,
    Match,
    MatchMethod,
    PlanFile,
)
from tests.conftest import make_message


@pytest.fixture
def workspace_with_tracker(tmp_workspace, tracker_csv, gmail_config_json):
    """Pre-populated workspace with the tracker + auth config."""
    return tmp_workspace


def make_match(
    msg: EmailMessage,
    folder_key: str = "abound_graduate_ai_engineer",
    classification: Classification = Classification.REJECTION,
) -> Match:
    return Match(
        message=msg,
        matched_application=folder_key,
        match_method=MatchMethod.SENT_THREAD,
        classification=classification,
        classification_confidence=0.9,
        classifier_source="regex",
        classification_signals=["unfortunately"],
    )


class TestSanitiseFilename:
    def test_simple(self):
        assert sanitise_filename("document.pdf") == "document.pdf"

    def test_strips_path_separators(self):
        assert "/" not in sanitise_filename("a/b/c.pdf")
        assert "\\" not in sanitise_filename("a\\b\\c.pdf")

    def test_strips_control_chars(self):
        assert "\x00" not in sanitise_filename("file\x00name.pdf")

    def test_trims_trailing_dots(self):
        assert sanitise_filename("file.pdf...") == "file.pdf"

    def test_windows_reserved_name(self):
        result = sanitise_filename("CON.pdf")
        assert result.startswith("_")
        assert "CON" in result

    def test_empty_returns_hash_fallback(self):
        result = sanitise_filename("")
        # Empty input → "attachment" (the early-return case)
        assert result == "attachment"

    def test_only_special_chars_returns_hash_fallback(self):
        result = sanitise_filename("///")
        # Sanitising-only-specials leaves underscores, not empty,
        # so the hash fallback is for the *truly empty* case.
        assert result.startswith("_")

    def test_only_special_chars_returns_hash_fallback(self):
        result = sanitise_filename("///")
        assert result.startswith("attachment_")

    def test_long_filename_truncated(self):
        long = "a" * 250 + ".pdf"
        result = sanitise_filename(long)
        assert len(result) <= 200


class TestApplyPlan:
    def test_writes_eml_and_md(self, workspace_with_tracker):
        # Create a per-application folder
        (paths.resolve_emails_folder("abound_graduate_ai_engineer").parent).mkdir(
            parents=True, exist_ok=True
        )

        msg = make_message(
            message_id="<test@mail.gmail.com>",
            sender="recruiter@getabound.com",
            subject="Update on your application",
            body="Unfortunately, we won't be moving forward.",
            raw_bytes=b"raw eml content here",
        )
        plan = PlanFile(matches=[make_match(msg)], unmatched=[])

        report = apply_plan(plan, gmail=None, download_attachments=False)
        assert len(report.errors) == 0, report.render()
        assert "written" in report.render()

        emails_dir = paths.resolve_emails_folder("abound_graduate_ai_engineer")
        eml_files = list(emails_dir.glob("*.eml"))
        md_files = [p for p in emails_dir.glob("*.md") if p.name != "_index.md"]
        index_files = list(emails_dir.glob("_index.md"))
        assert len(eml_files) == 1
        assert len(md_files) == 1
        assert len(index_files) == 1
        assert eml_files[0].read_bytes() == b"raw eml content here"

    def test_idempotent(self, workspace_with_tracker):
        (paths.resolve_emails_folder("abound_graduate_ai_engineer").parent).mkdir(
            parents=True, exist_ok=True
        )

        msg = make_message(
            message_id="<idem@mail.gmail.com>",
            sender="recruiter@getabound.com",
            subject="Test",
            body="Body",
            raw_bytes=b"raw",
        )
        plan = PlanFile(matches=[make_match(msg)], unmatched=[])

        apply_plan(plan, gmail=None, download_attachments=False)
        first_mtime = (paths.resolve_emails_folder("abound_graduate_ai_engineer") / "2026-07-18T0942_inbound_rejection.eml").stat().st_mtime

        # Second run with the same plan
        report = apply_plan(plan, gmail=None, download_attachments=False)
        second_mtime = (paths.resolve_emails_folder("abound_graduate_ai_engineer") / "2026-07-18T0942_inbound_rejection.eml").stat().st_mtime

        # File should be unchanged (same mtime) and the run should have skipped
        assert first_mtime == second_mtime
        assert any("skipped" in s for s in report.skipped) or len(report.skipped) > 0

    def test_attachments_saved(self, workspace_with_tracker):
        (paths.resolve_emails_folder("abound_graduate_ai_engineer").parent).mkdir(
            parents=True, exist_ok=True
        )

        # Mock gmail client
        gmail = MagicMock()
        gmail.get_attachment_bytes.return_value = b"attachment data here"

        msg = make_message(
            message_id="<att@mail.gmail.com>",
            sender="recruiter@getabound.com",
            subject="Rejection",
            body="See attached.",
            raw_bytes=b"raw",
            attachments=[
                {
                    "filename": "decision.pdf",
                    "mimeType": "application/pdf",
                    "size": 21,
                    "attachmentId": "att-1",
                }
            ],
        )
        plan = PlanFile(matches=[make_match(msg)], unmatched=[])

        report = apply_plan(plan, gmail=gmail, download_attachments=True)
        assert len(report.errors) == 0, report.render()
        att_path = (
            paths.resolve_emails_folder("abound_graduate_ai_engineer")
            / "_attachments"
            / "2026-07-18T0942_inbound_rejection"
            / "decision.pdf"
        )
        assert att_path.exists()
        assert att_path.read_bytes() == b"attachment data here"

    def test_oversized_attachment_skipped(self, workspace_with_tracker):
        (paths.resolve_emails_folder("abound_graduate_ai_engineer").parent).mkdir(
            parents=True, exist_ok=True
        )

        gmail = MagicMock()
        gmail.get_attachment_bytes.return_value = b"data"

        msg = make_message(
            message_id="<big@mail.gmail.com>",
            sender="recruiter@getabound.com",
            raw_bytes=b"raw",
            attachments=[
                {
                    "filename": "huge.bin",
                    "mimeType": "application/octet-stream",
                    "size": ATTACHMENT_SIZE_CAP_BYTES + 1,
                    "attachmentId": "att-1",
                }
            ],
        )
        plan = PlanFile(matches=[make_match(msg)], unmatched=[])
        apply_plan(plan, gmail=gmail, download_attachments=True)
        att_path = (
            paths.resolve_emails_folder("abound_graduate_ai_engineer")
            / "_attachments"
            / "2026-07-18T0942_inbound_rejection"
            / "huge.bin"
        )
        assert not att_path.exists()

    def test_attachment_dedup(self, workspace_with_tracker):
        """Two messages with byte-identical attachments share one copy."""
        (paths.resolve_emails_folder("abound_graduate_ai_engineer").parent).mkdir(
            parents=True, exist_ok=True
        )

        gmail = MagicMock()
        gmail.get_attachment_bytes.return_value = b"same data"

        common_attachments = [
            {
                "filename": "shared.pdf",
                "mimeType": "application/pdf",
                "size": 9,
                "attachmentId": "att-1",
            }
        ]
        msg1 = make_message(
            message_id="<m1@mail.gmail.com>",
            sender="recruiter@getabound.com",
            subject="First",
            raw_bytes=b"raw1",
            attachments=common_attachments,
        )
        msg2 = make_message(
            message_id="<m2@mail.gmail.com>",
            sender="recruiter@getabound.com",
            subject="Second",
            body="Different body",
            raw_bytes=b"raw2",
            attachments=common_attachments,
        )
        plan = PlanFile(
            matches=[make_match(msg1, classification=Classification.INTERVIEW_INVITE),
                     make_match(msg2, classification=Classification.REJECTION)],
            unmatched=[],
        )
        apply_plan(plan, gmail=gmail, download_attachments=True)
        # Only one copy should exist
        att_paths = list(
            paths.resolve_emails_folder("abound_graduate_ai_engineer")
            .rglob("shared.pdf")
        )
        assert len(att_paths) == 1


class TestMarkdownRendering:
    def test_full_headers_preserved(self, workspace_with_tracker):
        (paths.resolve_emails_folder("abound_graduate_ai_engineer").parent).mkdir(
            parents=True, exist_ok=True
        )

        msg = make_message(
            message_id="<full@mail.gmail.com>",
            sender="recruiter@getabound.com",
            subject="Test subject",
            body="Body content",
            raw_bytes=b"raw",
            headers={
                "From": "recruiter@getabound.com",
                "To": "yash@example.com",
                "Subject": "Test subject",
                "X-Custom-Header": "custom-value",
                "Authentication-Results": "dkim=pass",
            },
        )
        plan = PlanFile(matches=[make_match(msg)], unmatched=[])
        apply_plan(plan, gmail=None, download_attachments=False)

        md_path = (
            paths.resolve_emails_folder("abound_graduate_ai_engineer")
            / "2026-07-18T0942_inbound_rejection.md"
        )
        text = md_path.read_text(encoding="utf-8")
        assert "X-Custom-Header: custom-value" in text
        assert "Authentication-Results: dkim=pass" in text
        assert "Test subject" in text
        assert "Body content" in text

    def test_urls_preserved_not_stripped(self, workspace_with_tracker):
        (paths.resolve_emails_folder("abound_graduate_ai_engineer").parent).mkdir(
            parents=True, exist_ok=True
        )

        msg = make_message(
            message_id="<url@mail.gmail.com>",
            sender="recruiter@getabound.com",
            subject="With link",
            body="Please review https://example.com/portal/123",
            raw_bytes=b"raw",
        )
        plan = PlanFile(matches=[make_match(msg)], unmatched=[])
        apply_plan(plan, gmail=None, download_attachments=False)
        md_text = (
            paths.resolve_emails_folder("abound_graduate_ai_engineer")
            / "2026-07-18T0942_inbound_rejection.md"
        ).read_text(encoding="utf-8")
        assert "https://example.com/portal/123" in md_text

    def test_index_md_regenerated(self, workspace_with_tracker):
        (paths.resolve_emails_folder("abound_graduate_ai_engineer").parent).mkdir(
            parents=True, exist_ok=True
        )

        msg = make_message(
            message_id="<idx@mail.gmail.com>",
            sender="recruiter@getabound.com",
            subject="Index test",
            raw_bytes=b"raw",
        )
        plan = PlanFile(matches=[make_match(msg)], unmatched=[])
        apply_plan(plan, gmail=None, download_attachments=False)
        index_path = (
            paths.resolve_emails_folder("abound_graduate_ai_engineer") / "_index.md"
        )
        text = index_path.read_text(encoding="utf-8")
        assert "# Email index" in text
        assert "Index test" in text
        assert "2026-07-18 09:42" in text


class TestPlanFileSerialization:
    def test_round_trip(self):
        msg = make_message(
            message_id="<rt@mail.gmail.com>",
            raw_bytes=b"raw content",
        )
        m = make_match(msg)
        plan = PlanFile(matches=[m], unmatched=[])
        payload = plan.dump_json()
        loaded = PlanFile.load_json(payload)
        assert len(loaded.matches) == 1
        assert loaded.matches[0].message.raw_bytes == b"raw content"
        assert loaded.matches[0].classification == Classification.REJECTION
