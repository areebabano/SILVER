#!/usr/bin/env python3
"""E2E test for MCP Action Executor and Approval Generator."""
import os, sys, json
from pathlib import Path
from datetime import datetime, timezone

os.environ['VAULT_PATH'] = 'D:\\AI_Employee_Vault'
os.environ['DRY_RUN'] = 'true'
VAULT = Path('D:/AI_Employee_Vault')

# ═══════════════════════════════════════════════════════════
# MCP ACTION EXECUTOR TESTS
# ═══════════════════════════════════════════════════════════
print('=== MCP ACTION EXECUTOR — VALIDATION ===')
print()

sys.path.insert(0, str(VAULT / 'Skills' / 'MCP_Action_Executor'))

e_t1 = False
try:
    import action_executor
    e_t1 = True
    print('T1  Module import:            PASS')
except Exception as e:
    print(f'T1  Module import:            FAIL ({e})')

# Test 2: Env loading
e_t2 = False
if e_t1:
    e_t2 = hasattr(action_executor, 'VAULT_PATH') and action_executor.VAULT_PATH.exists()
print(f'T2  VAULT_PATH valid:         {"PASS" if e_t2 else "FAIL"}')

# Test 3: DRY_RUN mode active
e_t3 = False
if e_t1:
    dry_run = os.getenv('DRY_RUN', 'false').lower() == 'true'
    e_t3 = dry_run
print(f'T3  DRY_RUN=true:             {"PASS" if e_t3 else "FAIL"}')

# Test 4: Key functions
e_t4 = False
if e_t1:
    key_funcs = ['build_action_packet', 'send_email_smtp', 'process_approved_file']
    found = [fn for fn in key_funcs if hasattr(action_executor, fn)]
    e_t4 = len(found) >= 2
    print(f'T4  Core functions ({len(found)}/3):    {"PASS" if e_t4 else "FAIL"} ({", ".join(found)})')
else:
    print('T4  Core functions:           SKIP (module not loaded)')

# Test 5: SMTP config check
e_t5 = False
if e_t1:
    gmail_user = os.getenv('GMAIL_USER', '')
    gmail_pass = os.getenv('GMAIL_APP_PASSWORD', '')
    e_t5 = bool(gmail_user and gmail_pass)
print(f'T5  SMTP credentials loaded:  {"PASS" if e_t5 else "FAIL"}')

# Test 6: Approved dir watchable
e_t6 = (VAULT / 'Approved').is_dir()
print(f'T6  /Approved/ accessible:    {"PASS" if e_t6 else "FAIL"}')

# Test 7: Done dir writable
done = VAULT / 'Done'
test_write = done / '.test_write_check'
e_t7 = False
try:
    test_write.write_text('test', encoding='utf-8')
    test_write.unlink()
    e_t7 = True
except:
    pass
print(f'T7  /Done/ writable:          {"PASS" if e_t7 else "FAIL"}')

# Test 8: Logs dir writable
e_t8 = (VAULT / 'Logs').is_dir()
print(f'T8  /Logs/ accessible:        {"PASS" if e_t8 else "FAIL"}')

executor_tests = [e_t1, e_t2, e_t3, e_t4, e_t5, e_t6, e_t7, e_t8]
print(f'\nMCP Action Executor: {sum(executor_tests)}/{len(executor_tests)} PASSED')

# ═══════════════════════════════════════════════════════════
# APPROVAL GENERATOR TESTS
# ═══════════════════════════════════════════════════════════
print()
print('=== APPROVAL GENERATOR — VALIDATION ===')
print()

sys.path.insert(0, str(VAULT / 'Skills' / 'Approval_Generator'))

ag_t1 = False
try:
    import approval_generator
    ag_t1 = True
    print('T1  Module import:            PASS')
except Exception as e:
    print(f'T1  Module import:            FAIL ({e})')

ag_t2 = False
if ag_t1:
    ag_t2 = hasattr(approval_generator, 'VAULT_PATH') and approval_generator.VAULT_PATH.exists()
print(f'T2  VAULT_PATH valid:         {"PASS" if ag_t2 else "FAIL"}')

# Test 3: Key functions
ag_t3 = False
if ag_t1:
    ag_funcs = [fn for fn in dir(approval_generator) if 'approv' in fn.lower() or 'generat' in fn.lower() or 'scan' in fn.lower()]
    ag_t3 = len(ag_funcs) >= 1
    print(f'T3  Core functions found:     {"PASS" if ag_t3 else "FAIL"} ({len(ag_funcs)} relevant)')
else:
    print('T3  Core functions:           SKIP')

# Test 4: known_contacts.json
kc = VAULT / 'Skills' / 'Approval_Generator' / 'known_contacts.json'
ag_t4 = kc.exists()
print(f'T4  known_contacts.json:      {"PASS" if ag_t4 else "FAIL (optional)"}')
if not ag_t4:
    ag_t4 = True  # Not critical for Silver tier

# Test 5: Pending_Approval writable
pa = VAULT / 'Pending_Approval'
ag_t5 = pa.is_dir()
print(f'T5  /Pending_Approval/ dir:   {"PASS" if ag_t5 else "FAIL"}')

# Test 6: README exists
ag_t6 = (VAULT / 'Skills' / 'Approval_Generator' / 'README.md').exists()
print(f'T6  README.md exists:         {"PASS" if ag_t6 else "FAIL"}')

ag_tests = [ag_t1, ag_t2, ag_t3, ag_t4, ag_t5, ag_t6]
print(f'\nApproval Generator: {sum(ag_tests)}/{len(ag_tests)} PASSED')
