#!/usr/bin/env python3
"""Full Silver Tier Validation — All 9 Phases."""
import sys, json, os, subprocess
from pathlib import Path
from datetime import datetime, timezone

VAULT = Path("D:/AI_Employee_Vault")
results = []

def check(name, passed, detail=""):
    results.append({"name": name, "passed": passed, "detail": detail})
    status = "PASS" if passed else "FAIL"
    d = f"  --  {detail}" if detail else ""
    print(f"  [{status}] {name}{d}")

# ============================================================
print("=" * 60)
print("PHASE 1: PLAYWRIGHT + WATCHERS")
print("=" * 60)

try:
    from playwright.sync_api import sync_playwright
    check("Playwright installed", True, "sync_api importable")
except Exception as e:
    check("Playwright installed", False, str(e))

chromium_path = Path.home() / "AppData/Local/ms-playwright"
chromium_exists = any(chromium_path.glob("chromium-*"))
check("Chromium browser downloaded", chromium_exists)

sys.path.insert(0, str(VAULT / "Skills/WhatsApp_Watcher"))
try:
    import whatsapp_watcher
    check("WhatsApp Watcher import", True, f"VAULT={whatsapp_watcher.VAULT_PATH}")
    check("WhatsApp keywords loaded", len(whatsapp_watcher.KEYWORDS) > 0, f"{len(whatsapp_watcher.KEYWORDS)} keywords")
    check("WhatsApp seen registry path", True, str(whatsapp_watcher.SEEN_REGISTRY))
except Exception as e:
    check("WhatsApp Watcher import", False, str(e))

sys.path.insert(0, str(VAULT / "Skills/LinkedIn_Watcher"))
try:
    import linkedin_watcher
    check("LinkedIn Watcher import", True, f"VAULT={linkedin_watcher.VAULT_PATH}")
    check("LinkedIn service keywords", len(linkedin_watcher.SERVICE_KEYWORDS) > 0, f"{len(linkedin_watcher.SERVICE_KEYWORDS)} keywords")
    check("LinkedIn seen registry path", True, str(linkedin_watcher.SEEN_REGISTRY))
except Exception as e:
    check("LinkedIn Watcher import", False, str(e))

# ============================================================
print()
print("=" * 60)
print("PHASE 2: PM2 PROCESS MANAGEMENT")
print("=" * 60)

r = subprocess.run("pm2 jlist", capture_output=True, text=True, shell=True)
try:
    pm2_apps = json.loads(r.stdout)
    check("PM2 daemon running", True, f"{len(pm2_apps)} apps")

    expected = ["file-watcher", "gmail-watcher", "approval-gate", "approval-watcher"]
    for name in expected:
        is_online = any(a["name"] == name and a["pm2_env"]["status"] == "online" for a in pm2_apps)
        check(f"PM2 {name}", is_online, "online" if is_online else "not found/stopped")

    check("ecosystem.config.js", (VAULT / "ecosystem.config.js").exists())

    dump = Path.home() / ".pm2/dump.pm2"
    check("PM2 process list saved", dump.exists())
except Exception as e:
    check("PM2 daemon running", False, str(e))

# ============================================================
print()
print("=" * 60)
print("PHASE 3: SCHEDULED TASKS (CRON)")
print("=" * 60)

check("daily_briefing.sh exists", (VAULT / "scripts/daily_briefing.sh").exists())
check("daily_briefing.bat exists", (VAULT / "scripts/daily_briefing.bat").exists())
check("ceo_briefing.sh exists", (VAULT / "scripts/ceo_briefing.sh").exists())
check("ceo_briefing.bat exists", (VAULT / "scripts/ceo_briefing.bat").exists())

os.environ["MSYS_NO_PATHCONV"] = "1"
r1 = subprocess.run('schtasks /query /tn "AI_Employee_DailyBriefing" /fo CSV', capture_output=True, text=True, shell=True)
check("Scheduled: DailyBriefing", r1.returncode == 0, "registered in Task Scheduler")

r2 = subprocess.run('schtasks /query /tn "AI_Employee_CEOBriefing" /fo CSV', capture_output=True, text=True, shell=True)
check("Scheduled: CEOBriefing", r2.returncode == 0, "registered in Task Scheduler")

# ============================================================
print()
print("=" * 60)
print("PHASE 4: FILE SYSTEM WATCHER")
print("=" * 60)

sys.path.insert(0, str(VAULT / "Skills/File_System_Watcher"))
try:
    import fs_watcher
    check("FS Watcher import", True)
    check("FS Watcher VAULT_PATH", fs_watcher.VAULT_PATH.exists())
    check("FS Watcher Needs_Action dir", fs_watcher.NEEDS_ACTION.is_dir())
except Exception as e:
    check("FS Watcher import", False, str(e))

# ============================================================
print()
print("=" * 60)
print("PHASE 5: GMAIL WATCHER")
print("=" * 60)

sys.path.insert(0, str(VAULT / "Skills/Gmail_Watcher"))
try:
    import gmail_watcher
    check("Gmail Watcher import", True)
    check("Gmail VAULT_PATH", gmail_watcher.VAULT_PATH.exists())
    guser = getattr(gmail_watcher, "GMAIL_USER", "")
    gpass = getattr(gmail_watcher, "GMAIL_APP_PASSWORD", "")
    check("Gmail USER set", bool(guser), guser or "(empty)")
    check("Gmail APP_PASSWORD set", bool(gpass), "***" + gpass[-4:] if gpass else "(empty)")
