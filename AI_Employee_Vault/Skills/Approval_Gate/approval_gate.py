#!/usr/bin/env python3
"""
Silver Tier Approval Gate

Scans /Plans for HIGH-priority email plans with status: pending_approval
and creates concise approval request files in /Pending_Approval.

Criteria --ALL three must match:
  • status: pending_approval
  • priority: HIGH
  • source_type: email

Usage:
  python approval_gate.py            # single pass
  python approval_gate.py --watch    # continuous polling
"""

import os
import re
import json
import time
import logging
import argparse
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
    _VAULT_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
    _SKILL_LOCAL_ENV = Path(__file__).resolve().parent / ".env"
    load_dotenv(_VAULT_ROOT_ENV)
    load_dotenv(_SKILL_LOCAL_ENV, override=True)
except ImportError:
    pass  # python-dotenv optional; set env vars manually or via shell

# ── Config ────────────────────────────────────────────────────────────────────

VAULT_PATH      = Path(os.getenv(
    "VAULT_PATH",
    str(Path(__file__).resolve().parent.parent.parent),
)).resolve()
POLL_INTERVAL   = int(os.getenv("POLL_INTERVAL", "60"))
GATE_ACTOR      = os.getenv("GATE_ACTOR", "Approval Gate (Silver Tier)")

PLANS_DIR       = VAULT_PATH / "Plans"
PENDING_DIR     = VAULT_PATH / "Pending_Approval"
NEEDS_ACTION_DIR = VAULT_PATH / "Needs_Action"
DASHBOARD_PATH  = VAULT_PATH / "Dashboard.md"
LOGS_DIR        = VAULT_PATH / "Logs"

# ── Logging ───────────────────────────────────────────────────────────────────
_log_dir = Path(__file__).parent / "logs"
_log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(_log_dir / "approval_gate.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("ApprovalGate")


# ── Frontmatter helpers ───────────────────────────────────────────────────────
def parse_frontmatter(text: str) -> dict:
    """Return YAML frontmatter fields as a dict (empty dict if absent)."""
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}
    fm: dict = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip()
    return fm


