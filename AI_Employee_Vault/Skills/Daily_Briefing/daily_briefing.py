#!/usr/bin/env python3
"""
Daily Briefing — Bronze Tier Agent Skill  (Brain Layer)
========================================================
Aggregates the current state of the vault and produces:

  1. DAILY_BRIEFING.md   — in the vault root  (replaces previous one)
  2. Dashboard.md update — surgical in-place update of key metrics

Reads:
  /Needs_Action/*.md       — items waiting to be actioned
  /Plans/PLAN_*.md         — generated plans (has priority in front matter)
  /Done/*                  — completed items

Usage:
    python daily_briefing.py
"""

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)-8s]  %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "daily_briefing.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("daily_briefing")

# ── Environment ───────────────────────────────────────────────────────────────
_VAULT_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
_SKILL_LOCAL_ENV = Path(__file__).resolve().parent / ".env"
load_dotenv(_VAULT_ROOT_ENV)
load_dotenv(_SKILL_LOCAL_ENV, override=True)

# ── Configuration ─────────────────────────────────────────────────────────────

VAULT_PATH    = Path(os.getenv("VAULT_PATH", str(Path(__file__).parent.parent.parent)))
NEEDS_ACTION  = VAULT_PATH / "Needs_Action"
PLANS         = VAULT_PATH / "Plans"
DONE          = VAULT_PATH / "Done"
BRIEFING_FILE = VAULT_PATH / "DAILY_BRIEFING.md"
DASHBOARD     = VAULT_PATH / "Dashboard.md"


# ── Front matter parser (shared with Plan_Generator) ─────────────────────────

def parse_front_matter(text: str) -> dict:
    fm: dict = {}
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return fm
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1]
            fm[key] = [x.strip().strip("\"'") for x in inner.split(",") if x.strip()]
        else:
            fm[key] = val.strip("\"'")
    return fm


def get_table_field(content: str, field: str) -> str:
    pattern = rf"\|\s*\*\*{re.escape(field)}\*\*\s*\|\s*(.+?)\s*\|"
    m = re.search(pattern, content, re.IGNORECASE)
    return m.group(1).strip() if m else ""


# ── Vault scanners ────────────────────────────────────────────────────────────

def scan_needs_action() -> list:
    """
    Return list of dicts for every .md in /Needs_Action.
    Skips hidden files and the .gitkeep placeholder.
    """
    items = []
    if not NEEDS_ACTION.exists():
        return items
    for f in sorted(NEEDS_ACTION.glob("*.md")):
        if f.name.startswith("."):
            continue
        try:
            text = f.read_text(encoding="utf-8")
            fm   = parse_front_matter(text)
            items.append({
                "file":        f.name,
                "path":        f,
                "type":        fm.get("type", "unknown"),
                "source":      fm.get("source", "unknown"),
                "created":     fm.get("created", ""),
                "has_plan":    (PLANS / f"PLAN_{f.name}").exists(),
            })
        except Exception as exc:
            log.warning("Could not read %s: %s", f.name, exc)
    return items


def scan_plans() -> list:
    """
    Return list of dicts for every PLAN_*.md in /Plans.
    Front matter must include priority and source_type.
    """
    items = []
    if not PLANS.exists():
        return items
    for f in sorted(PLANS.glob("PLAN_*.md")):
        try:
            text = f.read_text(encoding="utf-8")
            fm   = parse_front_matter(text)
            items.append({
                "file":         f.name,
                "path":         f,
                "status":       fm.get("status", "pending"),
                "priority":     fm.get("priority", "LOW"),
                "source_file":  fm.get("source_file", ""),
                "source_type":  fm.get("source_type", "unknown"),
                "created":      fm.get("created", ""),
            })
        except Exception as exc:
            log.warning("Could not read %s: %s", f.name, exc)
    # Sort: HIGH → MEDIUM → LOW
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    items.sort(key=lambda x: order.get(x["priority"], 3))
    return items


def scan_done() -> list:
    """Return list of file names in /Done (excluding hidden/gitkeep)."""
    if not DONE.exists():
        return []
    return [
        f.name for f in sorted(DONE.iterdir())
        if f.is_file() and not f.name.startswith(".")
    ]


# ── Focus list builder ────────────────────────────────────────────────────────

def build_focus_list(plans: list, needs_action_items: list) -> list:
    """
    Produce an ordered list of what the operator should tackle first.
    HIGH plans come first, then MEDIUM, then unplanned Needs_Action items.
    """
    focus = []
    seen_sources: set = set()

    for p in plans:
        if p["status"] == "pending":
            label = _friendly_label(p["source_type"], p["source_file"])
            focus.append({
                "priority": p["priority"],
                "label":    label,
                "plan":     p["file"],
            })
            seen_sources.add(p["source_file"])

    # Any Needs_Action items without a plan yet
    for na in needs_action_items:
        if na["file"] not in seen_sources and not na["has_plan"]:
            focus.append({
                "priority": "—",
                "label":    f"(no plan yet) {na['file']}",
                "plan":     "—",
            })

    return focus


