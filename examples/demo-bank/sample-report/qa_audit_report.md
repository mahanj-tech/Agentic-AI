# QA Audit — http://localhost:8080

Requirements: 7 passed, 4 failed, 0 unverified · Scenarios: 16 · Defects: 5 · LLM cost: $0.0000

| Req | Title | Verdict | Basis |
|---|---|---|---|
| REQ-01 | Enter Demo opens dashboard | PASSED | all 1 scenarios passed (normal) |
| REQ-02 | Accounts shown with formatted balances | PASSED | all 1 scenarios passed (normal) |
| REQ-03 | Main navigation | PASSED | all 1 scenarios passed (normal) |
| REQ-04 | Transfer moves exact amount | FAILED | 1 of 2 scenarios failed: Cents are transferred exactly (10.55) |
| REQ-05 | Transfer creates debit and credit records | PASSED | all 1 scenarios passed (normal) |
| REQ-06 | Amount must be positive with max 2 decimals | FAILED | 2 of 4 scenarios failed: Negative amount is rejected; Three decimal places are rejected (1.005) |
| REQ-07 | Insufficient funds rejected | FAILED | 1 of 1 scenarios failed: Overdraft is rejected with Insufficient funds |
| REQ-08 | From and To must differ | PASSED | all 1 scenarios passed (negative) |
| REQ-09 | Empty amount validation | PASSED | all 1 scenarios passed (negative) |
| REQ-10 | Transactions newest first | PASSED | all 1 scenarios passed (normal) |
| REQ-11 | Type filter shows only selected type | FAILED | 1 of 2 scenarios failed: Debit filter shows only debits |

## Defects

### BUG-01 [HIGH] Not met: Cents are transferred exactly (10.55)
Scenario SC-04-b · requirements REQ-04

**Steps to reproduce**
1. Open http://localhost:8080 and click 'Enter Demo'
2. Click 'Transfer' in the top navigation
3. Read 'testid=balance-chk' as chk_before  → read 2425.75
4. Read 'testid=balance-sav' as sav_before  → read 10225.0
5. Select 'Everyday Checking (****4021)' in 'label=From account'
6. Select 'High-Yield Savings (****7788)' in 'label=To account'
7. Enter '10.55' into 'label=Amount'
8. Click the 'Transfer' submit button
9. Read 'testid=balance-chk' as chk_after  → read 2415.2
10. Read 'testid=balance-sav' as sav_after  → read 10235.0

**Expected:** Both balances move by exactly 10.55.

**Observed:** sav_after=10235.0, sav_before=10225.0

### BUG-02 [HIGH] Not met: Negative amount is rejected
Scenario SC-06-a · requirements REQ-06

**Steps to reproduce**
1. Open http://localhost:8080 and click 'Enter Demo'
2. Click 'Transfer' in the top navigation
3. Read 'testid=balance-chk' as chk_before  → read 2399.65
4. Read 'testid=balance-sav' as sav_before  → read 10250.0
5. Select 'Everyday Checking (****4021)' in 'label=From account'
6. Select 'High-Yield Savings (****7788)' in 'label=To account'
7. Enter '-50' into 'label=Amount'
8. Click the 'Transfer' submit button
9. Read 'testid=balance-chk' as chk_after  → read 2449.65
10. Read 'testid=balance-sav' as sav_after  → read 10200.0

**Expected:** Error shown, balances unchanged.

**Observed:** no error or validation message visible; chk_after=2449.65, chk_before=2399.65; sav_after=10200.0, sav_before=10250.0

### BUG-03 [HIGH] Not met: Three decimal places are rejected (1.005)
Scenario SC-06-d · requirements REQ-06

**Steps to reproduce**
1. Open http://localhost:8080 and click 'Enter Demo'
2. Click 'Transfer' in the top navigation
3. Read 'testid=balance-chk' as chk_before  → read 2499.65
4. Read 'testid=balance-sav' as sav_before  → read 10150.0
5. Select 'Everyday Checking (****4021)' in 'label=From account'
6. Select 'High-Yield Savings (****7788)' in 'label=To account'
7. Enter '1.005' into 'label=Amount'
8. Click the 'Transfer' submit button
9. Read 'testid=balance-chk' as chk_after  → read 2498.64
10. Read 'testid=balance-sav' as sav_after  → read 10151.0

**Expected:** Error shown, balances unchanged.

**Observed:** no error or validation message visible; chk_after=2498.64, chk_before=2499.65; sav_after=10151.0, sav_before=10150.0

### BUG-04 [HIGH] Not met: Overdraft is rejected with Insufficient funds
Scenario SC-07-a · requirements REQ-07

**Steps to reproduce**
1. Open http://localhost:8080 and click 'Enter Demo'
2. Click 'Transfer' in the top navigation
3. Read 'testid=balance-chk' as chk_before  → read 2497.63
4. Read 'testid=balance-sav' as sav_before  → read 10152.0
5. Select 'Everyday Checking (****4021)' in 'label=From account'
6. Select 'High-Yield Savings (****7788)' in 'label=To account'
7. Enter '999999' into 'label=Amount'
8. Click the 'Transfer' submit button
9. Read 'testid=balance-chk' as chk_after  → read -997501.37
10. Read 'testid=balance-sav' as sav_after  → read 1010151.0

**Expected:** 'Insufficient funds' shown, balances unchanged.

**Observed:** no error or validation message visible; chk_after=-997501.37, chk_before=2497.63; sav_after=1010151.0, sav_before=10152.0

### BUG-05 [HIGH] Not met: Debit filter shows only debits
Scenario SC-11-a · requirements REQ-11

**Steps to reproduce**
1. Open http://localhost:8080 and click 'Enter Demo'
2. Click 'Transactions' in the top navigation
3. Select 'Debit' in 'label=Type'

**Expected:** Only debit rows.

**Observed:** present on page
