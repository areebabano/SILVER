# Silver Tier Workflow — Test Report

**Date:** 2026-03-03
**Tester:** AI Employee (Gold Tier) — Automated Testing
**Environment:** D:\AI_Employee_Vault (Windows 10, Python 3.13)
**DRY_RUN:** True (no real emails sent)

---

## Executive Summary

**Overall Verdict: FAIL — Silver Tier is NOT ready for production**

The Silver Tier pipeline has a **critical integration bug** between the Approval Gate
(output) and the Action Executor (input). Every approval file processed by the Action
Executor fails with "Recipient address is empty" — even when the recipient IS known.
The root cause is a **frontmatter schema mismatch** between the two components.

Additionally, 4 secondary bugs and 2 minor issues were discovered.

---

## Test Results Summary

| # | Test Case                    | Result   | Severity |
|---|------------------------------|----------|----------|
| 1 | Plan Detection               | PASS     | —        |
| 2 | Recipient Validation         | PARTIAL  | Medium   |
| 3 | Draft Reply Generation       | FAIL     | Critical |
| 4 | Action Executor (DRY_RUN)    | FAIL     | Critical |
| 5 | Error Handling               | PASS     | —        |
| 6 | Vault Logging                | PASS     | —        |
| 7 | File System Behavior         | PASS     | —        |

**Pass: 4 | Partial: 1 | Fail: 2**

---

## Detailed Test Results

### TC-1: Plan Detection — PASS

**What was tested:**
- Approval Gate scans `/Plans` for `PLAN_*.md` files matching all three criteria:
  `status: pending_approval` + `priority: HIGH` + `source_type: email`

**Expected:** Gate detects `PLAN_EMAIL_TEST_SILVER.md` and creates an approval request.
**Actual:** Gate correctly detected the plan, created `APPROVAL_PLAN_EMAIL_TEST_SILVER_20260228_221751.md` in `/Pending_Approval`.

**Duplicate Detection:**
- **Expected:** Re-running the gate should NOT create a duplicate.
- **Actual:** Second run returned "0 new approval request(s) created" — duplicate guard works correctly.

**Multiple Plan Handling:**
- Tested with 3 plan files simultaneously (valid, no-recipient, malformed).
- Gate processed only those matching all 3 criteria; METADATA_*.md files correctly skipped.

**Sub-finding (BUG-5, Low):**
- Default `VAULT_PATH` in `approval_gate.py` uses `../../..` (3 levels up), which resolves to
  `D:\` instead of `D:\AI_Employee_Vault`. Requires `VAULT_PATH` env var to be set explicitly.
  Action Executor uses `Path(__file__).parent.parent` which resolves correctly.

---

### TC-2: Recipient Validation — PARTIAL PASS

**What was tested:**
- Gate extracts recipient from source file `from:` field, plan `**From:**` callout,
  or email pattern in Objective section.

**Test 2a — Valid recipient:**
- **Expected:** Extract `client@test.com` from plan text.
- **Actual:** Correctly extracted `client@test.com`. PASS.

**Test 2b — Missing recipient (no source file, no From field):**
- **Expected:** Log a warning and either block the approval or flag it clearly.
- **Actual:** Gate silently set `recipient: unknown` and created the approval anyway.
  No warning was logged. PARTIAL — the "unknown" recipient is only caught downstream
  by the Action Executor.

**Sub-finding (BUG-6, Medium):**
- The Approval Gate should validate that `recipient != "unknown"` and log a WARNING
  before creating the approval. Currently it silently passes through.

---

### TC-3: Draft Reply Generation — FAIL

**What was tested:**
- Action Executor extracts draft reply from `## Draft Reply`, `## Suggested Reply`,
  or `## Reply` sections in the approved file.

**Expected:** Executor reads draft from the source plan or generates a clear fallback.
**Actual:** Executor searches the APPROVAL file body for `## Draft Reply` — but
approval files contain `## Reason`, `## To Approve`, `## To Reject` (NOT draft replies).

The warning logged was:
```
No Draft Reply section found in APPROVAL_PLAN_EMAIL_TEST_SILVER_20260228_200951.md
— using generic template.
```

**Root Cause:**
The Approval Gate creates minimal approval files with no draft content. The Action
Executor looks for the draft in the file it's processing (the approval file), NOT in
the original plan file or source email. The generic fallback template is used every time:
```
Hi, Thank you for your message. I have reviewed your request and will follow up
shortly with further details. Kind regards, [YOUR NAME]
```

