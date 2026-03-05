# AI Employee — Silver Tier Skills

Eleven autonomous skills forming a complete Watcher → Brain → Approval Gate → Approval Watcher → Executor pipeline.

---

## Vault Flow

```
External Sources                  Vault Folders
─────────────────                 ──────────────────────────────────────────────
Gmail           ──┐
Local Drop Folder──┼──►  /Needs_Action
File Inbox      ──┘         │
                             │  Plan_Generator reads each .md
                             ▼
                         /Plans/PLAN_*.md   (status: pending_approval)
                             │
                             │  Approval_Gate scans for HIGH + email + pending
                             ▼
                   /Pending_Approval/APPROVAL_*.md
                             │
                             │  Human operator reviews (approve / reject)
                             ▼
                    /Approved/ or /Rejected/
                             │
                             │  Approval_Watcher detects + logs + archives
                             ▼
                          /Done            ←── file archived here
                             │
                   Daily_Briefing + CEO_Briefing read logs + tasks
                             ▼
                     DAILY_BRIEFING.md  +  /Briefings/  +  Dashboard.md
```

---

## Skills

### Watcher Layer (Silver L08)
| Skill | Trigger | Output |
|-------|---------|--------|
| [Gmail_Watcher](Gmail_Watcher/README.md) | Unread + Important Gmail emails | `EMAIL_*.md` in `/Needs_Action` |
| [File_System_Watcher](File_System_Watcher/README.md) | Files dropped in `/Inbox` | `FILE_*.md` in `/Needs_Action` |

### Brain Layer (Bronze)
| Skill | Input | Output |
|-------|-------|--------|
| [Plan_Generator](Plan_Generator/README.md) | `/Needs_Action/*.md` | `PLAN_*.md` in `/Plans` |
| [Daily_Briefing](Daily_Briefing/README.md) | `/Plans`, `/Needs_Action`, `/Done` | `DAILY_BRIEFING.md` + `Dashboard.md` |

### Approval Layer (Silver L09)
| Skill | Input | Output |
|-------|-------|--------|
| [Approval_Gate](Approval_Gate/README.md) | `/Plans/*.md` — HIGH + email + pending_approval | `APPROVAL_*.md` in `/Pending_Approval` |
| [Approval_Watcher](Approval_Watcher/README.md) | `/Approved/*.md` and `/Rejected/*.md` | Logs + archives to `/Done/` |

### Gold Layer (Planned)
| Skill | Input | Output |
|-------|-------|--------|
| [Approval_Generator](Approval_Generator/README.md) | `/Plans/*.md` (all sensitive types) | `APPROVAL_*.md` in `/Pending_Approval` |
| [MCP_Action_Executor](MCP_Action_Executor/README.md) | `/Approved/*.md` | Email/WhatsApp/LinkedIn dispatch + `/Done` |
| [WhatsApp_Watcher](WhatsApp_Watcher/README.md) | Unread WA messages | `WHATSAPP_*.md` in `/Needs_Action` |
| [LinkedIn_Watcher](LinkedIn_Watcher/README.md) | Unread LI messages | `LINKEDIN_*.md` in `/Needs_Action` |

---

## Quick Start (Silver Tier)

```bash
# ── Step 1: Install dependencies ─────────────────────────────────────────────
pip install -r Skills/File_System_Watcher/requirements.txt
pip install -r Skills/Gmail_Watcher/requirements.txt
pip install -r Skills/Approval_Gate/requirements.txt
pip install -r Skills/Approval_Watcher/requirements.txt
pip install -r Skills/Plan_Generator/requirements.txt
pip install -r Skills/Daily_Briefing/requirements.txt

# ── Step 2: Configure ────────────────────────────────────────────────────────
cp Skills/Gmail_Watcher/.env.example        Skills/Gmail_Watcher/.env
cp Skills/File_System_Watcher/.env.example  Skills/File_System_Watcher/.env
cp Skills/Approval_Watcher/.env.example     Skills/Approval_Watcher/.env
# Edit each .env — set VAULT_PATH and credentials

# ── Step 3: Start with PM2 ──────────────────────────────────────────────────
npm install -g pm2
pm2 start ecosystem.config.js
pm2 save && pm2 startup

# ── Step 4: Manual runs ─────────────────────────────────────────────────────
python Skills/Plan_Generator/plan_generator.py       # generate plans
python Skills/Daily_Briefing/daily_briefing.py       # daily briefing

# ── Step 5: Human approval ──────────────────────────────────────────────────
# Review /Pending_Approval → move to /Approved or /Rejected
# Approval Watcher auto-detects and archives to /Done
```

---

## Tier Roadmap

- [x] **Bronze** — Watchers + rule-based brain + daily briefing
- [x] **Silver** — Approval Gate + Approval Watcher + PM2 + Cron + CEO Briefing
- [ ] **Gold** — MCP Action Executor + WhatsApp/LinkedIn + self-healing workflows
