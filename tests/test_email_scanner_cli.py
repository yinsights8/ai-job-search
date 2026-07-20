"""End-to-end tests for the CLI: status, revoke, plan, apply."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.email_scanner import __main__ as cli_main
from tools.email_scanner.auth import READONLY_SCOPE, StoredToken, TokenStore


def run_cli(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    """Invoke the CLI as a subprocess. Returns the completed process."""
    cmd = [sys.executable, "-m", "tools.email_scanner", *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        stdin=subprocess.PIPE if stdin is not None else None,
        input=stdin,
        timeout=60,
        cwd=str(Path(__file__).resolve().parents[1]),
    )


class TestStatus:
    def test_status_no_tokens(self, tmp_workspace, gmail_config_json, monkeypatch):
        monkeypatch.chdir(tmp_workspace)
        result = run_cli("status")
        assert "tokens_present: no" in result.stdout
        assert result.returncode == 0

    def test_status_with_tokens(self, tmp_workspace, gmail_config_json, monkeypatch):
        monkeypatch.chdir(tmp_workspace)
        # Save a readonly token
        store = TokenStore(tmp_workspace / "auth" / "tokens.json")
        store.save(
            StoredToken(
                access_token="x",
                refresh_token="y",
                token_type="Bearer",
                scopes=[READONLY_SCOPE],
            )
        )
        result = run_cli("status")
        assert "tokens_present: yes" in result.stdout
        assert "readonly: yes" in result.stdout

    def test_status_non_readonly_warns(self, tmp_workspace, gmail_config_json, monkeypatch):
        monkeypatch.chdir(tmp_workspace)
        store = TokenStore(tmp_workspace / "auth" / "tokens.json")
        store.save(
            StoredToken(
                access_token="x",
                refresh_token="y",
                token_type="Bearer",
                scopes=["https://www.googleapis.com/auth/gmail.modify"],
            )
        )
        result = run_cli("status")
        assert "WARNING" in result.stderr or "NO — STOP" in result.stdout
        assert result.returncode == 1


class TestRevoke:
    def test_revoke_no_tokens(self, tmp_workspace, gmail_config_json, monkeypatch):
        monkeypatch.chdir(tmp_workspace)
        result = run_cli("revoke")
        assert "No tokens to revoke" in result.stdout
        assert result.returncode == 0

    def test_revoke_deletes_tokens(self, tmp_workspace, gmail_config_json, monkeypatch):
        monkeypatch.chdir(tmp_workspace)
        store = TokenStore(tmp_workspace / "auth" / "tokens.json")
        store.save(
            StoredToken(access_token="x", refresh_token="y", token_type="Bearer")
        )
        assert (tmp_workspace / "auth" / "tokens.json").exists()
        result = run_cli("revoke")
        assert "Token revoked" in result.stdout or "revocation call failed" in result.stdout
        assert "Deleted" in result.stdout
        assert not (tmp_workspace / "auth" / "tokens.json").exists()
        # Idempotent
        result2 = run_cli("revoke")
        assert "No tokens to revoke" in result2.stdout


class TestVersion:
    def test_version_flag(self):
        result = run_cli("--version")
        assert "0.1.0" in result.stdout


class TestStats:
    def test_stats_empty(self, tmp_workspace, monkeypatch):
        monkeypatch.chdir(tmp_workspace)
        result = run_cli("stats")
        assert "No archived emails yet" in result.stdout
        assert result.returncode == 0
