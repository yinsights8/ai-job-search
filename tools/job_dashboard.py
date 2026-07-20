#!/usr/bin/env python3
"""Job Application Dashboard - Catppuccin-themed TUI using rich.

Style ported from career-ops Go dashboard (Bubble Tea + Lip Gloss).
"""

import csv
import json
import os
import re
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta

try:
    from rich.console import Console, Group
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich.columns import Columns
    from rich import box
except ImportError:
    print("Error: 'rich' is required. Install with: pip install rich")
    sys.exit(1)

if sys.platform == "win32":
    os.system("")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent
TRACKER_CSV = REPO_ROOT / "job_search_tracker.csv"
SEEN_JSON = REPO_ROOT / "job_scraper" / "seen_jobs.json"

# ---------------------------------------------------------------------------
# Catppuccin Mocha palette
# ---------------------------------------------------------------------------
class C:
    base    = "#1e1e2e"
    surface = "#313244"
    overlay = "#45475a"
    text    = "#cdd6f4"
    subtext = "#a6adc8"
    blue    = "#89b4fa"
    mauve   = "#cba6f7"
    green   = "#a6e3a1"
    yellow  = "#f9e2af"
    sky     = "#89dceb"
    peach   = "#fab387"
    red     = "#f38ba8"
    pink    = "#f5c2e7"

# Bar block character
BLOCK = "\u2588"

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def parse_salary(s):
    if not s:
        return None, None
    cleaned = s.replace("GBP", "").replace(",", "").replace("£", "").strip()
    m = re.search(r"(\d+)\s*[-\u2013]\s*(\d+)", cleaned)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d+)", cleaned)
    if m:
        v = int(m.group(1))
        return v, v
    return None, None


