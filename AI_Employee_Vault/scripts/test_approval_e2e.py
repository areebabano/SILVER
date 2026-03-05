#!/usr/bin/env python3
"""E2E test for Approval Gate + Approval Watcher."""
import os, sys, json
from pathlib import Path
from datetime import datetime, timezone

os.environ['VAULT_PATH'] = 'D:\\AI_Employee_Vault'
VAULT = Path('D:/AI_Employee_Vault')

# ═══════════════════════════════════════════════════════════
# APPROVAL GATE TESTS
# ═══════════════════════════════════════════════════════════
print('=== APPROVAL GATE — E2E TEST ===')
print()

plans_dir = VAULT / 'Plans'
pending = VAULT / 'Pending_Approval'

# Create 3 test plans
(plans_dir / 'PLAN_GATE_TEST_PASS.md').write_text("""---
status: pending_approval
priority: HIGH
source_type: email
source_file: EMAIL_gate_test.md
---

# Reply to gate test email

> **Priority:** HIGH | **From:** client@gatetest.com

## Objective
Reply to email from client@gatetest.com about project update.

## Draft Reply
Thank you for your email. The project is on track.

## Steps
1. Send reply
""", encoding='utf-8')

(plans_dir / 'PLAN_GATE_TEST_LOW.md').write_text("""---
status: pending_approval
priority: LOW
source_type: email
source_file: EMAIL_gate_low.md
---

# Low priority email
## Objective
Low priority — should NOT trigger gate.
""", encoding='utf-8')

(plans_dir / 'PLAN_GATE_TEST_NOMAIL.md').write_text("""---
status: pending_approval
priority: HIGH
source_type: file
source_file: FILE_gate_nomail.md
---

# File task — not email
## Objective
Should NOT trigger gate.
""", encoding='utf-8')

# Clear old test approvals
for f in pending.glob('APPROVAL_*GATE_TEST*.md'):
    f.unlink()

# Run gate
sys.path.insert(0, str(VAULT / 'Skills' / 'Approval_Gate'))
from approval_gate import scan_plans
created = scan_plans()

# Check results
pass_approvals = list(pending.glob('APPROVAL_*GATE_TEST_PASS*.md'))
low_approvals = list(pending.glob('APPROVAL_*GATE_TEST_LOW*.md'))
nomail_approvals = list(pending.glob('APPROVAL_*GATE_TEST_NOMAIL*.md'))

t1 = len(pass_approvals) > 0
t2 = len(low_approvals) == 0
t3 = len(nomail_approvals) == 0

print(f'T1  HIGH+email creates approval:  {"PASS" if t1 else "FAIL"}')
print(f'T2  LOW+email skipped:            {"PASS" if t2 else "FAIL"}')
print(f'T3  HIGH+file skipped:            {"PASS" if t3 else "FAIL"}')

# Check frontmatter
t4=t5=t6=t7=t8=False
if pass_approvals:
    ac = pass_approvals[0].read_text(encoding='utf-8')
    t4 = 'expires:' in ac
    t5 = 'reason:' in ac
    t6 = 'to_email: client@gatetest.com' in ac
    t7 = '## Draft Reply' in ac
    t8 = 'status: pending' in ac
print(f'T4  expires: field:               {"PASS" if t4 else "FAIL"}')
print(f'T5  reason: field:                {"PASS" if t5 else "FAIL"}')
print(f'T6  Recipient resolved:           {"PASS" if t6 else "FAIL"}')
print(f'T7  Draft Reply included:         {"PASS" if t7 else "FAIL"}')
print(f'T8  status: pending:              {"PASS" if t8 else "FAIL"}')

# Duplicate guard
created2 = scan_plans()
t9 = created2 == 0
print(f'T9  Duplicate blocked:            {"PASS" if t9 else "FAIL"}')

# Vault log
today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
log_file = VAULT / 'Logs' / f'{today}.json'
t10 = False
if log_file.exists():
    data = json.loads(log_file.read_text(encoding='utf-8'))
    t10 = any(e.get('component') == 'ApprovalGate' and 'GATE_TEST' in e.get('file', '') for e in data.get('entries', []))
