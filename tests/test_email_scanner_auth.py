"""Tests for the auth module: config loading, token store, revoke, status."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from tools.email_scanner.auth import (
    READONLY_SCOPE,
    AuthError,
    GmailConfig,
    ScopeError,
    StoredToken,
    TokenStore,
    check_llm_endpoint,
    credentials_to_stored,
    load_config,
    report_status,
    revoke_token,
    verify_scopes_via_tokeninfo,
)


class TestLoadConfig:
    def test_loads_valid_config(self, gmail_config_json):
        cfg = load_config(gmail_config_json)
        assert cfg.client_id == "test.apps.googleusercontent.com"
        assert cfg.client_secret == "test-secret"
        assert cfg.scopes == [READONLY_SCOPE]
        assert cfg.readonly_scope is True
        assert cfg.redirect_uri == "http://localhost:3000/oauth2callback"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(AuthError, match="Config not found"):
            load_config(tmp_path / "nope.json")

    def test_invalid_json_raises(self, tmp_workspace):
        p = tmp_workspace / "auth" / "gmail-config.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("not json", encoding="utf-8")
        with pytest.raises(AuthError, match="Invalid JSON"):
            load_config(p)

    def test_missing_required_field_raises(self, tmp_workspace):
        p = tmp_workspace / "auth" / "gmail-config.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"client_id": "x"}), encoding="utf-8")
        with pytest.raises(AuthError, match="Missing required field"):
            load_config(p)

    def test_wrong_scope_raises_via_property(self, tmp_workspace):
        p = tmp_workspace / "auth" / "gmail-config.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {
                    "client_id": "x",
                    "client_secret": "y",
                    "redirect_uris": ["http://localhost:3000/oauth2callback"],
                    "scopes": ["https://www.googleapis.com/auth/gmail.modify"],
                }
            ),
            encoding="utf-8",
        )
        cfg = load_config(p)
        assert cfg.readonly_scope is False


class TestTokenStore:
    def test_exists_false_initially(self, tmp_workspace):
        store = TokenStore(tmp_workspace / "auth" / "tokens.json")
        assert store.exists() is False
        assert store.load() is None

    def test_save_and_load(self, tmp_workspace):
        path = tmp_workspace / "auth" / "tokens.json"
        store = TokenStore(path)
        token = StoredToken(
            access_token="access",
            refresh_token="refresh",
            token_type="Bearer",
            expiry=datetime(2027, 1, 1, tzinfo=timezone.utc),
            scopes=[READONLY_SCOPE],
        )
        store.save(token)
        assert store.exists()
        loaded = store.load()
        assert loaded.access_token == "access"
        assert loaded.refresh_token == "refresh"
        assert loaded.is_readonly is True

    def test_delete(self, tmp_workspace):
        path = tmp_workspace / "auth" / "tokens.json"
        store = TokenStore(path)
        store.save(StoredToken(access_token="x", refresh_token="y", token_type="Bearer"))
        assert store.exists()
        assert store.delete() is True
        assert store.exists() is False
        # Deleting again is a no-op
        assert store.delete() is False

    def test_is_expired(self):
        from datetime import timedelta

        past = datetime.now(timezone.utc) - timedelta(hours=2)
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        t_past = StoredToken(access_token="x", refresh_token="y", token_type="Bearer", expiry=past)
        t_future = StoredToken(access_token="x", refresh_token="y", token_type="Bearer", expiry=future)
        assert t_past.is_expired is True
        assert t_future.is_expired is False

    def test_is_readonly(self):
        t1 = StoredToken(access_token="x", refresh_token="y", token_type="Bearer", scopes=[READONLY_SCOPE])
        t2 = StoredToken(
            access_token="x", refresh_token="y", token_type="Bearer",
            scopes=["https://www.googleapis.com/auth/gmail.modify"],
        )
        assert t1.is_readonly is True
        assert t2.is_readonly is False


class TestCredentialsToStored:
    def test_round_trip(self):
        from tools.email_scanner.auth import AuthenticatedCredentials

        creds = AuthenticatedCredentials(
            access_token="a",
            refresh_token="r",
            token_uri="https://oauth2.googleapis.com/token",
            client_id="c",
            client_secret="s",
            scopes=[READONLY_SCOPE],
            expiry=datetime(2027, 1, 1, tzinfo=timezone.utc),
        )
        stored = credentials_to_stored(creds)
        assert stored.access_token == "a"
        assert stored.refresh_token == "r"
        assert stored.is_readonly is True


class TestRevokeToken:
    def test_no_token(self):
        token = StoredToken(access_token="", refresh_token=None, token_type="Bearer")
        assert revoke_token(token) is False

    @patch("urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        from unittest.mock import MagicMock

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda self: self
        mock_resp.__exit__ = lambda self, *a: None
        mock_urlopen.return_value = mock_resp
        token = StoredToken(access_token="abc", refresh_token="r", token_type="Bearer")
        assert revoke_token(token) is True

    @patch("urllib.request.urlopen")
    def test_already_revoked_is_treated_as_success(self, mock_urlopen):
        from urllib.error import HTTPError
        from unittest.mock import MagicMock

        mock_urlopen.side_effect = HTTPError(
            "https://oauth2.googleapis.com/revoke", 400, "Bad Request", {}, None
        )
        token = StoredToken(access_token="abc", refresh_token="r", token_type="Bearer")
        assert revoke_token(token) is True


@patch("tools.email_scanner.auth.check_llm_endpoint", return_value=False)
class TestStatus:
    def test_no_tokens(self, _mock_llm, gmail_config_json):
        store = TokenStore(gmail_config_json.parent / "tokens.json")
        config = load_config(gmail_config_json)
        status = report_status(store, config)
        assert status.tokens_present is False
        assert status.readonly is False
        assert status.llm_reachable is False

    def test_with_readonly_tokens(self, _mock_llm, gmail_config_json):
        store = TokenStore(gmail_config_json.parent / "tokens.json")
        store.save(
            StoredToken(
                access_token="a",
                refresh_token="r",
                token_type="Bearer",
                scopes=[READONLY_SCOPE],
            )
        )
        config = load_config(gmail_config_json)
        status = report_status(store, config)
        assert status.tokens_present is True
        assert status.readonly is True

    def test_with_non_readonly_tokens(self, _mock_llm, gmail_config_json):
        store = TokenStore(gmail_config_json.parent / "tokens.json")
        store.save(
            StoredToken(
                access_token="a",
                refresh_token="r",
                token_type="Bearer",
                scopes=["https://www.googleapis.com/auth/gmail.modify"],
            )
        )
        config = load_config(gmail_config_json)
        status = report_status(store, config)
        assert status.tokens_present is True
        assert status.readonly is False


class TestCheckLLMEndpoint:
    @patch("urllib.request.urlopen")
    def test_unreachable_endpoint(self, mock_urlopen):
        from urllib.error import URLError

        mock_urlopen.side_effect = URLError("connection refused")
        assert check_llm_endpoint("http://localhost:11434/v1") is False

    @patch("urllib.request.urlopen")
    def test_auth_required_counts_as_reachable(self, mock_urlopen):
        from urllib.error import HTTPError

        mock_urlopen.side_effect = HTTPError(
            "https://api.openai.com/v1/models", 401, "Unauthorized", {}, None
        )
        assert check_llm_endpoint("https://api.openai.com/v1") is True
