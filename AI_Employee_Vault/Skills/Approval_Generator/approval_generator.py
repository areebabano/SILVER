#!/usr/bin/env python3
"""
Approval Request Generator — Gold Tier Agent Skill
===================================================
Generates Obsidian-flavoured Markdown approval requests for any sensitive
action before it is executed by the MCP Action Executor.

Trigger rules
-------------
1. send_email   — recipient not in known_contacts.json whitelist
2. payment      — any $ amount > PAYMENT_THRESHOLD (default $50)
3. post         — social media post on LinkedIn (not a DM reply)
4. approve_plan — plan contains a non-trivial ## Approval Required section

Input sources
-------------
A. Automatic scan mode  — reads every new PLAN_*.md in /Plans
B. Direct CLI mode      — caller provides --action, --recipient, --amount, etc.
C. Both can run together via --watch

Output
------
/Pending_Approval/APPROVAL_<action>_<topic>_<YYYYMMDD_HHMMSS>.md

Expiry
------
Priority HIGH    → 4 h
Payment actions  → 24 h
Priority MEDIUM  → 24 h
Social posts     → 12 h
Priority LOW     → 48 h

Expiry checker runs on every pass and marks stale pending requests `expired`.

Usage
-----
    # Scan /Plans automatically
    python approval_generator.py
    python approval_generator.py --watch

    # Create a specific approval request directly
    python approval_generator.py --action send_email \\
        --recipient alice@newclient.com \\
        --reason "First email to new client"

    python approval_generator.py --action payment \\
        --amount 250 \\
        --recipient "Acme Suppliers" \\
        --reason "Invoice #2041 payment"

    python approval_generator.py --action post \\
        --reason "LinkedIn post announcing new service offering"
"""

import argparse
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)-8s]  %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "approval_generator.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("approval_generator")

# ── Environment ───────────────────────────────────────────────────────────────
_VAULT_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
_SKILL_LOCAL_ENV = Path(__file__).resolve().parent / ".env"
load_dotenv(_VAULT_ROOT_ENV)
load_dotenv(_SKILL_LOCAL_ENV, override=True)

# ── Configuration ─────────────────────────────────────────────────────────────

VAULT_PATH          = Path(os.getenv("VAULT_PATH", str(Path(__file__).parent.parent.parent)))
PLANS               = VAULT_PATH / "Plans"
PENDING_APPROVAL    = VAULT_PATH / "Pending_Approval"
NEEDS_ACTION        = VAULT_PATH / "Needs_Action"
DONE                = VAULT_PATH / "Done"
LOGS_DIR            = VAULT_PATH / "Logs"
DASHBOARD           = VAULT_PATH / "Dashboard.md"
POLL_INTERVAL       = int(os.getenv("POLL_INTERVAL", "60"))
PAYMENT_THRESHOLD   = float(os.getenv("PAYMENT_THRESHOLD", "50.0"))
ACTOR               = os.getenv("APPROVAL_ACTOR", "Approval Generator (Gold Tier)")
AUTO_EXPIRE_MOVE    = os.getenv("AUTO_EXPIRE_MOVE", "false").lower() == "true"

KNOWN_CONTACTS_FILE = Path(__file__).parent / "known_contacts.json"
SEEN_REGISTRY       = Path(__file__).parent / ".approval_seen.json"

# Expiry durations in hours
EXPIRY_HOURS = {
    "HIGH":    4,
    "payment": 24,
    "post":    12,
    "MEDIUM":  24,
    "LOW":     48,
    "default": 24,
}

# Trivial phrases in Approval Required sections that don't warrant a request
TRIVIAL_APPROVAL_PHRASES = {
    "no approval required",
    "no approval needed",
    "self-managed",
    "n/a",
    "none required",
    "not required",
}


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


# ── Known contacts loader ─────────────────────────────────────────────────────

def load_known_contacts() -> dict:
    """
    Load trusted contacts from known_contacts.json.
    Returns {"domains": [...], "addresses": [...]}
    """
    if KNOWN_CONTACTS_FILE.exists():
        try:
            return json.loads(KNOWN_CONTACTS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"domains": [], "addresses": []}


