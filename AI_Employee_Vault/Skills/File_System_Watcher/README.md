# File System Watcher
**Bronze Tier — AI Employee Agent Skill**

## Purpose
Monitors a local **drop folder** (default: vault `/Inbox`) for newly created files. When a file appears it is:
1. **Copied** to `/Needs_Action` with a timestamp prefix.
2. Accompanied by a **Markdown metadata note** containing the file name, type, MIME type, size, and suggested action checkboxes.

---

## Folder Structure
```
File_System_Watcher/
├── fs_watcher.py         ← main script
├── requirements.txt
├── .env.example          ← copy to .env and fill in values
├── README.md             ← this file
├── logs/                 ← created automatically at runtime
│   └── fs_watcher.log
└── examples/
    └── example_file_action.md
```

---

## Setup

### 1 · Install dependencies
```bash
pip install -r requirements.txt
```

### 2 · Configure `.env`
```bash
cd Skills/File_System_Watcher
cp .env.example .env
# Edit .env — at minimum set VAULT_PATH
```

### 3 · Run
```bash
python fs_watcher.py
```
Press `Ctrl+C` to stop.

---

## Configuration

| Variable            | Default              | Description                                        |
|---------------------|----------------------|----------------------------------------------------|
| `VAULT_PATH`        | `../../..`           | Absolute path to your Obsidian vault root          |
| `DROP_FOLDER`       | `<vault>/Inbox`      | Folder to monitor for new files                    |
| `WATCH_EXTENSIONS`  | `.pdf,.docx,.xlsx,.txt,.png,.jpg,.jpeg,.csv,.zip,.mp3,.mp4` | Extensions to process; others are ignored |

---

## How It Works

1. Uses the `watchdog` library to listen for `FileCreatedEvent` events in `DROP_FOLDER`.
2. When a new file appears, waits 0.8 s for the OS to finish writing it, then:
   - Copies it to `/Needs_Action` as `YYYYMMDD_HHMMSS_<original_name>`.
   - Creates a companion `.md` metadata note: `FILE_YYYYMMDD_HHMMSS_<stem>.md`.
3. Files whose extension is not in `WATCH_EXTENSIONS` are silently skipped.
4. All activity is logged.

---

## Output

For every processed file, two items appear in `/Needs_Action`:

```
Needs_Action/
├── 20260224_103045_Q1_Report.pdf          ← copied file
└── FILE_20260224_103045_Q1_Report.md      ← metadata note
```

The metadata note contains:
- YAML front matter (`type`, `status`, `source`, `created`, file metadata)
- Details table: original name, category, type, MIME type, size, timestamps
- Suggested action checkboxes: Review / Process / File Away / Archive / Delete
- Free-text Notes section

Once handled, tick the checkbox and move the `.md` note to `/Done`.
You can also delete or move the copied file as appropriate.

---

## Logging
All activity is written to `logs/fs_watcher.log` and echoed to the terminal.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Files dropped but no action created | Check `WATCH_EXTENSIONS` — the extension must be in the list |
| `PermissionError` when copying | Ensure the script has read access to `DROP_FOLDER` and write access to `Needs_Action` |
| Watcher misses files | Some editors write to a temp file then rename — use `on_moved` event in addition to `on_created` if needed |
| `ModuleNotFoundError: watchdog` | Run `pip install -r requirements.txt` |
