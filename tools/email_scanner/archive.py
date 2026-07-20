"""Archive writer: persist a PlanFile to disk.

Writes per email:
- `<stem>.eml` (raw RFC-822 bytes)
- `<stem>.md` (full-fidelity human-readable mirror)
- `<stem>.md` references attachments under `_attachments/<stem>/`

Regenerates `_index.md` from the file list on every call.

All writes are idempotent (SHA-256 of the source bytes is checked
before writing). Re-running with the same plan produces identical
files.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import paths
from .gmail import GmailClient
from .models import AttachmentRef, EmailMessage, Match, PlanFile
from .redactor import safe_log_message

log = logging.getLogger("email_scanner.archive")


ATTACHMENT_SIZE_CAP_BYTES = 25 * 1024 * 1024  # 25 MB
WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


@dataclass
class WriteReport:
    """Per-run summary of what was written or skipped."""
    written: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            f"written: {len(self.written)}",
            f"skipped: {len(self.skipped)}",
            f"errors: {len(self.errors)}",
        ]
        if self.errors:
            lines.append("--- errors ---")
            lines.extend(self.errors)
        return "\n".join(lines)


# ---------- Public entry point ---------------------------------------------


def apply_plan(
    plan: PlanFile,
    gmail: Optional[GmailClient] = None,
    download_attachments: bool = True,
) -> WriteReport:
    """Write everything in the plan to disk. Idempotent.

    `gmail` is required when `download_attachments` is True and the
    plan contains messages with attachments. It's optional otherwise."""
    report = WriteReport()
    attachment_index: dict[str, str] = {}  # sha256 -> relative path

    # Group matches by application folder
    by_app: dict[str, list[Match]] = {}
    for m in plan.matches:
        if not m.matched_application:
            continue
        by_app.setdefault(m.matched_application, []).append(m)

    for folder_key, matches in by_app.items():
        emails_dir = paths.resolve_emails_folder(folder_key)
        try:
            emails_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            report.errors.append(f"mkdir {emails_dir}: {safe_log_message(e)}")
            continue

        for match in matches:
            try:
                _write_one(match, gmail, emails_dir, attachment_index, report, download_attachments)
            except Exception as e:
                report.errors.append(
                    f"{folder_key}/{match.file_stem}: {safe_log_message(e)}"
                )

        # Regenerate _index.md from disk (idempotent and convergent)
        try:
            _regenerate_index(emails_dir)
            report.written.append(f"{folder_key}/_index.md")
        except Exception as e:
            report.errors.append(f"{folder_key}/_index.md: {safe_log_message(e)}")

    return report


# ---------- Per-message write ----------------------------------------------


def _write_one(
    match: Match,
    gmail: Optional[GmailClient],
    emails_dir: Path,
    attachment_index: dict[str, str],
    report: WriteReport,
    download_attachments: bool,
) -> None:
    msg = match.message
    stem = match.file_stem
    eml_file = emails_dir / f"{stem}.eml"
    md_file = emails_dir / f"{stem}.md"

    # ---- .eml -------------------------------------------------------------
    eml_bytes = msg.raw_bytes
    if eml_bytes is None and gmail is not None:
        try:
            eml_bytes = gmail.get_message_raw_bytes(msg.gmail_id or msg.message_id)
        except Exception as e:
            report.errors.append(f"raw fetch {stem}: {safe_log_message(e)}")
            return
    if eml_bytes is None:
        report.errors.append(f"{stem}: no raw bytes and no gmail client")
        return

    eml_hash = hashlib.sha256(eml_bytes).hexdigest()
    if not _should_write(eml_file, eml_hash):
        report.skipped.append(f"{eml_file.name} (unchanged)")
    else:
        try:
            eml_file.write_bytes(eml_bytes)
            report.written.append(str(eml_file.relative_to(paths.APPLICATIONS_DIR().parent)))
        except Exception as e:
            report.errors.append(f"write {eml_file}: {safe_log_message(e)}")
            return

    # ---- .md --------------------------------------------------------------
    md_bytes = _render_markdown(match).encode("utf-8")
    md_hash = hashlib.sha256(md_bytes).hexdigest()
    if not _should_write(md_file, md_hash):
        report.skipped.append(f"{md_file.name} (unchanged)")
    else:
        try:
            md_file.write_bytes(md_bytes)
            report.written.append(str(md_file.relative_to(paths.APPLICATIONS_DIR().parent)))
        except Exception as e:
            report.errors.append(f"write {md_file}: {safe_log_message(e)}")

    # ---- attachments ------------------------------------------------------
    if download_attachments and msg.attachments and gmail is not None:
        for att in msg.attachments:
            try:
                _write_attachment(att, stem, emails_dir, gmail, attachment_index, report, msg.gmail_id or msg.message_id)
            except Exception as e:
                report.errors.append(f"attachment {att.get('filename', '?')}: {safe_log_message(e)}")