def load_tracker():
    rows = []
    if not TRACKER_CSV.exists():
        return rows
    with open(TRACKER_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sal_min, sal_max = parse_salary(row.get("salary", ""))
            fit_m = re.search(r"(\d+)/100", row.get("notes", ""))
            fit_score = int(fit_m.group(1)) if fit_m else None
            rows.append({
                "date": row.get("date", ""),
                "company": row.get("company", ""),
                "role": row.get("role", ""),
                "location": row.get("location", ""),
                "salary_str": row.get("salary", ""),
                "salary_min": sal_min,
                "salary_max": sal_max,
                "source": row.get("source", ""),
                "status": row.get("status", ""),
                "notes": row.get("notes", ""),
                "fit_score": fit_score,
            })
    return rows


def load_seen():
    if not SEEN_JSON.exists():
        return {}
    with open(SEEN_JSON, encoding="utf-8") as f:
        return json.load(f).get("seen", {})


# ---------------------------------------------------------------------------
# Metrics computation (mirrors Go model/career.go)
# ---------------------------------------------------------------------------
def compute_metrics(tracker, seen):
    # Count statuses from BOTH sources (tracker is authoritative)
    statuses = defaultdict(int)
    for v in seen.values():
        statuses[v.get("status", "new")] += 1
    # Tracker overrides/adds statuses
    for r in tracker:
        s = r.get("status", "")
        if s:
            statuses[s] += 1

    # Fit scores: prefer numeric tracker score, fall back to categorical
    fit_scores = []
    seen_matched = set()
    for r in tracker:
        if r.get("fit_score"):
            fit_scores.append(r["fit_score"] / 20.0)  # 0-100 -> 0-5
        # Find matching seen entry (flexible matching)
        for sk, sv in seen.items():
            if sk in seen_matched:
                continue
            sc = sv.get("company", "").lower()
            rc = r["company"].lower()
            st = sv.get("title", "").lower()
            rt = r["role"].lower()
            name_match = (sc == rc or sc in rc or rc in sc)
            role_words = set(st.split()) & set(rt.split()) - {"the", "a", "an", "and", "or", "of", "for", "in", "at", "to", "with"}
            role_match = len(role_words) >= 3
            if name_match or role_match:
                if not r.get("fit_score"):
                    fit = sv.get("fit", "")
                    score_map = {"high": 4.5, "medium": 3.8, "low": 2.5}
                    fit_scores.append(score_map.get(fit, 3.0))
                seen_matched.add(sk)
                break
    # Add remaining seen entries
    for sk, sv in seen.items():
        if sk not in seen_matched:
            fit = sv.get("fit", "")
            score_map = {"high": 4.5, "medium": 3.8, "low": 2.5}
            fit_scores.append(score_map.get(fit, 3.0))

    avg_score = sum(fit_scores) / len(fit_scores) if fit_scores else 0
    top_score = max(fit_scores) if fit_scores else 0

    # Salary stats
    salaries = [r for r in tracker if r["salary_max"] is not None]
    avg_salary = sum(r["salary_max"] for r in salaries) / len(salaries) if salaries else 0

    # Funnel stages (mapped from our statuses)
    total_evaluated = statuses.get("evaluated", 0)
    total_applied = statuses.get("applied", 0)
    total_preparing = statuses.get("preparing_application", 0)
    total_active = total_applied + total_preparing
    funnel = [
        ("Seen", len(seen)),
        ("Active", total_active),
        ("Applied", total_applied),
        ("Preparing", total_preparing),
    ]

    # Score buckets
    buckets = {"4.5-5.0": 0, "4.0-4.4": 0, "3.5-3.9": 0, "3.0-3.4": 0, "<3.0": 0}
    for s in fit_scores:
        if s >= 4.5:
            buckets["4.5-5.0"] += 1
        elif s >= 4.0:
            buckets["4.0-4.4"] += 1
        elif s >= 3.5:
            buckets["3.5-3.9"] += 1
        elif s >= 3.0:
            buckets["3.0-3.4"] += 1
        else:
            buckets["<3.0"] += 1

    # Conversion rates
    total = len(seen)
    applied = statuses.get("applied", 0) + statuses.get("preparing_application", 0)
    eval_only = statuses.get("evaluated", 0)
    response_rate = (applied / total * 100) if total > 0 else 0
    interview_rate = 0  # no interview data yet
    offer_rate = 0

    return {
        "total": total,
        "statuses": dict(statuses),
        "avg_score": avg_score,
        "top_score": top_score,
        "avg_salary": avg_salary,
        "funnel": funnel,
        "buckets": buckets,
        "response_rate": response_rate,
        "interview_rate": interview_rate,
        "offer_rate": offer_rate,
        "applied": applied,
        "evaluated": eval_only,
    }


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------
def bar_chart(value, max_val, width=30, color=C.sky):
    """Render a bar using Unicode block characters."""
    if max_val == 0:
        return Text(" " * width, style=f"dim {C.overlay}")
    filled = max(1, int((value / max_val) * width)) if value > 0 else 0
    empty = width - filled
    return Text(BLOCK * filled + " " * empty, style=color)


def score_color(score):
    if score >= 4.2:
        return C.green
    if score >= 3.8:
        return C.yellow
    if score >= 3.0:
        return C.text
    return C.red


def status_color(status):
    return {
        "applied": C.sky,
        "preparing_application": C.yellow,
        "evaluated": C.text,
        "new": C.subtext,
        "skipped": C.red,
    }.get(status, C.text)


# ---------------------------------------------------------------------------
# Render: Header bar
# ---------------------------------------------------------------------------
def render_header(console, metrics):
    title = Text("  CAREER PIPELINE", style=f"bold {C.blue}")
    stats = Text()
    stats.append("   ", style="default")
    stats.append(f"{metrics['total']} jobs", style=f"bold {C.sky}")
    stats.append(" | ", style=f"dim {C.subtext}")
    stats.append(f"{metrics['applied']} applied", style=f"bold {C.green}")
    stats.append(" | ", style=f"dim {C.subtext}")
    avg = f"{metrics['avg_score']:.1f}" if metrics['avg_score'] else "N/A"
    stats.append(f"Avg {avg}/5", style=f"bold {C.yellow}")

    header = Text()
    header.append_text(title)
    header.append_text(stats)

    console.print(Panel(
        header,
        box=box.SIMPLE,
        border_style=C.surface,
        style=f"on {C.surface}",
        padding=(0, 0),
    ))


# ---------------------------------------------------------------------------
# Render: Tab bar
# ---------------------------------------------------------------------------
def render_tabs(console, statuses, total):
    tabs = Text()
    tabs.append("ALL", style=f"bold {C.blue}")
    tabs.append(f"({total})", style=f"dim {C.subtext}")

    tab_order = ["new", "evaluated", "preparing_application", "applied", "skipped"]
    tab_labels = {
        "new": "NEW", "evaluated": "EVALUATED", "preparing_application": "PREPARING",
        "applied": "APPLIED", "skipped": "SKIPPED",
    }

    for s in tab_order:
        count = statuses.get(s, 0)
        if count == 0:
            continue
        tabs.append("  ", style="default")
        tabs.append(tab_labels[s], style=f"bold {status_color(s)}")
        tabs.append(f"({count})", style=f"dim {C.subtext}")

    console.print(Panel(tabs, box=box.SIMPLE, border_style=C.surface, padding=(0, 1)))


# ---------------------------------------------------------------------------
# Render: Metrics bar
# ---------------------------------------------------------------------------
def render_metrics_bar(console, metrics):
    m = Text()
    m.append("  ", style="default")
    m.append("interview:", style=f"dim {C.subtext}")
    m.append("0", style=f"bold {C.green}")
    m.append("  ", style="default")
    m.append("applied:", style=f"dim {C.subtext}")
    m.append(str(metrics["applied"]), style=f"bold {C.sky}")
    m.append("  ", style="default")
    m.append("evaluated:", style=f"dim {C.subtext}")
    m.append(str(metrics["evaluated"]), style=f"bold {C.text}")
    m.append("  ", style="default")
    m.append("skipped:", style=f"dim {C.subtext}")
    m.append(str(metrics["statuses"].get("skipped", 0)), style=f"bold {C.red}")

    console.print(Panel(m, box=box.SIMPLE, border_style=C.surface, style=f"on {C.surface}", padding=(0, 0)))


# ---------------------------------------------------------------------------
# Render: Pipeline funnel
# ---------------------------------------------------------------------------
def render_funnel(console, metrics):
    title = Text("  Pipeline Funnel", style=f"bold {C.mauve}")
    console.print(title)

    funnel_colors = [C.blue, C.sky, C.green, C.yellow]
    max_val = max(v for _, v in metrics["funnel"]) if metrics["funnel"] else 1

    table = Table(box=None, show_header=False, padding=(0, 1))
    table.add_column(width=16)
    table.add_column(width=35)
    table.add_column(width=8, justify="right")

    for i, (label, count) in enumerate(metrics["funnel"]):
        color = funnel_colors[i % len(funnel_colors)]
        pct = f"({count/max_val*100:.0f}%)" if max_val > 0 else ""
        table.add_row(
            Text(f"  {label}", style=f"bold {color}"),
            bar_chart(count, max_val, width=30, color=color),
            Text(f"{count}", style=f"bold {color}"),
        )

    console.print(table)
    console.print()


# ---------------------------------------------------------------------------
# Render: Score distribution
# ---------------------------------------------------------------------------
def render_score_distribution(console, metrics):
    title = Text("  Score Distribution", style=f"bold {C.mauve}")
    console.print(title)

    bucket_colors = [C.green, C.green, C.yellow, C.peach, C.red]
    max_val = max(metrics["buckets"].values()) if metrics["buckets"] else 1

    table = Table(box=None, show_header=False, padding=(0, 1))
    table.add_column(width=16)
    table.add_column(width=35)
    table.add_column(width=8, justify="right")

    for i, (bucket, count) in enumerate(metrics["buckets"].items()):
        color = bucket_colors[i]
        table.add_row(
            Text(f"  {bucket}", style=f"bold {color}"),
            bar_chart(count, max_val, width=30, color=color),
            Text(str(count), style=f"bold {color}"),
        )

    console.print(table)
    console.print()


# ---------------------------------------------------------------------------
# Render: Conversion rates
# ---------------------------------------------------------------------------
def render_conversion_rates(console, metrics):
    title = Text("  Conversion Rates", style=f"bold {C.mauve}")
    console.print(title)

    def rate_color(rate):
        if rate >= 30:
            return C.green
        if rate >= 15:
            return C.yellow
        if rate >= 5:
            return C.peach
        return C.red

    lines = Text()
    lines.append("  ", style="default")

    lines.append("Response Rate: ", style=f"dim {C.subtext}")
    rr = metrics["response_rate"]
    lines.append(f"{rr:.1f}%", style=f"bold {rate_color(rr)}")
    lines.append("  |  ", style=f"dim {C.subtext}")

    lines.append("Interview Rate: ", style=f"dim {C.subtext}")
    ir = metrics["interview_rate"]
    lines.append(f"{ir:.1f}%", style=f"bold {rate_color(ir)}")
    lines.append("  |  ", style=f"dim {C.subtext}")

    lines.append("Offer Rate: ", style=f"dim {C.subtext}")
    orr = metrics["offer_rate"]
    lines.append(f"{orr:.1f}%", style=f"bold {rate_color(orr)}")

    console.print(lines)

    detail = Text()
    detail.append("  ", style="default")
    detail.append(f"{metrics['applied']} active applications", style=f"bold {C.sky}")
    detail.append(" | ", style=f"dim {C.subtext}")
    detail.append("0 total offers", style=f"dim {C.subtext}")
    console.print(detail)
    console.print()


# ---------------------------------------------------------------------------
# Render: Application table
# ---------------------------------------------------------------------------
def render_applications(console, tracker, seen):
    title = Text("  Applications", style=f"bold {C.mauve}")
    console.print(title)

    # Track which seen entries have been matched to a tracker row
    seen_matched = set()
    apps = []

    def companies_match(c1, c2, r1="", r2=""):
        """Check if two company+role pairs refer to the same job."""
        c1 = c1.lower().strip()
        c2 = c2.lower().strip()
        if c1 == c2:
            return True
        if c1 in c2 or c2 in c1:
            return True
        # Check role similarity as fallback
        if r1 and r2:
            r1_words = set(r1.lower().split())
            r2_words = set(r2.lower().split())
            common = r1_words & r2_words - {"the", "a", "an", "and", "or", "of", "for", "in", "at", "to", "with"}
            if len(common) >= 3:
                return True
        return False

    # First: add all tracker entries (these are the authoritative source)
    for r in tracker:
        # Find matching seen entry
        match_key = None
        for sk, sv in seen.items():
            if companies_match(sv.get("company", ""), r["company"],
                             sv.get("title", ""), r["role"]):
                match_key = sk
                break

        fit = seen[match_key].get("fit", "") if match_key else ""
        fit_score_map = {"high": 4.5, "medium": 3.8, "low": 2.5}
        score = fit_score_map.get(fit, 3.0)
        if r.get("fit_score"):
            score = r["fit_score"] / 20.0  # 0-100 -> 0-5

        if match_key:
            seen_matched.add(match_key)

        apps.append({
            "company": r["company"],
            "role": r["role"],
            "status": r["status"],
            "salary": r["salary_str"],
            "source": r["source"],
            "score": score,
            "fit": fit,
            "date": r["date"],
        })

    # Second: add seen entries NOT already in tracker
    for key, v in seen.items():
        if key in seen_matched:
            continue
        fit = v.get("fit", "")
        fit_score_map = {"high": 4.5, "medium": 3.8, "low": 2.5}
        score = fit_score_map.get(fit, 3.0)
        apps.append({
            "company": v.get("company", ""),
            "role": v.get("title", ""),
            "status": v.get("status", ""),
            "salary": v.get("salary", ""),
            "source": v.get("source", ""),
            "score": score,
            "fit": fit,
            "date": v.get("first_seen", ""),
        })

    # Sort by score descending
    apps.sort(key=lambda x: x["score"], reverse=True)

    table = Table(box=box.SIMPLE_HEAVY, border_style=C.overlay, padding=(0, 1))
    table.add_column("#", justify="right", width=4, style=f"dim {C.subtext}")
    table.add_column("FIT", justify="center", width=8)
    table.add_column("APPLIED", width=14, style=f"dim {C.subtext}")
    table.add_column("COMPANY", style=f"bold {C.text}", width=22)
    table.add_column("ROLE", width=28)
    table.add_column("STATUS", width=18)
    table.add_column("SALARY", width=18, style=f"dim {C.sky}")

    for i, app in enumerate(apps, 1):
        sc = score_color(app["score"])
        sc_label = f"{app['score']:.1f}" if app["score"] else "-"

        status = app["status"]
        if status == "preparing_application":
            status_label = "Preparing"
            sc_status = C.yellow
        elif status == "applied":
            status_label = "Applied"
            sc_status = C.sky
        elif status == "evaluated":
            status_label = "Evaluated"
            sc_status = C.text
        elif status == "skipped":
            status_label = "Skipped"
            sc_status = C.red
        else:
            status_label = status.title()
            sc_status = C.subtext

        table.add_row(
            Text(str(i)),
            Text(sc_label, style=f"bold {sc}"),
            Text(app["date"][:10] if app["date"] else ""),
            Text(app["company"][:20]),
            Text(app["role"][:26]),
            Text(status_label, style=f"bold {sc_status}"),
            Text(app["salary"][:16]),
        )

    console.print(table)
    console.print()


# ---------------------------------------------------------------------------
# Render: Salary overview
# ---------------------------------------------------------------------------
def render_salary(console, tracker):
    title = Text("  Salary Overview", style=f"bold {C.mauve}")
    console.print(title)

    with_sal = [r for r in tracker if r["salary_max"] is not None]
    if not with_sal:
        console.print(Text("  No salary data available", style=f"dim {C.subtext}"))
        console.print()
        return

    global_max = max(r["salary_max"] for r in with_sal)

    table = Table(box=None, show_header=False, padding=(0, 1))
    table.add_column(width=22)
    table.add_column(width=30)
    table.add_column(width=22, justify="right")

    for r in sorted(with_sal, key=lambda x: x["salary_max"], reverse=True):
        sal_min = r["salary_min"]
        sal_max = r["salary_max"]
        range_text = f"GBP {sal_min:,}-{sal_max:,}"

        bar_w = 25
        filled = max(1, int((sal_max / global_max) * bar_w)) if global_max > 0 else 1
        bar_str = BLOCK * filled + " " * (bar_w - filled)

        color = C.green if sal_max >= 40000 else C.yellow if sal_max >= 30000 else C.peach
        table.add_row(
            Text(f"  {r['company'][:20]}", style=f"bold {color}"),
            Text(bar_str, style=color),
            Text(range_text, style=f"dim {color}"),
        )

    console.print(table)
    console.print()


# ---------------------------------------------------------------------------
# Render: Help bar
# ---------------------------------------------------------------------------
def render_footer(console):
    footer = Text()
    footer.append("  q quit  ", style=f"dim {C.subtext}")
    footer.append("|  career-ops style dashboard", style=f"dim {C.overlay}")
    console.print(Panel(footer, box=box.SIMPLE, border_style=C.surface, style=f"on {C.surface}", padding=(0, 0)))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    console = Console(force_terminal=True, width=100)
    console.clear()

    tracker = load_tracker()
    seen = load_seen()

    if not tracker and not seen:
        console.print(f"[{C.red}]No data found. Run the job scraper first.[/{C.red}]")
        console.print(f"  Tracker: {TRACKER_CSV}")
        console.print(f"  Seen:    {SEEN_JSON}")
        return

    metrics = compute_metrics(tracker, seen)

    render_header(console, metrics)
    render_tabs(console, metrics["statuses"], metrics["total"])
    render_metrics_bar(console, metrics)
    console.print()
    render_funnel(console, metrics)
    render_score_distribution(console, metrics)
    render_conversion_rates(console, metrics)
    render_applications(console, tracker, seen)
    render_salary(console, tracker)
    render_footer(console)


if __name__ == "__main__":
    main()
