# AI Employee — User Instructions

**Tier:** Silver
**Version:** 2.0.0
**Effective:** 2026-03-05T00:00:00Z

---

## 1. How to Add Files

The AI Employee has multiple intake points monitored by watchers:

- **`/Inbox`** — Primary drop point. File System Watcher (watchdog) monitors this folder.
- **`/Drop_Folder`** — Legacy intake point (Bronze compatibility).
- **Gmail** — Gmail Watcher polls for UNSEEN+IMPORTANT emails automatically.

1. Name your file using the convention: `YYYY-MM-DD_TaskName.ext`
   - Example: `2026-02-23_InvoiceReview.md`
2. Accepted formats: `.md`, `.txt`, `.json`, `.csv`, `.pdf`
3. Maximum file size: 10 MB per file.
4. Place the file directly inside `/Drop_Folder`. Do not create subfolders.
5. Do not place API keys, passwords, credentials, or PII in any file.
6. Once placed, take no further action. The AI Employee will handle routing deterministically.

> **Note:** Files with unrecognized formats are automatically moved to `/Rejected` and logged as a `WARN` event.

---

## 2. How Files Move Through the Pipeline

The AI Employee processes every file through a fixed, deterministic sequence of stages. No stage may be skipped.

```
Drop_Folder → Needs_Action → Plans → Pending_Approval → Approved → Done
                                                       ↘ Rejected
```

### Stage-by-Stage Breakdown

1. **Drop_Folder → Needs_Action**
   - The AI Employee detects the file in `/Drop_Folder`.
   - It validates the filename format and file type.
   - On success, the file is moved to `/Needs_Action` and a log entry is written.
   - On failure, the file is moved to `/Rejected` with a `failed` status log.

2. **Needs_Action → Plans**
   - The AI Employee reads the file in `/Needs_Action`.
   - It generates a corresponding `PLAN_<filename>.md` in `/Plans`.
   - The plan includes: filename, file size, creation timestamp, status, and step-by-step processing instructions.
   - The original file remains in `/Needs_Action` until the plan is confirmed.

3. **Plans → Pending_Approval**
   - The generated plan is staged in `/Pending_Approval` for human review.
   - No action is taken on the task until an authorized operator approves or rejects the plan.

4. **Pending_Approval → Approved or Rejected**
   - **Approve:** Move or mark the plan as approved. The AI Employee moves it to `/Approved` and logs the decision.
   - **Reject:** Move or mark the plan as rejected. The AI Employee moves it to `/Rejected` and logs the decision.
   - All decisions are immutable once logged.

5. **Approved → Done**
   - The AI Employee executes the approved plan steps.
   - Upon successful completion, the task file is moved to `/Done`.
   - A final `success` log entry is written.

---

## 3. How to Read Logs

All system activity is recorded in `/Logs/` as daily JSON files.

### Log File Location and Naming

```
/Logs/YYYY-MM-DD.json
```

Example: `/Logs/2026-02-23.json`

### Log Entry Structure

```json
{
  "timestamp": "YYYY-MM-DDTHH:MM:SSZ",
  "level": "INFO | WARN | ERROR | AUDIT",
  "component": "<system component>",
  "event": "<event name>",
  "file": "<filename or none>",
  "status": "success | failed | plan_exists",
  "message": "<human-readable description>"
}
```

### Steps to Read a Log

1. Open `/Logs/YYYY-MM-DD.json` for the date you want to review.
2. Each object inside `"entries"` represents one system event.
3. Filter by `"level"` to find issues:
   - `INFO` — routine operations.
   - `WARN` — non-critical issues (e.g. unrecognized file format).
   - `ERROR` — processing failures requiring attention.
   - `AUDIT` — human approval or rejection events.
4. Filter by `"file"` to trace the full history of a specific task.
5. Filter by `"status": "failed"` to identify all failures for the day.

### Log Retention

- Logs rotate daily.
- Minimum retention: 90 days.
- Logs are append-only. No entry may be modified or deleted.

---

