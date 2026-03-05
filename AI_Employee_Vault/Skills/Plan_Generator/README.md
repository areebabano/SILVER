# Plan Generator
**Silver Tier — AI Employee Brain Layer**

## Purpose
Reads every unprocessed `.md` file in `/Needs_Action`, uses the **Claude API**
to generate an intelligent action plan, and writes it to
`/Plans/PLAN_<source_filename>.md`.

When `ANTHROPIC_API_KEY` is not set (or the API call fails), the script
automatically falls back to a rule-based engine so the pipeline never stalls.

After every pass it updates `/Dashboard.md` with the new plans count and
a Recent Activity entry per plan.

---

## Folder Structure
```
Plan_Generator/
├── plan_generator.py     ← main script (Silver Tier)
├── requirements.txt
├── .env.example          ← copy to .env; set VAULT_PATH + ANTHROPIC_API_KEY
├── README.md             ← this file
├── logs/                 ← created automatically at runtime
│   └── plan_generator.log
└── examples/
    └── example_plan.md
```

---

## Setup

### 1 · Install dependencies
```bash
pip install -r requirements.txt
```

### 2 · Configure `.env`
```bash
cd Skills/Plan_Generator
cp .env.example .env
# Edit .env — set VAULT_PATH and ANTHROPIC_API_KEY
```

### 3 · Run (single pass)
```bash
python plan_generator.py
```

### 4 · Run (watch mode — reruns every N seconds)
```bash
python plan_generator.py --watch
```

---

## Configuration

| Variable            | Default                     | Description                                              |
|---------------------|-----------------------------|----------------------------------------------------------|
| `VAULT_PATH`        | `../../..`                  | Absolute path to the Obsidian vault root                 |
| `POLL_INTERVAL`     | `120`                       | Seconds between passes in `--watch` mode                 |
| `ANTHROPIC_API_KEY` | _(empty)_                   | Anthropic API key — enables Silver Tier AI generation    |
| `CLAUDE_MODEL`      | `claude-haiku-4-5-20251001` | Model for plan generation; upgrade to `claude-sonnet-4-6` for richer plans |

---

## How It Works

```
/Needs_Action/*.md
       │
       ▼
  Parse front matter + extract metadata
  (supports new direct-YAML and legacy table formats)
       │
       ▼
  Detect priority  (HIGH / MEDIUM / LOW)
       │
       ├─ ANTHROPIC_API_KEY set? ──► Call Claude API → JSON plan
       │                                  │ fail?
       └─ Rule-based fallback ◄───────────┘
       │
       ▼
  Write /Plans/PLAN_<filename>.md
       │
       ▼
  Update /Dashboard.md
```

1. Scans `/Needs_Action` for all `.md` files.
2. Skips any file whose `PLAN_<name>.md` already exists in `/Plans` (idempotent).
3. For each unprocessed file:
   - Parses the YAML front matter and body to extract `sender`, `subject`, `received`, `content`.
   - Scores **priority** from front matter flags and keyword matching.
   - Calls Claude API (if configured) to produce: **Objective**, **Steps**, **Approval Required**.
   - Falls back to rule-based templates if the API is unavailable.
4. Writes `PLAN_<source_filename>.md` to `/Plans` with `status: pending_approval`.
5. Calls `update_dashboard()` for all newly created plans.

### Source types supported

| `type` value | Source skill |
|---|---|
| `email` | Gmail_Watcher |
| `whatsapp` | WhatsApp_Watcher |
| `linkedin` | LinkedIn_Watcher |
| `file_drop` | File_System_Watcher |

---

## Output

```
Plans/
└── PLAN_EMAIL_CABcd1234_mail_gmail_com.md
```

### Plan file format

```markdown
---
created: 2026-02-28T10:20:00Z
status: pending_approval
source_file: EMAIL_CABcd1234_mail_gmail_com.md
source_type: email
priority: HIGH
---

## Objective
…

## Steps
- [ ] Step 1
- [ ] Step 2
…

## Approval Required
…
```

---

## Priority Rules (rule-based fallback)

| Level  | Trigger keywords |
|--------|-----------------|
| HIGH   | urgent, asap, overdue, critical, deadline, legal, breach, unpaid … |
| MEDIUM | invoice, payment, review, follow-up, reminder, proposal, contract … |
| LOW    | Everything else |

Priority in the source front matter (`priority: high`) is always respected.

---

## Integration with Other Skills

```
Gmail_Watcher / WhatsApp_Watcher / LinkedIn_Watcher / File_System_Watcher
        ↓  writes .md to /Needs_Action
   Plan_Generator   ← (you are here)
        ↓  writes PLAN_*.md to /Plans   (status: pending_approval)
        ↓  updates Dashboard.md
   Daily_Briefing
        ↓  reads /Plans → DAILY_BRIEFING.md
```

---

## Logging
All activity is written to `logs/plan_generator.log` and echoed to the terminal.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "No .md files found" | Check that `VAULT_PATH` is correct in `.env` |
| Plans generated but no AI content | `ANTHROPIC_API_KEY` is not set — using rule-based fallback |
| `anthropic.AuthenticationError` | API key is invalid — check console.anthropic.com |
| JSON parse error from Claude | Increase `max_tokens` or switch to `claude-sonnet-4-6` |
| Dashboard not updating | Check that `VAULT_PATH/Dashboard.md` exists and is writable |
| Same file planned twice | Cannot happen — script checks for `PLAN_` prefix before processing |
