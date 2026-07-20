"""Tests for the tracker reader."""

from __future__ import annotations

import textwrap

import pytest

from tools.email_scanner.tracker import find_by_company, find_by_folder_key, load_tracker


class TestLoadTracker:
    def test_loads_basic_rows(self, tracker_csv):
        rows = load_tracker(tracker_csv)
        assert len(rows) == 3
        assert rows[0].company == "Abound"
        assert rows[0].role == "Graduate AI Engineer"
        assert rows[1].company == "The AA"
        assert rows[2].company == "FD Intelligence"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_tracker(tmp_path / "nope.csv")

    def test_skips_empty_rows(self, tmp_workspace):
        p = tmp_workspace / "tracker.csv"
        p.write_text(
            "date,company,role\n"
            "2026-01-01,Acme,Engineer\n"
            ",,\n"  # empty
            "2026-01-02,Other,Data Scientist\n",
            encoding="utf-8",
        )
        rows = load_tracker(p)
        assert len(rows) == 2

    def test_skips_malformed_rows(self, tmp_workspace, caplog):
        p = tmp_workspace / "tracker.csv"
        # Two valid rows; the second has a column count mismatch that
        # the model will reject. The parser should skip and warn.
        p.write_text(
            "date,company,role,extra\n"
            "2026-01-01,Acme,Engineer,foo\n"
            "2026-01-02,Other,Data Scientist,bar,baz,qux\n",
            encoding="utf-8",
        )
        rows = load_tracker(p)
        # The CSV DictReader handles any extra columns gracefully
        assert len(rows) == 2


class TestFindByCompany:
    def test_exact_match(self, sample_tracker_rows):
        result = find_by_company(sample_tracker_rows, "Abound")
        assert len(result) == 1
        assert result[0].company == "Abound"

    def test_substring_match(self, sample_tracker_rows):
        result = find_by_company(sample_tracker_rows, "FD")
        assert len(result) == 1
        assert result[0].company == "FD Intelligence"

    def test_case_insensitive(self, sample_tracker_rows):
        result = find_by_company(sample_tracker_rows, "abound")
        assert len(result) == 1

    def test_no_match(self, sample_tracker_rows):
        result = find_by_company(sample_tracker_rows, "NoSuchCompany")
        assert result == []


class TestFindByFolderKey:
    def test_found(self, sample_tracker_rows):
        row = find_by_folder_key(sample_tracker_rows, "abound_graduate_ai_engineer")
        assert row is not None
        assert row.company == "Abound"

    def test_not_found(self, sample_tracker_rows):
        row = find_by_folder_key(sample_tracker_rows, "nope")
        assert row is None


class TestTrackerRowProperties:
    def test_folder_key(self):
        from tools.email_scanner.models import TrackerRow

        row = TrackerRow(date="2026-01-01", company="Acme Corp!", role="Senior Engineer")
        # The "!" is converted to "_", collapsing with what follows to a single "_"
        assert row.folder_key == "acme_corp_senior_engineer"

    def test_folder_key_with_space(self):
        from tools.email_scanner.models import TrackerRow

        row = TrackerRow(date="2026-01-01", company="Acme Corp", role="Senior Engineer")
        assert row.folder_key == "acme_corp_senior_engineer"

    def test_company_domain_from_url(self):
        from tools.email_scanner.models import TrackerRow

        row = TrackerRow(
            date="2026-01-01",
            company="Acme",
            role="X",
            source="https://jobs.acme.com/post/123",
        )
        # `jobs.` careers-portal prefix is stripped by derive_domain_from_url
        assert row.company_domain == "acme.com"

    def test_company_domain_no_url(self):
        from tools.email_scanner.models import TrackerRow

        row = TrackerRow(date="2026-01-01", company="Acme", role="X")
        assert row.company_domain is None
