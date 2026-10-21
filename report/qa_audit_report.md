# QA Audit — http://localhost:5173

Requirements: 22 passed, 4 failed, 0 unverified · Scenarios: 45 · Defects: 7 · LLM cost: $0.0000

| Req | Title | Verdict | Basis |
|---|---|---|---|
| AUTH-01 | Enter Demo opens the dashboard | PASSED | all 1 scenarios passed (normal) |
| AUTH-02 | Header shows active customer and Log out | PASSED | all 1 scenarios passed (normal) |
| AUTH-03 | Logout returns to landing and protects views | PASSED | all 3 scenarios passed (edge, negative, normal) |
| AUTH-04 | Refresh preserves a valid session | PASSED | all 1 scenarios passed (normal) |
| DASH-01 | Accounts listed with name, mask, type, balance | PASSED | all 1 scenarios passed (normal) |
| DASH-02 | Balances shown to two decimals | PASSED | all 1 scenarios passed (normal) |
| DASH-03 | No full account identifier exposed | PASSED | all 1 scenarios passed (negative) |
| DASH-04 | Account detail view agrees with dashboard | PASSED | all 2 scenarios passed (normal) |
| XFER-01 | Valid transfer is atomic and exact | PASSED | all 4 scenarios passed (edge, normal) |
| XFER-02 | Transfer creates one record in both histories | PASSED | all 1 scenarios passed (normal) |
| XFER-03 | Same-account transfer rejected | PASSED | all 1 scenarios passed (negative) |
| XFER-04 | Invalid amounts rejected | FAILED | 3 of 7 scenarios failed: Zero amount is rejected; Zero written as 0.00 is rejected; Negative amount is rejected |
| XFER-05 | Insufficient funds rejected | FAILED | 2 of 2 scenarios failed: Amount above the available balance is rejected; Balance + $0.01 is rejected |
| XFER-06 | Success shown only after commit; failures explained | FAILED | 4 of 10 scenarios failed: Zero amount is rejected; Zero written as 0.00 is rejected; Negative amount is rejected; Amount above the available balance is rejected |
| XFER-07 | Transfer survives refresh | PASSED | all 1 scenarios passed (normal) |
| XFER-08 | No duplicate submission | PASSED | all 1 scenarios passed (edge) |
| HIST-01 | Rows show required fields and direction | PASSED | all 1 scenarios passed (normal) |
| HIST-02 | Filters show only matching rows | PASSED | all 6 scenarios passed (edge, normal) |
| HIST-03 | Date range is inclusive | FAILED | 2 of 2 scenarios failed: Range Jan 3 – Jan 18, 2025 includes both boundary dates; Single-day range (Mar 4 – Mar 4, 2025) shows that day's transaction |
| HIST-04 | Empty result shows a clear empty state | PASSED | all 1 scenarios passed (edge) |
| HIST-05 | Clearing filters restores full history | PASSED | all 1 scenarios passed (normal) |
| PROF-01 | Profile shows masked synthetic details | PASSED | all 1 scenarios passed (normal) |
| PROF-02 | Profile leaks no secrets or identifiers | PASSED | all 1 scenarios passed (negative) |
| UI-01 | Usable at narrow widths | PASSED | all 2 scenarios passed (edge) |
| UI-02 | Links lead to the labelled destination | PASSED | all 2 scenarios passed (normal) |
| UI-03 | Recoverable errors allow retry or return | PASSED | all 1 scenarios passed (negative) |

## Defects

### BUG-01 [HIGH] Not met: Zero amount is rejected
Scenario SC-XFER-09 · requirements XFER-04, XFER-06

**Steps to reproduce**
1. Open http://localhost:5173 and click 'Enter Demo'
2. Open Transactions
3. Read the transaction count ('Showing N transactions') as tx_before  → read 20.0
4. Open Transfer (fresh page load)
5. Read Everyday Checking balance as chk_before  → read 4365.15
6. Read Rainy Day Savings balance as sav_before  → read 8279.6
7. Choose From account: Everyday Checking  → read selected 'Everyday Checking (•••• 1042) — $4,365.15'
8. Choose To account: Rainy Day Savings  → read selected 'Rainy Day Savings (•••• 7781) — $8,279.60'
9. Enter amount '0'
10. Click 'Transfer funds'
11. Read the confirmation / error shown  → read 'Transfer complete Amount $0.00 From Everyday Checking (•••• 1042) To Rainy Day Savings (•••• 7781) Date & time Oct 21, 2'
12. Open Transfer (fresh page load)
13. Read Everyday Checking balance as chk_after  → read 4365.15
14. Read Rainy Day Savings balance as sav_after  → read 8279.6
15. Open Transactions
16. Read the transaction count ('Showing N transactions') as tx_after  → read 21.0

**Expected:** Rejected with a clear message; balances and history unchanged.

