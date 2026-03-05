# AI Employee — Silver Tier

## Purpose

The AI Employee system is a workflow automation platform built on an Obsidian vault. Silver Tier adds **autonomous perception** (watchers), **HITL approval workflows**, **process persistence** (PM2/cron), and **business intelligence** (CEO Briefing) on top of the Bronze foundation.

---

## Folder Structure

| Folder | Role |
|---|---|
| `/Drop_Folder` | Legacy intake zone (Bronze). |
| `/Inbox` | Primary intake — File System Watcher monitors this folder. |
| `/Needs_Action` | Parsed tasks awaiting processing or execution. |
| `/Plans` | Generated plans, proposals, or structured responses awaiting review. |
| `/Pending_Approval` | Approval requests staged for human review (HITL gate). |
| `/Approved` | Human-approved items. Approval Watcher archives these to Done. |
| `/Rejected` | Human-rejected items. Approval Watcher archives with `REJECTED_` prefix. |
| `/Done` | Fully processed and closed tasks. |
| `/Logs` | Immutable JSON audit trail of all system events. |
| `/Briefings` | Weekly CEO Briefing output. |
| `/Skills` | Python skill modules (watchers, generators, executors). |
| `/scripts` | Wrapper scripts for cron scheduling. |
| `/references` | Audit rules, thresholds, supporting documents. |

---

## How Tasks Are Processed

```
Inbox / Gmail / Drop_Folder
    └─► Needs_Action         (Watchers detect + create action files)
            └─► Plans        (Plan Generator creates plans)
                    └─► Pending_Approval   (Approval Gate creates approval requests)
                            ├─► Approved ─► Done   (Approval Watcher archives)
                            └─► Rejected ─► Done   (REJECTED_ prefix + archive)
```

All state transitions are logged to `/Logs/YYYY-MM-DD.json`.

---

## Silver Tier Components

| Component | Script | Purpose |
|-----------|--------|---------|
| File System Watcher | `Skills/File_System_Watcher/fs_watcher.py` | Watchdog-based file monitoring |
| Gmail Watcher | `Skills/Gmail_Watcher/gmail_watcher.py` | IMAP polling for UNSEEN+IMPORTANT emails |
| Approval Gate | `Skills/Approval_Gate/approval_gate.py` | Scans Plans, creates approval requests |
| Approval Watcher | `Skills/Approval_Watcher/approval_watcher.py` | Polls Approved/Rejected, archives to Done |
| PM2 Config | `ecosystem.config.js` | Process management for all watchers |
| Stop Hook | `.claude/hooks/check_tasks.sh` | Persists Claude through multi-step workflows |
| CEO Briefing | `.claude/skills/ceo-briefing/SKILL.md` | Weekly business intelligence report |

---

## Process Management

```bash
pm2 start ecosystem.config.js     # Start all watchers
pm2 list                          # View status
pm2 logs                          # View all logs
pm2 save && pm2 startup           # Persist across reboots
```

---

## Tier Roadmap

| Tier | Status | Capability |
|---|---|---|
| Bronze | Complete | Rule-based routing, human approval gate, audit logging |
| Silver | Active | Watchers, HITL approval, PM2/cron persistence, CEO Briefing |
| Gold | Planned | Fully autonomous execution, self-healing workflows, SLA enforcement |
