"""OAuth flow, token storage, and status reporting for read-only Gmail.

The CLI exposes three auth-related subcommands:

- `auth-login`  — one-time consent flow. Writes `auth/tokens.json`.
- `status`      — print token state, scopes, Ollama availability, etc.
- `revoke`      — revoke the token at Google, delete `auth/tokens.json`.

All three are testable in isolation by passing a `TokenStore` and
`GmailAuthenticator` explicitly; the production wiring reads from
`auth/gmail-config.json` and `auth/oauth-client.json`.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import paths
from .redactor import domain_of, safe_log_message

log = logging.getLogger("email_scanner.auth")


READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"


# ---------- Errors ----------------------------------------------------------


class AuthError(Exception):
    """Raised when authentication setup is missing or invalid."""


class ScopeError(AuthError):
    """Raised when the granted scope is not the read-only scope we expect."""


# ---------- Config + token storage ------------------------------------------


@dataclass
class GmailConfig:
    client_id: str
    client_secret: str
    redirect_uris: list[str]
    scopes: list[str]
    project_id: Optional[str] = None

    @property
    def redirect_uri(self) -> str:
        if not self.redirect_uris:
            raise AuthError("No redirect_uri in gmail-config.json")
        return self.redirect_uris[0]

    @property
    def readonly_scope(self) -> bool:
        return READONLY_SCOPE in self.scopes and all(
            s == READONLY_SCOPE for s in self.scopes
        )


def load_config(path: Path | None = None) -> GmailConfig:
    """Load `auth/gmail-config.json`. Raises AuthError if missing or invalid."""
    p = path or paths.GMAIL_CONFIG_FILE()
    if not p.exists():
        raise AuthError(
            f"Config not found: {p}\n"
            f"See plan/01-auth.md for the one-time setup."
        )
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise AuthError(f"Invalid JSON in {p}: {e}") from e

    try:
        return GmailConfig(
            client_id=data["client_id"],
            client_secret=data["client_secret"],
            redirect_uris=data.get("redirect_uris") or [],
            scopes=data.get("scopes") or [],
            project_id=data.get("project_id"),
        )
    except KeyError as e:
        raise AuthError(f"Missing required field in {p}: {e}") from e


@dataclass
class StoredToken:
    """A token record as stored in `auth/tokens.json`."""

    access_token: str
    refresh_token: Optional[str]
    token_type: str
    expiry: Optional[datetime] = None
    scopes: list[str] = field(default_factory=list)

    @property
    def is_expired(self) -> bool:
        if self.expiry is None:
            return False
        # Subtract 60s safety margin
        return datetime.now(timezone.utc) >= self.expiry.replace(tzinfo=timezone.utc) - __import__("datetime").timedelta(seconds=60)

    @property
    def is_readonly(self) -> bool:
        return READONLY_SCOPE in self.scopes

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": self.token_type,
            "expiry": self.expiry.isoformat() if self.expiry else None,
            "scopes": self.scopes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StoredToken":
        expiry = None
        if data.get("expiry"):
            try:
                expiry = datetime.fromisoformat(data["expiry"])
            except (ValueError, TypeError):
                expiry = None
        scopes = data.get("scopes") or []
        if isinstance(scopes, str):
            scopes = scopes.split()
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            token_type=data.get("token_type", "Bearer"),
            expiry=expiry,
            scopes=list(scopes),
        )


class TokenStore:
    """Read/write `auth/tokens.json`. Pure filesystem — no network."""

    def __init__(self, path: Path | None = None):
        self.path = path or paths.TOKENS_FILE()

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> Optional[StoredToken]:
        if not self.path.exists():
            return None
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return StoredToken.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            raise AuthError(f"Invalid token file {self.path}: {e}") from e

    def save(self, token: StoredToken) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(token.to_dict(), f, indent=2)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            # Windows doesn't fully support chmod, that's fine
            pass

    def delete(self) -> bool:
        if self.path.exists():
            self.path.unlink()
            return True
        return False


# ---------- Token verification (online) -------------------------------------


def _decode_jwt_unverified(token: str) -> dict[str, Any]:
    """Decode the payload of a JWT without verifying the signature.
    Used only to read the `scope` claim. NOT for security decisions
    beyond the user's own local UX — the actual scope is enforced by
    Google's API server."""
    import base64

    parts = token.split(".")
    if len(parts) != 3:
        return {}
    payload = parts[1]
    # Add padding
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload + padding)
        return json.loads(decoded)
    except (ValueError, json.JSONDecodeError):
        return {}


def verify_scopes_via_tokeninfo(token: StoredToken) -> list[str]:
    """Call Google's tokeninfo endpoint to confirm the actual scopes
    the token was issued with. Belt-and-suspenders against silent
    scope expansion."""
    if not token.access_token:
        return token.scopes
    try:
        url = f"{GOOGLE_TOKENINFO_URL}?access_token={urllib.parse.quote(token.access_token)}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        scope_str = data.get("scope", "")
        if scope_str:
            return scope_str.split()
    except Exception as e:
        log.warning("tokeninfo lookup failed: %s", safe_log_message(e))
    return token.scopes


# ---------- OAuth flow ------------------------------------------------------


