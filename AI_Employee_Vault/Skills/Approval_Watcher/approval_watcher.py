#!/usr/bin/env python3
"""
Approval Watcher — Silver Tier Agent Skill
===========================================
Monitors /Approved/ and /Rejected/ folders for processed approval requests.

When a file appears in /Approved/:
  1. Logs the approval with timestamp
  2. Moves the file to /Done/

When a file appears in /Rejected/:
  1. Logs the rejection with timestamp
  2. Renames with REJECTED_ prefix
  3. Moves to /Done/

Polling interval: 5 seconds (human-paced approvals).

Usage:
    python approval_watcher.py

Requirements:
    pip install python-dotenv
    Copy .env.example → .env and adjust VAULT_PATH if needed.
"""

import json
import logging
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
    _VAULT_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
    _SKILL_LOCAL_ENV = Path(__file__).resolve().parent / ".env"
    load_dotenv(_VAULT_ROOT_ENV)
    load_dotenv(_SKILL_LOCAL_ENV, override=True)
except ImportError:
    pass

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)-8s]  %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "approval_watcher.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("approval_watcher")

# ── Configuration ─────────────────────────────────────────────────────────────
VAULT_PATH    = Path(os.getenv(
    "VAULT_PATH",
    str(Path(__file__).resolve().parent.parent.parent),
)).resolve()
POLL_INTERVAL = int(os.getenv("APPROVAL_POLL_INTERVAL", "5"))
ACTOR         = "Approval Watcher (Silver Tier)"

APPROVED_DIR  = VAULT_PATH / "Approved"
REJECTED_DIR  = VAULT_PATH / "Rejected"
DONE_DIR      = VAULT_PATH / "Done"
LOGS_DIR      = VAULT_PATH / "Logs"
DASHBOARD     = VAULT_PATH / "Dashboard.md"


# ── Helpers ───────────────────────────────────────────────────────────────────

def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def vault_log(filename: str, status: str, details: str = "") -> None:
    """Append a timestamped entry to today's JSON log file."""
    LOGS_DIR.mkdir(exist_ok=True)
    today    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_file = LOGS_DIR / f"{today}.json"

    if log_file.exists():
        try:
            data = json.loads(log_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {"log_date": today, "tier": "Silver", "entries": []}
    else:
        data = {"log_date": today, "tier": "Silver", "entries": []}

    if "entries" not in data or not isinstance(data.get("entries"), list):
        data["entries"] = []

    entry = {
        "timestamp": utc_now(),
        "level":     "AUDIT",
        "component": "ApprovalWatcher",
        "event":     status,
        "file":      filename,
        "status":    "success",
        "actor":     ACTOR,
    }
    if details:
        entry["details"] = details

    data["entries"].append(entry)
    log_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def update_dashboard(filename: str, event: str) -> None:
    """Insert a Recent Activity row in Dashboard.md."""
    if not DASHBOARD.exists():
        return

    now  = utc_now()
    text = DASHBOARD.read_text(encoding="utf-8")

    activity_row = f"\n| {now} | {event} | {filename} | {ACTOR} |\n"

    sentinel = "---\n\n## Flags & Alerts"
    if sentinel in text:
        text = text.replace(sentinel, activity_row + sentinel)
    else:
        text += activity_row

    import re
    text = re.sub(r"\*\*Last Updated:\*\* .+", f"**Last Updated:** {now}", text)

    DASHBOARD.write_text(text, encoding="utf-8")


# ── Processing ────────────────────────────────────────────────────────────────

def process_approved() -> int:
    """Process all .md files in /Approved/ directory."""
    count = 0
    for filepath in APPROVED_DIR.glob("*.md"):
        if filepath.name == ".gitkeep":
            continue

        log.info("APPROVED: %s", filepath.name)
        vault_log(filepath.name, "APPROVED_AND_EXECUTED")
        update_dashboard(filepath.name, "approval_executed")

        dest = DONE_DIR / filepath.name
        # Handle name collisions
        if dest.exists():
            stem = filepath.stem
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = DONE_DIR / f"{stem}_{ts}.md"

        shutil.move(str(filepath), str(dest))
        log.info("  -> Archived to Done/%s", dest.name)
        count += 1

    return count


def process_rejected() -> int:
    """Process all .md files in /Rejected/ directory."""
    count = 0
    for filepath in REJECTED_DIR.glob("*.md"):
        if filepath.name == ".gitkeep":
            continue

        log.info("REJECTED: %s", filepath.name)
        vault_log(filepath.name, "REJECTED_NOT_EXECUTED")
        update_dashboard(filepath.name, "approval_rejected")

        # Prefix with REJECTED_ if not already prefixed
        if filepath.name.startswith("REJECTED_"):
            dest_name = filepath.name
        else:
            dest_name = f"REJECTED_{filepath.name}"

        dest = DONE_DIR / dest_name
        # Handle name collisions
        if dest.exists():
            stem = Path(dest_name).stem
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = DONE_DIR / f"{stem}_{ts}.md"

        shutil.move(str(filepath), str(dest))
        log.info("  -> Archived to Done/%s", dest.name)
        count += 1

    return count


# ── Main loop ─────────────────────────────────────────────────────────────────

def main() -> None:
    # Ensure directories exist
    for d in [APPROVED_DIR, REJECTED_DIR, DONE_DIR, LOGS_DIR]:
        d.mkdir(parents=True, exist_ok=True)

    log.info("=" * 62)
    log.info("  Approval Watcher — Silver Tier Agent Skill")
    log.info("  Approved  : %s", APPROVED_DIR)
    log.info("  Rejected  : %s", REJECTED_DIR)
    log.info("  Archive   : %s", DONE_DIR)
    log.info("  Logs      : %s", LOGS_DIR)
    log.info("  Poll      : every %d seconds", POLL_INTERVAL)
    log.info("=" * 62)
    log.info("Press Ctrl+C to stop.\n")

    try:
        while True:
            approved = process_approved()
            rejected = process_rejected()

            if approved or rejected:
                log.info(
                    "Cycle: %d approved, %d rejected processed.",
                    approved, rejected,
                )

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        log.info("\nStopped by user.")


if __name__ == "__main__":
    main()
