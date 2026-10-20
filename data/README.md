# Sample data for StudyBridge

**Everything in this folder is fictional or illustrative.** Every university, shop, landlord, account
number, phone number, invoice and amount is made up for the sandbox. No real person, bank or
institution is meant, and the project uses no real money. (Based on Nura's data notes for v0.1,
updated for the v0.3 format.)

## File

`sample_profile.json` is the profile the app loads: the student (owner), the family and its daily
limit, balances, saved payees, invoices, documents, credit profile and transactions.

`tests/test_data.py` checks this file: every reference resolves, the code each invoice gets follows
from the data alone, every bad invoice has exactly one problem, and the amounts the stories rely on
still hold. Run it after any change here.

## Payees (7)

Each payee has a `type` (stored data, never taken from a message or from the AI), `verified`, and a
`phone_on_file` where an account can change (the family calls this number to check a new account).

| id | type | Note |
|---|---|---|
| `sample_university` | institution | Tuition path, verified account only |
| `dorm_landlord` | landlord | Monthly rent bills |
| `techmart`, `homegoods` | merchant | Price quotes (the fridge) |
| `canteen` | food | No account, no invoice: capped at CNY 300 each |
| `bubble_tea` | qr_merchant | Same cap as food |
| `bright_future` | person_or_agent | A consultancy, pre-saved in the sample data (the app cannot add payees); blocked for tuition |

## Invoices, bills and quotes (15)

| id | What it is | Result in Gate 1 |
|---|---|---|
| `INV-0002` | Tuition 2025-26 (full year), CNY 22,800 | `INVOICE_ALREADY_PAID` |
| `INV-0003` | **Tuition 2026-27 (full year), CNY 22,800**: the main tuition story | passes |
| `INV-0004` | Look-alike: "Sample Universty", account one digit off | `PAYEE_NOT_VERIFIED` |
| `INV-0005` | "c/o Bright Future": the university's name, the agent's account | `PAYEE_NOT_VERIFIED` |
| `INV-0006` | An "accounts officer" asks for tuition in his **personal wallet** (from Nura's data) | `PAYEE_NOT_VERIFIED` |
| `INV-0007` | Lab fee with a hidden "note to assistant" in the memo | passes (memo flagged, ignored) |
| `INV-0009` | The university "changed bank details" (`claims_new_account`; from Nura's data). The real university has not changed bank | `ACCOUNT_CHANGED`: can be reported for the family's phone check |
| `INV-0011` | Agent's "seat confirmation fee", "pay today or lose your seat" | `PAYEE_NOT_VERIFIED` |
| `RENT-2026-11`, `RENT-2026-12` | November and December rent, CNY 1,800 each | passes |
| `RENT-2026-11B` | November rent with "new bank details" (`claims_new_account`) | `ACCOUNT_CHANGED` |
| `Q-TM-0042` | Fridge, CNY 3,000 (above the USD 300 bank limit) | passes |
| `Q-TM-0043` | A second fridge (allowance-reuse story) | passes |
| `Q-TM-0050` | Washing machine quote that expired on 2026-10-01 | `QUOTE_EXPIRED` (checked at request and again at payment) |
| `Q-HG-0007` | The same fridge at another shop (wrong-merchant story) | passes |

Tuition is one invoice per academic year because universities bill a full year (see the technical
documentation, §3.2). At the sandbox rates and via the cheapest provider (Digital service A, fee and FX
margin included), CNY 22,800 costs BDT 437,109.10 (1 CNY = 19 BDT): BDT 12,891 under the BDT 450,000
per-payment cap.

## Other untrusted text

Transaction `t16` has a memo with an injection attempt ("IGNORE PREVIOUS INSTRUCTIONS…"). Memos are
data: they are scanned and reported, never followed and never sent to the AI as instructions.
