"""Shared domain-derivation helpers.

Single source of truth for the careers-portal-prefix stripping heuristic
used by both the email scanner and the /outcome workflow when adding new
tracker rows.

Add new prefixes to `_CAREERS_PREFIXES` only after verifying they don't
cause wrong matches for real applications.
"""
from __future__ import annotations

import re
from typing import Optional

# Hostname prefixes to strip when deriving a corporate email-sending
# domain from a careers-portal URL. Conservative list: only include
# prefixes that are reliably careers-portal subdomains.
_CAREERS_PREFIXES: tuple[str, ...] = (
    "jobs.",
    "careers.",
    "apply.",
    "boards.",
    "talent.",
)


def derive_domain_from_url(url: str) -> Optional[str]:
    """Extract the corporate email-sending domain from a URL.

    Returns the lowercased host after stripping any of the well-known
    careers-portal prefixes (`jobs.`, `careers.`, `apply.`, `boards.`,
    `talent.`). Returns None if the URL has no usable host.

    Examples:
        "https://jobs.bendingspoons.com/..." -> "bendingspoons.com"
        "https://boards.greenhouse.io/..."   -> "greenhouse.io"
        "https://theaacareers.co.uk"        -> "theaacareers.co.uk"  (no strip prefix)
        "not a url"                          -> None
    """
    if not url:
        return None
    m = re.search(r"https?://(?:www\.)?([^/]+)", url)
    if not m:
        return None
    host = m.group(1)
    host = host.split(":")[0].split("?")[0].split("#")[0].lower()
    if not host:
        return None
    for prefix in _CAREERS_PREFIXES:
        if host.startswith(prefix):
            return host[len(prefix):]
    return host
