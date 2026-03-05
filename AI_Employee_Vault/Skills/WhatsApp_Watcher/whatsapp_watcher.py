#!/usr/bin/env python3
"""
WhatsApp Watcher — Bronze Tier Agent Skill  (Playwright edition)
================================================================
Monitors WhatsApp Web via a persistent Playwright Chromium browser for
incoming messages that contain urgent trigger keywords, then writes
Obsidian-flavoured Markdown action files into the vault's /Needs_Action
folder and logs each detection to /Dashboard.md.

Filter rules
------------
- Only **unread** chats are inspected (blue badge present).
- Only messages that contain at least one trigger keyword are acted on.
- One file per sender per calendar day: WHATSAPP_<sender>_<YYYYMMDD>.md
- Already-processed sender+date keys are persisted to .whatsapp_seen.json
  so no duplicate is ever created across restarts.

First run
---------
A Chromium window opens at web.whatsapp.com.
Open WhatsApp on your phone → Linked Devices → Link a device, scan the QR.
The browser profile is saved under PLAYWRIGHT_PROFILE_PATH so subsequent
runs skip the QR step.

Usage
-----
    pip install -r requirements.txt
    playwright install chromium
    cp .env.example .env          # fill in VAULT_PATH etc.
    python whatsapp_watcher.py
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
        logging.FileHandler(LOG_DIR / "whatsapp_watcher.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("whatsapp_watcher")

# ── Environment ───────────────────────────────────────────────────────────────
_VAULT_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
_SKILL_LOCAL_ENV = Path(__file__).resolve().parent / ".env"
load_dotenv(_VAULT_ROOT_ENV)
load_dotenv(_SKILL_LOCAL_ENV, override=True)

# ── Configuration ─────────────────────────────────────────────────────────────

VAULT_PATH       = Path(os.getenv("VAULT_PATH", str(Path(__file__).parent.parent.parent)))
NEEDS_ACTION     = VAULT_PATH / "Needs_Action"
DASHBOARD        = VAULT_PATH / "Dashboard.md"
KEYWORDS         = [k.strip().lower() for k in
                    os.getenv("KEYWORDS", "urgent,asap,invoice,payment,help").split(",")
                    if k.strip()]
POLL_INTERVAL    = int(os.getenv("POLL_INTERVAL", "30"))
PLAYWRIGHT_PROFILE = Path(os.getenv(
    "PLAYWRIGHT_PROFILE_PATH",
    str(Path.home() / ".wa_watcher_playwright")
))
WHATSAPP_URL     = "https://web.whatsapp.com"
HEADLESS         = os.getenv("HEADLESS", "false").lower() == "true"

# Persistent registry of already-processed sender+date keys
SEEN_REGISTRY = Path(__file__).parent / ".whatsapp_seen.json"

# WhatsApp Web CSS / ARIA selectors (WA Web 2025-2026 layout)
SEL_CHAT_LIST   = '[aria-label="Chat list"]'
SEL_CHAT_ITEM   = '[data-testid="cell-frame-container"]'
SEL_UNREAD      = '[data-testid="icon-unread-count"]'
SEL_CHAT_TITLE  = 'span[title]'
SEL_MSG_IN      = 'div.message-in'
SEL_MSG_TEXT    = (
    'span[data-testid="conversation-text-message-body"],'
    'span.selectable-text.copyable-text'
)


# ── Seen-key registry ─────────────────────────────────────────────────────────

def load_seen() -> set:
    """Load the set of already-processed sender+date keys from disk."""
    if SEEN_REGISTRY.exists():
        try:
            return set(json.loads(SEEN_REGISTRY.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            return set()
    return set()


def save_seen(seen: set) -> None:
    """Persist the set of processed keys to disk."""
    SEEN_REGISTRY.write_text(
        json.dumps(sorted(seen), indent=2), encoding="utf-8"
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_date_str() -> str:
    return datetime.now().strftime("%Y%m%d")


def safe_sender(name: str, max_len: int = 50) -> str:
    """Strip filesystem-unsafe characters and spaces for use in a filename."""
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned[:max_len]


def find_keywords(text: str) -> list:
    """Return list of matched keywords found in text (case-insensitive)."""
    lower = text.lower()
    return [kw for kw in KEYWORDS if kw in lower]


# ── Dashboard updater ─────────────────────────────────────────────────────────

def update_dashboard(filename: str) -> None:
    """Append a detection row to the Recent Activity table in Dashboard.md."""
    if not DASHBOARD.exists():
        log.warning("Dashboard.md not found — skipping dashboard update.")
        return

    text = DASHBOARD.read_text(encoding="utf-8")
    now  = utc_now()

    row = f"| {now} | whatsapp_message_detected | {filename} | WhatsApp Watcher |"

    # Insert just before the Flags & Alerts separator
    sentinel = "---\n\n## Flags & Alerts"
    if sentinel in text:
        text = text.replace(sentinel, f"{row}\n\n---\n\n## Flags & Alerts")
    else:
        text = text.rstrip() + f"\n\n{row}\n"

    # Refresh Last Updated timestamp
    text = re.sub(r"\*\*Last Updated:\*\* .+", f"**Last Updated:** {now}", text)

    DASHBOARD.write_text(text, encoding="utf-8")
    log.info(f"Dashboard updated  →  {filename}")


# ── Action file writer ────────────────────────────────────────────────────────

def write_action_file(sender: str, message: str, seen: set) -> bool:
    """
    Create WHATSAPP_<sender>_<YYYYMMDD>.md in /Needs_Action.

    Returns True if a new file was written, False if skipped.

    Dedup strategy
    --------------
    Key = "<safe_sender>::<YYYYMMDD>"
    One file per sender per calendar day — matches the filename convention.
    The key is checked against the in-memory+disk registry before writing.
    """
    NEEDS_ACTION.mkdir(parents=True, exist_ok=True)

    safe  = safe_sender(sender)
    date  = local_date_str()
    key   = f"{safe}::{date}"
    fname = f"WHATSAPP_{safe}_{date}.md"
    fpath = NEEDS_ACTION / fname

    # ── Skip-already-processed guard ──────────────────────────────────────────
    if key in seen:
        log.info(f"Already processed (registry)  →  {fname} — skipped.")
        return False

    if fpath.exists():
        log.info(f"File already on disk          →  {fname} — skipped.")
        seen.add(key)
        save_seen(seen)
        return False

    received_iso = utc_now()

    md = f"""---
