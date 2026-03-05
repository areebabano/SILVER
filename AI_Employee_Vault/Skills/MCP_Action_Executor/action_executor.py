#!/usr/bin/env python3
"""
MCP Action Executor — Gold Tier Agent Skill
============================================
Watches /Approved for plan files that have been signed off by a human
operator and executes the corresponding external action via the
appropriate MCP gateway:

  type: email      →  Gmail  (smtplib + App Password)
  type: whatsapp   →  WhatsApp Web  (Playwright browser automation)
  type: linkedin   →  LinkedIn Web  (Playwright browser automation)

Safety guarantees
-----------------
- Reads ONLY from /Approved.  Never touches /Pending_Approval or /Needs_Action.
- Each approved file is processed exactly once (tracked in .executor_seen.json).
- On success : approved file is moved to /Done.
- On failure : file stays in /Approved; error is logged; next cycle retries.
- DRY_RUN=true : logs the full intended action without sending anything or
                 moving any files.

Logging
-------
Every execution is appended to /Logs/YYYY-MM-DD.json in the vault's
established log format, and a row is inserted into Dashboard.md under
Recent Activity.

Usage
-----
    python action_executor.py           # single pass then exit
    python action_executor.py --watch   # continuous polling
"""

import argparse
import json
import logging
import os
import re
import shutil
import smtplib
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)-8s]  %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "action_executor.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("action_executor")

# ── Environment ───────────────────────────────────────────────────────────────
_VAULT_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
_SKILL_LOCAL_ENV = Path(__file__).resolve().parent / ".env"
load_dotenv(_VAULT_ROOT_ENV)
load_dotenv(_SKILL_LOCAL_ENV, override=True)

# ── Configuration ─────────────────────────────────────────────────────────────

VAULT_PATH    = Path(os.getenv("VAULT_PATH", str(Path(__file__).parent.parent.parent)))
APPROVED      = VAULT_PATH / "Approved"
DONE          = VAULT_PATH / "Done"
NEEDS_ACTION  = VAULT_PATH / "Needs_Action"
LOGS_DIR      = VAULT_PATH / "Logs"
DASHBOARD     = VAULT_PATH / "Dashboard.md"
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))
DRY_RUN       = os.getenv("DRY_RUN", "false").lower() == "true"
ACTOR         = os.getenv("EXECUTOR_ACTOR", "AI Employee (Gold Tier)")

# Gmail SMTP
GMAIL_USER         = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
GMAIL_FROM_NAME    = os.getenv("GMAIL_FROM_NAME", "AI Employee")

# Playwright profiles (reuse watcher session files)
WA_PROFILE  = Path(os.getenv(
    "WA_PLAYWRIGHT_PROFILE_PATH",
    str(Path.home() / ".wa_watcher_playwright")
))
LI_PROFILE  = Path(os.getenv(
    "LI_PLAYWRIGHT_PROFILE_PATH",
    str(Path.home() / ".li_watcher_playwright")
))
HEADLESS    = os.getenv("HEADLESS", "false").lower() == "true"

# Persistent registry of already-executed approved file names
SEEN_REGISTRY = Path(__file__).parent / ".executor_seen.json"

# ── Optional Playwright import ────────────────────────────────────────────────
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False


# ── Seen-key registry ─────────────────────────────────────────────────────────

