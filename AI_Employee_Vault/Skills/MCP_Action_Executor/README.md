# MCP Action Executor
**Gold Tier — AI Employee Agent Skill**

## Purpose
Watches `/Approved` for plan files that have been signed off by a human
operator and executes the corresponding external action via the appropriate
MCP gateway:

| Source type | Gateway | Transport |
|---|---|---|
| `email` | **GmailMCP** | `smtplib` SMTP + App Password |
| `whatsapp` | **WhatsAppMCP** | Playwright browser automation |
| `linkedin` | **LinkedInMCP** | Playwright browser automation |

After execution, results are logged to `/Logs/YYYY-MM-DD.json`, the
Dashboard is updated, and the approved file is moved to `/Done`.

---

## Folder Structure
```
MCP_Action_Executor/
├── action_executor.py        ← main Gold Tier script
├── requirements.txt
├── .env.example              ← copy to .env and fill in credentials
├── .executor_seen.json       ← auto-created; tracks processed file names
├── README.md                 ← this file
├── logs/                     ← created automatically at runtime
│   └── action_executor.log
└── examples/
    ├── example_approved_email.md
    └── example_approved_linkedin.md
```

---

## Setup

### 1 · Install dependencies
```bash
cd Skills/MCP_Action_Executor
pip install -r requirements.txt
playwright install chromium   # only if WhatsApp/LinkedIn dispatch is needed
```

### 2 · Configure `.env`
```bash
cp .env.example .env
# Edit .env — set VAULT_PATH, GMAIL credentials, browser profile paths
```

### 3 · Always start with DRY_RUN
```bash
# In .env: DRY_RUN=true
python action_executor.py
# Verify the log output looks correct before going live
```

### 4 · Go live
```bash
# In .env: DRY_RUN=false
python action_executor.py           # single pass
python action_executor.py --watch   # continuous polling
```

### 5 · Override DRY_RUN from the command line
```bash
python action_executor.py --dry-run   # force DRY_RUN regardless of .env
```

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `VAULT_PATH` | `../../..` | Absolute path to vault root |
| `POLL_INTERVAL` | `30` | Seconds between polls in `--watch` mode |
| `DRY_RUN` | `true` | Log intended actions without sending or moving files |
| `EXECUTOR_ACTOR` | `AI Employee (Gold Tier)` | Name written to logs and Dashboard |
| `GMAIL_USER` | — | Gmail address for email dispatch |
| `GMAIL_APP_PASSWORD` | — | 16-char App Password (not your regular password) |
| `GMAIL_FROM_NAME` | `AI Employee` | Display name in email From: header |
| `WA_PLAYWRIGHT_PROFILE_PATH` | `~/.wa_watcher_playwright` | WhatsApp Web session profile |
| `LI_PLAYWRIGHT_PROFILE_PATH` | `~/.li_watcher_playwright` | LinkedIn session profile |
| `HEADLESS` | `false` | Hide browser windows during dispatch |

---

## How It Works

```
/Approved/*.md
      │
      ▼
 parse front matter
 → source_type, source_file, priority
      │
      ▼
 resolve original source file
 (/Needs_Action → /Done fallback)
 → extract recipient (from: field)
 → extract subject
      │
      ▼
 extract draft reply
 Priority: ## Draft Reply → ## Suggested Reply → generic template
      │
      ├─ DRY_RUN=true? ──► log intended action, skip send
      │
      ▼ (live run)
 MCPGateway.execute()
      ├─ email     → GmailMCP.send(to, subject, body)
      ├─ whatsapp  → WhatsAppMCP.send(contact, message)
      └─ linkedin  → LinkedInMCP.send(contact, message)
      │
      ▼
 post_execute()
      ├─ append to /Logs/YYYY-MM-DD.json
      ├─ update /Dashboard.md  (row + folder counts + metrics)
      ├─ success + live → move approved file to /Done
      └─ save .executor_seen.json
```

---

## Safety Constraints

| Constraint | Implementation |
|---|---|
| Never touch `/Pending_Approval` or `/Needs_Action` | Only `APPROVED` path is read |
| Never double-execute | `.executor_seen.json` tracks processed file names |
| Failed actions stay for retry | File only moves to `/Done` on confirmed success |
| DRY_RUN protection | Checked before every dispatch; CLI flag overrides env |
| Missing recipient → abort | Execution blocked; error logged; file stays in `/Approved` |

---

## Approved File Format

Files in `/Approved` must be plan files containing a `## Draft Reply`
section with the message you want to send.  The front matter must include
`source_type` and `source_file`.

```markdown
---
created: 2026-02-28T10:20:00Z
status: approved
source_file: EMAIL_CABcd1234_mail_gmail_com.md
source_type: email
priority: HIGH
---

## Draft Reply

Dear John,

[Your personalised reply here]

Kind regards,
Your Name
```

If no `## Draft Reply` section is found the executor uses a generic
acknowledgment template and logs a warning.

---

## Log Entry Format

Every execution appends to `/Logs/YYYY-MM-DD.json`:

```json
{
  "timestamp":   "2026-02-28T10:30:00Z",
  "level":       "AUDIT",
  "component":   "ActionExecutor",
  "event":       "action_email_sent",
  "file":        "PLAN_EMAIL_CABcd1234_mail_gmail_com.md",
  "status":      "success",
  "message":     "EMAIL action executed for '...' → sent to 'john@example.com'.",
  "actor":       "AI Employee (Gold Tier)",
  "dry_run":     false,
  "action_type": "email",
  "recipient":   "john@example.com"
}
```

---

## Dashboard Updates

After each execution:
- A `action_<type>_success` or `action_<type>_failed` row is appended to **Recent Activity**
- `/Approved` and `/Done` folder counts are refreshed
- `Completed_Today` (or `Failed_Today`) counter is incremented
- `Last Updated` and `Last Execution` timestamps are refreshed

---

## MCP Extension Points

The three gateway classes (`GmailMCP`, `WhatsAppMCP`, `LinkedInMCP`) are
designed to be swapped out for real MCP server tool calls when available.
Each gateway exposes a single `send(**kwargs) → {"success": bool, ...}` method.

To integrate a real MCP server:
1. Import your MCP client SDK.
2. Replace the method body of the relevant gateway class.
3. Keep the return signature identical — the rest of the pipeline is unchanged.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Recipient address is empty" | Add `to_email: address@example.com` to the approved plan front matter, or verify the source Needs_Action file has a `from:` field |
| `SMTP authentication failed` | Regenerate the Gmail App Password; ensure 2FA is enabled |
| WhatsApp: "No chat found" | The contact name must exactly match the WhatsApp display name; check for typos |
| LinkedIn: "No LinkedIn thread found" | The contact must have an existing message thread; LinkedIn cannot initiate new conversations to unconnected users |
| File not moved to `/Done` | Check logs for error detail; the file stays in `/Approved` for retry |
| Same file executed twice | `.executor_seen.json` may be missing — re-check file permissions |

---

## Logging
All activity is written to `logs/action_executor.log` and echoed to the terminal.
