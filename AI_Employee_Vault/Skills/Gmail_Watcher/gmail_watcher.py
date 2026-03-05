#!/usr/bin/env python3
"""
Gmail Watcher — Silver Tier Agent Skill
========================================
Polls Gmail via IMAP for messages that are both UNSEEN and IMPORTANT,
then writes Obsidian-flavoured Markdown action files into /Needs_Action.

Guarantees:
- Only UNSEEN + IMPORTANT messages are processed.
- Files are named  EMAIL_<sanitised_message_id>.md
- Already-processed message IDs are persisted in .gmail_seen.json so
  the script never creates a duplicate file across restarts.
- Every new action file is logged to /Dashboard.md under Recent Activity.

Usage:
    python gmail_watcher.py

Requirements:
    pip install -r requirements.txt
    Copy .env.example → .env and fill in your credentials.
"""

import email
import email.message
import imaplib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from email.header import decode_header
from pathlib import Path

from dotenv import load_dotenv

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)-8s]  %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "gmail_watcher.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("gmail_watcher")

# ── Environment ───────────────────────────────────────────────────────────────
# Load vault root .env first, then skill-local .env as override
_VAULT_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
_SKILL_LOCAL_ENV = Path(__file__).resolve().parent / ".env"
load_dotenv(_VAULT_ROOT_ENV)
load_dotenv(_SKILL_LOCAL_ENV, override=True)

log.info("ENV loaded: root=%s (exists=%s), local=%s (exists=%s)",
         _VAULT_ROOT_ENV, _VAULT_ROOT_ENV.exists(),
         _SKILL_LOCAL_ENV, _SKILL_LOCAL_ENV.exists())

# ── Configuration ─────────────────────────────────────────────────────────────
GMAIL_USER         = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
VAULT_PATH         = Path(os.getenv("VAULT_PATH", str(Path(__file__).parent.parent.parent)))
NEEDS_ACTION       = VAULT_PATH / "Needs_Action"
DASHBOARD          = VAULT_PATH / "Dashboard.md"
POLL_INTERVAL      = int(os.getenv("POLL_INTERVAL", "60"))
IMAP_HOST          = "imap.gmail.com"

log.info("GMAIL_USER=%s, APP_PASSWORD=%s, VAULT=%s",
         GMAIL_USER or "(empty)",
         ("***" + GMAIL_APP_PASSWORD[-4:]) if GMAIL_APP_PASSWORD else "(empty)",
         VAULT_PATH)

# Persistent registry of already-processed Gmail Message-IDs
SEEN_REGISTRY = Path(__file__).parent / ".gmail_seen.json"


# ── Seen-ID registry ──────────────────────────────────────────────────────────

