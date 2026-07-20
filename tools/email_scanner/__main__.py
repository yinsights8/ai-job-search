"""CLI entry point: `python -m tools.email_scanner <subcommand>`.

Subcommands:
- auth-login   — one-time OAuth consent flow
- status       — print token state, scopes, Ollama availability
- revoke       — revoke token at Google, delete local token file
- plan         — search + match + classify, write JSON plan to stdout
- apply        — read JSON plan from stdin, write archive to disk
- stats        — report total archive size per application
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Optional, Sequence

from . import __version__, paths
from .archive import apply_plan
from .auth import (
    AuthError,
    GmailConfig,
    ScopeError,
    TokenStore,
    credentials_to_stored,
    load_config,
    report_status,
    revoke_token,
    run_consent_flow,
    verify_scopes_via_tokeninfo,
)
from .gmail import GmailClient
from .match import MatcherConfig, match_tracker
from .models import PlanFile
from .redactor import safe_log_message
from .tracker import load_tracker


# ---------- Logging setup ---------------------------------------------------


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


# ---------- Subcommand handlers --------------------------------------------


def cmd_auth_login(args: argparse.Namespace) -> int:
    config = load_config()
    store = TokenStore()
    if not paths.OAUTH_CLIENT_FILE().exists():
        print(
            f"error: OAuth client file not found: {paths.OAUTH_CLIENT_FILE()}\n"
            f"See plan/01-auth.md for the one-time setup.",
            file=sys.stderr,
        )
        return 2
    print(
        "Starting OAuth consent flow. Your browser will open. "
        "Grant ONLY the read-only Gmail scope. If the consent screen "
        "asks for more, deny and re-check auth/gmail-config.json.",
        file=sys.stderr,
    )
    try:
        creds = run_consent_flow(
            config, paths.OAUTH_CLIENT_FILE(), open_browser=not args.no_browser
        )
    except (AuthError, ScopeError) as e:
        print(f"error: {safe_log_message(e)}", file=sys.stderr)
        return 1
    store.save(credentials_to_stored(creds))
    print(f"Token saved: {store.path}", file=sys.stderr)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    config = load_config()
    store = TokenStore()
    status = report_status(store, config)
    print(status.render())
    if not status.readonly and status.tokens_present:
        print(
            "\nWARNING: token scopes are not read-only. "
            "Run `python -m tools.email_scanner revoke` and re-run auth-login.",
            file=sys.stderr,
        )
        return 1
    if not status.llm_reachable:
        print(
            f"\nNote: no LLM endpoint reachable at {status.llm_base_url}. "
            "Start Ollama (or point --llm-base-url / EMAIL_SCANNER_LLM_BASE_URL "
            "at any OpenAI-compatible endpoint) to enable LLM classification. "
            "Ambiguous emails will surface as 'needs-review' until then.",
            file=sys.stderr,
        )
    return 0


def cmd_revoke(args: argparse.Namespace) -> int:
    store = TokenStore()
    if not store.exists():
        print("No tokens to revoke.")
        return 0
    try:
        token = store.load()
    except AuthError as e:
        print(f"error: {safe_log_message(e)}", file=sys.stderr)
        return 1
    if token is None:
        print("No tokens to revoke.")
        return 0
    print("Revoking token at Google...", file=sys.stderr)
    ok = revoke_token(token)
    if ok:
        print("Token revoked at Google.")
    else:
        print("Token revocation call failed (already revoked, or network issue). Continuing.")
    store.delete()
    print(f"Deleted: {store.path}")
    print("Belt-and-suspenders: visit https://myaccount.google.com/permissions")
    print("and confirm 'job-search-email-scanner' is no longer listed.")
    return 0


def _build_gmail_client(config: GmailConfig) -> GmailClient:
    """Construct a GmailClient from the stored token. The google-auth
    library handles the refresh-token dance; we just need a
    google.auth.credentials.Credentials instance."""
    from google.oauth2.credentials import Credentials

    store = TokenStore()
    token = store.load()
    if token is None:
        raise AuthError(
            "No tokens. Run `python -m tools.email_scanner auth-login` first."
        )
    if not token.is_readonly:
        raise ScopeError(
            f"Stored token scope is not read-only: {token.scopes}\n"
            f"Run `python -m tools.email_scanner revoke` then auth-login."
        )
    expiry = token.expiry
    creds = Credentials(
        token=token.access_token,
        refresh_token=token.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config.client_id,
        client_secret=config.client_secret,
        scopes=token.scopes or config.scopes,
        expiry=expiry,
    )
    return GmailClient(creds)


def cmd_plan(args: argparse.Namespace) -> int:
    config = load_config()
    rows = load_tracker()
    if args.company:
        from .tracker import find_by_company

        rows = find_by_company(rows, args.company)
        if not rows:
            print(f"No tracker rows match: {args.company}", file=sys.stderr)
            return 1
    if args.since:
        from datetime import datetime
        since = datetime.fromisoformat(args.since)
    else:
        since = None
    from .classify import resolve_llm_api_key, resolve_llm_base_url, resolve_llm_model

    matcher_config = MatcherConfig(
        use_llm=not args.no_llm,
        llm_base_url=resolve_llm_base_url(args.llm_base_url),
        llm_model=resolve_llm_model(args.llm_model),
        llm_api_key=resolve_llm_api_key(args.llm_api_key_env),
        llm_timeout=args.llm_timeout,
        max_results_per_query=args.limit,
        since=since,
    )
    try:
        client = _build_gmail_client(config)
    except (AuthError, ScopeError) as e:
        print(f"error: {safe_log_message(e)}", file=sys.stderr)
        return 1
    result = match_tracker(rows, client, matcher_config)
    plan = PlanFile(
        matches=result.matches,
        unmatched=result.unmatched,
        since=args.since,
    )
    sys.stdout.write(plan.dump_json())
    if result.first_contact_warnings:
        print(
            f"\n--- first-contact warnings ({len(result.first_contact_warnings)}) ---\n"
            + "\n".join(result.first_contact_warnings),
            file=sys.stderr,
        )
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    payload = sys.stdin.read()
    if not payload.strip():
        print("error: empty plan on stdin", file=sys.stderr)
        return 1
    plan = PlanFile.load_json(payload)
    gmail = None
    if not args.no_attachments:
        try:
            config = load_config()
            gmail = _build_gmail_client(config)
        except (AuthError, ScopeError) as e:
            print(
                f"warning: cannot build gmail client for attachments: "
                f"{safe_log_message(e)}",
                file=sys.stderr,
            )
    report = apply_plan(plan, gmail=gmail, download_attachments=not args.no_attachments)
    print(report.render(), file=sys.stderr)
    return 0 if not report.errors else 2


def cmd_stats(args: argparse.Namespace) -> int:
    applications = paths.APPLICATIONS_DIR()
    if not applications.exists():
        print(f"Applications dir not found: {applications}", file=sys.stderr)
        return 1
    total_bytes = 0
    rows = []
    for app in sorted(applications.iterdir()):
        if not app.is_dir():
            continue
        emails = app / "emails"
        if not emails.exists():
            continue
        size = sum(p.stat().st_size for p in emails.rglob("*") if p.is_file())
        total_bytes += size
        rows.append((app.name, size, len(list(emails.glob("*.eml")))))
    if not rows:
        print("No archived emails yet.")
        return 0
    print("Application archive stats:")
    for name, size, count in rows:
        print(f"  {name}: {count} emails, {_human_bytes(size)}")
    print(f"  TOTAL: {_human_bytes(total_bytes)}")
    return 0


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# ---------- Argument parser -------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="email_scanner",
        description="Read-only Gmail ingestion for the job-search workflow.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("-v", "--verbose", action="store_true", help="verbose logging")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p = sub.add_parser("auth-login", help="run the OAuth consent flow")
    p.add_argument("--no-browser", action="store_true", help="don't auto-open the browser")
    p.set_defaults(func=cmd_auth_login)

    p = sub.add_parser("status", help="print auth and Ollama state")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("revoke", help="revoke token and delete local files")
    p.set_defaults(func=cmd_revoke)

    p = sub.add_parser("plan", help="search + match + classify; JSON to stdout")
    p.add_argument("--since", help="ISO date (YYYY-MM-DD); only consider newer")
    p.add_argument("--company", help="restrict to one company (substring match)")
    p.add_argument("--limit", type=int, default=50, help="max results per query (default 50)")
    p.add_argument(
        "--llm-base-url",
        help="OpenAI-compatible API base URL (default: EMAIL_SCANNER_LLM_BASE_URL "
        "or http://localhost:11434/v1 for local Ollama)",
    )
    p.add_argument(
        "--llm-model",
        help="model name (default: EMAIL_SCANNER_LLM_MODEL or llama3.2:3b)",
    )
    p.add_argument(
        "--llm-api-key-env",
        default="OPENAI_API_KEY",
        help="name of the env var holding the API key (default OPENAI_API_KEY; "
        "not needed for local endpoints)",
    )
    p.add_argument(
        "--llm-timeout",
        type=int,
        default=120,
        help="per-call LLM timeout in seconds (default 120)",
    )
    p.add_argument(
        "--no-llm",
        action="store_true",
        help="disable the LLM fallback; ambiguous emails become needs-review",
    )
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("apply", help="read JSON plan from stdin; write archive")
    p.add_argument("--no-attachments", action="store_true", help="skip downloading attachments")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("stats", help="report archive size per application")
    p.set_defaults(func=cmd_stats)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(args.verbose)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"fatal: {safe_log_message(e)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
