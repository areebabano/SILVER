# Gmail Watcher
**Bronze Tier — AI Employee Agent Skill**

## Purpose
Monitors your Gmail inbox via IMAP for messages that are **unread AND marked
Important**, then automatically creates Obsidian-flavoured Markdown action files
in `/Needs_Action`. Each new file is also logged in `/Dashboard.md` under
**Recent Activity**.

---

## Folder Structure
```
Gmail_Watcher/
├── gmail_watcher.py        ← main script
├── requirements.txt
├── .env.example            ← copy to .env and fill in credentials
├── .gmail_seen.json        ← auto-created; tracks processed Message-IDs
├── README.md               ← this file
├── logs/                   ← created automatically at runtime
│   └── gmail_watcher.log
└── examples/
    └── example_email_action.md
```

---

## Setup

### 1 · Enable Gmail IMAP
1. Open Gmail → **Settings** (gear icon) → **See all settings**
2. Go to the **Forwarding and POP/IMAP** tab
3. Under *IMAP access*, select **Enable IMAP** → Save

### 2 · Generate an App Password
> Gmail requires 2-Factor Authentication to use App Passwords.

1. Go to **Google Account → Security → 2-Step Verification**
2. Scroll to the bottom → **App passwords**
3. Select *Mail* + your device → click **Generate**
4. Copy the 16-character password shown

### 3 · Configure `.env`
```bash
cd Skills/Gmail_Watcher
cp .env.example .env
# Open .env and set GMAIL_USER, GMAIL_APP_PASSWORD, and VAULT_PATH
```

### 4 · Install dependencies
```bash
pip install -r requirements.txt
```

### 5 · Run
```bash
python gmail_watcher.py
```
Press `Ctrl+C` to stop.

---

## Configuration

| Variable             | Default    | Description                                   |
|----------------------|------------|-----------------------------------------------|
| `GMAIL_USER`         | —          | Your full Gmail address                       |
| `GMAIL_APP_PASSWORD` | —          | 16-char App Password from Google Security     |
| `VAULT_PATH`         | `../../..` | Absolute path to your Obsidian vault root     |
| `POLL_INTERVAL`      | `60`       | Seconds between inbox checks                  |

---

## Message Filter

Only messages meeting **both** criteria are processed:

| Criterion  | IMAP flag          | Meaning                                        |
|------------|--------------------|------------------------------------------------|
| Unread     | `UNSEEN`           | Message has not been opened                    |
| Important  | `KEYWORD $Important` | Gmail's automatic or manual Important label  |

All other messages (read, or not marked Important) are silently skipped.

---

## Output

A new `.md` file is created in `/Needs_Action` for every qualifying email:

```
Needs_Action/
└── EMAIL_CABcd1234_mail_gmail_com.md
```

### File naming

```
EMAIL_<sanitised_message_id>.md
```

The `Message-ID` header is stripped of angle brackets and any
filesystem-unsafe characters are replaced with underscores.

### File format

```markdown
---
type: email
from: Sender Name <sender@example.com>
subject: Email subject line
received: 2026-02-25T11:00:00Z
priority: high
status: pending
---

## Email Content

<plain-text body, up to 2 000 characters>

## Suggested Actions

- [ ] Reply to sender
- [ ] Forward to relevant party
- [ ] Archive after processing
```

---

## Duplicate Prevention

Processed Message-IDs are persisted in `.gmail_seen.json` alongside the
script. On startup the registry is loaded, so the script **never creates a
duplicate file** even across restarts.

A file is also skipped if `EMAIL_<id>.md` already exists on disk (safety net
for a missing or corrupt registry).

---

## Dashboard Logging

After each new action file is created, a row is appended to the
**Recent Activity** table in `/Dashboard.md`:

```
| <ISO timestamp> | gmail_email_detected | EMAIL_<id>.md | Gmail Watcher |
```

---

## Logging
All activity is written to `logs/gmail_watcher.log` and echoed to the terminal.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `IMAP error: [AUTHENTICATIONFAILED]` | Wrong credentials or App Password — regenerate it. |
| `IMAP error: command SEARCH illegal in state AUTH` | IMAP not enabled in Gmail settings. |
| No files created despite Important unread emails | Check `VAULT_PATH` is correct and the directory is writable. |
| Script exits immediately | `GMAIL_USER` or `GMAIL_APP_PASSWORD` is empty in `.env`. |
| Files created for non-important emails | Gmail may not have labelled them Important yet — allow a few minutes. |