def load_seen() -> set:
    """Load the set of already-processed Message-IDs from disk."""
    if SEEN_REGISTRY.exists():
        try:
            return set(json.loads(SEEN_REGISTRY.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            return set()
    return set()


def save_seen(seen: set) -> None:
    """Persist the set of processed Message-IDs to disk."""
    SEEN_REGISTRY.write_text(
        json.dumps(sorted(seen), indent=2), encoding="utf-8"
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def decode_header_value(raw: str) -> str:
    """Decode a MIME-encoded email header into a plain string."""
    if not raw:
        return ""
    parts = decode_header(raw)
    result = []
    for chunk, charset in parts:
        if isinstance(chunk, bytes):
            result.append(chunk.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(str(chunk))
    return "".join(result).strip()


def extract_body(msg: email.message.Message) -> str:
    """Return plain-text body, truncated to 2 000 characters."""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp  = str(part.get("Content-Disposition", ""))
            if ctype == "text/plain" and "attachment" not in disp:
                try:
                    charset = part.get_content_charset() or "utf-8"
                    return part.get_payload(decode=True).decode(
                        charset, errors="replace"
                    ).strip()[:2000]
                except Exception:
                    pass
    else:
        try:
            charset = msg.get_content_charset() or "utf-8"
            return msg.get_payload(decode=True).decode(
                charset, errors="replace"
            ).strip()[:2000]
        except Exception:
            pass
    return "(body could not be decoded)"


def sanitise_message_id(raw_id: str) -> str:
    """
    Turn a raw Message-ID header value into a safe filename component.

    Example:  <CABcd1234@mail.gmail.com>  →  CABcd1234_mail_gmail_com
    """
    # Strip angle brackets
    mid = raw_id.strip().lstrip("<").rstrip(">")
    # Replace filesystem-unsafe characters with underscores
    mid = re.sub(r'[\\/:*?"<>|\r\n\t @]', "_", mid)
    # Collapse multiple underscores
    mid = re.sub(r"_+", "_", mid).strip("_")
    return mid[:120]  # cap length


# ── Dashboard updater ─────────────────────────────────────────────────────────

def update_dashboard(filename: str) -> None:
    """Append a row to the Recent Activity table in Dashboard.md."""
    if not DASHBOARD.exists():
        log.warning("Dashboard.md not found — skipping dashboard update.")
        return

    text = DASHBOARD.read_text(encoding="utf-8")
    now  = utc_now()

    activity_row = f"| {now} | gmail_email_detected | {filename} | Gmail Watcher |"

    # Insert the row just before the Flags & Alerts section separator
    activity_marker = "---\n\n## Flags & Alerts"
    if activity_marker in text:
        text = text.replace(
            activity_marker,
            f"{activity_row}\n\n---\n\n## Flags & Alerts",
        )
    else:
        # Fallback: append to end of file
        text = text.rstrip() + f"\n\n{activity_row}\n"

    # Refresh "Last Updated" timestamp
    text = re.sub(r"\*\*Last Updated:\*\* .+", f"**Last Updated:** {now}", text)

    DASHBOARD.write_text(text, encoding="utf-8")
    log.info(f"Dashboard updated for  {filename}")


# ── Action file writer ────────────────────────────────────────────────────────

def write_action_file(data: dict, seen: set) -> None:
    """
    Create a Markdown action note in /Needs_Action.

    File name:  EMAIL_<sanitised_message_id>.md
    Skips the message if a file with that name already exists on disk
    or if the Message-ID is already in the seen registry.
    """
    NEEDS_ACTION.mkdir(parents=True, exist_ok=True)

    msg_id_raw = data.get("message_id", "")
    safe_id    = sanitise_message_id(msg_id_raw) if msg_id_raw else utc_now().replace(":", "").replace("-", "")
    fname      = f"EMAIL_{safe_id}.md"
    fpath      = NEEDS_ACTION / fname

    # ── Skip-already-processed guard ──────────────────────────────────────────
    if msg_id_raw in seen:
        log.info(f"Already processed (registry)  →  {fname} — skipped.")
        return

    if fpath.exists():
        log.info(f"File already exists on disk   →  {fname} — skipped.")
        seen.add(msg_id_raw)
        save_seen(seen)
        return

    # ── Build ISO received timestamp ──────────────────────────────────────────
    raw_date = data.get("date", "")
    try:
        from email.utils import parsedate_to_datetime
        received_dt = parsedate_to_datetime(raw_date)
        received_iso = received_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        received_iso = utc_now()

    body_text = data["body"]
    truncated = len(body_text) == 2000

    md = f"""---
type: email
from: {data['from']}
subject: {data['subject']}
received: {received_iso}
priority: high
status: pending
---

## Email Content

{body_text}{"…  *(truncated)*" if truncated else ""}

## Suggested Actions

- [ ] Reply to sender
- [ ] Forward to relevant party
- [ ] Archive after processing
"""

    fpath.write_text(md, encoding="utf-8")
    log.info(f"Action file created  →  {fname}")

    # Mark as processed
    seen.add(msg_id_raw)
    save_seen(seen)

    # Log to Dashboard
    update_dashboard(fname)


# ── IMAP helpers ──────────────────────────────────────────────────────────────

def fetch_important_unread(mail: imaplib.IMAP4_SSL) -> list:
    """
    Return a list of message dicts for every message in INBOX that is
    both UNSEEN (unread) and IMPORTANT (starred / Google Important label).

    Gmail exposes the Important label as \\Important via IMAP.
    The search criterion  (UNSEEN KEYWORD $Important)  is the standard
    way to target that label without requiring X-GM-EXT-1 extensions.
    """
    mail.select("INBOX")

    # Primary search: UNSEEN and Gmail Important label
    status, data = mail.search(None, "UNSEEN", "KEYWORD", "$Important")

    if status != "OK":
        log.warning("IMAP SEARCH returned non-OK status — falling back to UNSEEN only.")
        status, data = mail.search(None, "UNSEEN")

    if not data or not data[0]:
        return []

    results = []
    for mid in data[0].split():
        try:
            _, msg_data = mail.fetch(mid, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            results.append({
                "imap_id":    mid,
                "from":       decode_header_value(msg.get("From", "")),
                "subject":    decode_header_value(msg.get("Subject", "(No Subject)")),
                "date":       msg.get("Date", ""),
                "message_id": msg.get("Message-ID", "").strip(),
                "body":       extract_body(msg),
            })
        except Exception as exc:
            log.warning(f"Could not parse message {mid}: {exc}")

    return results


# ── Main loop ─────────────────────────────────────────────────────────────────

def run() -> None:
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        log.error("GMAIL_USER and GMAIL_APP_PASSWORD must be set in .env")
        raise SystemExit(1)

    log.info("=" * 62)
    log.info("  Gmail Watcher  —  Silver Tier Agent Skill")
    log.info(f"  Account       : {GMAIL_USER}")
    log.info(f"  Filter        : UNSEEN + IMPORTANT")
    log.info(f"  Vault         : {VAULT_PATH}")
    log.info(f"  Needs_Action  : {NEEDS_ACTION}")
    log.info(f"  Poll interval : {POLL_INTERVAL}s")
    log.info("=" * 62)

    seen = load_seen()
    log.info(f"Loaded {len(seen)} already-processed message ID(s) from registry.")

    while True:
        try:
            log.info("Connecting to Gmail IMAP …")
            mail = imaplib.IMAP4_SSL(IMAP_HOST)
            mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)

            messages  = fetch_important_unread(mail)
            new_msgs  = [m for m in messages if m["message_id"] not in seen]

            if new_msgs:
                log.info(f"Found {len(new_msgs)} new unread+important email(s).")
                for em in new_msgs:
                    write_action_file(em, seen)
            else:
                log.info("No new unread+important emails.")

            mail.logout()

        except imaplib.IMAP4.error as exc:
            log.error(f"IMAP error: {exc}")
        except OSError as exc:
            log.error(f"Network error: {exc}")
        except Exception as exc:
            log.exception(f"Unexpected error: {exc}")

        log.info(f"Next check in {POLL_INTERVAL}s …\n")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run()
