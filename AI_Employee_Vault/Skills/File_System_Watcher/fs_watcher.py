#!/usr/bin/env python3
"""
File System Watcher — Silver Tier Agent Skill
=============================================
Watches a drop folder (default: vault /Inbox) for newly created files.
When a file appears it is:
  1. Copied to /Needs_Action with a timestamp prefix.
  2. Accompanied by a Markdown metadata note describing the file.

Usage:
    python fs_watcher.py

Requirements:
    pip install -r requirements.txt
    Copy .env.example → .env and adjust VAULT_PATH / DROP_FOLDER.
"""

import logging
import mimetypes
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from watchdog.events import FileCreatedEvent, FileSystemEventHandler
from watchdog.observers import Observer

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)-8s]  %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "fs_watcher.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("fs_watcher")

# ── Environment ───────────────────────────────────────────────────────────────
# Load vault root .env first, then skill-local .env as override
_VAULT_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
_SKILL_LOCAL_ENV = Path(__file__).resolve().parent / ".env"
load_dotenv(_VAULT_ROOT_ENV)
load_dotenv(_SKILL_LOCAL_ENV, override=True)

# ── Configuration ─────────────────────────────────────────────────────────────

VAULT_PATH   = Path(os.getenv("VAULT_PATH", str(Path(__file__).parent.parent.parent)))
DROP_FOLDER  = Path(os.getenv("DROP_FOLDER", str(VAULT_PATH / "Inbox")))
NEEDS_ACTION = VAULT_PATH / "Needs_Action"

_raw_ext     = os.getenv(
    "WATCH_EXTENSIONS",
    ".pdf,.docx,.xlsx,.txt,.png,.jpg,.jpeg,.csv,.zip,.mp3,.mp4"
)
WATCH_EXT    = {e.strip().lower() for e in _raw_ext.split(",") if e.strip()}


# ── Helpers ───────────────────────────────────────────────────────────────────

def safe_filename(text: str, max_len: int = 60) -> str:
    return re.sub(r'[\\/:*?"<>|\r\n\t]', "_", text).strip()[:max_len]


def human_size(num_bytes: int) -> str:
    """Return a human-readable file size string."""
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} TB"


def guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def file_category(ext: str) -> str:
    """Map an extension to a friendly category label."""
    mapping = {
        "document":    {".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md"},
        "spreadsheet": {".xls", ".xlsx", ".csv", ".ods"},
        "image":       {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp"},
        "archive":     {".zip", ".tar", ".gz", ".rar", ".7z"},
        "audio":       {".mp3", ".wav", ".ogg", ".flac", ".m4a"},
        "video":       {".mp4", ".mov", ".avi", ".mkv", ".webm"},
    }
    for category, exts in mapping.items():
        if ext.lower() in exts:
            return category
    return "file"


# ── Action file writer ────────────────────────────────────────────────────────

def write_metadata_file(original: Path, dest: Path) -> Path:
    """Create a Markdown metadata note alongside the copied file."""
    NEEDS_ACTION.mkdir(parents=True, exist_ok=True)

    ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"FILE_{ts}_{safe_filename(original.stem)}.md"
    fpath = NEEDS_ACTION / fname

    try:
        size_bytes = dest.stat().st_size
    except OSError:
        size_bytes = 0

    ext      = original.suffix.lower()
    mime     = guess_mime(original)
    category = file_category(ext)

    md = f"""---
type: file_received
status: needs_action
source: file_system_watcher
created: {datetime.now().isoformat()}
file_name: "{original.name}"
file_type: "{ext}"
mime_type: "{mime}"
file_size: "{human_size(size_bytes)}"
category: "{category}"
---

# File Drop — Action Required

## File Details

| Field             | Value |
|-------------------|-------|
| **Original Name** | `{original.name}` |
| **Category**      | {category.capitalize()} |
| **File Type**     | `{ext.upper() or "unknown"}` |
| **MIME Type**     | `{mime}` |
| **Size**          | {human_size(size_bytes)} |
| **Dropped At**    | {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} |
| **Copied To**     | `{dest.name}` |

## Suggested Actions

- [ ] **Review** — Open and review the file contents
- [ ] **Process** — Take required action based on file type
- [ ] **File Away** — Move to the appropriate project folder
- [ ] **Archive** — Handled → move this note to `/Done`
- [ ] **Delete** — Not relevant, discard file and note

## Notes

> _Add your notes or follow-up context here_

---
*Auto-created by File System Watcher · {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}*
"""

    fpath.write_text(md, encoding="utf-8")
    log.info(f"Metadata note created  →  {fpath.name}")
    return fpath


# ── File processor ────────────────────────────────────────────────────────────

def process_file(src: Path) -> None:
    """Copy a dropped file to /Needs_Action and create its metadata note."""
    if src.suffix.lower() not in WATCH_EXT:
        log.debug("Skipped (extension not in watch list): %s", src.name)
        return

    NEEDS_ACTION.mkdir(parents=True, exist_ok=True)

    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = NEEDS_ACTION / f"{ts}_{src.name}"

    try:
        shutil.copy2(src, dest)
        log.info(f"Copied  {src.name}  →  {dest.name}")
        write_metadata_file(src, dest)
    except PermissionError:
        log.error("Permission denied copying: %s", src.name)
    except Exception as exc:
        log.error("Failed to process %s: %s", src.name, exc)


# ── Watchdog event handler ────────────────────────────────────────────────────

class DropFolderHandler(FileSystemEventHandler):
    def on_created(self, event: FileCreatedEvent) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        src = Path(event.src_path)
        log.info("New file detected: %s", src.name)
        # Brief pause to let the OS finish writing the file before we copy it
        time.sleep(0.8)
        process_file(src)


# ── Entry point ───────────────────────────────────────────────────────────────

def run() -> None:
    DROP_FOLDER.mkdir(parents=True, exist_ok=True)
    NEEDS_ACTION.mkdir(parents=True, exist_ok=True)

    log.info("=" * 62)
    log.info("  File System Watcher  —  Silver Tier Agent Skill")
    log.info(f"  Watching      : {DROP_FOLDER}")
    log.info(f"  Needs_Action  : {NEEDS_ACTION}")
    log.info(f"  Watched exts  : {', '.join(sorted(WATCH_EXT))}")
    log.info("=" * 62)

    handler  = DropFolderHandler()
    observer = Observer()
    observer.schedule(handler, str(DROP_FOLDER), recursive=False)
    observer.start()
    log.info("Observer running. Drop files into:  %s", DROP_FOLDER)
    log.info("Press Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Stopped by user.")
    finally:
        observer.stop()
        observer.join()
        log.info("Observer stopped.")


if __name__ == "__main__":
    run()
