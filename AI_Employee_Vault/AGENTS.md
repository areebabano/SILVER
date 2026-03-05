# AI Employee — Workspace Governance

## Workspace Structure

This vault operates as a **Silver Tier** AI Employee system with the following agent hierarchy:

### Active Agents

| Agent | Tier | Role | Script |
|-------|------|------|--------|
| File System Watcher | Silver | Monitor Inbox for new files, create action notes | `Skills/File_System_Watcher/fs_watcher.py` |
| Gmail Watcher | Silver | Poll Gmail for UNSEEN+IMPORTANT emails | `Skills/Gmail_Watcher/gmail_watcher.py` |
| Approval Gate | Silver | Scan Plans for HIGH-priority email plans, create approvals | `Skills/Approval_Gate/approval_gate.py` |
| Approval Watcher | Silver | Poll Approved/Rejected folders, archive to Done | `Skills/Approval_Watcher/approval_watcher.py` |
| Plan Generator | Bronze | Generate structured plans from Needs_Action items | `Skills/Plan_Generator/plan_generator.py` |
| Daily Briefing | Bronze | Generate daily operational summary | `Skills/Daily_Briefing/daily_briefing.py` |

### Process Management

All long-running agents are managed by **PM2** via `ecosystem.config.js`:

```bash
pm2 start ecosystem.config.js    # Start all watchers
pm2 list                          # View status
pm2 logs                          # View all logs
pm2 save                          # Persist across reboots
pm2 startup                       # Auto-start on boot
```

### Scheduled Tasks (Cron)

| Schedule | Task | Script |
|----------|------|--------|
| Weekdays 8:00 AM | Daily Briefing | `scripts/daily_briefing.sh` |
| Sunday 11:00 PM | CEO Briefing | `scripts/ceo_briefing.sh` |

---

## Governance Rules

### Permission Boundaries

| Category | Auto-Approve | Requires Approval |
|----------|--------------|-------------------|
| Email replies | Known contacts (3+ exchanges/90 days) | New contacts, bulk sends, executives |
| File operations | Create, read, copy within vault | Delete, move outside vault |
| Calendar | Accept during work hours | Decline, reschedule, external attendees |
| Reports | Internal summaries, daily briefings | External-facing documents |

### Safety Protocols

1. **HITL Gate**: All HIGH-priority email responses must pass through `/Pending_Approval/`
2. **DRY_RUN**: New integrations must be tested with `DRY_RUN=true` before live execution
3. **Audit Trail**: Every action logged to `/Logs/YYYY-MM-DD.json` with full context
4. **Expiry**: Approval requests expire after 24 hours if not acted upon
5. **Rejection Archive**: Rejected items prefixed with `REJECTED_` and moved to `/Done/`

### Skill Organization

```
Skills/
├── <SkillName>/
│   ├── <script>.py          → Main implementation
│   ├── README.md            → Skill documentation
│   ├── requirements.txt     → Python dependencies
│   ├── .env.example         → Environment variable template
│   └── logs/                → Skill-specific logs
```

### Agent Communication

- Agents communicate through the **filesystem** (not direct calls)
- Agent A writes to a folder → Agent B watches that folder
- All inter-agent data uses **YAML frontmatter** in Markdown files
- No agent may bypass the approval pipeline
