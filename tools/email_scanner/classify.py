"""Email classification.

Two passes:
1. Regex rules on subject + sender + body opening. Covers ~95% of cases.
2. LLM fallback via any OpenAI-compatible /chat/completions endpoint
   (local Ollama/LM Studio or a cloud provider). Sends redacted
   snippets only — never the full body.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

from .models import Classification, EmailMessage, Match
from .redactor import redacted_body_snippet

log = logging.getLogger("email_scanner.classify")


# ---------- Regex rules -----------------------------------------------------


@dataclass(frozen=True)
class Rule:
    pattern: re.Pattern[str]
    classification: Classification
    label: str


def _compile(pat: str, flags: int = re.IGNORECASE) -> re.Pattern[str]:
    return re.compile(pat, flags)


RULES: list[Rule] = [
    # Interview invitations
    Rule(_compile(r"\binterview\b"), Classification.INTERVIEW_INVITE, "interview-keyword"),
    Rule(_compile(r"\bnext steps\b"), Classification.INTERVIEW_INVITE, "next-steps"),
    Rule(_compile(r"\bschedule (a|an) (call|chat|interview)\b"), Classification.INTERVIEW_INVITE, "schedule-call"),
    Rule(_compile(r"\bavailability\b"), Classification.INTERVIEW_INVITE, "availability"),
    # Reschedules
    Rule(_compile(r"\breschedule\b|\bnew time\b|\bdifferent time\b"), Classification.INTERVIEW_RESCHEDULE, "reschedule"),
    # Tasks
    Rule(_compile(r"\btake[-\s]?home\b|\bcoding challenge\b|\bassessment\b|\btask\b"), Classification.TASK_ASSIGNMENT, "task"),
    # Offers
    Rule(_compile(r"\boffer\b|\bpleased to offer\b|\boffer letter\b"), Classification.OFFER, "offer"),
    # Rejections
    Rule(_compile(r"\bunfortunately\b"), Classification.REJECTION, "unfortunately"),
    Rule(_compile(r"\bnot moving forward\b|\bwon'?t be proceeding\b|\bdecided to (move forward with|pursue)\b|\bother candidates\b"),
         Classification.REJECTION, "rejection-language"),
    Rule(_compile(r"\bwe have decided\b"), Classification.REJECTION, "we-have-decided"),
    # Withdrawn
    Rule(_compile(r"\bposition (has been )?filled\b|\brole (has been )?closed\b|\bcancelled\b"),
         Classification.WITHDRAWN_BY_THEM, "position-filled"),
    # Acknowledgement
    Rule(_compile(r"\bthank you for applying\b|\breceived your application\b"),
         Classification.ACKNOWLEDGEMENT, "thanks-applying"),
    # Info requests
    Rule(_compile(r"\breferences?\b|\breference check\b"), Classification.INFO_REQUEST, "references"),
    # Out of office
    Rule(_compile(r"\bout of (the )?office\b|\bOOO\b"), Classification.OUT_OF_OFFICE, "ooo"),
    # Suspicious
    Rule(
        _compile(r"\b(ignore (all )?(previous|prior) instructions|"
                 r"disregard (all )?(previous|prior) instructions|"
                 r"new instructions|system prompt|you are now)\b"),
        Classification.SUSPICIOUS,
        "prompt-injection-pattern",
    ),
]


# ATS sender patterns
ATS_SENDERS: list[tuple[str, Classification]] = [
    ("@greenhouse-mail.io", Classification.PORTAL_ACK),
    ("@lever.co", Classification.PORTAL_ACK),
    ("@workable-mail.com", Classification.PORTAL_ACK),
    ("@ashbyhq.com", Classification.PORTAL_ACK),
    ("@myworkday.com", Classification.PORTAL_ACK),
    ("@bamboohr.com", Classification.PORTAL_ACK),
    ("@icims.com", Classification.PORTAL_ACK),
    ("@smartrecruiters.com", Classification.PORTAL_ACK),
    ("@jobvite.com", Classification.PORTAL_ACK),
    ("@teamtailor-mail.com", Classification.PORTAL_ACK),
]


# ---------- Classifier ------------------------------------------------------


@dataclass
class ClassificationResult:
    classification: Classification
    confidence: float
    source: str  # "regex" | "llm"
    signals: list[str] = field(default_factory=list)
    notes: str = ""


def classify_message(msg: EmailMessage) -> ClassificationResult:
    """Classify using regex first. Returns NEEDS_REVIEW if nothing matches
    and the LLM fallback is unavailable."""
    subject = msg.subject or ""
    body_open = (msg.body_text or "")[:1000]
    sender = msg.from_.email or ""
    sender_lower = sender.lower()
    haystack = f"{subject}\n{body_open}\n{sender_lower}"

    signals: list[str] = []
    matched: list[tuple[Rule, re.Match[str]]] = []

    # ATS sender check first (highest specificity)
    for suffix, cls in ATS_SENDERS:
        if suffix in sender_lower:
            signals.append(f"ats-sender:{suffix}")
            return ClassificationResult(
                classification=cls,
                confidence=0.95,
                source="regex",
                signals=signals,
            )

    # Subject + body regex pass
    for rule in RULES:
        m = rule.pattern.search(haystack)
        if m:
            matched.append((rule, m))
            signals.append(f"{rule.label}:{m.group(0)[:40]}")

    if matched:
        # Use the rule with the highest classification priority order
        # Rejection and offer are high-signal; prefer them
        priority = [
            Classification.OFFER,
            Classification.REJECTION,
            Classification.WITHDRAWN_BY_THEM,
            Classification.INTERVIEW_INVITE,
            Classification.INTERVIEW_RESCHEDULE,
            Classification.TASK_ASSIGNMENT,
            Classification.INFO_REQUEST,
            Classification.ACKNOWLEDGEMENT,
            Classification.SUSPICIOUS,
            Classification.OUT_OF_OFFICE,
        ]
        best = None
        for p in priority:
            for rule, _ in matched:
                if rule.classification == p:
                    best = rule
                    break
            if best:
                break
        if not best:
            best = matched[0][0]
        return ClassificationResult(
            classification=best.classification,
            confidence=0.85,
            source="regex",
            signals=signals,
        )

    # Nothing matched
    return ClassificationResult(
        classification=Classification.NEEDS_REVIEW,
        confidence=0.0,
        source="regex",
        signals=[],
        notes="no regex rule matched; LLM fallback recommended",
    )


# ---------- LLM fallback (OpenAI-compatible API) ----------------------------


DEFAULT_LLM_BASE_URL = "http://localhost:11434/v1"
DEFAULT_LLM_MODEL = "llama3.2:3b"
DEFAULT_API_KEY_ENV = "OPENAI_API_KEY"


def _dotenv_values() -> dict[str, str]:
    """Parse `<repo-root>/.env` (KEY=VALUE lines, # comments). Stdlib only."""
    from . import paths

    env_file = paths.ROOT() / ".env"
    values: dict[str, str] = {}
    if not env_file.exists():
        return values
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip("'\"")
    except OSError:
        pass
    return values


def _resolve(cli_value: Optional[str], env_key: str, default: str) -> str:
    """Precedence: CLI flag > process env > .env file > default."""
    return (
        cli_value
        or os.environ.get(env_key)
        or _dotenv_values().get(env_key)
        or default
    )


def resolve_llm_base_url(cli_value: Optional[str] = None) -> str:
    return _resolve(cli_value, "EMAIL_SCANNER_LLM_BASE_URL", DEFAULT_LLM_BASE_URL)


def resolve_llm_model(cli_value: Optional[str] = None) -> str:
    return _resolve(cli_value, "EMAIL_SCANNER_LLM_MODEL", DEFAULT_LLM_MODEL)


def resolve_llm_api_key(api_key_env: str = DEFAULT_API_KEY_ENV) -> Optional[str]:
    return os.environ.get(api_key_env) or _dotenv_values().get(api_key_env) or None


def _build_llm_prompt(msg: EmailMessage) -> str:
    """Build a redacted prompt for the LLM. Never the full body."""
    sender_domain = msg.from_.email.split("@")[-1] if msg.from_.email and "@" in msg.from_.email else ""
    attachments = ", ".join(a.get("filename", "?") for a in msg.attachments)
    snippet = redacted_body_snippet(msg.body_text or "", max_chars=200)
    return (
        "Classify this email for a job application tracker. "
        "Reply with JSON only, no commentary.\n"
        "\n"
        f"sender_domain: {sender_domain}\n"
        f"subject: {msg.subject}\n"
        f"body_snippet: {snippet}\n"
        f"attachments: {attachments}\n"
        "\n"
        "Choose exactly one of:\n"
        "  outbound-application, acknowledgement, interview-invite, "
        "interview-reschedule, task-assignment, info-request, offer, "
        "rejection, withdrawn-by-them, portal-ack, out-of-office, "
        "suspicious, other, needs-review\n"
        "\n"
        "Reply with JSON: {\"classification\": \"<one>\", \"confidence\": <0..1>, "
        "\"signals\": [\"<short reason>\"]}"
    )


def classify_with_llm(
    msg: EmailMessage,
    base_url: str = DEFAULT_LLM_BASE_URL,
    model: str = DEFAULT_LLM_MODEL,
    api_key: Optional[str] = None,
    timeout: int = 120,
) -> Optional[ClassificationResult]:
    """Call an OpenAI-compatible /chat/completions endpoint (local Ollama,
    LM Studio, or a cloud provider). Returns None if the endpoint is
    unreachable or the response can't be parsed — caller falls back to
    NEEDS_REVIEW."""
    prompt = _build_llm_prompt(msg)
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
    ).encode("utf-8")
    # Explicit User-Agent: Cloudflare-fronted endpoints reject urllib's default.
    headers = {"Content-Type": "application/json", "User-Agent": "email-scanner/1.0"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=payload,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        log.warning("llm call error (%s): %s", base_url, e)
        return None
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        log.warning("llm response missing choices[0].message.content")
        return None
    return _parse_llm_response(content)


def _parse_llm_response(text: str) -> Optional[ClassificationResult]:
    """Best-effort JSON extraction from the LLM output."""
    # Find the first { ... } block
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    cls_str = data.get("classification", "").strip()
    try:
        cls = Classification(cls_str)
    except ValueError:
        return None
    conf = data.get("confidence", 0.5)
    try:
        conf = float(conf)
    except (TypeError, ValueError):
        conf = 0.5
    signals = data.get("signals", []) or []
    if isinstance(signals, str):
        signals = [signals]
    return ClassificationResult(
        classification=cls,
        confidence=conf,
        source="llm",
        signals=[str(s)[:80] for s in signals][:10],
    )


# ---------- Top-level entry point -------------------------------------------


def classify(
    msg: EmailMessage,
    *,
    use_llm: bool = True,
    llm_base_url: str = DEFAULT_LLM_BASE_URL,
    llm_model: str = DEFAULT_LLM_MODEL,
    llm_api_key: Optional[str] = None,
    llm_timeout: int = 120,
) -> ClassificationResult:
    """Run regex first, then the LLM fallback if needed. Returns a
    ClassificationResult.

    The LLM NEVER receives the full body — it gets a redacted snippet
    via `_build_llm_prompt`. This applies to local and cloud endpoints
    alike."""
    regex_result = classify_message(msg)
    if regex_result.classification != Classification.NEEDS_REVIEW:
        return regex_result

    if use_llm:
        llm_result = classify_with_llm(
            msg,
            base_url=llm_base_url,
            model=llm_model,
            api_key=llm_api_key,
            timeout=llm_timeout,
        )
        if llm_result is not None:
            return llm_result

    return regex_result


def apply_classification(match: Match, result: ClassificationResult) -> None:
    """Mutate a Match in place with the classification result."""
    match.classification = result.classification
    match.classification_confidence = result.confidence
    match.classifier_source = result.source
    match.classification_signals = result.signals
    match.classification_notes = result.notes
    match.needs_review = (
        result.classification == Classification.NEEDS_REVIEW
        or result.confidence < 0.5
    )