**Impact:** No human-written or AI-suggested reply is ever sent. Only the generic
fallback template would be dispatched.

---

### TC-4: Action Executor (DRY_RUN) — FAIL

**What was tested:**
- Process approved files in DRY_RUN mode.
- Verify no real emails are sent, correct logging, correct action type resolution.

**Expected:** DRY_RUN logs "Would send EMAIL to 'client@test.com'" with a preview.
**Actual:** ALL 3 approved files FAILED with:
```
Action FAILED [APPROVAL_REQUEST] → ... Recipient address is empty.
```

**Three root causes identified:**

#### BUG-1 (CRITICAL): Action Type Mismatch

The Approval Gate writes:
```yaml
type: approval_request
action: send_email
```

The Action Executor resolves action_type via:
```python
action_type = fm.get("source_type", fm.get("type", "unknown")).lower()
```

Since the approval file has NO `source_type` key, it falls back to
`fm.get("type")` = `"approval_request"`. The action type becomes
`"approval_request"` instead of `"email"`.

Even if the recipient were found, dispatch would fail with:
```
Unknown action type 'approval_request'. Supported: email, whatsapp, linkedin.
```

**Fix needed:** The approval file should include `source_type: email` OR the
executor should read the `action:` field (which IS `send_email`).

#### BUG-2 (CRITICAL): Recipient Field Name Mismatch

The Approval Gate writes: `recipient: client@test.com`
The Action Executor looks for: `to_email:` or `to:` (via `fm.get("to_email", fm.get("to", ""))`)

The executor NEVER checks the `recipient:` frontmatter key.

**Fix needed:** The executor should check `fm.get("recipient")` as a fallback,
OR the approval file should use `to_email:` instead of `recipient:`.

#### BUG-3 (CRITICAL): No Source File Linkage

The Approval Gate writes: `source_plan: PLAN_EMAIL_TEST_SILVER.md`
The Action Executor looks for: `source_file:` (to find the original email in `/Needs_Action`)

The approval file has NO `source_file` key. Without it:
- The executor can't read the source email's `from:` field (primary recipient source)
- The executor can't read the source email's `subject:` field
- The executor can't find the draft reply from the source plan

**Fix needed:** The approval file should propagate `source_file` from the original
plan, OR the executor should resolve through `source_plan` → read the plan's
`source_file` field.

---

### TC-5: Error Handling — PASS

**What was tested:**
- Missing fields in plan file (no source_file, no recipient, no objective)
- Action Executor response to empty recipient
- Log entries for error conditions

**Expected:** Clear error messages, no crashes, no KeyErrors, proper logging.
**Actual:**
- Approval Gate: No crash on malformed plans. Creates approval with `recipient: unknown`.
- Action Executor: Clear error message about empty recipient. No KeyError (previous
  fix verified). All errors properly logged with full context.
- JSON log files validated: proper structure, entries array populated.

**Note:** The KeyError fix from the previous session (adding `entries` key guard)
was confirmed working — JSON logs always have a valid `entries` array.

---

### TC-6: Vault Logging — PASS

**What was tested:**
- All actions logged to `/Logs/YYYY-MM-DD.json`
- JSON structure validity
- Entry field completeness

**Actual results:**
```
Valid JSON: True
Has entries key: True
Entries is list: True
Entry count: 7
All entries have timestamp: True
All entries have level: True
All entries have component: True
```

Both AUDIT (ApprovalGate) and ERROR (ActionExecutor) entries are correctly formatted
with timestamp, level, component, event, file, status, message, and actor fields.

The `entries` key guard (added in prior fix) prevents KeyError — CONFIRMED working.

---

### TC-7: File System Behavior — PASS

**What was tested:**
- Files remain in `/Approved` during DRY_RUN (not moved to `/Done`)
- Folder structure integrity maintained
- Seen registry updated correctly

**Expected:** No file moves during DRY_RUN.
**Actual:**
- All 3 files remained in `/Approved` after DRY_RUN execution.
- `/Done` directory empty (correct for DRY_RUN + failed actions).
- Seen registry updated with all 3 filenames (prevents re-processing).
- `/Pending_Approval`, `/Plans`, `/Rejected` all maintained correctly.

---

## Bug Registry