type: whatsapp
from: {sender}
received: {received_iso}
priority: high
status: pending
---

## Message Content

{message}

## Suggested Actions

- [ ] Respond to message
- [ ] Notify human if approval needed
- [ ] Log message in Dashboard.md
"""

    fpath.write_text(md, encoding="utf-8")
    log.info(f"Action file created  →  {fname}")

    seen.add(key)
    save_seen(seen)
    update_dashboard(fname)
    return True


# ── Playwright browser helpers ────────────────────────────────────────────────

def wait_for_chat_list(page, timeout_ms: int = 120_000) -> bool:
    """Block until the WhatsApp chat list is visible (post-QR login)."""
    log.info("Waiting for WhatsApp Web chat list (scan QR if prompted) …")
    try:
        page.wait_for_selector(SEL_CHAT_LIST, timeout=timeout_ms)
        log.info("Chat list ready.")
        return True
    except PWTimeoutError:
        log.error("Chat list did not appear — QR not scanned in time?")
        return False


def get_unread_chats(page) -> list[dict]:
    """
    Return [{sender, element}] for every chat row that has an unread badge.
    Only unread chats are returned — read chats are entirely skipped.
    """
    results = []
    try:
        items = page.query_selector_all(SEL_CHAT_ITEM)
        for item in items:
            # Must have an unread badge — skip read chats entirely
            if not item.query_selector(SEL_UNREAD):
                continue

            title_el = item.query_selector(SEL_CHAT_TITLE)
            if not title_el:
                continue

            sender = (title_el.get_attribute("title") or title_el.inner_text() or "").strip()
            if not sender:
                continue

            results.append({"sender": sender, "element": item})

    except Exception as exc:
        log.warning("Error reading chat list: %s", exc)

    return results


def open_chat_and_get_messages(page, chat_el) -> list[str]:
    """
    Click a chat row open, wait for the panel to render, and return the
    text of the last 10 incoming messages.
    """
    messages = []
    try:
        chat_el.click()
        # Give the conversation panel time to render
        page.wait_for_timeout(1_500)

        msg_els = page.query_selector_all(SEL_MSG_IN)
        for el in msg_els[-10:]:
            text_el = el.query_selector(SEL_MSG_TEXT)
            if text_el:
                text = text_el.inner_text().strip()
                if text:
                    messages.append(text)
    except Exception as exc:
        log.debug("Could not read messages from chat: %s", exc)
    return messages


# ── Core scan loop ────────────────────────────────────────────────────────────

def scan(page, seen: set) -> int:
    """
    One full scan pass: inspect every unread chat for trigger keywords.

    For each unread chat:
      1. Open it and fetch the last 10 incoming messages.
      2. For every message that contains a keyword, create one action file
         (one per sender per day — deduped by registry).

    Returns the count of new action files created.
    """
    created      = 0
    unread_chats = get_unread_chats(page)
    log.info("Unread chats detected: %d", len(unread_chats))

    for chat in unread_chats:
        sender = chat["sender"]
        messages = open_chat_and_get_messages(page, chat["element"])

        # Pick the first message that hits a keyword and write one file
        # per sender per day (subsequent keyword hits in the same chat are
        # captured in the same file by the dedup key design)
        for msg in messages:
            hits = find_keywords(msg)
            if hits:
                log.info(
                    "Keyword(s) %s found in message from '%s'.",
                    hits, sender
                )
                if write_action_file(sender, msg, seen):
                    created += 1
                # One file per sender per day — stop scanning this chat
                break

    return created


# ── Entry point ───────────────────────────────────────────────────────────────

def run() -> None:
    log.info("=" * 62)
    log.info("  WhatsApp Watcher  —  Bronze Tier Agent Skill (Playwright)")
    log.info(f"  Keywords      : {', '.join(KEYWORDS)}")
    log.info(f"  Vault         : {VAULT_PATH}")
    log.info(f"  Needs_Action  : {NEEDS_ACTION}")
    log.info(f"  Poll interval : {POLL_INTERVAL}s")
    log.info(f"  Browser profile: {PLAYWRIGHT_PROFILE}")
    log.info(f"  Headless      : {HEADLESS}")
    log.info("=" * 62)

    seen = load_seen()
    log.info("Loaded %d already-processed sender-day key(s) from registry.", len(seen))

    with sync_playwright() as pw:
        # launch_persistent_context preserves the WhatsApp Web session between runs
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(PLAYWRIGHT_PROFILE),
            headless=HEADLESS,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--window-size=1280,900",
            ],
            viewport={"width": 1280, "height": 900},
        )

        page = context.pages[0] if context.pages else context.new_page()
        page.goto(WHATSAPP_URL, wait_until="domcontentloaded")

        if not wait_for_chat_list(page):
            context.close()
            return

        log.info("Starting scan loop …")
        try:
            while True:
                try:
                    count = scan(page, seen)
                    if count:
                        log.info("Created %d new action file(s).", count)
                    else:
                        log.info("No new keyword matches in unread chats.")
                except Exception as exc:
                    log.warning("Scan error (will retry): %s", exc)

                log.info("Next scan in %ds …\n", POLL_INTERVAL)
                time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            log.info("Stopped by user.")
        finally:
            context.close()
            log.info("Browser closed.")


if __name__ == "__main__":
    run()