## 4. How to Check Dashboard.md Metrics

`/Dashboard.md` provides a real-time operational view of the AI Employee workspace.

1. Open `/Dashboard.md` from the vault root.
2. Review the following sections:

   | Section | What It Shows |
   |---|---|
   | **Task Queue Metrics** | Current file counts per folder and last-updated timestamps |
   | **Throughput Summary** | Cumulative totals: received, completed, rejected, approval rate |
   | **System Health** | Status of each pipeline component (Standby / Active) |
   | **Recent Activity Log** | Timestamped list of the last system events |
   | **Flags & Alerts** | Active warnings or escalation notices |

3. Key metrics to monitor:

   - `Completed_Today` — tasks successfully processed in the current cycle.
   - `Failed_Today` — tasks that encountered errors in the current cycle.
   - `Last Execution` — timestamp of the most recent processing run.
   - `Last Summary Generated` — confirms the daily summary was produced.

4. If `Needs_Action` count is non-zero and `Last Execution` is older than 24 hours, escalate to Admin.
5. If `Pending_Approval` count is non-zero and unchanged for 48 hours, escalate to Admin.

---

## 5. Error Handling Instructions

The AI Employee handles errors deterministically. The following covers what happens and what you should do.

### 5.1 File Rejected at Intake

**Cause:** Unrecognized file format, invalid filename, or file exceeds size limit.

1. Open `/Rejected` and locate the file.
2. Open `/Logs/YYYY-MM-DD.json` and find the corresponding `WARN` or `ERROR` entry.
3. Correct the issue (rename the file, convert the format, or reduce file size).
4. Re-drop the corrected file into `/Drop_Folder`.

### 5.2 Plan Generation Failure

**Cause:** File in `/Needs_Action` is unreadable, empty, or corrupted.

1. Open `/Logs/YYYY-MM-DD.json` and locate the `ERROR` entry for the file.
2. Verify the file is not empty or corrupted by opening it directly.
3. If corrupted, replace it with a valid version and re-drop into `/Drop_Folder`.
4. If the plan already exists (`plan_exists` status), no action is required — the file will be processed on the next run.

### 5.3 Task Stuck in Needs_Action

**Cause:** Planner has not run, or an error prevented routing.

1. Check `/Logs/YYYY-MM-DD.json` for any `ERROR` entries referencing the file.
2. Verify `/Plans/PLAN_<filename>.md` exists. If missing, the planner failed silently.
3. Manually trigger a planner run or notify Admin.

### 5.4 Task Stuck in Pending_Approval

**Cause:** No human operator has reviewed the plan.

1. Open `/Pending_Approval` and review the staged plan.
2. Approve or reject the plan explicitly.
3. If stuck for more than 48 hours, escalate to Admin per the Company Handbook.

### 5.5 Log Write Failure

**Cause:** Disk full, permissions error, or file system issue.

1. This is a critical failure. The pipeline halts automatically.
2. Notify Admin immediately.
3. Do not resume processing until the log system is confirmed operational.
4. Verify `/Logs/` directory permissions and available disk space.

### 5.6 Three Consecutive Rejections of the Same Task

**Cause:** Repeated plan failures or persistent operator rejection.

1. The task is escalated automatically and flagged in `/Dashboard.md`.
2. Admin must review the task manually before any further processing.
3. Do not re-drop the file without Admin authorization.

---

## 6. Quick Reference

| Action | Location |
|---|---|
| Submit a new task | `/Drop_Folder` |
| View tasks awaiting processing | `/Needs_Action` |
| View generated plans | `/Plans` |
| Approve or reject a plan | `/Pending_Approval` |
| View approved tasks | `/Approved` |
| View completed tasks | `/Done` |
| View rejected files | `/Rejected` |
| Read system logs | `/Logs/YYYY-MM-DD.json` |
| Check live metrics | `/Dashboard.md` |
| Read daily summary | `/DAILY_SUMMARY_YYYY-MM-DD.md` |
| Read operational rules | `/Company_Handbook.md` |