def _friendly_label(source_type: str, source_file: str) -> str:
    """Return a short human label for a plan item."""
    stem = Path(source_file).stem
    if source_type == "email":
        # EMAIL_YYYYMMDD_HHMMSS_Subject → extract subject part
        parts = stem.split("_", 3)
        return f"Email — {parts[3].replace('_', ' ')}" if len(parts) > 3 else stem
    if source_type == "whatsapp":
        parts = stem.split("_", 3)
        return f"WhatsApp — {parts[3].replace('_', ' ')}" if len(parts) > 3 else stem
    if source_type == "file_drop":
        parts = stem.split("_", 3)
        return f"File — {parts[3].replace('_', ' ')}" if len(parts) > 3 else stem
    return stem


# ── Briefing writer ───────────────────────────────────────────────────────────

def write_briefing(
    na_items: list,
    plans: list,
    done_files: list,
    focus: list,
    now: datetime,
) -> Path:
    """Generate DAILY_BRIEFING.md in the vault root."""

    today_str = now.strftime("%Y-%m-%d")
    now_str   = now.strftime("%Y-%m-%d %H:%M:%S")
    now_iso   = now.isoformat()

    high_plans   = [p for p in plans if p["priority"] == "HIGH"   and p["status"] == "pending"]
    medium_plans = [p for p in plans if p["priority"] == "MEDIUM" and p["status"] == "pending"]
    low_plans    = [p for p in plans if p["priority"] == "LOW"    and p["status"] == "pending"]
    unplanned    = [na for na in na_items if not na["has_plan"]]

    # Counts
    na_total    = len(na_items)
    plan_total  = len(plans)
    done_total  = len(done_files)
    high_count  = len(high_plans)

    # ── At a Glance table
    glance_rows = [
        f"| Items in `/Needs_Action`   | {na_total} |",
        f"| Plans generated            | {plan_total} |",
        f"| Items completed (`/Done`)  | {done_total} |",
        f"| 🔴 HIGH priority pending   | {high_count} |",
        f"| 🟡 MEDIUM priority pending | {len(medium_plans)} |",
        f"| 🟢 LOW priority pending    | {len(low_plans)} |",
        f"| Unplanned items            | {len(unplanned)} |",
    ]

    # ── High priority table
    def plan_table_rows(plan_list: list) -> str:
        if not plan_list:
            return "_None._"
        header = "| # | Plan File | Source Type | Source File |\n|---|-----------|-------------|-------------|"
        rows   = "\n".join(
            f"| {i+1} | `{p['file']}` | {p['source_type'].replace('_',' ').title()} | `{p['source_file']}` |"
            for i, p in enumerate(plan_list)
        )
        return f"{header}\n{rows}"

    # ── All pending plans table
    def all_plans_table(plan_list: list) -> str:
        if not plan_list:
            return "_No plans on record._"
        badge = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}
        header = "| # | Priority | Source Type | Plan File |\n|---|----------|-------------|-----------|"
        rows   = "\n".join(
            f"| {i+1} | {badge.get(p['priority'],'')} {p['priority']} "
            f"| {p['source_type'].replace('_',' ').title()} | `{p['file']}` |"
            for i, p in enumerate(plan_list)
        )
        return f"{header}\n{rows}"

    # ── Done table
    def done_table(done_list: list) -> str:
        if not done_list:
            return "_Nothing moved to `/Done` yet today._"
        header = "| # | File |\n|---|------|"
        rows   = "\n".join(f"| {i+1} | `{f}` |" for i, f in enumerate(done_list))
        return f"{header}\n{rows}"

    # ── Focus list
    def focus_block(focus_list: list) -> str:
        if not focus_list:
            return "_Nothing pending — all clear!_"
        badge = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢", "—": "⚪"}
        lines = [
            f"{i+1}. {badge.get(f['priority'], '')} **[{f['priority']}]** {f['label']}"
            for i, f in enumerate(focus_list[:10])
        ]
        return "\n".join(lines)

    # ── Unplanned items note
    unplanned_note = ""
    if unplanned:
        names = "\n".join(f"  - `{na['file']}`" for na in unplanned)
        unplanned_note = (
            f"\n## ⚠ Unplanned Items\n\n"
            f"The following items in `/Needs_Action` have **no plan yet**. "
            f"Run `plan_generator.py` to process them.\n\n{names}\n"
        )

    md = f"""---
type: daily_briefing
generated: {now_iso}
date: {today_str}
needs_action_count: {na_total}
plans_count: {plan_total}
done_count: {done_total}
high_priority_count: {high_count}
---

# Daily Briefing — {today_str}

**Generated:** {now_str}  |  **Tier:** Bronze  |  **Vault:** `{VAULT_PATH}`

---

## Today at a Glance

| Metric | Count |
|--------|-------|
{chr(10).join(glance_rows)}

---

## 🔴 High Priority Items

{plan_table_rows(high_plans)}

---

## 🟡 Medium Priority Items

{plan_table_rows(medium_plans)}

---

## All Pending Plans

{all_plans_table([p for p in plans if p['status'] == 'pending'])}

---

## Completed (`/Done`)

{done_table(done_files)}

---
{unplanned_note}
## Suggested Focus Order

> Work through this list top-to-bottom. Open each linked Plan for full context and a reply draft.

{focus_block(focus)}

---
*Auto-generated by Daily Briefing · {now_str}*
"""

    BRIEFING_FILE.write_text(md, encoding="utf-8")
    log.info("Briefing written  →  %s", BRIEFING_FILE.name)
    return BRIEFING_FILE