@dataclass
class AuthenticatedCredentials:
    """Lightweight result type returned by the auth flow, compatible
    with `google.oauth2.credentials.Credentials` for the gmail wrapper."""

    access_token: str
    refresh_token: Optional[str]
    token_uri: str
    client_id: str
    client_secret: str
    scopes: list[str]
    expiry: Optional[datetime] = None


def run_consent_flow(
    config: GmailConfig,
    client_secrets_path: Path,
    open_browser: bool = True,
) -> AuthenticatedCredentials:
    """Run the one-time OAuth consent flow. Uses `google-auth-oauthlib`
    for the heavy lifting — `InstalledAppFlow` starts a local HTTP
    server on the configured redirect URI and captures the code.

    The `client_secrets_path` is the file Google Cloud Console
    downloads. The `config` is the read-only config. The two should
    agree on the OAuth client."""
    if not config.readonly_scope:
        raise ScopeError(
            f"Config scope is not read-only. Found: {config.scopes}\n"
            f"Required: ['{READONLY_SCOPE}']\n"
            f"Edit auth/gmail-config.json and re-run."
        )

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as e:
        raise AuthError(
            "google-auth-oauthlib is not installed. Run: "
            "pip install google-auth-oauthlib"
        ) from e

    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_secrets_path),
        scopes=config.scopes,
    )
    flow.redirect_uri = config.redirect_uri

    try:
        creds = flow.run_local_server(
            host="localhost",
            port=_port_from_uri(config.redirect_uri),
            open_browser=open_browser,
            authorization_prompt_message=(
                "Opening browser for Google consent. "
                "Grant only the read-only Gmail scope. "
                "If the consent screen asks for more, deny and re-check "
                "auth/gmail-config.json scopes."
            ),
        )
    except Exception as e:
        raise AuthError(f"OAuth flow failed: {safe_log_message(e)}") from e

    return AuthenticatedCredentials(
        access_token=creds.token,
        refresh_token=creds.refresh_token,
        token_uri=creds.token_uri,
        client_id=creds.client_id,
        client_secret=creds.client_secret,
        scopes=list(creds.scopes) if creds.scopes else list(config.scopes),
        expiry=creds.expiry,
    )


def _port_from_uri(uri: str) -> int:
    """Extract the port from a redirect URI. Defaults to 3000."""
    from urllib.parse import urlparse

    parsed = urlparse(uri)
    if parsed.port:
        return parsed.port
    return 3000


def credentials_to_stored(creds: AuthenticatedCredentials) -> StoredToken:
    return StoredToken(
        access_token=creds.access_token,
        refresh_token=creds.refresh_token,
        token_type="Bearer",
        expiry=creds.expiry,
        scopes=creds.scopes,
    )


# ---------- Revoke ----------------------------------------------------------


def revoke_token(token: StoredToken) -> bool:
    """Call Google's revocation endpoint. Returns True on success.
    Idempotent: a 400 (invalid token) is treated as already-revoked."""
    if not token.access_token:
        return False
    data = urllib.parse.urlencode({"token": token.access_token}).encode("ascii")
    req = urllib.request.Request(GOOGLE_REVOKE_URL, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as e:
        if e.code == 400:
            # Token already invalid/revoked
            return True
        raise
    except Exception as e:
        log.warning("revoke call failed: %s", safe_log_message(e))
        return False


# ---------- Status ----------------------------------------------------------


@dataclass
class Status:
    tokens_file: str
    tokens_present: bool
    token_expiry: Optional[str]
    scopes: list[str]
    readonly: bool
    llm_base_url: str
    llm_model: str
    llm_reachable: bool

    def render(self) -> str:
        lines = [
            f"tokens_file: {self.tokens_file}",
            f"tokens_present: {'yes' if self.tokens_present else 'no'}",
            f"token_expiry: {self.token_expiry or 'n/a'}",
            f"scopes: {' '.join(self.scopes) if self.scopes else 'n/a'}",
            f"readonly: {'yes' if self.readonly else 'NO — STOP'}",
            f"llm_base_url: {self.llm_base_url}",
            f"llm_model: {self.llm_model}",
            f"llm_reachable: {'yes' if self.llm_reachable else 'no'}",
        ]
        return "\n".join(lines)


def check_llm_endpoint(base_url: str, timeout: int = 3) -> bool:
    """Ping the OpenAI-compatible endpoint's /models route."""
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/models",
            headers={"User-Agent": "email-scanner/1.0"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except urllib.error.HTTPError as e:
        # 401/403 means the endpoint is up but wants an API key — reachable.
        return e.code in (401, 403)
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def report_status(store: TokenStore, config: GmailConfig) -> Status:
    from .classify import resolve_llm_base_url, resolve_llm_model

    token = store.load() if store.exists() else None
    base_url = resolve_llm_base_url()
    return Status(
        tokens_file=str(store.path),
        tokens_present=token is not None,
        token_expiry=token.expiry.isoformat() if token and token.expiry else None,
        scopes=token.scopes if token else [],
        readonly=bool(token and token.is_readonly),
        llm_base_url=base_url,
        llm_model=resolve_llm_model(),
        llm_reachable=check_llm_endpoint(base_url),
    )
