# Northwind Demo Bank — Product Requirements (sample)

Stand-in PRD for the local demo target. Synthetic data only.

## 1. Entry
1.1 The landing page shows an **Enter Demo** button. Clicking it opens the dashboard. No login is required.

## 2. Dashboard
2.1 The dashboard lists every account with its name, masked number and current balance formatted as US dollars with two decimals.
2.2 Navigation offers Dashboard, Transfer and Transactions.

## 3. Transfers
3.1 Users can move money between two of their own accounts by choosing a From account, a To account and an Amount, then pressing **Transfer**.
3.2 On success the source balance decreases and the destination balance increases by exactly the transfer amount, and a confirmation with a reference number is shown.
3.3 Every successful transfer creates a debit record for the source account and a credit record for the destination account in Transactions.
3.4 The amount must be a number greater than zero with at most two decimal places. Otherwise the transfer is rejected with an error message and no balance changes.
3.5 A transfer larger than the source account's available balance is rejected with an "Insufficient funds" message.
3.6 The From and To accounts must be different.
3.7 An empty amount shows a validation message.

## 4. Transactions
4.1 Transactions are listed newest first with date, account, description, type and amount.
4.2 A Type filter (All, Credit, Debit) shows only transactions of the selected type.