def is_known_contact(address: str, contacts: dict) -> bool:
    """Return True if the address matches a known domain or exact address."""
    if not address:
        return False
    addr_lower = address.lower().strip()
    # Strip display name: "Name <email>" → "email"
    m = re.search(r"<([^>]+)>", addr_lower)
    if m:
        addr_lower = m.group(1).strip()

    for known in contacts.get("addresses", []):
        if known.lower().strip() == addr_lower:
            return True
    domain = addr_lower.split("@")[-1] if "@" in addr_lower else ""
    for known_domain in contacts.get("domains", []):
        if known_domain.lower().strip() == domain:
            return True
    return False


# ── Timestamp helpers ─────────────────────────────────────────────────────────

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_str() -> str:
    return utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


def log_date() -> str:
    return utc_now().strftime("%Y-%m-%d")


def expires_at(action: str, priority: str) -> str:
    """Calculate the ISO expiry timestamp for an approval request."""
    hours = (
        EXPIRY_HOURS.get(action)            # action-specific first
        or EXPIRY_HOURS.get(priority.upper() if priority else "")  # then priority
        or EXPIRY_HOURS["default"]
    )
    dt = utc_now() + timedelta(hours=hours)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Front matter & content helpers ───────────────────────────────────────────

def parse_front_matter(text: str) -> dict:
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
    pattern = rf"##\s+{re.escape(heading)}\s*\n(.*?)(?=\n##\s|\Z)"
    m = re.search(pattern, body, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def get_table_field(text: str, field: str) -> str:
    for pattern in [
        rf"\|\s*\*\*{re.escape(field)}\*\*\s*\|\s*(.+?)\s*\|",
        rf"\|\s*{re.escape(field)}\s*\|\s*(.+?)\s*\|",
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def extract_amounts(text: str) -> list[float]:
    """Find all dollar amounts in text and return them as floats."""
    # Match: $1,234.56  $1234  $1,234  $50.00
    raw = re.findall(r"\$\s*([\d,]+(?:\.\d{1,2})?)", text)
    amounts = []
    for r in raw:
        try:
            amounts.append(float(r.replace(",", "")))
        except ValueError:
            pass
    return amounts


def safe_filename(text: str, max_len: int = 40) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t@]', "_", text).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned[:max_len]


def resolve_source_file(source_name: str) -> Path | None:
    for folder in [NEEDS_ACTION, DONE]:
        candidate = folder / source_name
        if candidate.exists():
            return candidate
    return None


# ── Sensitivity detection ─────────────────────────────────────────────────────

def detect_sensitive_actions(
    plan_path: Path,
    plan_fm: dict,
    plan_body: str,
    contacts: dict,
) -> list[dict]:
    """
    Analyse a plan file and return a list of sensitive action dicts:
    [{ action, recipient, amount, reason, priority, plan_file, source_text }, ...]
    """
    source_type = plan_fm.get("source_type", plan_fm.get("type", "")).lower()
    priority    = plan_fm.get("priority", "MEDIUM").upper()
    source_name = plan_fm.get("source_file", "")
    full_text   = plan_path.read_text(encoding="utf-8")

    # Load original source file for richer context
    source_text = ""
    source_path = resolve_source_file(source_name) if source_name else None
    if source_path:
        source_text = source_path.read_text(encoding="utf-8")

    combined_text = full_text + "\n" + source_text

    found: list[dict] = []

    # ── Rule 1: Email to new contact ─────────────────────────────────────────
    if source_type == "email":
        src_fm    = parse_front_matter(source_text) if source_text else {}
        recipient = (
            src_fm.get("from")
            or get_table_field(source_text, "From")
            or get_table_field(full_text, "Recipient")
            or ""
        ).strip()

        if recipient and not is_known_contact(recipient, contacts):
            subject = (
                src_fm.get("subject")
                or get_table_field(source_text, "Subject")
                or "(no subject)"
            ).strip()
            found.append({
                "action":    "send_email",
                "recipient": recipient,
                "amount":    "",
                "reason":    f"Email reply to new contact: {recipient} — Subject: {subject}",
                "priority":  priority,
                "detail":    (
                    f"The Plan Generator has identified a reply action to "
                    f"**{recipient}**, who is not in your known contacts whitelist. "
                    f"Subject: *{subject}*. "
                    f"Original message received: {src_fm.get('received', 'unknown')}."
                ),
                "plan_file": plan_path,
            })

    # ── Rule 2: Payment above threshold ──────────────────────────────────────
    amounts = extract_amounts(combined_text)
    for amount in amounts:
        if amount > PAYMENT_THRESHOLD:
            src_fm    = parse_front_matter(source_text) if source_text else {}
            recipient = (
                src_fm.get("from")
                or get_table_field(source_text, "From")
                or get_table_field(source_text, "Sender")
                or "Unknown"
            ).strip()
            found.append({
                "action":    "payment",
                "recipient": recipient,
                "amount":    f"${amount:,.2f}",
                "reason":    f"Payment of ${amount:,.2f} to {recipient} exceeds ${PAYMENT_THRESHOLD:.0f} threshold",
                "priority":  priority,
                "detail":    (
                    f"A payment of **${amount:,.2f}** has been identified in the plan for "
                    f"**{recipient}**. This exceeds the automated approval threshold of "
                    f"${PAYMENT_THRESHOLD:.0f}. Human authorisation is required before "
                    f"any funds are transferred or committed."
                ),
                "plan_file": plan_path,
            })
            break   # one approval per plan for the largest amount

    # ── Rule 3: Social media post (LinkedIn post, not DM reply) ──────────────
    if source_type == "linkedin":
        post_indicators = [
            "post", "publish", "announce", "share on linkedin",
            "write a post", "create a post", "linkedin post",
        ]
        body_lower = (plan_body + source_text).lower()
        is_post = any(ind in body_lower for ind in post_indicators)
        # DMs are NOT posts — only trigger for actual post actions
        if is_post:
            src_fm = parse_front_matter(source_text) if source_text else {}
            found.append({
                "action":    "post",
                "recipient": "LinkedIn (public or connections)",
                "amount":    "",
                "reason":    "LinkedIn social media post requires pre-approval",
                "priority":  priority,
                "detail":    (
                    f"The plan involves **publishing a public LinkedIn post** or "
                    f"sharing content on social media. Public posts cannot be recalled "
                    f"easily and may affect brand reputation. Please review the draft "
                    f"content in the plan before approving."
                ),
                "plan_file": plan_path,
            })

    # ── Rule 4: Explicit non-trivial Approval Required section ───────────────
    approval_section = get_section(plan_body, "Approval Required")
    if approval_section:
        lower_section = approval_section.lower()
        is_trivial    = any(phrase in lower_section for phrase in TRIVIAL_APPROVAL_PHRASES)
        # Avoid double-flagging something already caught by rules 1-3
        already_flagged = any(a["action"] in ("send_email", "payment", "post") for a in found)

        if not is_trivial and not already_flagged:
            src_fm    = parse_front_matter(source_text) if source_text else {}
            recipient = (
                src_fm.get("from")
                or get_table_field(source_text, "From")
                or get_table_field(source_text, "Sender")
                or ""
            ).strip()
            snippet = approval_section[:300].replace("\n", " ")
            found.append({
                "action":    "approve_plan",
                "recipient": recipient,
                "amount":    "",
                "reason":    f"Plan requires human approval: {snippet[:120]}",
                "priority":  priority,
                "detail":    (
                    f"The Silver Tier Plan Generator flagged the following steps as "
                    f"requiring human approval:\n\n{approval_section}"
                ),
                "plan_file": plan_path,
            })

    return found


# ── Vault JSON logger ─────────────────────────────────────────────────────────

def append_vault_log(
    level: str,
    event: str,
    file: str,
    status: str,
    message: str,
    **extra,
) -> None:
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
        "timestamp": utc_now_str(),
        "level":     level,
        "component": "ApprovalGenerator",
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

def update_dashboard(created_files: list[str]) -> None:
    if not DASHBOARD.exists():
        log.warning("Dashboard.md not found — skipping dashboard update.")
        return

    text = DASHBOARD.read_text(encoding="utf-8")
    now  = utc_now_str()

    # Activity rows
    rows = "\n".join(
        f"| {now} | approval_request_created | {f} | {ACTOR} |"
        for f in created_files
    )

    sentinel = "---\n\n## Flags & Alerts"
    if sentinel in text:
        text = text.replace(sentinel, f"{rows}\n\n---\n\n## Flags & Alerts")
    else:
        text = text.rstrip() + f"\n\n{rows}\n"

    # Refresh Pending_Approval count
    count = (
        sum(1 for f in PENDING_APPROVAL.iterdir()
            if f.is_file() and not f.name.startswith("."))
        if PENDING_APPROVAL.exists() else 0
    )
    text = re.sub(
        r"(\| Pending_Approval \| )\d+( \| )(.+?)( \|)",
        rf"\g<1>{count}\g<2>{now}\g<4>",
        text,
    )

    text = re.sub(r"\*\*Last Updated:\*\* .+", f"**Last Updated:** {now}", text)
    DASHBOARD.write_text(text, encoding="utf-8")
    log.info("Dashboard updated — %d approval request(s) logged.", len(created_files))


# ── Approval file writer ──────────────────────────────────────────────────────

def write_approval_file(action_data: dict, seen: set) -> Path | None:
    """
    Write one APPROVAL_*.md file to /Pending_Approval.
    Returns the path on success, None if skipped.

    Dedup key: "<plan_file_name>::<action>::<safe_recipient>"
    """
    PENDING_APPROVAL.mkdir(parents=True, exist_ok=True)

    action     = action_data["action"]
    recipient  = action_data.get("recipient", "")
    amount     = action_data.get("amount", "")
    reason     = action_data.get("reason", "")
    priority   = action_data.get("priority", "MEDIUM")
    detail     = action_data.get("detail", reason)
    plan_path  = action_data.get("plan_file")

    # ── Dedup key ────────────────────────────────────────────────────────────
    plan_name = plan_path.name if plan_path else "cli"
    safe_recip = safe_filename(recipient or action)
    dedup_key  = f"{plan_name}::{action}::{safe_recip}"

    if dedup_key in seen:
        log.debug("Already queued (registry): %s — skipped.", dedup_key)
        return None

    # Check for an existing open approval in Pending_Approval for same key
    existing_pattern = f"APPROVAL_{action}_{safe_recip}_"
    if PENDING_APPROVAL.exists():
        for existing in PENDING_APPROVAL.glob("APPROVAL_*.md"):
            if existing.stem.startswith(existing_pattern):
                existing_fm = parse_front_matter(
                    existing.read_text(encoding="utf-8")
                )
                if existing_fm.get("status", "").lower() == "pending":
                    log.info(
                        "Open approval already exists: %s — skipped.", existing.name
                    )
                    seen.add(dedup_key)
                    save_seen(seen)
                    return None

    # ── Build filename ────────────────────────────────────────────────────────
    ts    = utc_now().strftime("%Y%m%d_%H%M%S")
    fname = f"APPROVAL_{action}_{safe_recip}_{ts}.md"
    fpath = PENDING_APPROVAL / fname

    # ── Expiry ────────────────────────────────────────────────────────────────
    exp = expires_at(action, priority)

    # ── Frontmatter fields ────────────────────────────────────────────────────
    amount_line    = f"amount: {amount}"    if amount    else "amount: N/A"
    recipient_line = f"recipient: {recipient}" if recipient else "recipient: N/A"

    # ── Plan context block ────────────────────────────────────────────────────
    plan_ref = (
        f"\n**Source Plan:** `{plan_path.name}`" if plan_path else ""
    )

    # ── Action-specific approve instructions ──────────────────────────────────
    if action in ("send_email", "approve_plan"):
        approve_instructions = (
            "1. Review the Details section above.\n"
            "2. If you want to customise the reply, open the source plan file\n"
            "   and add a `## Draft Reply` section with the message text.\n"
            "3. Move **this file** to `/Approved`.\n"
            "4. The MCP Action Executor will read the draft and send it automatically."
        )
    elif action == "payment":
        approve_instructions = (
            "1. Verify the payment amount and recipient are correct.\n"
            "2. Confirm funds are available in the relevant account.\n"
            "3. Move **this file** to `/Approved`.\n"
            "4. Initiate the payment transfer manually or via your payment system.\n"
            "5. Log the transaction reference in the source plan's Notes section."
        )
    elif action == "post":
        approve_instructions = (
            "1. Review the draft content in the source plan file.\n"
            "2. Edit the `## Draft Reply` section in the plan with the final post text.\n"
            "3. Move **this file** to `/Approved`.\n"
            "4. The MCP Action Executor will publish the post via LinkedIn automation."
        )
    else:
        approve_instructions = (
            "1. Review the Details section above.\n"
            "2. Move **this file** to `/Approved` to proceed.\n"
            "3. The relevant downstream skill will execute the action."
        )

    md = f"""---
type: approval_request
action: {action}
{amount_line}
{recipient_line}
reason: {reason}
created: {utc_now_str()}
expires: {exp}
status: pending
---

## Details

{detail}
{plan_ref}

| Field       | Value |
|-------------|-------|
| Action Type | `{action}` |
| Recipient   | {recipient or "N/A"} |
| Amount      | {amount or "N/A"} |
| Priority    | {priority} |
| Expires     | {exp} |
| Source Plan | {plan_path.name if plan_path else "N/A"} |

## To Approve

{approve_instructions}

## To Reject

1. Move **this file** to `/Rejected`.
2. The action will not be executed.
3. Optionally add a rejection note below explaining why.

### Rejection Note

> _Add your reason for rejection here (optional)_

---

*Auto-generated by Approval Generator (Gold Tier) · {utc_now_str()}*
"""

    fpath.write_text(md, encoding="utf-8")
    log.info("Approval request created  [%s]  →  %s", action.upper(), fname)

    seen.add(dedup_key)
    save_seen(seen)
    return fpath


# ── Expiry checker ────────────────────────────────────────────────────────────

def check_expiry(seen: set) -> int:
    """
    Scan /Pending_Approval for requests whose `expires` timestamp has passed.
    Marks their status as `expired` in-place.
    Optionally moves them to /Rejected if AUTO_EXPIRE_MOVE is enabled.
    Returns count of newly expired files.
    """
    if not PENDING_APPROVAL.exists():
        return 0

    now     = utc_now()
    expired = 0

    for path in PENDING_APPROVAL.glob("APPROVAL_*.md"):
        text = path.read_text(encoding="utf-8")
        fm   = parse_front_matter(text)

        if fm.get("status", "").lower() != "pending":
            continue

        expires_str = fm.get("expires", "")
        if not expires_str:
            continue

        try:
            expires_dt = datetime.fromisoformat(
                expires_str.replace("Z", "+00:00")
            )
        except ValueError:
            continue

        if now > expires_dt:
            # Patch status in-place
            updated = re.sub(r"(^status:\s*)pending", r"\1expired", text, flags=re.MULTILINE)
            path.write_text(updated, encoding="utf-8")
            log.warning("Approval request expired  →  %s", path.name)

            append_vault_log(
                level="WARN",
                event="approval_expired",
                file=path.name,
                status="expired",
                message=f"Approval request '{path.name}' expired at {expires_str}.",
            )
            expired += 1

            if AUTO_EXPIRE_MOVE:
                import shutil
                rejected = VAULT_PATH / "Rejected" / path.name
                (VAULT_PATH / "Rejected").mkdir(exist_ok=True)
                shutil.move(str(path), str(rejected))
                log.info("Expired file moved to /Rejected  →  %s", path.name)

    return expired


# ── Plan scanner ──────────────────────────────────────────────────────────────

def scan_plans(seen: set, contacts: dict) -> list[Path]:
    """
    Scan every PLAN_*.md in /Plans and generate approval requests for
    any sensitive actions found.  Returns list of created approval paths.
    """
    if not PLANS.exists():
        log.warning("Plans folder not found: %s", PLANS)
        return []

    plan_files = sorted(PLANS.glob("PLAN_*.md"))
    if not plan_files:
        log.info("No plan files found in /Plans.")
        return []

    log.info("Scanning %d plan file(s) for sensitive actions …", len(plan_files))
    created: list[Path] = []

    for plan_path in plan_files:
        try:
            full_text  = plan_path.read_text(encoding="utf-8")
            plan_fm    = parse_front_matter(full_text)
            plan_body  = strip_front_matter(full_text)

            sensitive_actions = detect_sensitive_actions(
                plan_path, plan_fm, plan_body, contacts
            )

            if not sensitive_actions:
                log.debug("No sensitive actions in %s.", plan_path.name)
                continue

            for action_data in sensitive_actions:
                result = write_approval_file(action_data, seen)
                if result:
                    created.append(result)

        except Exception as exc:
            log.error("Error processing plan %s: %s", plan_path.name, exc, exc_info=True)

    return created


# ── Single pass ───────────────────────────────────────────────────────────────

def run_once(seen: set, contacts: dict) -> int:
    """Full scan + expiry check. Returns total files created."""

    # 1. Check for expired pending approvals
    expired = check_expiry(seen)
    if expired:
        log.info("%d approval request(s) marked as expired.", expired)

    # 2. Scan plans for new sensitive actions
    created = scan_plans(seen, contacts)

    if created:
        update_dashboard([p.name for p in created])
        for p in created:
            append_vault_log(
                level="AUDIT",
                event="approval_request_created",
                file=p.name,
                status="success",
                message=f"Approval request created: {p.name}",
            )

    log.info("Pass complete — %d new approval request(s), %d expired.", len(created), expired)
    return len(created)


# ── Direct CLI invocation ─────────────────────────────────────────────────────

def create_direct(
    action: str,
    recipient: str,
    amount: str,
    reason: str,
    priority: str,
    seen: set,
) -> Path | None:
    """
    Create a single approval request directly from CLI arguments.
    No plan file scanning is performed.
    """
    detail_map = {
        "send_email": (
            f"A new email to **{recipient}** has been requested. "
            f"This contact is not in the known contacts whitelist. "
            f"Reason: {reason}"
        ),
        "payment": (
            f"A payment of **{amount}** to **{recipient}** has been requested. "
            f"This exceeds the automated approval threshold. "
            f"Reason: {reason}"
        ),
        "post": (
            f"A social media post has been prepared for publication. "
            f"Reason: {reason}"
        ),
    }

    action_data = {
        "action":    action,
        "recipient": recipient,
        "amount":    amount,
        "reason":    reason,
        "priority":  priority.upper(),
        "detail":    detail_map.get(action, reason),
        "plan_file": None,
    }

    result = write_approval_file(action_data, seen)
    if result:
        update_dashboard([result.name])
        append_vault_log(
            level="AUDIT",
            event="approval_request_created",
            file=result.name,
            status="success",
            message=f"Direct approval request created: {result.name}",
            direct=True,
        )
    return result


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Approval Request Generator — Gold Tier"
    )
    parser.add_argument("--watch", action="store_true",
                        help="Poll /Plans continuously.")
    parser.add_argument("--action", choices=["send_email", "payment", "post", "approve_plan"],
                        help="Direct mode: action type.")
    parser.add_argument("--recipient", default="",
                        help="Direct mode: recipient address or name.")
    parser.add_argument("--amount", default="",
                        help="Direct mode: payment amount (e.g. $250.00).")
    parser.add_argument("--reason", default="",
                        help="Direct mode: short reason for the request.")
    parser.add_argument("--priority", default="MEDIUM",
                        choices=["HIGH", "MEDIUM", "LOW"],
                        help="Direct mode: priority level.")
    args = parser.parse_args()

    log.info("=" * 62)
    log.info("  Approval Request Generator  —  Gold Tier")
    log.info("  Vault           : %s", VAULT_PATH)
    log.info("  Payment threshold: $%.2f", PAYMENT_THRESHOLD)
    log.info("  Actor           : %s", ACTOR)
    if args.watch:
        log.info("  Mode            : watch (poll every %ds)", POLL_INTERVAL)
    else:
        log.info("  Mode            : single pass")
    log.info("=" * 62)

    seen     = load_seen()
    contacts = load_known_contacts()
    log.info(
        "Known contacts: %d domains, %d addresses.",
        len(contacts.get("domains", [])),
        len(contacts.get("addresses", [])),
    )

    # ── Direct mode ───────────────────────────────────────────────────────────
    if args.action:
        log.info("Direct mode: creating approval request for action='%s'", args.action)
        result = create_direct(
            action    = args.action,
            recipient = args.recipient,
            amount    = args.amount,
            reason    = args.reason or f"Manual {args.action} request",
            priority  = args.priority,
            seen      = seen,
        )
        if result:
            log.info("Created: %s", result.name)
        else:
            log.info("Skipped (duplicate).")
        return

    # ── Scan mode ─────────────────────────────────────────────────────────────
    if args.watch:
        log.info("Watch mode active. Press Ctrl+C to stop.")
        while True:
            try:
                run_once(seen, contacts)
            except Exception as exc:
                log.exception("Unexpected error in watch loop: %s", exc)
            log.info("Next pass in %ds …\n", POLL_INTERVAL)
            time.sleep(POLL_INTERVAL)
    else:
        run_once(seen, contacts)
        log.info("Done.")


if __name__ == "__main__":
    main()
