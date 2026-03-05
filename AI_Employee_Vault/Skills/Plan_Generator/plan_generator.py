#!/usr/bin/env python3
"""
Plan Generator — Silver Tier Agent Skill  (Brain Layer)
========================================================
Reads every unprocessed .md file in /Needs_Action, uses the Claude API
to generate an intelligent, structured action plan, and writes it to
/Plans/PLAN_<source_filename>.md.

Silver Tier enhancements over Bronze
--------------------------------------
- Claude API (claude-haiku-4-5-20251001) generates the Objective, Steps, and
  Approval Required sections intelligently from the source content.
- Falls back to a rule-based engine automatically if ANTHROPIC_API_KEY is
  not set or the API call fails.
- Supports all four watcher output types: email, whatsapp, linkedin, file_drop.
- Reads both new direct-YAML front matter and legacy Markdown-table formats.
- Updates /Dashboard.md after every pass: Plans count, Recent Activity rows,
  and Last Updated timestamp.

Plan file format
----------------
    ---
    created: <ISO timestamp>
    status: pending_approval
    source_file: <original filename>
    source_type: <email|whatsapp|linkedin|file_drop>
    priority: <HIGH|MEDIUM|LOW>
    ---

    ## Objective
    …

    ## Steps
    - [ ] Step 1
    …

    ## Approval Required
    …

Modes
-----
    python plan_generator.py           # single pass then exit
    python plan_generator.py --watch   # poll continuously
"""

import argparse
import json
import logging
import os
import re
import time
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
        logging.FileHandler(LOG_DIR / "plan_generator.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("plan_generator")

# ── Environment ───────────────────────────────────────────────────────────────
_VAULT_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
_SKILL_LOCAL_ENV = Path(__file__).resolve().parent / ".env"
load_dotenv(_VAULT_ROOT_ENV)
load_dotenv(_SKILL_LOCAL_ENV, override=True)

# ── Configuration ─────────────────────────────────────────────────────────────

VAULT_PATH       = Path(os.getenv("VAULT_PATH", str(Path(__file__).parent.parent.parent)))
NEEDS_ACTION     = VAULT_PATH / "Needs_Action"
PLANS            = VAULT_PATH / "Plans"
DASHBOARD        = VAULT_PATH / "Dashboard.md"
POLL_INTERVAL    = int(os.getenv("POLL_INTERVAL", "120"))
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL     = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

# ── Optional Anthropic import ─────────────────────────────────────────────────
try:
    import anthropic as _anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

# ── Priority keyword tables (rule-based fallback) ─────────────────────────────
HIGH_WORDS = {
    "urgent", "asap", "immediately", "critical", "emergency", "overdue",
    "past due", "final notice", "deadline", "breach", "legal", "lawsuit",
    "escalate", "failed", "data loss", "security", "compromised",
    "payment due", "unpaid", "collections", "court",
}
MEDIUM_WORDS = {
    "invoice", "payment", "review", "pending", "follow up", "follow-up",
    "reminder", "confirm", "confirmation", "question", "query", "help",
    "request", "update", "check", "important", "please respond",
    "action required", "response needed", "unread", "awaiting",
    "consulting", "services", "hire", "project", "proposal", "quote",
    "retainer", "contract", "partnership",
}

# Steps that always need explicit human approval
APPROVAL_STEPS = {
    "reply",
    "send",
    "transfer",
    "payment",
    "pay",
    "approve",
    "sign",
    "commit",
    "forward to client",
    "escalate",
    "legal",
    "contract",
}


# ── Timestamp helpers ─────────────────────────────────────────────────────────

def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Front matter & content parsers ───────────────────────────────────────────

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
        key = key.strip()
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1]
            fm[key] = [x.strip().strip("\"'") for x in inner.split(",") if x.strip()]
        else:
            fm[key] = val.strip("\"'")
    return fm


def strip_front_matter(text: str) -> str:
    return re.sub(r"^---\s*\n.*?\n---\s*\n?", "", text, flags=re.DOTALL).strip()


