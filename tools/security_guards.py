#!/usr/bin/env python3
"""Supply-chain guards for the template's riskiest surfaces.

Run from anywhere: python tools/security_guards.py

This repo ships pre-approved Claude Code permissions and CLI code that every
fork user executes. These guards make the dangerous changes LOUD, not
impossible: a PR that intentionally needs one of them must update the
allowlists in this file in the same diff, so the change is explicit and
reviewable rather than buried.

Checks:
1. .claude/settings.json — every permissions.allow entry must be in the exact
   allowlist below. Catches permission widening (e.g. Bash(*), Bash(curl:*)),
   which would auto-approve commands on every fork.
2. .gitignore — the personal-data ignore rules must all still be present,
   and no un-allowlisted negation (!pattern) may re-include them. Catches
   weakening that would make future users silently commit their tracker,
   profile exports, or application archives.
3. .agents/**/package.json — no npm/bun lifecycle scripts (preinstall,
   install, postinstall, prepare, prepack) and no trustedDependencies.
   Catches code execution smuggled into `bun install`.
4. requirements.txt — every dependency must be pinned with `==` exactly.
   Catches supply-chain widening (e.g. `>=` allowing silent major-version
   upgrades that could exfiltrate data or escalate scope).
5. .opencode/agents/email-scanner.md and .claude/agents/email-scanner.md —
   the `tools:` allowlist must not contain `Bash(*)`, `WebFetch`,
   `WebSearch`, `Write`, or `Edit`. Catches a future refactor that broadens
   the email-scanner agent's reach beyond the read-only Gmail CLI.

Stdlib only. Exit 0 on success, 1 with a failure list otherwise.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
errors: list[str] = []

# The exact permission entries the template ships. A PR that adds or changes
# an entry must add it here too - that is the point: the diff shows both.
ALLOWED_PERMISSIONS = {
    "Skill(job-application-assistant)",
    "Bash(bun run:*)",
    "Bash(python salary_lookup.py:*)",
    "Bash(python3 salary_lookup.py:*)",
    "Bash(pdftotext:*)",
    # email-scanner CLI subcommands. Each is subcommand-pinned (no `*`
    # globs at the parent) so the agent can only call these specific
    # subcommands. See plan/02-scan-email.md §8.
    "Bash(python -m tools.email_scanner:plan*)",
    "Bash(python -m tools.email_scanner:apply*)",
    "Bash(python -m tools.email_scanner:revoke*)",
    "Bash(python -m tools.email_scanner:status*)",
    "Bash(python -m tools.email_scanner:auth-login*)",
    "Bash(python -m tools.email_scanner:stats*)",
}

# Personal-data ignore rules that must never disappear from .gitignore.
REQUIRED_IGNORE_RULES = [
    "salary_data.json",
    "job_scraper/seen_jobs.json",
    "cv/main_*.tex",
    "!cv/main_example.tex",
    "cover_letters/cover_*.tex",
    "documents/cv/**",
    "documents/linkedin/**",
    "documents/diplomas/**",
    "documents/references/**",
    "documents/applications/**",
    "job_search_tracker.csv",
]

# Negation (re-include) rules the template legitimately ships. .gitignore is
# order-sensitive: a later `!pattern` re-includes a path an earlier rule
# excluded, so a rule can be physically present in REQUIRED_IGNORE_RULES yet
# no longer ignored (e.g. adding `!salary_data.json`). Set membership on the
# required rules cannot see that. Any negation outside this allowlist is a
# failure - add an intentional one here in the same PR, exactly as with
# ALLOWED_PERMISSIONS, so the widening is explicit and reviewable.
ALLOWED_IGNORE_NEGATIONS = {
    "!cover_letters/OpenFonts/fonts/**",
    "!cv/main_example.tex",
    "!cover_letters/cover_example.tex",
    "!documents/**/.gitkeep",
}

FORBIDDEN_SCRIPTS = {"preinstall", "install", "postinstall", "prepare", "prepack"}


def check_permissions() -> None:
    path = ROOT / ".claude" / "settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f".claude/settings.json: unreadable or invalid JSON: {exc}")
        return
    if not isinstance(data, dict):
        errors.append(".claude/settings.json: top-level JSON value must be an object")
        return
    permissions = data.get("permissions", {})
    if not isinstance(permissions, dict):
        errors.append(".claude/settings.json: permissions must be an object")
        return
    allow = permissions.get("allow", [])
    if not isinstance(allow, list) or not all(isinstance(entry, str) for entry in allow):
        errors.append(".claude/settings.json: permissions.allow must be a list of strings")
        return
    for entry in allow:
        if entry not in ALLOWED_PERMISSIONS:
            errors.append(
                f".claude/settings.json: permission not in the reviewed allowlist: {entry!r}. "
                "Pre-approved permissions run without prompting on every fork. If this entry is "
                "intentional, add it to ALLOWED_PERMISSIONS in tools/security_guards.py in the "
                "same PR so the widening is explicit and reviewable."
            )
    for entry in ALLOWED_PERMISSIONS - set(allow):
        # Not an error: settings may legitimately drop an entry. But an
        # allowlist entry that no longer exists should be pruned.
        print(f"note: allowlisted permission not present in settings.json: {entry!r}")


def check_gitignore() -> None:
    path = ROOT / ".gitignore"
    try:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    except OSError as exc:
        errors.append(f".gitignore: unreadable: {exc}")
        return
    rules = set(lines)
    for rule in REQUIRED_IGNORE_RULES:
        if rule not in rules:
            errors.append(
                f".gitignore: required personal-data rule missing: {rule!r}. "
                "These rules keep fork users from committing personal data. If the rule moved "
                "or was renamed intentionally, update REQUIRED_IGNORE_RULES in "
                "tools/security_guards.py in the same PR."
            )
    for line in lines:
        if line.startswith("!") and line not in ALLOWED_IGNORE_NEGATIONS:
            errors.append(
                f".gitignore: negation rule not in the reviewed allowlist: {line!r}. "
                "A negation re-includes a path an earlier rule excluded and can silently "
                "re-expose personal data (a required ignore rule stays present but stops "
                "taking effect). If this negation is intentional, add it to "
                "ALLOWED_IGNORE_NEGATIONS in tools/security_guards.py in the same PR."
            )


def check_package_manifests() -> None:
    manifests = [
        p for p in ROOT.glob(".agents/**/package.json") if "node_modules" not in p.parts
    ]
    if not manifests:
        errors.append(".agents: no package.json files found - glob roots are wrong or the tree moved")
    for manifest in manifests:
        relpath = manifest.relative_to(ROOT)
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{relpath}: unreadable or invalid JSON: {exc}")
            continue
        if not isinstance(data, dict):
            errors.append(f"{relpath}: top-level JSON value must be an object")
            continue
        scripts = data.get("scripts", {})
        if not isinstance(scripts, dict):
            errors.append(f"{relpath}: scripts must be an object")
            continue
        bad = FORBIDDEN_SCRIPTS & set(scripts)
        if bad:
            errors.append(
                f"{relpath}: lifecycle script(s) {sorted(bad)} are forbidden - they execute "
                "arbitrary code during `bun install` on every fork user's machine."
            )
        if "trustedDependencies" in data:
            errors.append(
                f"{relpath}: trustedDependencies is forbidden - it re-enables dependency "
                "lifecycle scripts that bun blocks by default."
            )


def check_python_requirements() -> None:
    """Every line in requirements.txt must be pinned with `==` exactly.
    `>=` and unpinned deps are forbidden — they could be silently upgraded
    to a malicious version on the next install."""
    path = ROOT / "requirements.txt"
    if not path.exists():
        # No requirements.txt is fine — many setups have no Python deps.
        return
    relpath = path.relative_to(ROOT)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        errors.append(f"{relpath}: unreadable: {exc}")
        return
    for i, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Strip inline comments
        if "#" in line:
            line = line[: line.index("#")].strip()
        # Allow `-r other.txt` and similar pip directives
        if line.startswith("-"):
            continue
        if "==" not in line:
            errors.append(
                f"{relpath}:{i}: dep {line!r} is not pinned with `==`. "
                "Use exact versions (e.g. `pydantic==2.9.2`) to prevent silent "
                "supply-chain upgrades."
            )


def check_email_scanner_agent_allowlist() -> None:
    """The email-scanner subagent's `tools:` allowlist must not contain
    `Bash(*)`, `WebFetch`, `WebSearch`, `Write`, or `Edit`. Any of these
    would break the read-only-on-Gmail safety posture."""
    forbidden_in_allowlist = [
        "Bash(*)",
        "WebFetch",
        "WebSearch",
        "Write",
        "Edit",
    ]
    for path in (ROOT / ".opencode" / "agents" / "email-scanner.md", ROOT / ".claude" / "agents" / "email-scanner.md"):
        if not path.exists():
            continue
        relpath = path.relative_to(ROOT)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"{relpath}: unreadable: {exc}")
            continue
        # Extract the frontmatter block
        m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
        if not m:
            errors.append(f"{relpath}: no frontmatter block found")
            continue
        frontmatter = m.group(1)
        # Look for the `tools:` line and its (possibly multi-line) list
        m2 = re.search(r"^tools:\s*\n((?:[ \t]+-.*\n?)+)", frontmatter, re.MULTILINE)
        if not m2:
            errors.append(f"{relpath}: no `tools:` list in frontmatter")
            continue
        tools_block = m2.group(1)
        for forbidden in forbidden_in_allowlist:
            if forbidden in tools_block:
                errors.append(
                    f"{relpath}: tools allowlist contains {forbidden!r}. "
                    "The email-scanner subagent is read-only on Gmail and "
                    "read-only on disk except via the `apply` subcommand. "
                    f"Remove {forbidden} from the allowlist to preserve the "
                    "safety posture."
                )


def main() -> int:
    check_permissions()
    check_gitignore()
    check_package_manifests()
    check_python_requirements()
    check_email_scanner_agent_allowlist()
    if errors:
        print(f"security_guards: {len(errors)} failure(s)")
        for err in errors:
            print(f"  - {err}")
        return 1
    print(
        "security_guards: OK (permissions allowlist, gitignore rules, "
        "package manifests, requirements pinning, agent allowlists)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
