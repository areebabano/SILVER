#!/usr/bin/env python3
"""
LinkedIn Watcher — Bronze Tier Agent Skill  (Playwright edition)
================================================================
Monitors two LinkedIn surfaces for new activity mentioning your
business services:

  1. /messaging/      — direct message threads (unread only)
  2. /notifications/  — comments on your posts (unread only)

For every qualifying item an Obsidian-flavoured Markdown action file
is created in /Needs_Action and a row is appended to /Dashboard.md.

Filter rules
------------
- Only **unread** message threads and notifications are inspected.
- Content must contain at least one SERVICE_KEYWORD to trigger a file.
- One file per sender per calendar day:
      LINKEDIN_<safe_sender>_<YYYYMMDD>.md
- Processed sender+date keys are persisted in .linkedin_seen.json so
  no duplicate is ever created across restarts.

First run
---------
A Chromium window opens at linkedin.com.  Log in manually.
The session is saved to PLAYWRIGHT_PROFILE_PATH so subsequent runs
remain logged in automatically.

Usage
-----
    pip install -r requirements.txt
    playwright install chromium
    cp .env.example .env
    python linkedin_watcher.py
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)-8s]  %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "linkedin_watcher.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("linkedin_watcher")

# ── Environment ───────────────────────────────────────────────────────────────
_VAULT_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
_SKILL_LOCAL_ENV = Path(__file__).resolve().parent / ".env"
load_dotenv(_VAULT_ROOT_ENV)
load_dotenv(_SKILL_LOCAL_ENV, override=True)

# ── Configuration ─────────────────────────────────────────────────────────────

VAULT_PATH    = Path(os.getenv("VAULT_PATH", str(Path(__file__).parent.parent.parent)))
NEEDS_ACTION  = VAULT_PATH / "Needs_Action"
DASHBOARD     = VAULT_PATH / "Dashboard.md"
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "60"))
HEADLESS      = os.getenv("HEADLESS", "false").lower() == "true"
LOGIN_TIMEOUT = int(os.getenv("LOGIN_TIMEOUT_SECONDS", "120")) * 1_000   # ms

PLAYWRIGHT_PROFILE = Path(os.getenv(
    "PLAYWRIGHT_PROFILE_PATH",
    str(Path.home() / ".li_watcher_playwright")
))

# Service keywords — all are lower-cased at match time
SERVICE_KEYWORDS = [
    kw.strip().lower()
    for kw in os.getenv(
        "SERVICE_KEYWORDS",
        "consulting,services,hire,project,proposal,quote,retainer,"
        "contract,partnership,collaboration,work together,offer,"
        "pricing,rates,available,freelance,agency,solution"
    ).split(",")
    if kw.strip()
]

LINKEDIN_BASE = "https://www.linkedin.com"
SEEN_REGISTRY = Path(__file__).parent / ".linkedin_seen.json"

# ── LinkedIn CSS / ARIA selectors (WA Web 2025-2026 layout) ──────────────────
# These may need updating if LinkedIn changes its DOM structure.
# Prefer data-* attributes and aria-labels — more stable than class names.

# ── Messaging page (linkedin.com/messaging/) ──────────────────────────────────
SEL_MSG_FEED    = ".msg-conversations-container__conversations-list"
SEL_MSG_THREAD  = "li.msg-conversation-listitem"
SEL_MSG_UNREAD  = ".msg-conversation-listitem--unread"          # unread thread row
SEL_MSG_NAME    = "h3.msg-conversation-listitem__title-name"
SEL_MSG_SNIPPET = ".msg-conversation-card__message-snippet-body"
SEL_MSG_BUBBLE  = (
    ".msg-s-event-listitem__message-bubble, "
    ".msg-s-message-text"
)

# ── Notifications page (linkedin.com/notifications/) ─────────────────────────
SEL_NOTIF_FEED  = ".notification-content__list, .notifications-container"
SEL_NOTIF_ITEM  = "li.notification-item, [data-occludable-job-id]"
SEL_NOTIF_UNREAD = ".notification-item--unread"
SEL_NOTIF_ACTOR = (
    ".notification-item__title span[aria-label], "
    ".notification-item__text strong, "
    ".notification-item__title a span"
)
SEL_NOTIF_TEXT  = (
    ".notification-item__text, "
    ".notification-item__title"
)


# ── Seen-key registry ─────────────────────────────────────────────────────────

def load_seen() -> set:
    """Load already-processed sender+date keys from disk."""
    if SEEN_REGISTRY.exists():
        try:
            return set(json.loads(SEEN_REGISTRY.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            return set()
    return set()


def save_seen(seen: set) -> None:
    """Persist processed keys to disk (sorted for diffability)."""
    SEEN_REGISTRY.write_text(
        json.dumps(sorted(seen), indent=2), encoding="utf-8"
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_date_str() -> str:
    return datetime.now().strftime("%Y%m%d")


def safe_name(text: str, max_len: int = 50) -> str:
    """Strip filesystem-unsafe chars; convert spaces to underscores."""
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", text).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned[:max_len]


def find_service_keywords(text: str) -> list[str]:
    """Return matched service keywords (case-insensitive)."""
    lower = text.lower()
    return [kw for kw in SERVICE_KEYWORDS if kw in lower]


def first_nonempty(*values) -> str:
    """Return the first non-empty string from the arguments."""
    return next((v.strip() for v in values if v and v.strip()), "Unknown")


# ── Dashboard updater ─────────────────────────────────────────────────────────

def update_dashboard(filename: str, source: str) -> None:
    """Append a detection row to Dashboard.md Recent Activity table."""
    if not DASHBOARD.exists():
        log.warning("Dashboard.md not found — skipping dashboard update.")
        return

    text = DASHBOARD.read_text(encoding="utf-8")
    now  = utc_now()
    row  = f"| {now} | linkedin_{source}_detected | {filename} | LinkedIn Watcher |"

    sentinel = "---\n\n## Flags & Alerts"
    if sentinel in text:
        text = text.replace(sentinel, f"{row}\n\n---\n\n## Flags & Alerts")
    else:
        text = text.rstrip() + f"\n\n{row}\n"

    text = re.sub(r"\*\*Last Updated:\*\* .+", f"**Last Updated:** {now}", text)
    DASHBOARD.write_text(text, encoding="utf-8")
    log.info("Dashboard updated  →  %s", filename)


# ── Action file writer ────────────────────────────────────────────────────────

def write_action_file(
    sender: str,
    content: str,
    source: str,        # "message" | "comment"
    seen: set,
) -> bool:
    """
    Create LINKEDIN_<safe_sender>_<YYYYMMDD>.md in /Needs_Action.

    Dedup key: "<safe_sender>::<source>::<YYYYMMDD>"
    Returns True when a new file is written, False when skipped.

    source prefixes distinguish a message and a comment from the same
    person on the same day so both can be captured.
    """
    NEEDS_ACTION.mkdir(parents=True, exist_ok=True)

    safe   = safe_name(sender)
    date   = local_date_str()
    key    = f"{safe}::{source}::{date}"
    fname  = f"LINKEDIN_{safe}_{date}.md"

    # When both a message and comment arrive from the same sender on the
    # same day, append the source suffix to keep files distinct.
    if source == "comment":
        fname = f"LINKEDIN_{safe}_CMT_{date}.md"

    fpath  = NEEDS_ACTION / fname

    # ── Dedup guard ───────────────────────────────────────────────────────────
    if key in seen:
        log.info("Already processed (registry)  →  %s — skipped.", fname)
        return False

    if fpath.exists():
        log.info("File already on disk          →  %s — skipped.", fname)
        seen.add(key)
        save_seen(seen)
        return False

    received_iso = utc_now()

    md = f"""---