**Observed:** 'Transfer complete Amount $0.00 From Everyday Checking (•••• 1042) To Rainy Day Savings (•••• 7781) Date & time Oct 21, 2'; 'Transfer complete Amount $0.00 From Everyday Checking (•••• 1042) To Rainy Day Savings (•••• 7781) Date & time Oct 21, 2'; tx_after=21.0, tx_before=20.0

### BUG-02 [HIGH] Not met: Zero written as 0.00 is rejected
Scenario SC-XFER-10 · requirements XFER-04, XFER-06

**Steps to reproduce**
1. Open http://localhost:5173 and click 'Enter Demo'
2. Open Transactions
3. Read the transaction count ('Showing N transactions') as tx_before  → read 22.0
4. Open Transfer (fresh page load)
5. Read Everyday Checking balance as chk_before  → read 4365.15
6. Read Rainy Day Savings balance as sav_before  → read 8279.6
7. Choose From account: Everyday Checking  → read selected 'Everyday Checking (•••• 1042) — $4,365.15'
8. Choose To account: Rainy Day Savings  → read selected 'Rainy Day Savings (•••• 7781) — $8,279.60'
9. Enter amount '0.00'
10. Click 'Transfer funds'
11. Read the confirmation / error shown  → read 'Transfer complete Amount $0.00 From Everyday Checking (•••• 1042) To Rainy Day Savings (•••• 7781) Date & time Oct 21, 2'
12. Open Transfer (fresh page load)
13. Read Everyday Checking balance as chk_after  → read 4365.15
14. Read Rainy Day Savings balance as sav_after  → read 8279.6
15. Open Transactions
16. Read the transaction count ('Showing N transactions') as tx_after  → read 23.0

**Expected:** Rejected with a clear message; balances and history unchanged.

**Observed:** 'Transfer complete Amount $0.00 From Everyday Checking (•••• 1042) To Rainy Day Savings (•••• 7781) Date & time Oct 21, 2'; 'Transfer complete Amount $0.00 From Everyday Checking (•••• 1042) To Rainy Day Savings (•••• 7781) Date & time Oct 21, 2'; tx_after=23.0, tx_before=22.0

### BUG-03 [HIGH] Not met: Negative amount is rejected
Scenario SC-XFER-11 · requirements XFER-04, XFER-06

**Steps to reproduce**
1. Open http://localhost:5173 and click 'Enter Demo'
2. Open Transactions
3. Read the transaction count ('Showing N transactions') as tx_before  → read 24.0
4. Open Transfer (fresh page load)
5. Read Everyday Checking balance as chk_before  → read 4365.15
6. Read Rainy Day Savings balance as sav_before  → read 8279.6
7. Choose From account: Everyday Checking  → read selected 'Everyday Checking (•••• 1042) — $4,365.15'
8. Choose To account: Rainy Day Savings  → read selected 'Rainy Day Savings (•••• 7781) — $8,279.60'
9. Enter amount '-5.00'
10. Click 'Transfer funds'
11. Read the confirmation / error shown  → read 'Transfer complete Amount −$5.00 From Everyday Checking (•••• 1042) To Rainy Day Savings (•••• 7781) Date & time Oct 21, '
12. Open Transfer (fresh page load)
13. Read Everyday Checking balance as chk_after  → read 4370.15
14. Read Rainy Day Savings balance as sav_after  → read 8274.6
15. Open Transactions
16. Read the transaction count ('Showing N transactions') as tx_after  → read 25.0

**Expected:** Rejected with a clear message; balances and history unchanged.

**Observed:** 'Transfer complete Amount −$5.00 From Everyday Checking (•••• 1042) To Rainy Day Savings (•••• 7781) Date & time Oct 21, '; 'Transfer complete Amount −$5.00 From Everyday Checking (•••• 1042) To Rainy Day Savings (•••• 7781) Date & time Oct 21, '; chk_after=4370.15, chk_before=4365.15; sav_after=8274.6, sav_before=8279.6; tx_after=25.0, tx_before=24.0

### BUG-04 [HIGH] Not met: Amount above the available balance is rejected
Scenario SC-XFER-16 · requirements XFER-05, XFER-06

**Steps to reproduce**
1. Open http://localhost:5173 and click 'Enter Demo'
2. Open Transactions
3. Read the transaction count ('Showing N transactions') as tx_before  → read 26.0
4. Open Transfer (fresh page load)
5. Read Everyday Checking balance as chk_before  → read 4375.15
6. Read Rainy Day Savings balance as sav_before  → read 8269.6
7. Choose From account: Everyday Checking  → read selected 'Everyday Checking (•••• 1042) — $4,375.15'
8. Choose To account: Rainy Day Savings  → read selected 'Rainy Day Savings (•••• 7781) — $8,269.60'
9. Enter amount {chk_before} + 100  → read entered '4475.15'
10. Click 'Transfer funds'
11. Read the confirmation / error shown  → read 'Transfer complete Amount $4,475.15 From Everyday Checking (•••• 1042) To Rainy Day Savings (•••• 7781) Date & time Oct 2'
12. Open Transfer (fresh page load)
13. Read Everyday Checking balance as chk_after  → read -100.0
14. Read Rainy Day Savings balance as sav_after  → read 12744.75
15. Open Transactions
16. Read the transaction count ('Showing N transactions') as tx_after  → read 27.0

