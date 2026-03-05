# WhatsApp Watcher
**Bronze Tier — AI Employee Agent Skill  (Playwright edition)**

## Purpose
Monitors **WhatsApp Web** via a persistent Playwright Chromium browser.
Scans **unread chats only** for messages that contain any configured trigger
keyword (`urgent`, `asap`, `invoice`, `payment`, `help` by default).
When a match is found an Obsidian-flavoured Markdown action file is written to
`/Needs_Action` and a detection row is appended to `/Dashboard.md`.

---

## Folder Structure
```
WhatsApp_Watcher/
├── whatsapp_watcher.py       ← main script (Playwright)
├── requirements.txt
├── .env.example              ← copy to .env and fill in values
├── .whatsapp_seen.json       ← auto-created; tracks processed sender+date keys
├── README.md                 ← this file
├── logs/                     ← created automatically at runtime
│   └── whatsapp_watcher.log
└── examples/
    └── example_whatsapp_action.md
```

---

## Setup

### 1 · Install dependencies
```bash
cd Skills/WhatsApp_Watcher
pip install -r requirements.txt
playwright install chromium
```

### 2 · Configure `.env`
```bash
cp .env.example .env
# Edit .env — set VAULT_PATH and optionally KEYWORDS, POLL_INTERVAL
```

### 3 · First run — scan the QR code
```bash
python whatsapp_watcher.py
```
A Chromium window opens at **web.whatsapp.com**.
Open WhatsApp on your phone → **Linked Devices → Link a device** → scan the QR.
The browser profile is saved under `PLAYWRIGHT_PROFILE_PATH` so subsequent
runs skip the QR step automatically.

### 4 · Headless mode (optional — after first login)
Set `HEADLESS=true` in `.env` to run without a visible browser window.

---

## Configuration

| Variable                 | Default                          | Description                                      |
|--------------------------|----------------------------------|--------------------------------------------------|
| `VAULT_PATH`             | `../../..`                       | Absolute path to your Obsidian vault root        |
| `KEYWORDS`               | `urgent,asap,invoice,payment,help` | Comma-separated trigger words (case-insensitive) |
| `POLL_INTERVAL`          | `30`                             | Seconds between chat-list scans                  |
| `PLAYWRIGHT_PROFILE_PATH`| `~/.wa_watcher_playwright`       | Where Chromium stores the WA Web session         |
| `HEADLESS`               | `false`                          | Set to `true` to hide the browser window         |

---

## Message Filter

A message is processed **only if both conditions are true**:

| Condition | How it is detected |
|---|---|
| **Unread** | Chat row has a `[data-testid="icon-unread-count"]` badge |
| **Contains keyword** | At least one of the configured `KEYWORDS` appears in the message text (case-insensitive) |

Read chats are entirely skipped — they are never opened or inspected.

---

## Output

### File naming

```
WHATSAPP_<safe_sender>_<YYYYMMDD>.md
```

`<safe_sender>` — the sender's display name with spaces replaced by `_` and
any filesystem-unsafe characters removed.

```
Needs_Action/
└── WHATSAPP_Alice_Johnson_20260224.md
```

### File format

```markdown
---
type: whatsapp
from: Alice Johnson
received: 2026-02-24T09:22:15Z
priority: high
status: pending
---

## Message Content

<plain-text message body>

## Suggested Actions

- [ ] Respond to message
- [ ] Notify human if approval needed
- [ ] Log message in Dashboard.md
```

---

## Duplicate Prevention

**One file per sender per calendar day.**

Processed `<safe_sender>::<YYYYMMDD>` keys are persisted in
`.whatsapp_seen.json` alongside the script. On startup the registry is loaded,
so the watcher never creates a duplicate file even across restarts.

A file is also skipped if `WHATSAPP_<sender>_<YYYYMMDD>.md` already exists
on disk (safety net for a missing registry).

---

## Dashboard Logging

After each new action file is created, a row is appended to the
**Recent Activity** table in `/Dashboard.md`:

```
| <ISO timestamp> | whatsapp_message_detected | WHATSAPP_<sender>_<date>.md | WhatsApp Watcher |
```

---

## How the Scan Works

1. Query all visible chat rows for an unread badge.
2. For each unread chat, open it and read the last 10 incoming messages.
3. If any message contains a keyword, write one action file for that sender
   (capped to one file per sender per day by the dedup registry).
4. Sleep for `POLL_INTERVAL` seconds, then repeat from step 1.

---

## Logging
All activity is written to `logs/whatsapp_watcher.log` and echoed to the terminal.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| QR window closes before scan | Increase `timeout_ms` in `wait_for_chat_list()` (default 120 000 ms) |
| Chat list not found after scan | WA Web may have updated its layout; update `SEL_*` constants at the top of the script |
| No files created for known unread messages | Confirm the message text contains a keyword exactly as listed in `KEYWORDS` |
| `playwright._impl._errors.Error: Executable doesn't exist` | Run `playwright install chromium` |
| Session lost between runs | Check `PLAYWRIGHT_PROFILE_PATH` points to a writable directory |
