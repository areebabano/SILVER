# Approval Request Generator
**Gold Tier — AI Employee Agent Skill**

## Purpose
Generates Obsidian-flavoured Markdown approval requests in `/Pending_Approval`
for any sensitive action before it is executed by the MCP Action Executor.

Three automatic trigger rules plus a plan-level override:

| Rule | Trigger | Action type |
|---|---|---|
| **New contact email** | Recipient not in `known_contacts.json` | `send_email` |
| **Payment > threshold** | Dollar amount > `PAYMENT_THRESHOLD` (default $50) | `payment` |
| **Social media post** | LinkedIn post/publish action in plan | `post` |
| **Explicit approval** | Non-trivial `## Approval Required` section in plan | `approve_plan` |

---

## Folder Structure
```
Approval_Generator/
├── approval_generator.py      ← main script
├── requirements.txt
├── .env.example               ← copy to .env
├── known_contacts.json        ← trusted contacts whitelist
├── .approval_seen.json        ← auto-created; dedup registry
├── README.md                  ← this file
├── logs/                      ← auto-created
│   └── approval_generator.log
└── examples/
    ├── example_email_approval.md
    ├── example_payment_approval.md
    └── example_post_approval.md
```

---

## Setup

```bash
cd Skills/Approval_Generator
pip install -r requirements.txt
cp .env.example .env
# Edit known_contacts.json — add your trusted domains and addresses
```

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `VAULT_PATH` | `../../..` | Absolute path to vault root |
| `POLL_INTERVAL` | `60` | Seconds between passes in `--watch` mode |
| `PAYMENT_THRESHOLD` | `50.00` | Dollar amount above which a payment approval is required |
| `APPROVAL_ACTOR` | `Approval Generator (Gold Tier)` | Name in logs + Dashboard |
| `AUTO_EXPIRE_MOVE` | `false` | Move expired approvals to `/Rejected` automatically |

---

## Usage

### Automatic scan mode (reads /Plans)
```bash
python approval_generator.py           # single pass
python approval_generator.py --watch   # continuous polling
```

### Direct CLI mode (create a specific request)
```bash
# Email to new contact
python approval_generator.py \
    --action send_email \
    --recipient alice@newclient.com \
    --reason "First outreach to new prospect"

# Payment
python approval_generator.py \
    --action payment \
    --amount "$250.00" \
    --recipient "Acme Suppliers" \
    --reason "Invoice #2041 — 30-day payment terms"

# Social media post
python approval_generator.py \
    --action post \
    --reason "LinkedIn announcement: new consulting service launch"
```

---

## Output File Format

```
Pending_Approval/
└── APPROVAL_send_email_john_smith_clientco_com_20260228_100000.md
```

### Frontmatter

```yaml
---
type: approval_request
action: send_email
amount: N/A
recipient: john.smith@clientco.com
reason: Email reply to new contact — Subject: Invoice #1042
created: 2026-02-28T10:00:00Z
expires: 2026-02-28T14:00:00Z
status: pending
---
```

### Sections

| Section | Content |
|---|---|
| `## Details` | Full context: what will be sent, to whom, why it's sensitive, source plan reference |
| `## To Approve` | Step-by-step approval instructions (action-specific) |
| `## To Reject` | Move to `/Rejected` instructions + optional rejection note field |

---

## Expiry

Approval requests automatically expire if not acted on:

| Condition | Expiry |
|---|---|
| Priority HIGH | 4 hours |
| Action: `post` | 12 hours |
| Action: `payment` | 24 hours |
| Priority MEDIUM | 24 hours |
| Priority LOW | 48 hours |

On expiry, the `status` field is changed from `pending` → `expired` in-place.
If `AUTO_EXPIRE_MOVE=true`, the file is also moved to `/Rejected`.

---

## Known Contacts Whitelist

Edit `known_contacts.json` to add trusted email domains and addresses.
Recipients matching a known domain or exact address will NOT trigger an
approval request.

```json
{
  "domains":   ["mycompany.com", "trustedpartner.com"],
  "addresses": ["boss@company.com", "accountant@firm.com"]
}
```

---

## Pipeline Integration

```
/Plans/PLAN_*.md
       │
       ▼  (Approval Generator scans on every pass)
  detect_sensitive_actions()
       │
       ▼
/Pending_Approval/APPROVAL_*.md   (status: pending)
       │
       │  Human operator reviews
       ├──► Move to /Approved  + add ## Draft Reply in source plan
       └──► Move to /Rejected  + optional rejection note
       │
       ▼  (MCP Action Executor polls /Approved)
  Send email / WhatsApp / LinkedIn → move to /Done
```

---

## Log Entry Format

```json
{
  "timestamp": "2026-02-28T10:00:00Z",
  "level":     "AUDIT",
  "component": "ApprovalGenerator",
  "event":     "approval_request_created",
  "file":      "APPROVAL_send_email_john_20260228_100000.md",
  "status":    "success",
  "actor":     "Approval Generator (Gold Tier)"
}
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Approval created for a trusted contact | Add their domain or address to `known_contacts.json` |
| Payments not triggering approval | Check `PAYMENT_THRESHOLD` in `.env`; verify the plan contains a dollar amount (`$XXX`) |
| Duplicate approval requests | `.approval_seen.json` tracks processed keys; delete it to reset |
| Expired files not moving | Set `AUTO_EXPIRE_MOVE=true` in `.env` |
| "Plans folder not found" | Check `VAULT_PATH` in `.env` |
