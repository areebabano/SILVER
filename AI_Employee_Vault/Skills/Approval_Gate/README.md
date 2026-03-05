# Approval Gate
**Silver Tier — AI Employee Agent Skill**

## Purpose

Scans `/Plans` for high-priority email plans awaiting human review and writes
concise approval request files to `/Pending_Approval`.

A plan qualifies when **all three** conditions are true:

| Field | Required Value |
|---|---|
| `status` | `pending_approval` |
| `priority` | `HIGH` |
| `source_type` | `email` |

---

## Folder Structure

```
Approval_Gate/
├── approval_gate.py    ← main script
├── requirements.txt
├── .env.example        ← copy to .env
├── README.md           ← this file
└── logs/               ← auto-created
    └── approval_gate.log
```

---

## Setup

```bash
cd Skills/Approval_Gate
pip install -r requirements.txt
cp .env.example .env
# Edit .env — set VAULT_PATH
```

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `VAULT_PATH` | `../../..` | Absolute path to vault root |
| `POLL_INTERVAL` | `60` | Seconds between passes in `--watch` mode |
| `GATE_ACTOR` | `Approval Gate (Silver Tier)` | Name in logs + Dashboard |

---

## Usage

```bash
python approval_gate.py           # single pass
python approval_gate.py --watch   # continuous polling
```

---

## Output File Format

```
Pending_Approval/
└── APPROVAL_PLAN_EMAIL_TEST_SILVER_20260301_120000.md
```

### Frontmatter

```yaml
---
type: approval_request
action: send_email
recipient: client@example.com
source_plan: PLAN_EMAIL_TEST_SILVER.md
created: 2026-03-01T12:00:00Z
status: pending
---
```

### Sections

| Section | Content |
|---|---|
| `## Reason` | Single sentence explaining why approval is required |
| `## To Approve` | Move this file to `/Approved` folder |
| `## To Reject` | Move this file to `/Rejected` folder |

---

## Duplicate Prevention

Before creating a new approval file, the script scans `/Pending_Approval` for
any existing file whose frontmatter has:
- `source_plan` matching the current plan filename, **and**
- `status: pending`

If found, the plan is skipped for this pass.

---

## Pipeline Integration

```
/Plans/PLAN_*.md   (status: pending_approval, priority: HIGH, source_type: email)
       │
       ▼  (Approval Gate scans on every pass)
/Pending_Approval/APPROVAL_*.md   (status: pending)
       │
       │  Human operator reviews
       ├──► Move to /Approved  + add ## Draft Reply in source plan
       └──► Move to /Rejected  + optional rejection note
       │
       ▼  (MCP Action Executor polls /Approved)
  Send email → move plan to /Done
```

---

## Dashboard & Logs

- `Dashboard.md` — **Recent Activity** row added per approval request; Pending_Approval count incremented; Last Updated refreshed
- `/Logs/YYYY-MM-DD.json` — AUDIT entry per request: `{timestamp, level, component, event, file, source_plan, recipient, status, actor}`

---

## Troubleshooting

| Problem | Fix |
|---|---|
| No approvals created | Check that plan frontmatter has all three required fields (status/priority/source_type) |
| Duplicate approval created | Verify `.md` frontmatter `status` is not already `approved` or `rejected` |
| "Plans folder not found" | Check `VAULT_PATH` in `.env` |
| Recipient shows "unknown" | Ensure source Needs_Action file exists and has `from:` frontmatter field |