def _should_write(path: Path, new_hash: str) -> bool:
    """Skip write if file exists and matches the new content hash."""
    if not path.exists():
        return True
    try:
        existing = hashlib.sha256(path.read_bytes()).hexdigest()
        return existing != new_hash
    except OSError:
        return True


# ---------- Attachments -----------------------------------------------------


def _write_attachment(
    att: dict,
    stem: str,
    emails_dir: Path,
    gmail: GmailClient,
    attachment_index: dict[str, str],
    report: WriteReport,
    message_id: str,
) -> None:
    filename = att.get("filename", "attachment")
    mime_type = att.get("mimeType", "application/octet-stream")
    size = int(att.get("size", 0))
    att_id = att.get("attachmentId")

    if size > ATTACHMENT_SIZE_CAP_BYTES:
        log.info("skipping oversized attachment: %s (%d bytes)", filename, size)
        return

    safe_name = sanitise_filename(filename)
    target_dir = emails_dir / paths.ATTACHMENTS_SUBDIR / stem
    target_path = target_dir / safe_name

    # Check dedup by content hash (we need to download first to hash)
    try:
        data = gmail.get_attachment_bytes(message_id, att_id)
    except Exception as e:
        log.warning("attachment download failed: %s", safe_log_message(e))
        return

    data_hash = hashlib.sha256(data).hexdigest()
    if data_hash in attachment_index:
        # Already saved under a different stem — dedup
        return

    target_dir.mkdir(parents=True, exist_ok=True)
    if not _should_write(target_path, data_hash):
        return
    try:
        target_path.write_bytes(data)
        attachment_index[data_hash] = str(
            target_path.relative_to(emails_dir)
        )
        report.written.append(
            str(target_path.relative_to(paths.APPLICATIONS_DIR().parent))
        )
    except OSError as e:
        report.errors.append(f"write attachment {target_path}: {safe_log_message(e)}")


def sanitise_filename(name: str) -> str:
    """Strip path separators, control characters, and Windows reserved
    names. Returns a fallback hash-based name if the result is empty."""
    if not name:
        return "attachment"
    # Strip path separators and control characters
    cleaned = re.sub(r"[\\/\x00-\x1f]", "_", name)
    # Trim trailing dots and spaces (Windows quirk)
    cleaned = cleaned.rstrip(" .")
    # If the sanitisation left us with only underscores/digits, fall back
    if not cleaned.strip("_."):
        import hashlib

        return f"attachment_{hashlib.sha256(name.encode()).hexdigest()[:8]}"
    # Replace reserved names
    base = cleaned.split(".")[0].upper()
    if base in WINDOWS_RESERVED:
        cleaned = f"_{cleaned}"
    # Length cap
    if len(cleaned) > 200:
        # Keep extension if any
        if "." in cleaned:
            stem, ext = cleaned.rsplit(".", 1)
            ext = "." + ext
        else:
            stem, ext = cleaned, ""
        stem = stem[: 200 - len(ext)]
        cleaned = stem + ext
    return cleaned


# ---------- .md rendering ---------------------------------------------------


def _render_markdown(match: Match) -> str:
    """Render a Match as a full-fidelity .md file."""
    msg = match.message
    parts: list[str] = []

    # Frontmatter
    parts.append("---")
    parts.append(f"date_received: {msg.date_received.isoformat()}")
    parts.append(f"direction: {msg.direction.value}")
    parts.append(f"matched_application: {match.matched_application or ''}")
    parts.append(f"match_method: {match.match_method.value}")
    parts.append(f"classification: {match.classification.value}")
    parts.append(f"stage_link: {_stage_link_for(match.classification)}")
    if match.domain_mismatch:
        parts.append("domain_mismatch: true")
    if match.first_contact_from_domain:
        parts.append("first_contact_from_domain: true")
    parts.append(f"raw_file: {match.file_stem}.eml")
    parts.append(f"message_id: {msg.message_id}")
    parts.append(f"thread_id: {msg.thread_id}")
    if msg.headers.get("In-Reply-To"):
        parts.append(f"in_reply_to: {msg.headers['In-Reply-To']}")
    if msg.attachments:
        parts.append("attachments:")
        for att in msg.attachments:
            parts.append(f"  - filename: \"{_yaml_escape(att.get('filename', ''))}\"")
            parts.append(f"    mime_type: \"{_yaml_escape(att.get('mimeType', ''))}\"")
            parts.append(f"    size_bytes: {int(att.get('size', 0))}")
    parts.append("---")
    parts.append("")

    # Title
    parts.append(f"# {msg.subject or '(no subject)'}")
    parts.append("")

    # Headers (full, verbatim, in original order)
    parts.append("## Headers (full, verbatim)")
    parts.append("")
    for k, v in msg.headers.items():
        parts.append(f"- {k}: {v}")
    parts.append("")

    # Body
    parts.append("## Body (verbatim, original quoting preserved)")
    parts.append("")
    parts.append(msg.body_text or "*(no body)*")
    parts.append("")

    # Attachments
    if msg.attachments:
        parts.append("## Attachments")
        parts.append("")
        for att in msg.attachments:
            fname = sanitise_filename(att.get("filename", "attachment"))
            link = f"./_attachments/{match.file_stem}/{fname}"
            parts.append(f"- [{fname}]({link}) ({att.get('mimeType', '?')}, {int(att.get('size', 0))} bytes)")
        parts.append("")

    # Key signals (user-editable)
    parts.append("## Key signals (agent proposes, user accepts/edits)")
    parts.append("")
    if match.classification_signals:
        for sig in match.classification_signals:
            parts.append(f"- {sig}")
    else:
        parts.append("- (no signals yet — review and add)")
    parts.append("")

    return "\n".join(parts)


