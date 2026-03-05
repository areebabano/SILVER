# LinkedIn Watcher
**Bronze Tier — AI Employee Agent Skill  (Playwright edition)**

## Purpose
Monitors two LinkedIn surfaces for new activity mentioning your business
services:

| Surface | URL | What is detected |
|---|---|---|
| **Direct messages** | `/messaging/` | Unread threads containing service keywords |
| **Post comments** | `/notifications/` | Unread comment notifications containing service keywords |

For every match an Obsidian-flavoured Markdown action file is written to
`/Needs_Action` and a row is appended to `/Dashboard.md`.

---

## Folder Structure
```
LinkedIn_Watcher/
├── linkedin_watcher.py        ← main script (Playwright)
├── requirements.txt
├── .env.example               ← copy to .env and fill in values
├── .linkedin_seen.json        ← auto-created; tracks processed sender+date keys
├── README.md                  ← this file
├── logs/                      ← created automatically at runtime
│   └── linkedin_watcher.log
└── examples/
    └── example_linkedin_action.md
```

---

## Setup

### 1 · Install dependencies
```bash
cd Skills/LinkedIn_Watcher
pip install -r requirements.txt
playwright install chromium
```

### 2 · Configure `.env`
```bash
cp .env.example .env
# Edit .env — set VAULT_PATH and your SERVICE_KEYWORDS
```

### 3 · First run — log in manually
```bash
python linkedin_watcher.py
```
A Chromium window opens at **linkedin.com**.
Log in with your LinkedIn credentials.
Once your feed is visible the watcher begins scanning automatically.

The session is saved to `PLAYWRIGHT_PROFILE_PATH` — subsequent runs
skip the login step entirely.

### 4 · Headless mode (optional — after first login)
Set `HEADLESS=true` in `.env` to run without a visible browser window.

---

## Configuration

| Variable                  | Default       | Description                                                        |
|---------------------------|---------------|--------------------------------------------------------------------|
| `VAULT_PATH`              | `../../..`    | Absolute path to your Obsidian vault root                          |
| `POLL_INTERVAL`           | `60`          | Seconds between scan cycles                                        |
| `PLAYWRIGHT_PROFILE_PATH` | `~/.li_watcher_playwright` | Where Chromium stores the LinkedIn session        |
| `HEADLESS`                | `false`       | Set `true` to hide the browser after first login                   |
| `LOGIN_TIMEOUT_SECONDS`   | `120`         | Time allowed for manual login on first run                         |
| `SERVICE_KEYWORDS`        | *(see below)* | Comma-separated words that flag a business enquiry (case-insensitive) |

**Default SERVICE_KEYWORDS:**
```
consulting, services, hire, project, proposal, quote, retainer, contract,
partnership, collaboration, work together, offer, pricing, rates,
available, freelance, agency, solution
```
Add your own service or product names to this list.

---

## How the Scan Works

```
Every POLL_INTERVAL seconds:

  ┌─ 1. linkedin.com/messaging/ ─────────────────────────────────┐
  │  • Find all unread thread rows                                │
  │  • Open each thread, read the last 10 message bubbles        │
  │  • If any bubble contains a SERVICE_KEYWORD → write file     │
  └───────────────────────────────────────────────────────────────┘
                          ↓
  ┌─ 2. linkedin.com/notifications/ ─────────────────────────────┐
  │  • Find all unread notification items                        │
  │  • If notification text contains a SERVICE_KEYWORD → write file │
  └───────────────────────────────────────────────────────────────┘
```

Read messages/notifications are **never opened or inspected**.

---

## Output

### File naming

| Source | Filename pattern |
|---|---|
| Direct message | `LINKEDIN_<safe_sender>_<YYYYMMDD>.md` |
| Post comment | `LINKEDIN_<safe_sender>_CMT_<YYYYMMDD>.md` |

`<safe_sender>` — display name with spaces replaced by `_` and unsafe
characters removed.

```
Needs_Action/
├── LINKEDIN_Sarah_Chen_20260228.md         ← from a direct message
└── LINKEDIN_Marcus_Lee_CMT_20260228.md     ← from a comment notification
```

### File format

```markdown
---
type: linkedin
from: Sarah Chen
received: 2026-02-28T10:15:30Z
platform: linkedin
priority: medium
status: pending
---

## Message Content

<plain-text message or comment body>

## Suggested Actions

- [ ] Reply to message
- [ ] Add contact to CRM
- [ ] Archive after processing
```

---

## Duplicate Prevention

**One file per sender per source per calendar day.**

Dedup keys follow the pattern `<safe_sender>::<source>::<YYYYMMDD>` and are
persisted in `.linkedin_seen.json` alongside the script. On startup the
registry is loaded so no duplicate is ever created across restarts.

A file is also skipped if `LINKEDIN_<sender>_<date>.md` already exists
on disk (safety net for a missing or corrupt registry).

---

## Dashboard Logging

After each new action file is created, a row is appended to the
**Recent Activity** table in `/Dashboard.md`:

```
| <ISO timestamp> | linkedin_message_detected | LINKEDIN_Sarah_Chen_20260228.md | LinkedIn Watcher |
| <ISO timestamp> | linkedin_comment_detected | LINKEDIN_Marcus_Lee_CMT_20260228.md | LinkedIn Watcher |
```

---

## Selector Reference

LinkedIn's DOM changes periodically. All CSS selectors are defined as
named constants at the top of `linkedin_watcher.py` — update them there
if the watcher stops detecting items after a LinkedIn UI update.

| Constant | Target element |
|---|---|
| `SEL_MSG_FEED` | Messaging thread list container |
| `SEL_MSG_UNREAD` | Unread thread row |
| `SEL_MSG_NAME` | Sender name inside a thread row |
| `SEL_MSG_SNIPPET` | Preview text in the thread list |
| `SEL_MSG_BUBBLE` | Individual message bubble inside an open thread |
| `SEL_NOTIF_FEED` | Notifications list container |
| `SEL_NOTIF_ITEM` | Individual notification row |
| `SEL_NOTIF_UNREAD` | Unread notification row |
| `SEL_NOTIF_ACTOR` | Actor (commenter) name inside a notification |
| `SEL_NOTIF_TEXT` | Full notification text |

---

## Logging
All activity is written to `logs/linkedin_watcher.log` and echoed to the terminal.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Login window times out | Increase `LOGIN_TIMEOUT_SECONDS` in `.env` |
| Messaging feed not loading | LinkedIn may require a brief pause — increase `wait_for_timeout` delays in script |
| No files created despite matching messages | Confirm the message contains a word from `SERVICE_KEYWORDS` (check log for "No service keywords") |
| Selectors return empty results | LinkedIn updated its DOM — update `SEL_*` constants at top of script |
| Session lost between runs | Check `PLAYWRIGHT_PROFILE_PATH` points to a writable, persistent directory |
| `playwright._impl._errors.Error: Executable doesn't exist` | Run `playwright install chromium` |

> **Note:** LinkedIn's bot detection is active.
> The watcher uses a real user-agent, disables the `AutomationControlled`
> feature flag, and adds realistic wait times between actions.
> If you see CAPTCHA or "Suspicious activity" prompts, reduce `POLL_INTERVAL`
> or switch to manual headful mode (`HEADLESS=false`).