**Expected:** Rejected as insufficient funds; balances and history unchanged.

**Observed:** 'Transfer complete Amount $4,475.15 From Everyday Checking (•••• 1042) To Rainy Day Savings (•••• 7781) Date & time Oct 2'; 'Transfer complete Amount $4,475.15 From Everyday Checking (•••• 1042) To Rainy Day Savings (•••• 7781) Date & time Oct 2'; 'Transfer complete Amount $4,475.15 From Everyday Checking (•••• 1042) To Rainy Day Savings (•••• 7781) Date & time Oct 2'; chk_after=-100.0, chk_before=4375.15; sav_after=12744.75, sav_before=8269.6; tx_after=27.0, tx_before=26.0

### BUG-05 [HIGH] Not met: Balance + $0.01 is rejected
Scenario SC-XFER-17 · requirements XFER-05

**Steps to reproduce**
1. Open http://localhost:5173 and click 'Enter Demo'
2. Open Transactions
3. Read the transaction count ('Showing N transactions') as tx_before  → read 28.0
4. Open Transfer (fresh page load)
5. Read Everyday Checking balance as chk_before  → read -100.0
6. Read Rainy Day Savings balance as sav_before  → read 12744.75
7. Choose From account: Rainy Day Savings  → read selected 'Rainy Day Savings (•••• 7781) — $12,744.75'
8. Choose To account: Everyday Checking  → read selected 'Everyday Checking (•••• 1042) — −$100.00'
9. Enter amount {sav_before} + 0.01  → read entered '12744.76'
10. Click 'Transfer funds'
11. Read the confirmation / error shown  → read 'Transfer complete Amount $12,744.76 From Rainy Day Savings (•••• 7781) To Everyday Checking (•••• 1042) Date & time Oct '
12. Open Transfer (fresh page load)
13. Read Everyday Checking balance as chk_after  → read 12644.76
14. Read Rainy Day Savings balance as sav_after  → read -0.01
15. Open Transactions
16. Read the transaction count ('Showing N transactions') as tx_after  → read 29.0

**Expected:** Rejected; nothing changes.

**Observed:** 'Transfer complete Amount $12,744.76 From Rainy Day Savings (•••• 7781) To Everyday Checking (•••• 1042) Date & time Oct '; 'Transfer complete Amount $12,744.76 From Rainy Day Savings (•••• 7781) To Everyday Checking (•••• 1042) Date & time Oct '; chk_after=12644.76, chk_before=-100.0; sav_after=-0.01, sav_before=12744.75; tx_after=29.0, tx_before=28.0

### BUG-06 [HIGH] Not met: Range Jan 3 – Jan 18, 2025 includes both boundary dates
Scenario SC-HIST-08 · requirements HIST-03

**Steps to reproduce**
1. Open http://localhost:5173 and click 'Enter Demo'
2. Open Transactions
3. Set Start date 2025-01-03
4. Set End date 2025-01-18
5. Click 'Apply filters'
6. Read the filtered table  → read 'Filtered transaction history\nDATE & TIME\tDESCRIPTION\tTYPE\tACCOUNT\tAMOUNT\tSTATUS\nJan 3, 2025, 9:00 AM PST\tDemo payroll\tDeposit\tEveryday Checking (•••• 1042)\t\nMoney in:\n+$1,200.00\tCompleted'

**Expected:** Both Jan 3 and Jan 18 transactions shown.

**Observed:** 'Filtered transaction history DATE & TIME DESCRIPTION TYPE ACCOUNT AMOUNT STATUS Jan 3, 2025, 9:00 AM PST Demo payroll Deposit Everyday Checking (•••• 1042) Money in: +$1,200.00 Completed'

### BUG-07 [HIGH] Not met: Single-day range (Mar 4 – Mar 4, 2025) shows that day's transaction
Scenario SC-HIST-09 · requirements HIST-03

**Steps to reproduce**
1. Open http://localhost:5173 and click 'Enter Demo'
2. Open Transactions
3. Enter '2025-03-04' into 'css=#filter-start'
4. Enter '2025-03-04' into 'css=#filter-end'
5. Click 'Apply filters'
6. Count rows shown  → read 0
7. Read  as msg  → read 'No transactions match these filters Try a different combination, or clear the filters to see all transactions. Clear fil'

**Expected:** The Mar 4 'Demo utilities' row is shown.

**Observed:** n=0
