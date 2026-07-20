"""Read `job_search_tracker.csv` and produce TrackerRow records.

The canonical CSV schema is
`date,company,role,location,salary,source,status,notes,domain`.
We parse defensively by header name and accept any column order;
unknown columns from older CSVs are ignored.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Iterable, Optional

from . import paths
from .models import TrackerRow

log = logging.getLogger("email_scanner.tracker")


def _normalise_header(h: str) -> str:
    return (h or "").strip().lower().replace(" ", "_")


def load_tracker(path: Path | None = None) -> list[TrackerRow]:
    """Read the tracker CSV and return one TrackerRow per line.

    Empty lines and header rows are skipped. Malformed lines produce a
    warning and are skipped (we never raise on a single bad row — the
    tracker is the system of record and the user can fix it)."""
    p = path or paths.TRACKER_FILE()
    if not p.exists():
        raise FileNotFoundError(f"Tracker not found: {p}")

    rows: list[TrackerRow] = []
    with p.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for i, raw in enumerate(reader, start=2):  # start=2: header is line 1
            try:
                normalised = {_normalise_header(k): (v or "").strip() for k, v in raw.items() if k}
                if not normalised.get("company") or not normalised.get("role"):
                    # Empty row or missing required fields
                    continue
                rows.append(TrackerRow(**normalised))
            except Exception as e:
                log.warning("Skipping tracker row %d: %s", i, e)
    return rows


def find_by_company(
    rows: Iterable[TrackerRow], company: str
) -> list[TrackerRow]:
    """Case-insensitive partial match on company name."""
    needle = company.lower()
    return [r for r in rows if needle in r.company.lower()]


def find_by_folder_key(rows: Iterable[TrackerRow], folder_key: str) -> Optional[TrackerRow]:
    for r in rows:
        if r.folder_key == folder_key:
            return r
    return None
