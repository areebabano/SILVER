# Approval Watcher — Silver Tier

## Purpose

Monitors `/Approved/` and `/Rejected/` folders for processed approval requests. When files appear, it logs the decision, archives them to `/Done/`, and updates the Dashboard.

## How It Works

1. Polls `/Approved/` every 5 seconds for `.md` files
2. Polls `/Rejected/` every 5 seconds for `.md` files
3. **Approved files**: Logged as `APPROVED_AND_EXECUTED`, moved to `/Done/`
4. **Rejected files**: Logged as `REJECTED_NOT_EXECUTED`, prefixed with `REJECTED_`, moved to `/Done/`
5. All actions recorded in `/Logs/YYYY-MM-DD.json` and `/Dashboard.md`

## Setup

```bash
pip install python-dotenv
cp .env.example .env
# Edit .env if your vault path differs
python approval_watcher.py
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VAULT_PATH` | Auto-detected | Path to vault root |
| `APPROVAL_POLL_INTERVAL` | `5` | Seconds between polls |

## Integration

This watcher completes the HITL approval cycle:

```
Approval Gate → /Pending_Approval/ → Human moves to /Approved/ or /Rejected/
                                      → Approval Watcher detects
                                        → Logs + Archives to /Done/
```
