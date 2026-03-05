# Company Handbook — AI Employee Operations

**Version:** 2.0.0
**Tier:** Silver
**Effective Date:** 2026-03-05

---

## 1. Mission

The AI Employee system exists to process, route, plan, and execute operational tasks with full auditability and human oversight. At Silver Tier, autonomous watchers detect incoming work, HITL approval gates ensure human oversight on sensitive actions, and PM2 keeps all processes running continuously.

---

## 2. Core Operating Rules

### 2.1 Intake Rules
- Tasks enter via `/Inbox` (File Watcher), `/Drop_Folder` (legacy), or Gmail (Gmail Watcher). No task may be created directly in pipeline folders.
- Files must be named using the convention: `YYYY-MM-DD_TaskName.ext`
- Duplicate filenames will be suffixed with `_v2`, `_v3`, etc.
- Accepted formats: `.md`, `.txt`, `.json`, `.csv`, `.pdf`
- Maximum file size: 10 MB per file.

### 2.2 Routing Rules
- Files in `Drop_Folder` are moved to `Needs_Action` upon intake.
- Files in `Needs_Action` are processed and moved to `Plans`.
- No file may skip a stage in the pipeline.
- Files must not be manually moved between folders without a corresponding log entry.

### 2.3 Approval Rules
- All plans must pass through `Pending_Approval` before any action is taken.
- Only authorized operators may approve or reject items.
- Approval must be recorded in `/Logs` with operator identifier.
- Rejected items are moved to `/Rejected` and are never deleted without explicit operator instruction.
- Approved items are moved to `/Approved`, then to `/Done` upon task completion.

### 2.4 Logging Rules
- Every state transition must produce a log entry.
- Log format: `[YYYY-MM-DD HH:MM:SS UTC] | LEVEL | COMPONENT | MESSAGE`
- Logs are append-only. No log entry may be deleted or modified.
- Log files rotate daily: `YYYY-MM-DD_system.log`
- Log retention: minimum 90 days.

### 2.5 Data Rules
- No personally identifiable information (PII) may be stored in any folder without encryption.
- No API keys, passwords, or secrets may be placed in any vault folder.
- All files in `/Approved` and `/Done` are considered finalized records.

---

## 3. Operator Responsibilities

| Role | Responsibility |
|---|---|
| Task Submitter | Drops well-named files into `/Drop_Folder` |
| Reviewer | Reviews plans in `/Pending_Approval` and approves or rejects |
| Auditor | Reviews `/Logs` for compliance and anomalies |
| Admin | Manages folder health, archival, and escalation |

---

## 4. Escalation Policy

| Condition | Action |
|---|---|
| Task stuck in `Needs_Action` > 24 hours | Flag in Dashboard, notify operator |
| Task stuck in `Pending_Approval` > 48 hours | Escalate to Admin |
| Three consecutive rejections of same task | Escalate to Admin for manual review |
| Log write failure | Halt pipeline, alert Admin immediately |
| Unrecognized file format in `Drop_Folder` | Move to `Rejected`, log as `WARN` |

---

## 5. Prohibited Actions

- Deleting files from `/Rejected` or `/Done` without Admin authorization.
- Bypassing `/Pending_Approval` under any circumstance.
- Modifying log files.
- Placing executable code (`.exe`, `.sh`, `.py`, `.bat`) in `Drop_Folder` without explicit Admin pre-authorization.
- Operating without an active log session.

---

## 6. Archival Policy

| Folder | Archive Frequency | Retention |
|---|---|---|
| Done | Weekly | 1 year |
| Rejected | Monthly | 1 year |
| Logs | Daily rotation | 90 days minimum |
| Approved | Monthly | 1 year |

---

## 7. Tier Upgrade Criteria

### Bronze → Silver (COMPLETED)
- [x] File System Watcher operational (watchdog-based)
- [x] Gmail Watcher operational (IMAP polling)
- [x] Approval Gate scanning Plans for HIGH-priority emails
- [x] Approval Watcher processing Approved/Rejected folders
- [x] PM2 ecosystem configuration created
- [x] Cron scheduling for daily briefing and CEO briefing
- [x] Stop Hooks for persistent processing
- [x] CEO Briefing skill defined
- [x] Business Goals document created

### Silver → Gold
- [ ] MCP Action Executor in production (live email sending)
- [ ] WhatsApp Watcher operational
- [ ] LinkedIn Watcher operational
- [ ] Self-healing workflows (auto-retry failed tasks)
- [ ] SLA enforcement with automated escalation
- [ ] Full autonomous execution with minimal human intervention

---

## 8. Version History

| Version | Date | Change |
|---|---|---|
| 1.0.0 | 2026-02-23 | Initial Bronze Tier handbook created |
| 2.0.0 | 2026-03-05 | Upgraded to Silver Tier — added watchers, HITL, PM2, CEO Briefing |