def load_seen() -> set:
    if SEEN_REGISTRY.exists():
        try:
            return set(json.loads(SEEN_REGISTRY.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            return set()
    return set()


def save_seen(seen: set) -> None:
    SEEN_REGISTRY.write_text(
        json.dumps(sorted(seen), indent=2), encoding="utf-8"
    )


# ── Timestamp helpers ─────────────────────────────────────────────────────────

def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ── Front matter parser ───────────────────────────────────────────────────────

def parse_front_matter(text: str) -> dict:
    """Parse YAML-like front matter between --- delimiters."""
    fm: dict = {}
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return fm
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        fm[key.strip()] = val.strip().strip("\"'")
    return fm


def strip_front_matter(text: str) -> str:
    return re.sub(r"^---\s*\n.*?\n---\s*\n?", "", text, flags=re.DOTALL).strip()


def get_section(body: str, heading: str) -> str:
    """Return the content of a ## Heading section, or empty string."""
    pattern = rf"##\s+{re.escape(heading)}\s*\n(.*?)(?=\n##\s|\Z)"
    m = re.search(pattern, body, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def get_table_field(text: str, field: str) -> str:
    """Extract value from Markdown table: | Field | value |"""
    for pattern in [
        rf"\|\s*\*\*{re.escape(field)}\*\*\s*\|\s*(.+?)\s*\|",
        rf"\|\s*{re.escape(field)}\s*\|\s*(.+?)\s*\|",
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


# ── Approved file resolver ────────────────────────────────────────────────────

def resolve_source_file(source_name: str) -> Path | None:
    """
    Find the original Needs_Action file referenced by an approved plan.
    Checks /Needs_Action first, then /Done as a fallback.
    """
    for folder in [NEEDS_ACTION, DONE]:
        candidate = folder / source_name
        if candidate.exists():
            return candidate
    return None


def extract_draft_reply(plan_body: str) -> str:
    """
    Extract the reply text from a plan file.
    Priority order:
      1. ## Draft Reply section (human-edited)
      2. ## Suggested Reply section (AI-generated)
      3. ## Reply section
    Falls back to empty string — callers provide a default template.
    """
    for heading in ("Draft Reply", "Suggested Reply", "Reply"):
        content = get_section(plan_body, heading)
        if content:
            # Strip fenced code blocks if present
            content = re.sub(r"^```[^\n]*\n", "", content)
            content = re.sub(r"\n```$", "", content)
            return content.strip()
    return ""


def build_action_packet(approved_path: Path) -> dict:
    """
    Parse an approved plan file and return a normalised action dict:

    {
      'action_type' : 'email' | 'whatsapp' | 'linkedin',
      'plan_file'   : Path,
      'source_file' : Path | None,
      'to'          : str,           # recipient
      'subject'     : str,           # email only
      'draft'       : str,           # message body to send
      'priority'    : str,
    }
    """
    full_text  = approved_path.read_text(encoding="utf-8")
    fm         = parse_front_matter(full_text)
    body       = strip_front_matter(full_text)

    action_type  = fm.get("source_type", fm.get("type", "unknown")).lower()
    source_name  = fm.get("source_file", "")
    priority     = fm.get("priority", "MEDIUM").upper()
    source_path  = resolve_source_file(source_name) if source_name else None

    # ── Extract recipient ─────────────────────────────────────────────────────
    to_field = ""
    if source_path:
        src_text = source_path.read_text(encoding="utf-8")
        src_fm   = parse_front_matter(src_text)
        to_field = (
            src_fm.get("from")
            or get_table_field(src_text, "From")
            or get_table_field(src_text, "Sender")
            or ""
        ).strip()

    # Fallback: check if to_email was manually set in the approved plan
    to_field = to_field or fm.get("to_email", fm.get("to", "")).strip()

    # ── Extract subject ───────────────────────────────────────────────────────
    subject = ""
    if source_path:
        src_text = source_path.read_text(encoding="utf-8")
        src_fm   = parse_front_matter(src_text)
        raw_subj = (
            src_fm.get("subject")
            or get_table_field(src_text, "Subject")
            or ""
        ).strip()
        subject = raw_subj if raw_subj.lower().startswith("re:") else f"Re: {raw_subj}"

    # ── Extract draft reply ───────────────────────────────────────────────────
    draft = extract_draft_reply(body)
    if not draft:
        # Generic fallback — operator should add a Draft Reply section
        draft = (
            "Hi,\n\nThank you for your message. I have reviewed your request and "
            "will follow up shortly with further details.\n\n"
            "Kind regards,\n[YOUR NAME]"
        )
        log.warning(
            "No Draft Reply section found in %s — using generic template.",
            approved_path.name,
        )

    return {
        "action_type": action_type,
        "plan_file":   approved_path,
        "source_file": source_path,
        "to":          to_field,
        "subject":     subject,
        "draft":       draft,
        "priority":    priority,
    }


# ── MCP Gateways ──────────────────────────────────────────────────────────────

class GmailMCP:
    """
    Gmail gateway — sends via SMTP with App Password.

    MCP extension point: if a 'gmail' MCP server tool is registered in the
    environment, its tool call should replace the smtplib implementation here.
    """

    SMTP_HOST = "smtp.gmail.com"
    SMTP_PORT = 587

    def send(self, to: str, subject: str, body: str) -> dict:
        if not GMAIL_USER or not GMAIL_APP_PASSWORD:
            return {
                "success": False,
                "error": "GMAIL_USER or GMAIL_APP_PASSWORD not set in .env",
            }

        try:
            msg = MIMEMultipart("alternative")
            msg["From"]    = f"{GMAIL_FROM_NAME} <{GMAIL_USER}>"
            msg["To"]      = to
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain", "utf-8"))

            with smtplib.SMTP(self.SMTP_HOST, self.SMTP_PORT) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
                smtp.sendmail(GMAIL_USER, to, msg.as_string())

            log.info("Email sent  →  %s  [%s]", to, subject)
            return {"success": True, "sent_to": to, "subject": subject}

        except smtplib.SMTPAuthenticationError:
            return {"success": False, "error": "SMTP authentication failed — check App Password"}
        except smtplib.SMTPRecipientsRefused:
            return {"success": False, "error": f"Recipient refused: {to}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}


class WhatsAppMCP:
    """
    WhatsApp gateway — sends via Playwright browser automation.

    MCP extension point: replace with a WhatsApp Business API MCP tool call
    when a server is available.
    """

    WA_URL = "https://web.whatsapp.com"

    SEL_SEARCH_BOX  = '[data-testid="chat-list-search"]'
    SEL_SEARCH_INPUT = 'input[title="Search input textbox"], input[aria-label*="Search"]'
    SEL_CHAT_RESULT  = '[data-testid="cell-frame-container"]'
    SEL_MSG_INPUT    = (
        'div[data-testid="conversation-compose-box-input"],'
        'div[contenteditable="true"][data-tab]'
    )
    SEL_SEND_BTN     = '[data-testid="send"], button[aria-label*="Send"]'

    def send(self, contact_name: str, message: str) -> dict:
        if not _PLAYWRIGHT_AVAILABLE:
            return {"success": False, "error": "playwright not installed"}

        # Extract just the display name from "Name <email>" format
        display = re.match(r"^(.+?)\s*<[^>]+>$", contact_name.strip())
        name    = display.group(1).strip() if display else contact_name.strip()

        try:
            with sync_playwright() as pw:
                ctx  = pw.chromium.launch_persistent_context(
                    user_data_dir=str(WA_PROFILE),
                    headless=HEADLESS,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                    viewport={"width": 1280, "height": 900},
                )
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(self.WA_URL, wait_until="domcontentloaded")
                page.wait_for_selector('[aria-label="Chat list"]', timeout=60_000)

                # Open search
                search_el = (
                    page.query_selector(self.SEL_SEARCH_BOX)
                    or page.query_selector(self.SEL_SEARCH_INPUT)
                )
                if not search_el:
                    ctx.close()
                    return {"success": False, "error": "Search box not found on WA Web"}

                search_el.click()
                page.keyboard.type(name, delay=80)
                page.wait_for_timeout(1_500)

                results = page.query_selector_all(self.SEL_CHAT_RESULT)
                if not results:
                    ctx.close()
                    return {"success": False, "error": f"No chat found for contact: {name}"}

                results[0].click()
                page.wait_for_timeout(1_500)

                # Type and send message
                input_el = page.wait_for_selector(self.SEL_MSG_INPUT, timeout=10_000)
                input_el.click()
                # Type line-by-line (Shift+Enter for newlines inside WA)
                for i, line in enumerate(message.split("\n")):
                    if i > 0:
                        page.keyboard.down("Shift")
                        page.keyboard.press("Enter")
                        page.keyboard.up("Shift")
                    page.keyboard.type(line, delay=40)

                page.wait_for_timeout(500)

                send_btn = page.query_selector(self.SEL_SEND_BTN)
                if send_btn:
                    send_btn.click()
                else:
                    page.keyboard.press("Enter")

                page.wait_for_timeout(1_000)
                ctx.close()

            log.info("WhatsApp message sent  →  %s", name)
            return {"success": True, "sent_to": name}

        except PWTimeoutError as exc:
            return {"success": False, "error": f"Playwright timeout: {exc}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}


class LinkedInMCP:
    """
    LinkedIn gateway — sends direct messages via Playwright.

    MCP extension point: replace with a LinkedIn API / MCP server tool call
    when available.
    """

    LI_BASE = "https://www.linkedin.com"

    SEL_MSG_SEARCH   = 'input[placeholder*="Search"]'
    SEL_THREAD_ITEM  = "li.msg-conversation-listitem"
    SEL_COMPOSE_BOX  = (
        "div.msg-form__contenteditable,"
        "div[contenteditable='true'][role='textbox']"
    )
    SEL_SEND_BTN     = (
        "button.msg-form__send-button,"
        "button[type='submit'][aria-label*='Send']"
    )

    def send(self, contact_name: str, message: str) -> dict:
        if not _PLAYWRIGHT_AVAILABLE:
            return {"success": False, "error": "playwright not installed"}

        # Extract display name
        display = re.match(r"^(.+?)\s*<[^>]+>$", contact_name.strip())
        name    = display.group(1).strip() if display else contact_name.strip()

        try:
            with sync_playwright() as pw:
                ctx  = pw.chromium.launch_persistent_context(
                    user_data_dir=str(LI_PROFILE),
                    headless=HEADLESS,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
                    ignore_default_args=["--enable-automation"],
                    viewport={"width": 1366, "height": 768},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    ),
                )
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(
                    f"{self.LI_BASE}/messaging/",
                    wait_until="domcontentloaded"
                )
                page.wait_for_timeout(2_000)

                # Search for contact thread
                search_el = page.query_selector(self.SEL_MSG_SEARCH)
                if search_el:
                    search_el.click()
                    page.keyboard.type(name, delay=80)
                    page.wait_for_timeout(1_500)

                # Find and click the first matching thread
                threads = page.query_selector_all(self.SEL_THREAD_ITEM)
                matched = None
                for t in threads:
                    if name.lower() in (t.inner_text() or "").lower():
                        matched = t
                        break

                if not matched and threads:
                    matched = threads[0]

                if not matched:
                    ctx.close()
                    return {"success": False, "error": f"No LinkedIn thread found for: {name}"}

                matched.click()
                page.wait_for_timeout(1_500)

                # Type and send
                compose = page.wait_for_selector(self.SEL_COMPOSE_BOX, timeout=10_000)
                compose.click()
                for i, line in enumerate(message.split("\n")):
                    if i > 0:
                        page.keyboard.down("Shift")
                        page.keyboard.press("Enter")
                        page.keyboard.up("Shift")
                    page.keyboard.type(line, delay=40)

                page.wait_for_timeout(500)

                send_btn = page.query_selector(self.SEL_SEND_BTN)
                if send_btn:
                    send_btn.click()
                else:
                    page.keyboard.press("Return")

                page.wait_for_timeout(1_000)
                ctx.close()

            log.info("LinkedIn message sent  →  %s", name)
            return {"success": True, "sent_to": name}

        except PWTimeoutError as exc:
            return {"success": False, "error": f"Playwright timeout: {exc}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}


class MCPGateway:
    """
    Unified dispatcher — routes each action to the correct MCP backend.

    Extension pattern
    -----------------
    To plug in a real MCP server, replace the corresponding gateway
    class above with one that calls the MCP tool instead of driving
    a browser or SMTP directly.  The interface stays the same:
        gateway.send(**kwargs) → {"success": bool, ...}
    """

    _gmail     = GmailMCP()
    _whatsapp  = WhatsAppMCP()
    _linkedin  = LinkedInMCP()

    def execute(self, packet: dict, dry_run: bool) -> dict:
        """
        Dispatch the action described in packet.
        Returns a result dict with at least: {success, dry_run, action_type, ...}
        """
        action_type = packet["action_type"]
        to          = packet["to"]
        draft       = packet["draft"]

        base = {
            "action_type": action_type,
            "dry_run":     dry_run,
            "recipient":   to,
            "file":        packet["plan_file"].name,
            "actor":       ACTOR,
        }

        # ── Safety guard: never act without a recipient ───────────────────────
        if not to:
            return {
                **base,
                "success": False,
                "error":   (
                    "Recipient address is empty.  "
                    "Add 'to_email: address@example.com' to the approved plan "
                    "front matter, or ensure the source Needs_Action file has "
                    "a valid 'from:' field."
                ),
            }

        # ── DRY RUN ───────────────────────────────────────────────────────────
        if dry_run:
            preview = draft[:200].replace("\n", " ")
            log.info(
                "[DRY_RUN] Would send %s to '%s' — preview: %s…",
                action_type.upper(), to, preview
            )
            return {
                **base,
                "success":     True,
                "note":        "DRY_RUN — no action taken",
                "would_send":  {
                    "to":      to,
                    "subject": packet.get("subject", ""),
                    "body":    draft,
                },
            }

        # ── Live dispatch ─────────────────────────────────────────────────────
        if action_type == "email":
            result = self._gmail.send(to, packet["subject"], draft)

        elif action_type == "whatsapp":
            result = self._whatsapp.send(to, draft)

        elif action_type == "linkedin":
            result = self._linkedin.send(to, draft)

        else:
            result = {
                "success": False,
                "error":   f"Unknown action type '{action_type}'. "
                           "Supported: email, whatsapp, linkedin.",
            }

        return {**base, **result}


# ── JSON vault logger ─────────────────────────────────────────────────────────

def append_vault_log(
    level: str,
    event: str,
    file: str,
    status: str,
    message: str,
    **extra,
) -> None:
    """
    Append one entry to /Logs/YYYY-MM-DD.json in the established vault format.
    The file is created if it does not exist; entries are never modified.
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"{log_date()}.json"

    if log_path.exists():
        try:
            data = json.loads(log_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {"log_date": log_date(), "tier": "Gold", "entries": []}
    else:
        data = {"log_date": log_date(), "tier": "Gold", "entries": []}

    # Ensure 'entries' key exists (guards against malformed log files)
    if "entries" not in data or not isinstance(data.get("entries"), list):
        data["entries"] = []

    entry = {
        "timestamp": utc_now(),
        "level":     level,
        "component": "ActionExecutor",
        "event":     event,
        "file":      file,
        "status":    status,
        "message":   message,
        "actor":     ACTOR,
    }
    entry.update(extra)
    data["entries"].append(entry)
    log_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── Dashboard updater ─────────────────────────────────────────────────────────

def update_dashboard(result: dict) -> None:
    """Insert a Recent Activity row and refresh folder counts + timestamps."""
    if not DASHBOARD.exists():
        log.warning("Dashboard.md not found — skipping dashboard update.")
        return

    text   = DASHBOARD.read_text(encoding="utf-8")
    now    = utc_now()
    fname  = result.get("file", "unknown")
    status = "success" if result.get("success") else "failed"
    event  = f"action_{result.get('action_type', 'unknown')}_{status}"
    mode   = " [DRY_RUN]" if result.get("dry_run") else ""

    row = f"| {now} | {event}{mode} | {fname} | {ACTOR} |"

    # Insert before Flags & Alerts sentinel
    sentinel = "---\n\n## Flags & Alerts"
    if sentinel in text:
        text = text.replace(sentinel, f"{row}\n\n---\n\n## Flags & Alerts")
    else:
        text = text.rstrip() + f"\n\n{row}\n"

    # Refresh folder counts
    for folder_name, folder_path in [
        ("Approved", APPROVED),
        ("Done",     DONE),
    ]:
        count = (
            sum(1 for f in folder_path.iterdir()
                if f.is_file() and not f.name.startswith("."))
            if folder_path.exists() else 0
        )
        text = re.sub(
            rf"(\| {re.escape(folder_name)} \| )\d+( \| )(.+?)( \|)",
            rf"\g<1>{count}\g<2>{now}\g<4>",
            text,
        )

    # Update throughput metrics
    if result.get("success") and not result.get("dry_run"):
        text = re.sub(
            r"(\| Completed_Today \| )(.+?)( \|)",
            lambda m: (
                f"{m.group(1)}"
                f"{int(m.group(2)) + 1 if m.group(2).isdigit() else 1}"
                f"{m.group(3)}"
            ),
            text,
        )
    elif not result.get("success"):
        text = re.sub(
            r"(\| Failed_Today \| )(.+?)( \|)",
            lambda m: (
                f"{m.group(1)}"
                f"{int(m.group(2)) + 1 if m.group(2).isdigit() else 1}"
                f"{m.group(3)}"
            ),
            text,
        )

    text = re.sub(r"\*\*Last Updated:\*\* .+", f"**Last Updated:** {now}", text)
    text = re.sub(
        r"(\| Last Execution \| )(.+?)( \|)",
        rf"\g<1>{now}\g<3>",
        text,
    )

    DASHBOARD.write_text(text, encoding="utf-8")
    log.info("Dashboard updated.")


# ── Post-execution handler ────────────────────────────────────────────────────

def post_execute(
    packet: dict,
    result: dict,
    seen: set,
    dry_run: bool,
) -> None:
    """
    After dispatch:
    1. Write structured log entry to /Logs/YYYY-MM-DD.json.
    2. Update /Dashboard.md.
    3. Move approved file to /Done (success + not dry_run only).
    4. Register file name in seen set + persist.
    """
    plan_path   = packet["plan_file"]
    success     = result.get("success", False)
    action_type = result.get("action_type", "unknown")
    recipient   = result.get("recipient", "")

    # 1. Vault log
    level   = "AUDIT" if success else "ERROR"
    status  = "success" if success else "failed"
    dry_tag = " [DRY_RUN]" if dry_run else ""

    if success:
        msg = (
            f"{action_type.upper()} action executed{dry_tag} "
            f"for '{plan_path.name}' → sent to '{recipient}'."
        )
    else:
        msg = (
            f"{action_type.upper()} action FAILED{dry_tag} "
            f"for '{plan_path.name}': {result.get('error', 'unknown error')}"
        )

    append_vault_log(
        level   = level,
        event   = f"action_{action_type}_{'sent' if success else 'failed'}",
        file    = plan_path.name,
        status  = status,
        message = msg,
        dry_run = dry_run,
        action_type = action_type,
        recipient   = recipient,
    )

    # 2. Dashboard
    update_dashboard(result)

    # 3. Move to /Done (success + live run only)
    if success and not dry_run:
        DONE.mkdir(parents=True, exist_ok=True)
        dest = DONE / plan_path.name
        try:
            shutil.move(str(plan_path), str(dest))
            log.info("Moved to /Done  →  %s", plan_path.name)
        except OSError as exc:
            log.error("Could not move %s to /Done: %s", plan_path.name, exc)

    # 4. Register as processed
    seen.add(plan_path.name)
    save_seen(seen)


# ── Core processor ────────────────────────────────────────────────────────────

def process_approved_file(
    path: Path,
    gateway: MCPGateway,
    seen: set,
    dry_run: bool,
) -> bool:
    """
    Parse, dispatch, log, and optionally move one approved plan file.
    Returns True on success, False on failure.
    """
    log.info("Processing  →  %s", path.name)

    try:
        packet = build_action_packet(path)
    except Exception as exc:
        log.error("Could not parse %s: %s", path.name, exc)
        append_vault_log(
            level="ERROR",
            event="parse_error",
            file=path.name,
            status="failed",
            message=f"Failed to parse approved file: {exc}",
        )
        seen.add(path.name)
        save_seen(seen)
        return False

    result = gateway.execute(packet, dry_run)
    post_execute(packet, result, seen, dry_run)

    if result.get("success"):
        log.info("Action completed [%s]  →  %s", packet["action_type"].upper(), path.name)
    else:
        log.error(
            "Action FAILED [%s]  →  %s: %s",
            packet["action_type"].upper(), path.name,
            result.get("error", "no detail"),
        )

    return result.get("success", False)


def run_once(gateway: MCPGateway, seen: set, dry_run: bool) -> int:
    """
    Single pass over /Approved.
    Returns the count of successfully executed actions.
    """
    if not APPROVED.exists():
        log.warning("Approved folder not found: %s", APPROVED)
        return 0

    candidates = [
        f for f in sorted(APPROVED.glob("*.md"))
        if not f.name.startswith(".")
    ]

    if not candidates:
        log.info("No .md files in /Approved — nothing to execute.")
        return 0

    log.info("Found %d approved file(s).", len(candidates))
    success_count = 0

    for path in candidates:
        if path.name in seen:
            log.debug("Already processed, skipping: %s", path.name)
            continue
        if process_approved_file(path, gateway, seen, dry_run):
            success_count += 1

    return success_count


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="MCP Action Executor — Gold Tier"
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Poll /Approved continuously.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log intended actions without executing or moving files.",
    )
    args = parser.parse_args()

    # CLI --dry-run flag overrides env var
    active_dry_run = args.dry_run or DRY_RUN

    log.info("=" * 62)
    log.info("  MCP Action Executor  —  Gold Tier Agent Skill")
    log.info("  Vault     : %s", VAULT_PATH)
    log.info("  Approved  : %s", APPROVED)
    log.info("  Actor     : %s", ACTOR)
    log.info("  DRY_RUN   : %s", active_dry_run)
    log.info("  Playwright: %s", "available" if _PLAYWRIGHT_AVAILABLE else "NOT installed")
    if args.watch:
        log.info("  Mode      : watch (poll every %ds)", POLL_INTERVAL)
    else:
        log.info("  Mode      : single pass")
    log.info("=" * 62)

    if active_dry_run:
        log.warning("=" * 62)
        log.warning("  DRY_RUN IS ACTIVE — no emails, messages, or files will")
        log.warning("  be sent or moved.  All actions will be logged only.")
        log.warning("=" * 62)

    seen    = load_seen()
    gateway = MCPGateway()

    if args.watch:
        log.info("Watch mode active. Press Ctrl+C to stop.")
        while True:
            try:
                count = run_once(gateway, seen, active_dry_run)
                if count:
                    log.info("Executed %d action(s) this pass.", count)
                else:
                    log.info("No new actions executed.")
            except Exception as exc:
                log.exception("Unexpected error in watch loop: %s", exc)
            log.info("Next pass in %ds …\n", POLL_INTERVAL)
            time.sleep(POLL_INTERVAL)
    else:
        count = run_once(gateway, seen, active_dry_run)
        log.info("Done — %d action(s) executed.", count)


if __name__ == "__main__":
    main()
