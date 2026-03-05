"""
Bronze Tier AI Employee — Drop Folder Watcher
Monitors /Drop_Folder and routes new files through the pipeline.
"""

import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

VAULT_ROOT = Path(__file__).parent.resolve()

PATHS = {
    "drop":      VAULT_ROOT / "Drop_Folder",
    "needs":     VAULT_ROOT / "Needs_Action",
    "plans":     VAULT_ROOT / "Plans",
    "logs":      VAULT_ROOT / "Logs",
    "dashboard": VAULT_ROOT / "Dashboard.md",
}

ACCEPTED_EXTENSIONS = {".md", ".txt", ".json", ".csv", ".pdf"}
MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB
POLL_INTERVAL_SECONDS = 5
SEEN_REGISTRY = VAULT_ROOT / ".watcher_seen.json"


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Seen-file registry (duplicate prevention)
# ---------------------------------------------------------------------------

def load_seen() -> set:
    if SEEN_REGISTRY.exists():
        try:
            return set(json.loads(SEEN_REGISTRY.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            return set()
    return set()


def save_seen(seen: set) -> None:
    SEEN_REGISTRY.write_text(
        json.dumps(sorted(seen), indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# JSON logger
# ---------------------------------------------------------------------------

def append_log(entry: dict) -> None:
    log_path = PATHS["logs"] / f"{log_date()}.json"
    if log_path.exists():
        try:
            data = json.loads(log_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {"log_date": log_date(), "tier": "Bronze", "entries": []}
    else:
        data = {"log_date": log_date(), "tier": "Bronze", "entries": []}

    # Ensure 'entries' key exists (guards against malformed log files)
    if "entries" not in data or not isinstance(data.get("entries"), list):
        data["entries"] = []

    data["entries"].append(entry)
    log_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def log_event(
    level: str,
    component: str,
    event: str,
    file: str,
    status: str,
    message: str,
    **extra,
) -> None:
    entry = {
        "timestamp": utc_now(),
        "level": level,
        "component": component,
        "event": event,
        "file": file,
        "status": status,
        "message": message,
    }
    entry.update(extra)
    append_log(entry)


# ---------------------------------------------------------------------------
# File validation
# ---------------------------------------------------------------------------

def validate_file(path: Path) -> tuple[bool, str]:
    if path.suffix.lower() not in ACCEPTED_EXTENSIONS:
        return False, f"Rejected: unsupported extension '{path.suffix}'"
    if path.stat().st_size > MAX_FILE_BYTES:
        return False, f"Rejected: file exceeds 10 MB limit ({path.stat().st_size} bytes)"
    if not re.match(r"^\d{4}-\d{2}-\d{2}_.+", path.name):
        return False, f"Rejected: filename does not follow YYYY-MM-DD_Name.ext convention"
    return True, "valid"


# ---------------------------------------------------------------------------
# Metadata plan generator
# ---------------------------------------------------------------------------

def generate_metadata(src: Path, dest_needs: Path) -> None:
    stat = src.stat()
    created = datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    size_bytes = stat.st_size
    plan_name = f"METADATA_{src.name}.md"
    plan_path = PATHS["plans"] / plan_name

    if plan_path.exists():
        log_event(
            level="INFO",
            component="Planner",
            event="plan_exists",
            file=src.name,
            status="plan_exists",
            message=f"Plan already exists for '{src.name}'. Skipped.",
        )
        return

    content = f"""# Metadata Plan — {src.name}

**Generated:** {utc_now()}
**Tier:** Bronze
**Status:** planned

---

## File Information

| Field | Value |
|---|---|
| Filename | `{src.name}` |
| Extension | `{src.suffix.lower()}` |
| File Size | {size_bytes:,} bytes |
| Creation Timestamp | {created} |
| Source | `Drop_Folder` |
| Destination | `Needs_Action` |
| Plan File | `{plan_name}` |

---

## Processing Steps

1. Validate filename convention (`YYYY-MM-DD_Name.ext`).
2. Validate file extension against accepted formats: `.md .txt .json .csv .pdf`.
3. Validate file size is within 10 MB limit.
4. Copy file from `/Drop_Folder` to `/Needs_Action`.
5. Generate this metadata plan in `/Plans`.
6. Update `/Dashboard.md` queue metrics and activity log.
7. Append JSON entry to `/Logs/{log_date()}.json`.
8. Await operator review in `/Needs_Action`.
9. On operator approval: move to `/Approved`, then `/Done`.
10. On operator rejection: move to `/Rejected`.

---

## Logging Instructions

- All state transitions must produce a JSON log entry in `/Logs/YYYY-MM-DD.json`.
- Log format: `timestamp | level | component | event | file | status | message`
- Levels: `INFO`, `WARN`, `ERROR`, `AUDIT`
- This plan must not be modified after generation.

---

## Current Status

`planned` — Awaiting execution and operator approval.
"""
    plan_path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Dashboard updater
# ---------------------------------------------------------------------------

def _replace_dashboard_metric(text: str, label: str, value: str) -> str:
    pattern = rf"(\| {re.escape(label)} \| )(.+?)( \|)"
    replacement = rf"\g<1>{value}\g<3>"
    result, count = re.subn(pattern, replacement, text)
    if count == 0:
        return text
    return result


def update_dashboard(filename: str, status: str) -> None:
    dash = PATHS["dashboard"]
    if not dash.exists():
        return

    text = dash.read_text(encoding="utf-8")
    now = utc_now()

    # Recount actual folder sizes
    folder_counts = {}
    for key, folder in [
        ("Drop_Folder",      PATHS["drop"]),
        ("Needs_Action",     PATHS["needs"]),
        ("Plans",            PATHS["plans"]),
        ("Pending_Approval", VAULT_ROOT / "Pending_Approval"),
        ("Approved",         VAULT_ROOT / "Approved"),
        ("Rejected",         VAULT_ROOT / "Rejected"),
        ("Done",             VAULT_ROOT / "Done"),
    ]:
        folder_counts[key] = sum(
            1 for f in folder.iterdir() if f.is_file() and not f.name.startswith(".")
        ) if folder.exists() else 0

    # Update folder count rows
    for label, count in folder_counts.items():
        text = re.sub(
            rf"(\| {re.escape(label)} \| )\d+( \| )(.+?)( \|)",
            rf"\g<1>{count}\g<2>{now}\g<4>",
            text,
        )

    # Update throughput metrics
    text = _replace_dashboard_metric(text, "Last Execution", now)

    # Append to Recent Activity Log table
    activity_row = f"| {now} | file_detected | {filename} | System |"
    text = text.replace(
        "| — | No active flags | — |",
        "| — | No active flags | — |",
    )
    # Insert before the closing --- after the activity table
    activity_marker = "---\n\n## Flags & Alerts"
    if activity_marker in text:
        text = text.replace(
            activity_marker,
            f"{activity_row}\n\n---\n\n## Flags & Alerts",
        )

    text = re.sub(r"\*\*Last Updated:\*\* .+", f"**Last Updated:** {now}", text)
    dash.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# File router
# ---------------------------------------------------------------------------

def route_file(src: Path, seen: set) -> None:
    now = utc_now()

    valid, reason = validate_file(src)

    if not valid:
        rejected_path = VAULT_ROOT / "Rejected" / src.name
        shutil.copy2(src, rejected_path)
        src.unlink()
        log_event(
            level="WARN",
            component="Router",
            event="file_rejected",
            file=src.name,
            status="failed",
            message=reason,
        )
        seen.add(src.name)
        save_seen(seen)
        return

    dest = PATHS["needs"] / src.name
    if dest.exists():
        log_event(
            level="INFO",
            component="Router",
            event="duplicate_skipped",
            file=src.name,
            status="skipped",
            message=f"'{src.name}' already exists in /Needs_Action. Skipped.",
        )
        seen.add(src.name)
        save_seen(seen)
        return

    shutil.copy2(src, dest)
    src.unlink()

    log_event(
        level="AUDIT",
        component="Router",
        event="file_routed",
        file=src.name,
        status="success",
        message=f"'{src.name}' copied from Drop_Folder to Needs_Action.",
    )

    generate_metadata(dest, dest)

    log_event(
        level="INFO",
        component="Planner",
        event="metadata_generated",
        file=src.name,
        status="success",
        message=f"METADATA_{src.name}.md written to /Plans.",
    )

    update_dashboard(src.name, "success")

    log_event(
        level="INFO",
        component="Dashboard",
        event="dashboard_updated",
        file=src.name,
        status="success",
        message="Dashboard.md metrics updated.",
    )

    seen.add(src.name)
    save_seen(seen)


# ---------------------------------------------------------------------------
# Watcher loop
# ---------------------------------------------------------------------------

def scan_drop_folder(seen: set) -> None:
    for item in sorted(PATHS["drop"].iterdir()):
        if not item.is_file():
            continue
        if item.name.startswith("."):
            continue
        if item.name in seen:
            continue
        route_file(item, seen)


def ensure_paths() -> None:
    for path in PATHS.values():
        if isinstance(path, Path) and path.suffix == "":
            path.mkdir(parents=True, exist_ok=True)
    (VAULT_ROOT / "Rejected").mkdir(parents=True, exist_ok=True)
    (VAULT_ROOT / "Done").mkdir(parents=True, exist_ok=True)
    (VAULT_ROOT / "Approved").mkdir(parents=True, exist_ok=True)
    (VAULT_ROOT / "Pending_Approval").mkdir(parents=True, exist_ok=True)


def run() -> None:
    ensure_paths()
    seen = load_seen()

    log_event(
        level="INFO",
        component="Watcher",
        event="watcher_started",
        file="none",
        status="success",
        message=f"Bronze Tier watcher started. Polling /Drop_Folder every {POLL_INTERVAL_SECONDS}s.",
    )

    while True:
        try:
            scan_drop_folder(seen)
        except PermissionError as exc:
            log_event(
                level="ERROR",
                component="Watcher",
                event="permission_error",
                file="none",
                status="failed",
                message=str(exc),
            )
        except OSError as exc:
            log_event(
                level="ERROR",
                component="Watcher",
                event="os_error",
                file="none",
                status="failed",
                message=str(exc),
            )
        except Exception as exc:
            log_event(
                level="ERROR",
                component="Watcher",
                event="unexpected_error",
                file="none",
                status="failed",
                message=f"{type(exc).__name__}: {exc}",
            )
        time.sleep(POLL_INTERVAL_SECONDS)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run()
