# Daily Briefing
**Bronze Tier — AI Employee Brain Layer**

## Purpose
Aggregates the current state of the vault into a single morning-read document and updates the live Dashboard. Run it once per day (or any time you want a snapshot).

Produces:
- **`DAILY_BRIEFING.md`** in the vault root — replaces the previous one each run
- **`Dashboard.md`** — surgically updated counts, timestamps, activity log, and flags

---

## Folder Structure
```
Daily_Briefing/
├── daily_briefing.py     ← main script
├── requirements.txt
├── .env.example          ← copy to .env and set VAULT_PATH
├── README.md             ← this file
├── logs/                 ← created automatically at runtime
│   └── daily_briefing.log
└── examples/
    └── example_daily_briefing.md
```

---

## Setup

### 1 · Install dependencies
```bash
pip install -r requirements.txt
```

### 2 · Configure `.env`
```bash
cd Skills/Daily_Briefing
cp .env.example .env
# Edit .env — set VAULT_PATH
```

### 3 · Run
```bash
python daily_briefing.py
```

### 4 · Schedule it (optional — Linux/WSL cron)
```bash
# Run every day at 08:00
crontab -e
0 8 * * * cd /mnt/d/AI_Employee_Vault && python Skills/Daily_Briefing/daily_briefing.py
```

---

## Configuration

| Variable     | Default   | Description                                  |
|--------------|-----------|----------------------------------------------|
| `VAULT_PATH` | `../../..` | Absolute path to the Obsidian vault root    |

---

## How It Works

1. **Scans `/Needs_Action`** — reads every `.md` file, records its type and whether a plan already exists.
2. **Scans `/Plans`** — reads every `PLAN_*.md` file, extracts `priority` and `status` from front matter, sorts HIGH → MEDIUM → LOW.
3. **Scans `/Done`** — counts completed items.
4. **Writes `DAILY_BRIEFING.md`** with:
   - At-a-Glance counts table
   - HIGH priority items table
   - MEDIUM priority items table
   - Full pending plans table
   - Completed files list
   - Unplanned items warning (if any)
   - Suggested Focus Order (top 10 items to tackle)
5. **Updates `Dashboard.md`**:
   - `Last Updated` timestamp
   - Task Queue Metrics row counts (Needs_Action, Plans, Done)
   - Throughput — Last Execution + Last Summary Generated
   - Recent Activity Log — appends a new row
   - Flags & Alerts — lists HIGH priority items (or clears flags if none)

---

## Output Files

### `DAILY_BRIEFING.md`
```
DAILY_BRIEFING.md    ← always in vault root, overwritten each run
```

### `Dashboard.md` fields updated
| Field | Updated to |
|-------|------------|
| Last Updated | Current UTC timestamp |
| Needs_Action count | Live file count |
| Plans count | Live PLAN_*.md count |
| Done count | Live file count |
| Last Execution | Current UTC timestamp |
| Last Summary Generated | `DAILY_BRIEFING.md` |
| Recent Activity Log | New row appended |
| Flags & Alerts | HIGH priority items listed, or cleared |

---

## Integration with Other Skills

```
Gmail_Watcher / WhatsApp_Watcher / File_System_Watcher
        ↓
   Plan_Generator  →  /Plans/PLAN_*.md
        ↓
   Daily_Briefing  →  DAILY_BRIEFING.md  +  Dashboard.md update
```

**Recommended daily workflow:**
```bash
# 1. Watchers run continuously (background terminals)
# 2. Run Plan Generator to process overnight items
python Skills/Plan_Generator/plan_generator.py

# 3. Run Daily Briefing for your morning summary
python Skills/Daily_Briefing/daily_briefing.py

# 4. Open Obsidian → DAILY_BRIEFING.md
```

---

## Logging
All activity is written to `logs/daily_briefing.log` and echoed to the terminal.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `DAILY_BRIEFING.md` shows zero counts | Check `VAULT_PATH` is correct in `.env` |
| Dashboard not updated | Verify `Dashboard.md` exists in the vault root and is writable |
| HIGH items not appearing in Flags | Plan files must have `priority: HIGH` in YAML front matter — run `plan_generator.py` first |
| Cron job not running | Check cron logs: `grep CRON /var/log/syslog` |
