-- ============================================================
-- CORR_income_split.sql
-- Piranjeri Temples Family Trust — FY 2025-26
-- Purpose: Split I-01 NPK income into correct accounts
--
-- Problem: Receipts app tagged Aadi Pooram donations (₹31,556),
--          SB Interest (₹9,205) and FD Interest (₹5,823) all under
--          fund_source_id=1 (NPK → I-01). So I-01 shows ₹3,35,519
--          instead of the correct ₹2,88,935.
--
-- Fix: Add 3 new INCOME accounts, then post reclassification
--      JOURNAL entries to move the amounts out of I-01.
--
-- Source: PTFT ACC_FULL_2025-26.xlsx — RECEIPTS tab column totals
--   NPK proper (col J):    ₹2,88,935
--   Aadi Pooram (col L):   ₹31,556
--   SB Interest (col Q):   ₹9,205   (BANK INTEREST entries)
--   FD Interest (col Q):   ₹5,823   (INTEREST ON FD entry 2-Jul-2025)
--
-- Run this in Neon SQL editor.
-- Verify RETURNING clause output before any app reboot.
-- ============================================================

BEGIN;

-- ── Step 1: Add new income accounts ──────────────────────────────────────────
-- (Run this first and note the ids returned — should be 37, 38, 39
--  if accounts table currently has max id = 36)

INSERT INTO accounts (code, name, account_type, normal_balance)
VALUES
    ('I-07', 'Donations — Aadi Pooram',     'INCOME', 'CR'),
    ('I-08', 'Interest on Savings Bank',     'INCOME', 'CR'),
    ('I-09', 'Interest on Fixed Deposits',   'INCOME', 'CR')
RETURNING id, code, name;

-- ── Step 2: Reclassify Aadi Pooram: Dr I-01 (acct 5) / Cr I-07 (acct 37) ───
-- ₹31,556 — Aadi Pooram donations collected Jul 2025

INSERT INTO ledger_entries
    (account_id, entry_date, debit_amount, credit_amount,
     narration, batch_id, fy, entry_type, source_type)
VALUES
    (5,  '2026-03-31', 31556.00, 0.00,
     'Reclassify Aadi Pooram donations out of NPK (Excel RECEIPTS col-L)',
     'CORR-AADI-FY2526', '2025-26', 'JOURNAL', 'JOURNAL'),

    (37, '2026-03-31', 0.00, 31556.00,
     'Reclassify Aadi Pooram donations out of NPK (Excel RECEIPTS col-L)',
     'CORR-AADI-FY2526', '2025-26', 'JOURNAL', 'JOURNAL');

-- ── Step 3: Reclassify SB Interest: Dr I-01 (acct 5) / Cr I-08 (acct 38) ───
-- ₹9,205 — Bank interest credits (BANK INTEREST / SB INT entries)
-- Receipts: 27-Jun-25 ₹1,682 | 06-Sep-25 ₹2,937 | 27-Sep-25 ₹1,849
--           28-Dec-25 ₹1,537 | 27-Mar-26 ₹1,200

INSERT INTO ledger_entries
    (account_id, entry_date, debit_amount, credit_amount,
     narration, batch_id, fy, entry_type, source_type)
VALUES
    (5,  '2026-03-31', 9205.00, 0.00,
     'Reclassify SB interest out of NPK (Excel RECEIPTS col-Q BANK INTEREST)',
     'CORR-BINT-FY2526', '2025-26', 'JOURNAL', 'JOURNAL'),

    (38, '2026-03-31', 0.00, 9205.00,
     'Reclassify SB interest out of NPK (Excel RECEIPTS col-Q BANK INTEREST)',
     'CORR-BINT-FY2526', '2025-26', 'JOURNAL', 'JOURNAL');

-- ── Step 4: Reclassify FD Interest: Dr I-01 (acct 5) / Cr I-09 (acct 39) ───
-- ₹5,823 — Fixed deposit interest (INTEREST ON FD entry 02-Jul-2025)

INSERT INTO ledger_entries
    (account_id, entry_date, debit_amount, credit_amount,
     narration, batch_id, fy, entry_type, source_type)
VALUES
    (5,  '2026-03-31', 5823.00, 0.00,
     'Reclassify FD interest out of NPK (Excel RECEIPTS col-Q INTEREST ON FD)',
     'CORR-BINT-FY2526', '2025-26', 'JOURNAL', 'JOURNAL'),

    (39, '2026-03-31', 0.00, 5823.00,
     'Reclassify FD interest out of NPK (Excel RECEIPTS col-Q INTEREST ON FD)',
     'CORR-BINT-FY2526', '2025-26', 'JOURNAL', 'JOURNAL');

-- ── Step 5: Verify ────────────────────────────────────────────────────────────
SELECT
    a.code, a.name,
    COALESCE(SUM(le.credit_amount - le.debit_amount), 0) AS net_cr
FROM accounts a
LEFT JOIN ledger_entries le ON le.account_id = a.id AND le.fy = '2025-26'
WHERE a.id IN (5, 37, 38, 39)
GROUP BY a.id, a.code, a.name
ORDER BY a.id;

-- Expected output:
--   I-01 | Donations — Nithya Pooja  | 288,935.00
--   I-07 | Donations — Aadi Pooram   |  31,556.00
--   I-08 | Interest on Savings Bank  |   9,205.00
--   I-09 | Interest on Fixed Deposits|   5,823.00

COMMIT;