def get_table_field(content: str, field: str) -> str:
    """Extract value from '| **Field** | value |' table rows (legacy format)."""
    pattern = rf"\|\s*\*\*{re.escape(field)}\*\*\s*\|\s*(.+?)\s*\|"
    m = re.search(pattern, content, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # Also match plain '| Field | value |' rows
    pattern2 = rf"\|\s*{re.escape(field)}\s*\|\s*(.+?)\s*\|"
    m2 = re.search(pattern2, content, re.IGNORECASE)
    return m2.group(1).strip() if m2 else ""


def get_blockquote(text: str) -> str:
    lines = [re.sub(r"^>\s?", "", l) for l in text.splitlines() if l.strip().startswith(">")]
    return " ".join(lines).strip()


def parse_sender_display(raw: str) -> str:
    """Extract 'Name' from 'Name <email>' or return raw."""
    m = re.match(r"^(.+?)\s*<[^>]+>$", raw.strip())
    return m.group(1).strip() if m else raw.strip()


def extract_body_text(body: str) -> str:
    """Pull the main readable text from the body of a Needs_Action file."""
    # Strip Markdown headers, tables, checkbox lines, horizontal rules
    lines = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("|"):
            continue
        if stripped.startswith("- [ ]") or stripped.startswith("- [x]"):
            continue
        if re.match(r"^-{3,}$", stripped):
            continue
        if stripped.startswith(">"):
            lines.append(re.sub(r"^>\s?", "", stripped))
            continue
        # Strip leading "> " from blockquote lines already handled
        lines.append(stripped)
    return " ".join(lines).strip()


# ── Metadata extractor ────────────────────────────────────────────────────────

def extract_meta(fm: dict, full_text: str) -> dict:
    """
    Normalise metadata from any Needs_Action format into a consistent dict.

    Handles:
      - New direct-YAML format  (from: / received: / subject: in front matter)
      - Legacy table format     (| **From** | ... | rows in body)
    """
    src_type = fm.get("type", "unknown")
    body     = strip_front_matter(full_text)

    # ── Sender ────────────────────────────────────────────────────────────────
    sender = (
        fm.get("from")
        or get_table_field(full_text, "From")
        or get_table_field(full_text, "Sender")
        or "Unknown"
    ).strip()

    # ── Subject / topic ───────────────────────────────────────────────────────
    subject = (
        fm.get("subject")
        or get_table_field(full_text, "Subject")
        or ""
    ).strip()

    # ── Received timestamp ────────────────────────────────────────────────────
    received = (
        fm.get("received")
        or get_table_field(full_text, "Received")
        or fm.get("created")
        or utc_now()
    ).strip()

    # ── Platform ──────────────────────────────────────────────────────────────
    platform = fm.get("platform", fm.get("source", src_type))

    # ── Main content text ─────────────────────────────────────────────────────
    content_text = extract_body_text(body)

    return {
        "type":     src_type,
        "sender":   sender,
        "subject":  subject,
        "received": received,
        "platform": platform,
        "content":  content_text,
    }


# ── Priority detector ─────────────────────────────────────────────────────────

def detect_priority(fm: dict, full_text: str) -> str:
    """Return 'HIGH', 'MEDIUM', or 'LOW' based on keyword presence."""
    lower = full_text.lower()
    # Respect explicit priority from frontmatter
    explicit = fm.get("priority", "").upper()
    if explicit in ("HIGH", "MEDIUM", "LOW"):
        return explicit
    if any(w in lower for w in HIGH_WORDS):
        return "HIGH"
    if any(w in lower for w in MEDIUM_WORDS):
        return "MEDIUM"
    return "LOW"


# ── Claude API plan generation ────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a Silver Tier AI business assistant embedded inside an Obsidian vault.
Your role is to analyse incoming action items (emails, WhatsApp messages,
LinkedIn messages, and file drops) and produce concise, unambiguous action plans.

Respond with ONLY a valid JSON object — no markdown fences, no extra text.
The object must have exactly these three keys:

{
  "objective": "<1-2 sentence description of the main goal>",
  "steps": [
    "<Step 1: specific, actionable instruction>",
    "<Step 2: …>",
    … (3–7 steps total)
  ],
  "approval_required": "<Which steps need human review/approval and why. If none, say 'No approval required.'>"
}

Rules for steps:
- Begin each step with a strong verb (Reply, Verify, Forward, Review, …).
- Reference the sender by name when known.
- Be specific: include timeframes for HIGH priority items.
- Do not include vague steps like 'Handle the matter'.
- Last step is always: 'Move source file to /Done once fully resolved.'
"""


def call_claude_api(meta: dict, full_text: str) -> dict | None:
    """
    Call the Claude API to generate plan content.
    Returns {'objective': ..., 'steps': [...], 'approval_required': ...}
    or None on failure.
    """
    if not _ANTHROPIC_AVAILABLE or not ANTHROPIC_API_KEY:
        return None

    type_label = {
        "email":     "email message",
        "whatsapp":  "WhatsApp message",
        "linkedin":  "LinkedIn message or comment",
        "file_drop": "file drop",
    }.get(meta["type"], "action item")

    user_message = (
        f"Analyse this {type_label} and generate an action plan.\n\n"
        f"--- SOURCE ITEM ---\n{full_text}\n--- END ---"
    )

    try:
        client = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=800,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = response.content[0].text.strip()
        # Strip any accidental markdown fences
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        # Validate expected keys
        if all(k in data for k in ("objective", "steps", "approval_required")):
            return data
        log.warning("Claude response missing required keys — falling back.")
        return None
    except Exception as exc:
        log.warning("Claude API call failed (%s) — using rule-based fallback.", exc)
        return None


# ── Rule-based fallback plan generation ───────────────────────────────────────

def fallback_objective(meta: dict) -> str:
    src = meta["type"]
    sender  = meta["sender"]
    subject = meta["subject"]

    if src == "email":
        subj_part = f' regarding "{subject}"' if subject else ""
        return (
            f'Respond to an email from {sender}{subj_part} '
            f'received on {meta["received"]}.'
        )
    if src == "whatsapp":
        return (
            f'Address an urgent WhatsApp message from {sender} '
            f'received on {meta["received"]}.'
        )
    if src == "linkedin":
        return (
            f'Follow up on a LinkedIn enquiry from {sender} '
            f'about your business services, received on {meta["received"]}.'
        )
    if src == "file_drop":
        return f'Review and process the file dropped by {sender}.'
    return f'Action the item from {sender} received on {meta["received"]}.'


def fallback_steps(meta: dict, priority: str) -> list[str]:
    src      = meta["type"]
    sender   = parse_sender_display(meta["sender"])
    subject  = meta["subject"]
    timeframe = (
        "within 4 hours" if priority == "HIGH"
        else "within 24 hours" if priority == "MEDIUM"
        else "within 48 hours"
    )

    if src == "email":
        steps = [
            f'Verify the identity and context of the sender ({sender}).',
            f'Review the full email body for any attachments, deadlines, or figures.',
            f'Reply to {sender} {timeframe}'
            + (f' regarding: "{subject}"' if subject else ""),
            'If financial or contractual — obtain written approval before committing.',
            'Forward to the relevant team member if you are not the right owner.',
            'Move source file to /Done once fully resolved.',
        ]
        if priority == "HIGH":
            steps.insert(0, f'URGENT: Escalate to a manager immediately if you cannot personally respond {timeframe}.')
        return steps

    if src == "whatsapp":
        return [
            f'Review the full WhatsApp message from {sender}.',
            f'Reply to {sender} on WhatsApp {timeframe}.',
            'If the matter involves money or a commitment — escalate for human approval first.',
            'Follow up with a call if no reply is received within 1 hour.',
            'Move source file to /Done once the conversation is resolved.',
        ]

    if src == "linkedin":
        return [
            f'Review the LinkedIn enquiry from {sender}.',
            f'Prepare a personalised response addressing their specific interest.',
            f'Reply via LinkedIn {timeframe}.',
            'Add {sender} to your CRM with relevant tags (lead, enquiry date, topic).',
            'If the enquiry leads to a proposal — route to Pending_Approval for human sign-off.',
            'Move source file to /Done once the contact has been actioned.',
        ]

    if src == "file_drop":
        return [
            f'Open and read the dropped file from {sender}.',
            'Determine the correct handling procedure for this file type.',
            'File it in the appropriate project or client folder.',
            'Complete any tasks or follow-ups the file requires.',
            'Move source file to /Done once all actions are complete.',
        ]

    return [
        'Review the source item for full context.',
        'Identify the required action and the correct owner.',
        'Complete the required action.',
        'Document any decisions or outcomes in the Notes section.',
        'Move source file to /Done when resolved.',
    ]


def fallback_approval(meta: dict, steps: list[str]) -> str:
    content_lower = (meta["content"] + " ".join(steps)).lower()
    triggers = [w for w in APPROVAL_STEPS if w in content_lower]
    if not triggers:
        return "No approval required — this item can be self-managed."
    items = []
    for step in steps:
        if any(t in step.lower() for t in triggers):
            items.append(f'- "{step}"')
    if items:
        return (
            "Human approval required before completing the following steps "
            f"(involves: {', '.join(triggers)}):\n" + "\n".join(items)
        )
    return "No approval required — this item can be self-managed."


def generate_plan_content(meta: dict, full_text: str, priority: str) -> dict:
    """
    Return {'objective': str, 'steps': list[str], 'approval_required': str}.
    Tries Claude API first; falls back to rule-based if unavailable or failing.
    """
    if ANTHROPIC_API_KEY:
        result = call_claude_api(meta, full_text)
        if result:
            log.info("Plan content generated via Claude API.")
            return result
        log.info("Falling back to rule-based plan generation.")

    steps    = fallback_steps(meta, priority)
    return {
        "objective":         fallback_objective(meta),
        "steps":             steps,
        "approval_required": fallback_approval(meta, steps),
    }


# ── Dashboard updater ─────────────────────────────────────────────────────────

def update_dashboard(created_plans: list[str]) -> None:
    """
    Update Dashboard.md:
    - Append one Recent Activity row per new plan.
    - Refresh Last Updated timestamp.
    - Update Plans folder count.
    """
    if not DASHBOARD.exists():
        log.warning("Dashboard.md not found — skipping dashboard update.")
        return

    text = DASHBOARD.read_text(encoding="utf-8")
    now  = utc_now()

    # ── Append activity rows ───────────────────────────────────────────────────
    rows = "\n".join(
        f"| {now} | plan_generated | {p} | Plan Generator (Silver) |"
        for p in created_plans
    )
    sentinel = "---\n\n## Flags & Alerts"
    if sentinel in text:
        text = text.replace(sentinel, f"{rows}\n\n---\n\n## Flags & Alerts")
    else:
        text = text.rstrip() + f"\n\n{rows}\n"

    # ── Refresh Plans folder count ─────────────────────────────────────────────
    plan_count = sum(1 for f in PLANS.iterdir() if f.is_file()) if PLANS.exists() else 0
    text = re.sub(
        r"(\| Plans \| )\d+( \| )(.+?)( \|)",
        rf"\g<1>{plan_count}\g<2>{now}\g<4>",
        text,
    )

    # ── Refresh Last Updated + Last Execution ─────────────────────────────────
    text = re.sub(r"\*\*Last Updated:\*\* .+", f"**Last Updated:** {now}", text)
    text = re.sub(
        r"(\| Last Execution \| )(.+?)( \|)",
        rf"\g<1>{now}\g<3>",
        text,
    )

    DASHBOARD.write_text(text, encoding="utf-8")
    log.info("Dashboard updated — %d new plan(s) logged.", len(created_plans))


# ── Plan file writer ──────────────────────────────────────────────────────────

def write_plan(source_path: Path) -> Path:
    """
    Parse source_path, call plan generator, write /Plans/PLAN_<name>.md.
    Returns the path of the created plan file.
    """
    PLANS.mkdir(parents=True, exist_ok=True)

    full_text = source_path.read_text(encoding="utf-8")
    fm        = parse_front_matter(full_text)
    meta      = extract_meta(fm, full_text)
    priority  = detect_priority(fm, full_text)
    plan_data = generate_plan_content(meta, full_text, priority)

    plan_path = PLANS / f"PLAN_{source_path.name}"
    now_iso   = utc_now()

    # Build Steps checklist
    steps_block = "\n".join(f"- [ ] {s}" for s in plan_data["steps"])

    # Priority badge
    badge = {"HIGH": "🔴 HIGH", "MEDIUM": "🟡 MEDIUM", "LOW": "🟢 LOW"}.get(
        priority, priority
    )

    md = f"""---
created: {now_iso}
status: pending_approval
source_file: {source_path.name}
source_type: {meta['type']}
priority: {priority}
---

# Plan — {source_path.stem}

> **Priority:** {badge}  |  **Source:** `{source_path.name}`  |  **From:** {meta['sender']}

## Objective

{plan_data['objective']}

## Steps

{steps_block}

## Approval Required

{plan_data['approval_required']}

---

*Auto-generated by Plan Generator (Silver Tier) · {now_iso}*
"""

    plan_path.write_text(md, encoding="utf-8")
    log.info("Plan written  [%s]  →  %s", priority, plan_path.name)
    return plan_path


# ── Processor ─────────────────────────────────────────────────────────────────

def already_planned(source_path: Path) -> bool:
    return (PLANS / f"PLAN_{source_path.name}").exists()


def run_once() -> int:
    """
    Process all unplanned .md files in /Needs_Action.
    Returns the count of plans created.
    """
    if not NEEDS_ACTION.exists():
        log.warning("Needs_Action folder not found: %s", NEEDS_ACTION)
        return 0

    candidates = sorted(NEEDS_ACTION.glob("*.md"))
    if not candidates:
        log.info("No .md files found in Needs_Action.")
        return 0

    log.info("Found %d .md file(s) in Needs_Action.", len(candidates))

    created_plans: list[str] = []
    for md_path in candidates:
        if already_planned(md_path):
            log.debug("Already planned, skipping: %s", md_path.name)
            continue
        try:
            plan_path = write_plan(md_path)
            created_plans.append(plan_path.name)
        except Exception as exc:
            log.error("Failed to plan %s: %s", md_path.name, exc, exc_info=True)

    if created_plans:
        update_dashboard(created_plans)

    log.info("Plans created this pass: %d", len(created_plans))
    return len(created_plans)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plan Generator — Silver Tier Brain Layer"
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Poll Needs_Action continuously instead of running once.",
    )
    args = parser.parse_args()

    engine = (
        f"Claude API ({CLAUDE_MODEL})"
        if (_ANTHROPIC_AVAILABLE and ANTHROPIC_API_KEY)
        else "rule-based fallback (set ANTHROPIC_API_KEY to enable AI)"
    )

    log.info("=" * 62)
    log.info("  Plan Generator  —  Silver Tier Brain Layer")
    log.info("  Vault         : %s", VAULT_PATH)
    log.info("  Needs_Action  : %s", NEEDS_ACTION)
    log.info("  Plans         : %s", PLANS)
    log.info("  Engine        : %s", engine)
    if args.watch:
        log.info("  Mode          : watch (poll every %ds)", POLL_INTERVAL)
    else:
        log.info("  Mode          : single pass")
    log.info("=" * 62)

    if args.watch:
        log.info("Watch mode active. Press Ctrl+C to stop.")
        while True:
            try:
                run_once()
            except Exception as exc:
                log.exception("Unexpected error in watch loop: %s", exc)
            log.info("Next pass in %ds …\n", POLL_INTERVAL)
            time.sleep(POLL_INTERVAL)
    else:
        run_once()
        log.info("Done.")


if __name__ == "__main__":
    main()