# ── Recipient resolution ──────────────────────────────────────────────────────
def extract_recipient(plan_path: Path, source_file: str) -> str:
    """
    Resolve recipient email in priority order:
      1. `from:` frontmatter of the source Needs_Action file
      2. `**From:** email` in the plan's header callout line
      3. First email-looking string in the plan Objective paragraph
      4. Fallback: "unknown"
    """
    # 1. Source file frontmatter
    if source_file:
        src = NEEDS_ACTION_DIR / source_file
        if src.exists():
            fm = parse_frontmatter(src.read_text(encoding="utf-8"))
            if fm.get("from"):
                return fm["from"].strip()

    plan_text = plan_path.read_text(encoding="utf-8")

    # 2. Header callout: > **Priority:** ... | **From:** client@example.com
    m = re.search(r"\*\*From:\*\*\s*`?([^\s`|]+@[^\s`|]+)`?", plan_text)
    if m:
        return m.group(1).strip()

    # 3. Any email in the Objective section
    m = re.search(
        r"(?:email from|reply to|respond to)\s+([\w._%+\-]+@[\w.\-]+\.[a-zA-Z]{2,})",
        plan_text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    return "unknown"


def extract_subject(source_file: str) -> str:
    """Pull the email subject from the Needs_Action source file."""
    if not source_file:
        return ""
    src = NEEDS_ACTION_DIR / source_file
    if not src.exists():
        return ""
    fm = parse_frontmatter(src.read_text(encoding="utf-8"))
    raw = fm.get("subject", "").strip()
    if not raw:
        return ""
    return raw if raw.lower().startswith("re:") else f"Re: {raw}"


def extract_draft(plan_path: Path) -> str:
    """
    Extract draft reply text from the plan body.
    Checks ## Draft Reply, ## Suggested Reply, ## Reply in order.
    Returns empty string if none found.
    """
    text = plan_path.read_text(encoding="utf-8")
    # Strip frontmatter
    body = re.sub(r"^---\s*\n.*?\n---\s*\n?", "", text, flags=re.DOTALL).strip()
    for heading in ("Draft Reply", "Suggested Reply", "Reply"):
        pattern = rf"##\s+{re.escape(heading)}\s*\n(.*?)(?=\n##\s|\Z)"
        m = re.search(pattern, body, re.DOTALL | re.IGNORECASE)
        if m and m.group(1).strip():
            content = m.group(1).strip()
            content = re.sub(r"^```[^\n]*\n", "", content)
            content = re.sub(r"\n```$", "", content)
            return content.strip()
    return ""


# ── Duplicate guard ───────────────────────────────────────────────────────────
def approval_exists(source_plan_name: str) -> bool:
    """Return True if a pending approval for this source_plan is already in /Pending_Approval."""
    PENDING_DIR.mkdir(exist_ok=True)
    for f in PENDING_DIR.glob("APPROVAL_*.md"):
        try:
            fm = parse_frontmatter(f.read_text(encoding="utf-8"))
            if fm.get("source_plan") == source_plan_name and fm.get("status") == "pending":
                return True
        except Exception:
            pass
    return False


# ── File writer ───────────────────────────────────────────────────────────────
def write_approval(
    plan_path: Path,
    *,
    recipient: str,
    source_file: str,
    source_type: str,
    priority: str,
    subject: str,
    draft_reply: str,
) -> Path:
    """Write APPROVAL_<plan_stem>_<YYYYMMDD_HHMMSS>.md to /Pending_Approval.

    Frontmatter is fully compatible with MCP Action Executor's
    ``build_action_packet()`` so the file can be moved straight to
    /Approved and executed without manual edits.
    """
    now = datetime.now(timezone.utc)
    ts_file    = now.strftime("%Y%m%d_%H%M%S")
    ts_iso     = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    filename   = f"APPROVAL_{plan_path.stem}_{ts_file}.md"
    out_path   = PENDING_DIR / filename

    PENDING_DIR.mkdir(exist_ok=True)

    # ── Frontmatter (executor-compatible) ────────────────────────────────
    # Expiry: 24 hours from creation
    from datetime import timedelta
    expires_dt = now + timedelta(hours=24)
    expires_iso = expires_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    fm_lines = [
        "---",
        "type: approval_request",
        "action: send_email",
        f"source_type: {source_type}",
        f"source_file: {source_file}",
        f"to_email: {recipient}",
        f"subject: {subject}",
        f"source_plan: {plan_path.name}",
        f"priority: {priority}",
        f"created: {ts_iso}",
        f"expires: {expires_iso}",
        f"reason: High-priority {source_type} response requires human approval",
        "status: pending",
        "---",
    ]

    # ── Body ─────────────────────────────────────────────────────────────
    body_lines = [
        "",
        "## Reason",
        "",
        "High-priority email response requires human approval before execution.",
        "",
    ]

    if draft_reply:
        body_lines += [
            "## Draft Reply",
            "",
            draft_reply,
            "",
        ]

    body_lines += [
        "## To Approve",
        "",
        "Move this file to /Approved folder.",
        "",
        "## To Reject",
        "",
        "Move this file to /Rejected folder.",
        "",
        "---",
        "",
        f"*Auto-generated by {GATE_ACTOR} - {ts_iso}*",
    ]

    content = "\n".join(fm_lines + body_lines) + "\n"
    out_path.write_text(content, encoding="utf-8")
    log.info("Approval request written: %s", filename)
    return out_path


# ── Dashboard update ──────────────────────────────────────────────────────────
def update_dashboard(filename: str) -> None:
    """Insert a Recent Activity row and refresh Last Updated / Pending_Approval count."""
    if not DASHBOARD_PATH.exists():
        return

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    text = DASHBOARD_PATH.read_text(encoding="utf-8")

    # Bump Pending_Approval count
    text = re.sub(
        r"(\| Pending_Approval \| )(\d+)( \|)",
        lambda m: f"{m.group(1)}{int(m.group(2)) + 1}{m.group(3)}",
        text,
    )

    # Refresh Last Updated timestamp
    text = re.sub(
        r"\*\*Last Updated:\*\*.*",
        f"**Last Updated:** {now}",
        text,
    )

    # Insert activity row before the sentinel
    new_row = f"\n| {now} | approval_request_created | {filename} | {GATE_ACTOR} |\n"
    sentinel = "---\n\n## Flags & Alerts"
    if sentinel in text:
        text = text.replace(sentinel, new_row + sentinel)
    else:
        text += new_row

    DASHBOARD_PATH.write_text(text, encoding="utf-8")
    log.info("Dashboard updated")


# ── Vault log ─────────────────────────────────────────────────────────────────
def vault_log(filename: str, recipient: str, source_plan: str) -> None:
    """Append an AUDIT entry to /Logs/YYYY-MM-DD.json."""
    LOGS_DIR.mkdir(exist_ok=True)
    today    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_file = LOGS_DIR / f"{today}.json"

    if log_file.exists():
        try:
            data = json.loads(log_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {"log_date": today, "tier": "Gold", "entries": []}
    else:
        data = {"log_date": today, "tier": "Gold", "entries": []}

    # Ensure 'entries' key exists (guards against malformed log files)
    if "entries" not in data or not isinstance(data.get("entries"), list):
        data["entries"] = []

    entry = {
        "timestamp":   datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "level":       "AUDIT",
        "component":   "ApprovalGate",
        "event":       "approval_request_created",
        "file":        filename,
        "source_plan": source_plan,
        "recipient":   recipient,
        "status":      "success",
        "actor":       GATE_ACTOR,
    }

    data["entries"].append(entry)
    log_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── Core scan ─────────────────────────────────────────────────────────────────
def scan_plans() -> int:
    """
    Scan /Plans for qualifying plans and create approval requests.
    Returns the count of new approvals created in this pass.
    """
    if not PLANS_DIR.exists():
        log.error("Plans folder not found: %s", PLANS_DIR)
        return 0

    created = 0

    for plan_path in sorted(PLANS_DIR.glob("PLAN_*.md")):
        try:
            fm = parse_frontmatter(plan_path.read_text(encoding="utf-8"))

            # ── Filter: all three criteria must match ──────────────────────────
            if fm.get("status") != "pending_approval":
                continue
            if fm.get("priority", "").upper() != "HIGH":
                continue
            if fm.get("source_type", "").lower() != "email":
                continue

            # ── Duplicate guard ────────────────────────────────────────────────
            if approval_exists(plan_path.name):
                log.debug("Open approval already exists for %s --skipping", plan_path.name)
                continue

            # ── Gather metadata for executor-compatible output ────────────────
            source_file = fm.get("source_file", "")
            source_type = fm.get("source_type", "email").lower()
            priority    = fm.get("priority", "MEDIUM").upper()
            recipient   = extract_recipient(plan_path, source_file)
            subject     = extract_subject(source_file)
            draft_reply = extract_draft(plan_path)

            if recipient == "unknown":
                log.warning(
                    "Could not resolve recipient for %s -- "
                    "approval will need manual to_email before execution",
                    plan_path.name,
                )

            # ── Write approval file ────────────────────────────────────────────
            out_path = write_approval(
                plan_path,
                recipient=recipient,
                source_file=source_file,
                source_type=source_type,
                priority=priority,
                subject=subject,
                draft_reply=draft_reply,
            )

            # ── Side-effects ───────────────────────────────────────────────────
            update_dashboard(out_path.name)
            vault_log(out_path.name, recipient, plan_path.name)

            log.info(
                "Approval created for '%s' -> recipient: %s",
                plan_path.name,
                recipient,
            )
            created += 1

        except Exception as exc:
            log.error("Error processing %s: %s", plan_path.name, exc, exc_info=True)

    log.info("Scan complete -- %d new approval request(s) created", created)
    return created


# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Silver Tier Approval Gate --scans /Plans and creates approval requests"
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Run continuously, polling every POLL_INTERVAL seconds",
    )
    args = parser.parse_args()

    log.info("Approval Gate starting -- vault: %s", VAULT_PATH)

    if args.watch:
        while True:
            scan_plans()
            log.info("Next scan in %d seconds ...", POLL_INTERVAL)
            time.sleep(POLL_INTERVAL)
    else:
        scan_plans()


if __name__ == "__main__":
    main()