except Exception as e:
    check("Gmail Watcher import", False, str(e))

# ============================================================
print()
print("=" * 60)
print("PHASE 6: APPROVAL PIPELINE")
print("=" * 60)

sys.path.insert(0, str(VAULT / "Skills/Approval_Gate"))
try:
    import approval_gate
    check("Approval Gate import", True)
    check("Approval Gate scan_plans()", hasattr(approval_gate, "scan_plans"))
except Exception as e:
    check("Approval Gate import", False, str(e))

sys.path.insert(0, str(VAULT / "Skills/Approval_Watcher"))
try:
    import approval_watcher
    check("Approval Watcher import", True)
    check("Watcher: process_approved()", hasattr(approval_watcher, "process_approved"))
    check("Watcher: process_rejected()", hasattr(approval_watcher, "process_rejected"))
    check("Watcher: DONE_DIR", approval_watcher.DONE_DIR.is_dir())
except Exception as e:
    check("Approval Watcher import", False, str(e))

# ============================================================
print()
print("=" * 60)
print("PHASE 7: BRAIN LAYER")
print("=" * 60)

sys.path.insert(0, str(VAULT / "Skills/Plan_Generator"))
try:
    import plan_generator
    check("Plan Generator import", True)
    check("Plans dir exists", (VAULT / "Plans").is_dir())
except Exception as e:
    check("Plan Generator import", False, str(e))

sys.path.insert(0, str(VAULT / "Skills/Daily_Briefing"))
try:
    import daily_briefing
    check("Daily Briefing import", True)
    check("DAILY_BRIEFING.md exists", (VAULT / "DAILY_BRIEFING.md").exists())
except Exception as e:
    check("Daily Briefing import", False, str(e))

skill_md = VAULT / ".claude/skills/ceo-briefing/SKILL.md"
check("CEO Briefing SKILL.md", skill_md.exists())
if skill_md.exists():
    sc = skill_md.read_text(encoding="utf-8")
    check("CEO: Revenue Analysis step", "Revenue Analysis" in sc)
    check("CEO: Task Completion step", "Task Completion" in sc)
    check("CEO: Bottleneck Detection", "Bottleneck Detection" in sc)
    check("CEO: Subscription Audit", "Subscription Audit" in sc)
    check("CEO: Proactive Suggestions", "Proactive Suggestions" in sc)

check("Business_Goals.md", (VAULT / "Business_Goals.md").exists())
check("audit-rules.md", (VAULT / "references/audit-rules.md").exists())
check("Briefings/ dir", (VAULT / "Briefings").is_dir())

# ============================================================
print()
print("=" * 60)
print("PHASE 8: GOVERNANCE & STRUCTURE")
print("=" * 60)

check("CLAUDE.md exists", (VAULT / "CLAUDE.md").exists())
check("AGENTS.md exists", (VAULT / "AGENTS.md").exists())
check("Dashboard.md exists", (VAULT / "Dashboard.md").exists())
check(".env root exists", (VAULT / ".env").exists())
check("Stop Hook config", (VAULT / ".claude/settings.json").exists())
check("Stop Hook script", (VAULT / ".claude/hooks/check_tasks.sh").exists())

for folder in ["Drop_Folder", "Inbox", "Needs_Action", "Plans", "Pending_Approval", "Approved", "Rejected", "Done", "Logs"]:
    check(f"/{folder}/ exists", (VAULT / folder).is_dir())

# ============================================================
print()
print("=" * 60)
print("PHASE 9: VAULT LOGGING")
print("=" * 60)

today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
log_file = VAULT / "Logs" / f"{today}.json"
check("Today log file exists", log_file.exists(), log_file.name)
if log_file.exists():
    data = json.loads(log_file.read_text(encoding="utf-8"))
    entries = data.get("entries", [])
    check("Log has entries", len(entries) > 0, f"{len(entries)} entries")
    errors = [e for e in entries if e.get("level") == "ERROR"]
    check("No ERROR-level log entries", len(errors) == 0, f"{len(errors)} errors" if errors else "clean")

log_files = list((VAULT / "Logs").glob("*.json"))
check("Logs/ has JSON files", len(log_files) > 0, f"{len(log_files)} file(s)")

# ============================================================
print()
print("=" * 60)
print("FINAL SUMMARY")
print("=" * 60)

passed = sum(1 for r in results if r["passed"])
total = len(results)
pct = (passed / total * 100) if total else 0
print(f"  Total: {passed}/{total} PASSED ({pct:.1f}%)")
print()

failed = [r for r in results if not r["passed"]]
if failed:
    print(f"  FAILURES ({len(failed)}):")
    for f in failed:
        print(f"    - {f['name']}: {f['detail']}")
else:
    print("  ALL CHECKS PASSED")
    print("  Silver Tier: 10/10 PRODUCTION READY!")

# Write results as JSON for report generation
output = {
    "date": datetime.now(timezone.utc).isoformat(),
    "total": total,
    "passed": passed,
    "failed": len(failed),
    "pct": round(pct, 1),
    "results": results,
}
out_path = VAULT / "Logs" / "validation_results.json"
out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
print(f"\n  Results saved: {out_path}")