print(f'T10 Vault log created:            {"PASS" if t10 else "FAIL"}')

gate_tests = [t1,t2,t3,t4,t5,t6,t7,t8,t9,t10]
print(f'\nApproval Gate: {sum(gate_tests)}/{len(gate_tests)} PASSED')

# ═══════════════════════════════════════════════════════════
# APPROVAL WATCHER TESTS
# ═══════════════════════════════════════════════════════════
print()
print('=== APPROVAL WATCHER — E2E TEST ===')
print()

sys.path.insert(0, str(VAULT / 'Skills' / 'Approval_Watcher'))
from approval_watcher import process_approved, process_rejected, DONE_DIR

approved_dir = VAULT / 'Approved'
rejected_dir = VAULT / 'Rejected'
DONE_DIR.mkdir(exist_ok=True)

# Create test files
(approved_dir / 'TEST_WATCHER_APPROVE.md').write_text("---\ntype: approval_request\nstatus: approved\n---\nApproved test\n", encoding='utf-8')
(rejected_dir / 'TEST_WATCHER_REJECT.md').write_text("---\ntype: approval_request\nstatus: rejected\n---\nRejected test\n", encoding='utf-8')

done_before = set(f.name for f in DONE_DIR.glob('*.md'))

a_count = process_approved()
r_count = process_rejected()

done_after = set(f.name for f in DONE_DIR.glob('*.md'))
new_done = done_after - done_before

w_t1 = 'TEST_WATCHER_APPROVE.md' in new_done
w_t2 = not (approved_dir / 'TEST_WATCHER_APPROVE.md').exists()
w_t3 = any('REJECTED_TEST_WATCHER_REJECT' in f for f in new_done)
w_t4 = not (rejected_dir / 'TEST_WATCHER_REJECT.md').exists()
w_t5 = any(f.startswith('REJECTED_') and 'WATCHER_REJECT' in f for f in new_done)

# Log entries
w_t6 = w_t7 = False
if log_file.exists():
    data = json.loads(log_file.read_text(encoding='utf-8'))
    entries = data.get('entries', [])
    w_t6 = any(e.get('event') == 'APPROVED_AND_EXECUTED' and 'WATCHER_APPROVE' in e.get('file', '') for e in entries)
    w_t7 = any(e.get('event') == 'REJECTED_NOT_EXECUTED' and 'WATCHER_REJECT' in e.get('file', '') for e in entries)

print(f'T1  Approved archived to Done:    {"PASS" if w_t1 else "FAIL"}')
print(f'T2  Removed from /Approved:       {"PASS" if w_t2 else "FAIL"}')
print(f'T3  Rejected archived to Done:    {"PASS" if w_t3 else "FAIL"}')
print(f'T4  Removed from /Rejected:       {"PASS" if w_t4 else "FAIL"}')
print(f'T5  REJECTED_ prefix applied:     {"PASS" if w_t5 else "FAIL"}')
print(f'T6  Approve logged to JSON:       {"PASS" if w_t6 else "FAIL"}')
print(f'T7  Reject logged to JSON:        {"PASS" if w_t7 else "FAIL"}')

watcher_tests = [w_t1, w_t2, w_t3, w_t4, w_t5, w_t6, w_t7]
print(f'\nApproval Watcher: {sum(watcher_tests)}/{len(watcher_tests)} PASSED')

# Cleanup
for name in ['PLAN_GATE_TEST_PASS.md', 'PLAN_GATE_TEST_LOW.md', 'PLAN_GATE_TEST_NOMAIL.md']:
    (plans_dir / name).unlink(missing_ok=True)
for f in pending.glob('APPROVAL_*GATE_TEST*.md'):
    f.unlink()
for f in DONE_DIR.glob('*WATCHER*'):
    f.unlink()
print('\nTest artifacts cleaned up.')
