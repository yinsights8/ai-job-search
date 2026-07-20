"""Thin read-only wrapper over `google-api-python-client`.

The CLI only uses four operations:

- `search(query)` — run a Gmail search query
- `get_message(message_id, format='raw')` — fetch the full RFC-822 bytes
- `get_message(message_id, format='full')` — fetch the parsed Gmail Message
- `get_thread(thread_id)` — fetch the entire thread (for the Sent-thread pass)
- `get_attachment(message_id, attachment_id)` — download an attachment

Nothing else is exposed. The class is constructed with a `Credentials`
object (from `google-auth-oauthlib`/`google-auth`); the wrapper handles
token refresh transparently.
"""

from __future__ import annotations

import base64
import email
import email.utils
import logging
from datetime import datetime
from email.message import Message as EmailMessageObj
from pathlib import Path
from typing import Any, Optional

from .models import Direction, EmailAddress, EmailMessage
from .redactor import safe_log_message

log = logging.getLogger("email_scanner.gmail")


class GmailError(Exception):
    """Raised when a Gmail API call fails."""


class GmailClient:
    """Read-only Gmail API client. Construct with already-authenticated
    `google.auth.credentials.Credentials` (or our `AuthenticatedCredentials`
    shim, which exposes the same fields)."""

    USER_ID = "me"

    def __init__(self, credentials: Any):
        self._credentials = credentials
        self._service: Any = None

    @property
    def service(self) -> Any:
        if self._service is None:
            try:
                from googleapiclient.discovery import build
            except ImportError as e:
                raise GmailError(
                    "google-api-python-client is not installed. "
                    "Run: pip install google-api-python-client"
                ) from e
            self._service = build("gmail", "v1", credentials=self._credentials)
        return self._service

    # ---------- Search -----------------------------------------------------

    def search(self, query: str, max_results: int = 100) -> list[str]:
        """Run a Gmail search and return a list of message IDs (deduped,
        in chronological order). Empty list if no results."""
        if not query:
            return []
        ids: list[str] = []
        page_token: Optional[str] = None
        try:
            while True:
                kwargs: dict[str, Any] = {
                    "userId": self.USER_ID,
                    "q": query,
                    "maxResults": min(max_results - len(ids), 500),
                }
                if page_token:
                    kwargs["pageToken"] = page_token
                resp = self.service.users().messages().list(**kwargs).execute()
                batch = [m["id"] for m in resp.get("messages", []) or []]
                for mid in batch:
                    if mid not in ids:
                        ids.append(mid)
                if len(ids) >= max_results:
                    break
                page_token = resp.get("nextPageToken")
                if not page_token:
                    break
        except Exception as e:
            raise GmailError(f"Gmail search failed: {safe_log_message(e)}") from e
        return ids[:max_results]

    # ---------- Message fetch ---------------------------------------------

    def get_message(self, message_id: str, fmt: str = "full") -> EmailMessage:
        """Fetch a single message. `fmt` is 'full' (parsed) or 'raw'
        (RFC-822 bytes). We always parse headers and body ourselves
        so the result is the same shape regardless of `fmt`."""
        if fmt not in ("full", "raw", "metadata"):
            raise ValueError(f"Invalid format: {fmt}")
        try:
            resp = (
                self.service.users()
                .messages()
                .get(userId=self.USER_ID, id=message_id, format=fmt)
                .execute()
            )
        except Exception as e:
            raise GmailError(
                f"Failed to fetch message {message_id[:16]}: {safe_log_message(e)}"
            ) from e
        return self._parse_message(resp, message_id)

    def get_message_raw_bytes(self, message_id: str) -> bytes:
        """Fetch the raw RFC-822 bytes for a message. Used for the .eml file."""
        try:
            resp = (
                self.service.users()
                .messages()
                .get(userId=self.USER_ID, id=message_id, format="raw")
                .execute()
            )
        except Exception as e:
            raise GmailError(
                f"Failed to fetch raw {message_id[:16]}: {safe_log_message(e)}"
            ) from e
        return base64.urlsafe_b64decode(resp["raw"])

    def get_thread(self, thread_id: str) -> list[EmailMessage]:
        """Fetch every message in a thread, in chronological order."""
        try:
            resp = (
                self.service.users()
                .threads()
                .get(userId=self.USER_ID, id=thread_id, format="full")
                .execute()
            )
        except Exception as e:
            raise GmailError(
                f"Failed to fetch thread {thread_id[:16]}: {safe_log_message(e)}"
            ) from e
        out: list[EmailMessage] = []
        for m in resp.get("messages", []) or []:
            out.append(self._parse_message(m, m.get("id", "")))
        out.sort(key=lambda x: x.date_received)
        return out

    # ---------- Attachments -----------------------------------------------

    def get_attachment_bytes(
        self, message_id: str, attachment_id: str
    ) -> bytes:
        """Download an attachment's bytes."""
        try:
            resp = (
                self.service.users()
                .messages()
                .attachments()
                .get(userId=self.USER_ID, messageId=message_id, id=attachment_id)
                .execute()
            )
        except Exception as e:
            raise GmailError(
                f"Failed to fetch attachment {attachment_id[:16]}: {safe_log_message(e)}"
            ) from e
        return base64.urlsafe_b64decode(resp["data"])

    # ---------- Parsing helpers -------------------------------------------

    def _parse_message(self, raw: dict[str, Any], message_id: str) -> EmailMessage:
        """Convert a Gmail `messages.get` response into our EmailMessage
        shape. Handles both 'full' format (with `payload`) and 'raw'
        format (with `raw` base64)."""
        thread_id = raw.get("threadId", "")
        label_ids = raw.get("labelIds", []) or []
        direction = (
            Direction.INBOUND
            if "SENT" not in label_ids
            else Direction.OUTBOUND
        )

        if "raw" in raw:
            # Raw format: decode the RFC-822 bytes and parse with stdlib
            raw_bytes = base64.urlsafe_b64decode(raw["raw"])
            msg = email.message_from_bytes(raw_bytes)
            headers = {k: msg.get(k, "") for k in msg.keys()}
            body_text = _extract_text(msg)
            from_ = _parseaddr(msg.get("From", ""))
            to_addrs = _parseaddr_list(msg.get_all("To", []) or [])
            cc_addrs = _parseaddr_list(msg.get_all("Cc", []) or [])
            attachments = []
        else:
            raw_bytes = None
            payload = raw.get("payload", {}) or {}
            headers = {h["name"]: h["value"] for h in payload.get("headers", []) or []}
            body_text = _extract_text_from_gmail_payload(payload)
            from_ = _parseaddr(headers.get("From", ""))
            to_addrs = _parseaddr_list(_split_addresses(headers.get("To", "")))
            cc_addrs = _parseaddr_list(_split_addresses(headers.get("Cc", "")))
            attachments = _attachments_from_gmail_payload(payload)

        # Date parsing
        date_str = headers.get("Date", "") or ""
        try:
            date_received = email.utils.parsedate_to_datetime(date_str)
        except (TypeError, ValueError):
            internal_ms = raw.get("internalDate")
            if internal_ms:
                date_received = datetime.fromtimestamp(int(internal_ms) / 1000.0)
            else:
                date_received = datetime.now()

        # Sniff the actual message-id from headers (more reliable than the API id)
        msg_id_header = headers.get("Message-ID", "").strip() or raw.get("id", message_id)

        return EmailMessage(
            message_id=msg_id_header,
            gmail_id=raw.get("id", message_id),
            thread_id=thread_id,
            direction=direction,
            date_received=date_received,
            **{"from": from_},
            to=to_addrs,
            cc=cc_addrs,
            subject=headers.get("Subject", "") or "",
            body_text=body_text,
            headers=headers,
            attachments=attachments,
            raw_bytes=raw_bytes,
        )