def _stage_link_for(cls) -> str:
    """Map a classification to a string that hints at the outcome.md
    stage it corresponds to. Loose mapping — the user reconciles."""
    from .models import Classification

    mapping = {
        Classification.OFFER: "offer-received",
        Classification.INTERVIEW_INVITE: "interview",
        Classification.INTERVIEW_RESCHEDULE: "interview",
        Classification.TASK_ASSIGNMENT: "interview",
        Classification.REJECTION: "rejected",
        Classification.WITHDRAWN_BY_THEM: "withdrawn",
        Classification.ACKNOWLEDGEMENT: "in_progress",
        Classification.INFO_REQUEST: "in_progress",
        Classification.PORTAL_ACK: "in_progress",
    }
    return mapping.get(cls, "in_progress")


def _yaml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


# ---------- _index.md regeneration -----------------------------------------


def _regenerate_index(emails_dir: Path) -> None:
    """Rebuild `_index.md` from the on-disk file list. Idempotent."""
    rows: list[dict] = []
    attachments_section: list[str] = []

    for eml in sorted(emails_dir.glob("*.eml")):
        stem = eml.stem
        md = emails_dir / f"{stem}.md"
        if not md.exists():
            continue
        # Quick parse: read the frontmatter and a few first lines
        meta = _parse_md_frontmatter(md.read_text(encoding="utf-8", errors="replace"))
        rows.append(
            {
                "stem": stem,
                "date": meta.get("date_received", ""),
                "dir": meta.get("direction", ""),
                "from": meta.get("from_name", "") or _first_header_value(md, "From"),
                "classification": meta.get("classification", ""),
                "subject": _first_header_value(md, "Subject"),
                "first_contact": "first_contact_from_domain: true" in md.read_text(encoding="utf-8", errors="replace"),
            }
        )

        # Attachments
        att_dir = emails_dir / paths.ATTACHMENTS_SUBDIR / stem
        if att_dir.exists():
            att_files = sorted(att_dir.iterdir())
            if att_files:
                links = ", ".join(
                    f"[{p.name}](./_attachments/{stem}/{p.name})" for p in att_files
                )
                attachments_section.append(f"- {stem}: {links}")

    # Title: derive from the parent directory's parent name
    app_folder = emails_dir.parent.name
    pretty = app_folder.replace("_", " ").title()

    out: list[str] = []
    out.append(f"# Email index — {pretty}")
    out.append("")
    if rows:
        out.append("| Date | Dir | From | Classification | Subject | File |")
        out.append("|------|-----|------|----------------|---------|------|")
        for r in rows:
            first = " ⚠" if r["first_contact"] else ""
            out.append(
                f"| {r['date'].replace('T', ' ')[:16]} | {r['dir'][0] if r['dir'] else '?'} | "
                f"{r['from']}{first} | {r['classification']} | {r['subject']} | "
                f"[{_slug_label(r['stem'])}](./{r['stem']}.md) |"
            )
    else:
        out.append("*(no emails archived yet)*")
    out.append("")
    if attachments_section:
        out.append("## Attachments")
        out.append("")
        out.extend(attachments_section)
    out.append("")

    (emails_dir / paths.INDEX_FILE_NAME).write_text(
        "\n".join(out), encoding="utf-8"
    )


def _slug_label(stem: str) -> str:
    """`<stem>` is `YYYY-MM-DDTHHmm_<direction>_<slug>`. Return the
    `<slug>` part as a friendly label for the table."""
    parts = stem.split("_", 2)
    if len(parts) >= 3:
        return parts[2].replace("-", " ")
    return stem


def _parse_md_frontmatter(text: str) -> dict[str, str]:
    """Naive YAML frontmatter parser — handles the simple key: value
    and key: value list shape we produce. Sufficient for _index.md."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    block = text[3:end].strip()
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _first_header_value(md_path: Path, header_name: str) -> str:
    """Read the first `- Header: value` line from a .md file."""
    try:
        text = md_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for line in text.splitlines():
        if line.startswith(f"- {header_name}:"):
            return line[len(f"- {header_name}:") :].strip()
    return ""
