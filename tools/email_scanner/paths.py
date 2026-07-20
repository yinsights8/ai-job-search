"""Filesystem paths used by the email-scanner pipeline.

Single source of truth so the rest of the code never has to know about
the repo layout, the auth folder, or the application folder structure.

The repo root can be overridden via the `EMAIL_SCANNER_ROOT` env var.
This is used by tests to redirect all paths to a temp directory.
"""

from __future__ import annotations

import os
from pathlib import Path


def _repo_root() -> Path:
    """Resolve the repo root. Honours EMAIL_SCANNER_ROOT for tests."""
    env = os.environ.get("EMAIL_SCANNER_ROOT")
    if env:
        return Path(env).resolve()
    # Default: this file lives at <root>/tools/email_scanner/paths.py
    return Path(__file__).resolve().parents[2]


# These are recomputed on each call so the env var is honoured even
# after import (the tests use monkeypatch.setenv before any other call).
def ROOT() -> Path:
    return _repo_root()


def AUTH_DIR() -> Path:
    return ROOT() / "auth"


def OAUTH_CLIENT_FILE() -> Path:
    return AUTH_DIR() / "oauth-client.json"


def GMAIL_CONFIG_FILE() -> Path:
    return AUTH_DIR() / "gmail-config.json"


def TOKENS_FILE() -> Path:
    return AUTH_DIR() / "tokens.json"


def APPLICATIONS_DIR() -> Path:
    return ROOT() / "documents" / "applications"


def TRACKER_FILE() -> Path:
    return ROOT() / "job_search_tracker.csv"


EMAILS_SUBDIR = "emails"
ATTACHMENTS_SUBDIR = "_attachments"
INDEX_FILE_NAME = "_index.md"


def application_folder(folder_key: str) -> Path:
    """`documents/applications/<company>_<role>/`."""
    return APPLICATIONS_DIR() / folder_key


def emails_folder(folder_key: str) -> Path:
    """`documents/applications/<company>_<role>/emails/`."""
    return application_folder(folder_key) / EMAILS_SUBDIR


def attachments_folder(folder_key: str, message_stem: str) -> Path:
    """`documents/applications/<company>_<role>/emails/_attachments/<message-stem>/`."""
    return emails_folder(folder_key) / ATTACHMENTS_SUBDIR / message_stem


def eml_path(folder_key: str, stem: str) -> Path:
    return emails_folder(folder_key) / f"{stem}.eml"


def md_path(folder_key: str, stem: str) -> Path:
    return emails_folder(folder_key) / f"{stem}.md"


def archive_dir_override() -> Path | None:
    """Optional override from gmail-config.json: if the user has set
    `archive_dir` in the config, archive there instead of under
    `documents/applications/`. The override is a relative path under
    the repo root, or an absolute path."""
    try:
        import json

        if not GMAIL_CONFIG_FILE().exists():
            return None
        with GMAIL_CONFIG_FILE().open("r", encoding="utf-8") as f:
            cfg = json.load(f)
        override = cfg.get("archive_dir")
        if not override:
            return None
        p = Path(override)
        if not p.is_absolute():
            p = ROOT() / p
        return p
    except Exception:
        return None


def resolve_emails_folder(folder_key: str) -> Path:
    """If `archive_dir` is set, returns `<archive_dir>/<folder_key>/emails/`.
    Otherwise the default location under `documents/applications/`."""
    override = archive_dir_override()
    if override is not None:
        return override / folder_key / EMAILS_SUBDIR
    return emails_folder(folder_key)


def ensure_repo_paths() -> None:
    """Sanity check: required directories exist. Raises FileNotFoundError
    if the repo layout is unexpected."""
    if not ROOT().exists():
        raise FileNotFoundError(f"Repo root not found: {ROOT()}")
    if not APPLICATIONS_DIR().exists():
        raise FileNotFoundError(f"Applications dir not found: {APPLICATIONS_DIR()}")