# ---------- MIME helpers ----------------------------------------------------


def _extract_text(msg: EmailMessageObj) -> str:
    """Extract the best plaintext representation from a parsed email
    message. Prefers text/plain parts; falls back to a stripped
    text/html if no plain part exists."""
    parts: list[str] = []
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype == "text/plain" and not part.is_multipart():
            payload = part.get_payload(decode=True) or b""
            try:
                text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            except (LookupError, AttributeError):
                text = payload.decode("utf-8", errors="replace")
            parts.append(text)
    if parts:
        return "\n\n".join(parts).strip()
    # Fallback: text/html
    for part in msg.walk():
        if part.get_content_type() == "text/html" and not part.is_multipart():
            payload = part.get_payload(decode=True) or b""
            try:
                html = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            except (LookupError, AttributeError):
                html = payload.decode("utf-8", errors="replace")
            return _strip_html(html)
    return ""


def _strip_html(html: str) -> str:
    """Very conservative HTML -> text for the fallback case. Not pretty,
    but enough to capture the content."""
    import re

    text = re.sub(r"<\s*br\s*/?\s*>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</\s*p\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_text_from_gmail_payload(payload: dict[str, Any]) -> str:
    """Recursively walk a Gmail message payload and extract text parts."""
    mime = payload.get("mimeType", "")
    body = payload.get("body", {}) or {}
    data = body.get("data")

    if mime == "text/plain" and data:
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    if mime == "text/html" and data:
        html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        return _strip_html(html)

    parts = payload.get("parts", []) or []
    texts: list[str] = []
    for p in parts:
        sub = _extract_text_from_gmail_payload(p)
        if sub:
            texts.append(sub)
    return "\n\n".join(texts).strip()


def _attachments_from_gmail_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Recursively walk the payload and return a flat list of attachments."""
    out: list[dict[str, Any]] = []
    body = payload.get("body", {}) or {}
    if body.get("attachmentId"):
        out.append(
            {
                "filename": payload.get("filename", "attachment"),
                "mimeType": payload.get("mimeType", "application/octet-stream"),
                "size": body.get("size", 0),
                "attachmentId": body["attachmentId"],
            }
        )
    for p in payload.get("parts", []) or []:
        out.extend(_attachments_from_gmail_payload(p))
    return out


def _parseaddr(s: str) -> EmailAddress:
    if not s:
        return EmailAddress(name=None, email="")
    name, addr = email.utils.parseaddr(s)
    return EmailAddress(name=name or None, email=(addr or "").lower())


def _parseaddr_list(items: list[str]) -> list[EmailAddress]:
    out: list[EmailAddress] = []
    for s in items:
        for token in (s or "").split(","):
            token = token.strip()
            if token:
                out.append(_parseaddr(token))
    return [a for a in out if a.email]


def _split_addresses(s: str) -> list[str]:
    if not s:
        return []
    return [a.strip() for a in s.split(",") if a.strip()]