# ── Dashboard updater ─────────────────────────────────────────────────────────

def update_dashboard(
    na_count: int,
    plan_count: int,
    done_count: int,
    high_priority: list,
    briefing_name: str,
    now_utc: str,
) -> None:
    """
    Surgically update key sections of Dashboard.md without rewriting the whole file.
    Gracefully skips any section it cannot find.
    """
    if not DASHBOARD.exists():
        log.warning("Dashboard.md not found at %s — skipping update.", DASHBOARD)
        return

    text = DASHBOARD.read_text(encoding="utf-8")
    original = text

    # 1 · Last Updated timestamp
    text = re.sub(
        r"\*\*Last Updated:\*\*.*",
        f"**Last Updated:** {now_utc}",
        text,
    )

    # 2 · Task Queue Metrics table rows
    def replace_metric_row(t: str, label: str, count: int) -> str:
        return re.sub(
            rf"(\| {re.escape(label)} \|)\s*\d+\s*(\|[^|]+\|)",
            rf"\g<1> {count} | {now_utc} |",
            t,
        )

    text = replace_metric_row(text, "Needs_Action",  na_count)
    text = replace_metric_row(text, "Plans",         plan_count)
    text = replace_metric_row(text, "Done",          done_count)

    # 3 · Throughput — Last Summary Generated
    text = re.sub(
        r"(\| Last Summary Generated \|).*?(\|)",
        rf"\1 {briefing_name} \2",
        text,
    )

    # 4 · Throughput — Last Execution
    text = re.sub(
        r"(\| Last Execution \|).*?(\|)",
        rf"\1 {now_utc} \2",
        text,
    )

    # 5 · Recent Activity Log — append new row
    new_row = f"| {now_utc} | daily_briefing_generated | {briefing_name} | System |\n"
    # Find the activity table and append before the next --- separator
    text = re.sub(
        r"(## Recent Activity Log.*?)(---)",
        lambda m: m.group(1) + new_row + m.group(2),
        text,
        count=1,
        flags=re.DOTALL,
    )

    # 6 · Flags & Alerts — replace the table body
    if high_priority:
        flag_rows = "\n".join(
            f"| HIGH | {p['source_type'].replace('_',' ').upper()} "
            f"| {p['source_file']} needs immediate attention |"
            for p in high_priority[:5]
        )
        text = re.sub(
            r"(\| Priority \| Flag \| Details \|.*?\n\|[-| ]+\|[-| ]+\|[-| ]+\|)(.*?)(---)",
            rf"\g<1>\n{flag_rows}\n\g<3>",
            text,
            count=1,
            flags=re.DOTALL,
        )
    else:
        # Clear any stale flags
        text = re.sub(
            r"(\| Priority \| Flag \| Details \|.*?\n\|[-| ]+\|[-| ]+\|[-| ]+\|)(.*?)(---)",
            r"\g<1>\n| — | No active flags | — |\n\g<3>",
            text,
            count=1,
            flags=re.DOTALL,
        )

    if text != original:
        DASHBOARD.write_text(text, encoding="utf-8")
        log.info("Dashboard.md updated.")
    else:
        log.info("Dashboard.md — no changes needed.")


# ── Entry point ───────────────────────────────────────────────────────────────

def run() -> None:
    now      = datetime.now()
    now_utc  = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    log.info("=" * 62)
    log.info("  Daily Briefing  —  Bronze Tier Brain Layer")
    log.info(f"  Vault         : {VAULT_PATH}")
    log.info(f"  Briefing file : {BRIEFING_FILE.name}")
    log.info("=" * 62)

    log.info("Scanning vault …")
    na_items   = scan_needs_action()
    plans      = scan_plans()
    done_files = scan_done()

    log.info("  Needs_Action : %d item(s)", len(na_items))
    log.info("  Plans        : %d plan(s)", len(plans))
    log.info("  Done         : %d item(s)", len(done_files))

    high_plans = [p for p in plans if p["priority"] == "HIGH" and p["status"] == "pending"]
    if high_plans:
        log.warning("  HIGH priority: %d item(s) require immediate attention!", len(high_plans))

    focus = build_focus_list(plans, na_items)

    briefing_path = write_briefing(na_items, plans, done_files, focus, now)

    update_dashboard(
        na_count      = len(na_items),
        plan_count    = len(plans),
        done_count    = len(done_files),
        high_priority = high_plans,
        briefing_name = briefing_path.name,
        now_utc       = now_utc,
    )

    log.info("Daily Briefing complete.")
    if high_plans:
        log.warning("ACTION NEEDED: %d HIGH-priority item(s) are pending!", len(high_plans))
    log.info("Open %s in Obsidian to review.", briefing_path.name)


if __name__ == "__main__":
    run()