type: linkedin
from: {sender}
received: {received_iso}
platform: linkedin
priority: medium
status: pending
---

## Message Content

{content}

## Suggested Actions

- [ ] Reply to message
- [ ] Add contact to CRM
- [ ] Archive after processing
"""

    fpath.write_text(md, encoding="utf-8")
    log.info("Action file created  →  %s", fname)

    seen.add(key)
    save_seen(seen)
    update_dashboard(fname, source)
    return True


# ── Login check ───────────────────────────────────────────────────────────────

def ensure_logged_in(page) -> bool:
    """
    Navigate to LinkedIn home and verify the user is authenticated.
    If not, wait up to LOGIN_TIMEOUT ms for the user to log in manually.
    Returns True if authenticated, False on timeout.
    """
    page.goto(LINKEDIN_BASE, wait_until="domcontentloaded")
    # After login, LinkedIn shows the feed; the URL does NOT contain /login
    if "/login" not in page.url and "/checkpoint" not in page.url:
        log.info("Session active — already logged in.")
        return True

    log.warning(
        "Not logged in.  Please log in manually in the browser window "
        "within %d seconds …", LOGIN_TIMEOUT // 1_000
    )
    try:
        page.wait_for_url(
            lambda url: "/login" not in url and "/checkpoint" not in url,
            timeout=LOGIN_TIMEOUT,
        )
        log.info("Login detected — continuing.")
        return True
    except PWTimeoutError:
        log.error("Login timeout — could not authenticate.")
        return False


# ── Messaging scanner ─────────────────────────────────────────────────────────

def scan_messages(page, seen: set) -> int:
    """
    Scan /messaging/ for unread threads whose content matches a service keyword.
    Returns the count of new action files created.
    """
    created = 0
    log.info("Scanning LinkedIn messages …")

    try:
        page.goto(f"{LINKEDIN_BASE}/messaging/", wait_until="domcontentloaded")
        page.wait_for_selector(SEL_MSG_FEED, timeout=15_000)
    except PWTimeoutError:
        log.warning("Messaging feed did not load — skipping.")
        return 0

    # Small pause to let dynamic content settle
    page.wait_for_timeout(2_000)

    unread_threads = page.query_selector_all(SEL_MSG_UNREAD)
    log.info("Unread message threads: %d", len(unread_threads))

    for thread in unread_threads:
        # Extract sender name from the thread row before clicking
        name_el = thread.query_selector(SEL_MSG_NAME)
        sender  = name_el.inner_text().strip() if name_el else ""
        if not sender:
            continue

        # Snippet visible in the list (quick keyword check)
        snippet_el = thread.query_selector(SEL_MSG_SNIPPET)
        snippet    = snippet_el.inner_text().strip() if snippet_el else ""

        # Open the thread for full message text
        try:
            thread.click()
            page.wait_for_timeout(1_500)
        except Exception as exc:
            log.debug("Could not open thread for '%s': %s", sender, exc)
            continue

        # Collect last 10 message bubbles
        bubble_els = page.query_selector_all(SEL_MSG_BUBBLE)
        messages   = []
        for el in bubble_els[-10:]:
            txt = el.inner_text().strip()
            if txt:
                messages.append(txt)

        # Also include the snippet as a fallback
        full_text = "\n".join(messages) if messages else snippet

        hits = find_service_keywords(full_text)
        if hits:
            log.info(
                "Service keyword(s) %s in message from '%s'.", hits, sender
            )
            # Use the most recent message bubble as the filed content
            content = messages[-1] if messages else snippet
            if write_action_file(sender, content, "message", seen):
                created += 1
        else:
            log.debug("No service keywords in message from '%s'.", sender)

    return created


# ── Notifications scanner ─────────────────────────────────────────────────────

def scan_notifications(page, seen: set) -> int:
    """
    Scan /notifications/ for unread comment notifications whose text
    matches a service keyword.
    Returns the count of new action files created.
    """
    created = 0
    log.info("Scanning LinkedIn notifications …")

    try:
        page.goto(f"{LINKEDIN_BASE}/notifications/", wait_until="domcontentloaded")
        page.wait_for_selector(SEL_NOTIF_FEED, timeout=15_000)
    except PWTimeoutError:
        log.warning("Notifications feed did not load — skipping.")
        return 0

    page.wait_for_timeout(2_000)

    # All notification items on the page
    all_items = page.query_selector_all(SEL_NOTIF_ITEM)
    log.info("Total notification items visible: %d", len(all_items))

    for item in all_items:
        # Skip read notifications
        if not item.query_selector(SEL_NOTIF_UNREAD):
            continue

        # Extract actor name
        actor_el = item.query_selector(SEL_NOTIF_ACTOR)
        sender   = actor_el.inner_text().strip() if actor_el else "Unknown"

        # Extract notification text
        text_el  = item.query_selector(SEL_NOTIF_TEXT)
        notif_text = text_el.inner_text().strip() if text_el else ""

        if not notif_text:
            continue

        hits = find_service_keywords(notif_text)
        if hits:
            log.info(
                "Service keyword(s) %s in notification from '%s'.", hits, sender
            )
            if write_action_file(sender, notif_text, "comment", seen):
                created += 1
        else:
            log.debug("No service keywords in notification from '%s'.", sender)

    return created


# ── One full scan pass ────────────────────────────────────────────────────────

def full_scan(page, seen: set) -> int:
    """Run message scan then notification scan. Return total files created."""
    total = 0
    total += scan_messages(page, seen)
    total += scan_notifications(page, seen)
    return total


# ── Entry point ───────────────────────────────────────────────────────────────

def run() -> None:
    log.info("=" * 62)
    log.info("  LinkedIn Watcher  —  Bronze Tier Agent Skill (Playwright)")
    log.info("  Monitoring : Messages + Post Comments")
    log.info("  Keywords   : %s", ", ".join(SERVICE_KEYWORDS))
    log.info("  Vault      : %s", VAULT_PATH)
    log.info("  Poll       : %ds", POLL_INTERVAL)
    log.info("  Profile    : %s", PLAYWRIGHT_PROFILE)
    log.info("  Headless   : %s", HEADLESS)
    log.info("=" * 62)

    seen = load_seen()
    log.info(
        "Loaded %d already-processed sender-day key(s) from registry.",
        len(seen)
    )

    with sync_playwright() as pw:
        # Persistent context keeps the LinkedIn session alive between runs
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(PLAYWRIGHT_PROFILE),
            headless=HEADLESS,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
            # Make navigator.webdriver invisible to bot-detection
            ignore_default_args=["--enable-automation"],
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )

        page = context.pages[0] if context.pages else context.new_page()

        if not ensure_logged_in(page):
            context.close()
            return

        log.info("Starting LinkedIn scan loop …")
        try:
            while True:
                try:
                    count = full_scan(page, seen)
                    if count:
                        log.info(
                            "Scan complete — %d new action file(s) created.", count
                        )
                    else:
                        log.info(
                            "Scan complete — no new service-keyword matches."
                        )
                except Exception as exc:
                    log.warning("Scan error (will retry next cycle): %s", exc)

                log.info("Next scan in %ds …\n", POLL_INTERVAL)
                time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            log.info("Stopped by user.")
        finally:
            context.close()
            log.info("Browser closed.")


if __name__ == "__main__":
    run()