| ID    | Severity | Component        | Description                                            |
|-------|----------|------------------|--------------------------------------------------------|
| BUG-1 | CRITICAL | Action Executor  | Action type resolves to `approval_request` instead of `email` — frontmatter key mismatch (`type` vs `source_type`) |
| BUG-2 | CRITICAL | Action Executor  | Recipient not found — executor checks `to_email`/`to` but approval file uses `recipient` |
| BUG-3 | CRITICAL | Integration      | No `source_file` in approval file — executor can't resolve source email for `from`, `subject`, draft |
| BUG-4 | MEDIUM   | Draft Reply      | Executor searches approval file body for `## Draft Reply` but it only exists in the plan file |
| BUG-5 | LOW      | Approval Gate    | Default `VAULT_PATH = ../../..` resolves to `D:\` — requires env var to work |
| BUG-6 | MEDIUM   | Approval Gate    | No warning when `recipient` resolves to `"unknown"` — silently creates approval |
| BUG-7 | LOW      | Both Scripts     | Unicode arrow `→` in log messages causes `UnicodeEncodeError` on Windows cp1252 console |

---

## Recommended Fixes

### Fix 1: Approval File Schema (fixes BUG-1, BUG-2, BUG-3, BUG-4)

Update `approval_gate.py` `write_approval()` to propagate fields from the source plan:

```yaml
---
type: approval_request
action: send_email
source_type: email                    # ADD: propagate from plan
source_file: EMAIL_TEST_SILVER.md     # ADD: propagate from plan
recipient: client@test.com
to_email: client@test.com             # ADD: alias for executor compatibility
source_plan: PLAN_EMAIL_TEST_SILVER.md
created: 2026-02-28T20:09:51Z
status: pending
priority: HIGH                        # ADD: propagate from plan
---
```

### Fix 2: Action Executor Recipient Fallback (fixes BUG-2)

In `action_executor.py` `build_action_packet()`, add `recipient` as a fallback:

```python
to_field = to_field or fm.get("to_email", fm.get("to", fm.get("recipient", ""))).strip()
```

### Fix 3: Action Executor Action Type Resolution (fixes BUG-1)

Add `action` field parsing:

```python
action_type = fm.get("source_type", "").lower()
if not action_type or action_type == "unknown":
    action_raw = fm.get("action", fm.get("type", "unknown")).lower()
    action_type = action_raw.replace("send_", "")  # "send_email" → "email"
```

### Fix 4: Source File Chain Resolution (fixes BUG-3, BUG-4)

If `source_file` is missing but `source_plan` exists, read the plan to get `source_file`:

```python
if not source_name and fm.get("source_plan"):
    plan_path = VAULT_PATH / "Plans" / fm["source_plan"]
    if plan_path.exists():
        plan_fm = parse_front_matter(plan_path.read_text(encoding="utf-8"))
        source_name = plan_fm.get("source_file", "")
```

### Fix 5: VAULT_PATH Default (fixes BUG-5)

In `approval_gate.py`, change:
```python
VAULT_PATH = Path(os.getenv("VAULT_PATH", "../../..")).resolve()
```
To:
```python
VAULT_PATH = Path(os.getenv("VAULT_PATH", str(Path(__file__).resolve().parent.parent.parent))).resolve()
```

### Fix 6: Recipient Validation Warning (fixes BUG-6)

In `approval_gate.py` `scan_plans()`, after recipient resolution:
```python
if recipient == "unknown":
    log.warning("Could not resolve recipient for %s — approval will need manual recipient", plan_path.name)
```

### Fix 7: Unicode Console Fix (fixes BUG-7)

Replace `→` with `->` in log format strings, or set console encoding:
```python
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
```

---

## What Works Correctly

1. Plan detection and 3-criteria filtering (status + priority + source_type)
2. Duplicate approval guard (prevents re-creating existing pending approvals)
3. JSON vault logging with `entries` array (KeyError fix confirmed)
4. DRY_RUN mode correctly prevents file moves and real email dispatch
5. Error logging with full context (timestamps, component, actor, dry_run flag)
6. Seen registry prevents re-processing of already-handled files
7. File system integrity maintained across all operations
8. Dashboard.md metrics updated on each action

---

## Conclusion

The Silver Tier pipeline is **architecturally sound** but has a **critical integration
gap** between its two main components. The Approval Gate produces approval files in a
format that the Action Executor cannot consume. This means **every approved email will
fail** — the system can detect plans and create approvals, but it cannot execute them.

**Recommended priority:**
1. Apply Fixes 1-4 (critical path — enables end-to-end execution)
2. Apply Fix 5 (VAULT_PATH — prevents startup failures)
3. Apply Fixes 6-7 (quality improvements)

After applying fixes, re-run this test suite to validate the complete pipeline
end-to-end with DRY_RUN=true before going live.

---

*Report generated by AI Employee (Gold Tier) — 2026-03-03*
