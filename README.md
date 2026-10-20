# StudyBridge — Cross-border & Student Finance Assistant

**Topic C** submission. StudyBridge is a three-gate safe payment assistant for Bangladeshi students
abroad and the families who fund them. The demo persona is a fictional Bangladeshi student in
Shenzhen: her family in Dhaka funds her in BDT, while her tuition, rent and shopping are paid in CNY.

> **Sandbox only.** All rates, fees, invoices and accounts are illustrative sample data
> (`studybridge/config.py`, `data/sample_profile.json`). No real money or account is touched.
> The project makes no compliance claim.

## What it does

| Pain point | What StudyBridge does |
|---|---|
| **Unsafe payments** (scams, wrong accounts, bank limits) | Every payment passes up to three gates: **(1)** a real invoice, the payee's verified account and ready documents; **(2)** the family's approval, or the family daily limit plus an **allowance** (single-use, or monthly for rent), with a simulated bank review when the day's card total passes the bank limit; **(3)** the student's own final confirmation. Every refusal has a reason code and a fix step. A changed bank account is paid only after the family checks it by phone and a 24-hour wait. |
| Remittances | Ranks providers by **what the recipient actually gets**, including the hidden FX mark-up, and marks which routes may carry tuition (only the student's AD bank student file) |
| Tuition payments | Plans one transfer per unpaid tuition invoice, for the full amount (the university bills a year at a time), through the student file only, and pays it only against the stored invoice. A **tuition reserve**, set aside by the family, keeps that money out of everyday spending, and a **University check** card shows the fee change from last year and the bills that ask for another account |
| Credit building | A **payment record** (rent and university payments, on time or not) the student can download and show a landlord, scholarship office or bank, plus a transparent 0–100 readiness index. Neither is a credit score |
| Multi-currency management | BDT, CNY and USD only. The wallet shows what the family's taka is worth here; **This month** shows spending by category against last month, with code-written saving tips; every payment has a downloadable **receipt** |

## Design principle: AI suggests, code decides, the student confirms last

- The LLM (**Ollama `qwen2.5:7b`**, run locally; optional) only (1) reads the request into a strict form
  (intent, amount, currencies, payee, invoice id) and (2) writes up to three plain sentences.
- For money actions, a rules reader must agree with the model on the intent and on every field both read
  (payee, invoice id, amount). If they disagree, nothing is prepared and the student is shown the rules
  reader's reading to confirm. The model's values must also appear in the message (its payee must be
  named there, its amount written there). If the model's output is unusable,
  money actions **fail closed**. With the model off (rules-only mode), the rules reader decides alone.
- Payee and account always come from **stored data**. The amount does too, except for food and QR
  payments, which have no invoice: their amount comes from the message and is capped at CNY 300.
- The model sees structured result fields only. Invoice memos and purposes, the student's notes and
  transaction memos are never sent to it.
- **Tier** (what the assistant may do), **actor** (student or family, set only by the screen) and
  **allowance** (a family approval for one purchase) are three separate ideas.
- Every step is written to a **hash-chained audit log** with masked account numbers.

See [docs/TECHNICAL_DOCUMENTATION.md](docs/TECHNICAL_DOCUMENTATION.md) and
[docs/SECURITY_SELF_ASSESSMENT.md](docs/SECURITY_SELF_ASSESSMENT.md).

## Quick start

Requires Python 3.10+. There are **no third-party dependencies**; only the standard library is used.

```bash
git clone https://github.com/MehazabinLamiha/Fintech_StudyBridge.git && cd Fintech_StudyBridge
python -m unittest discover -s tests -t .                      # 348 tests
python -m studybridge --today 2026-10-13 web                    # http://127.0.0.1:8765 (payments on by default)
python -m studybridge --today 2026-10-13 demo                   # the 31 stories -> evidence/
python -m studybridge stories                                   # list the 31 stories
python -m studybridge --tier TRANSACT chat                      # terminal chat
```

On macOS and Linux, use `python3` if `python` is not found. On Windows, use `py` if `python` opens the Microsoft Store.

### The web UI

The page opens in the **product view**: the Student and Family screens only. The **Judge mode** button adds the
Glass Box, the stories, "Try to scam it", the Bank screen, the sandbox clock, the Qwen and permission switches and
Reset (`?judge=1` turns it on; `?tab=family` opens the Family screen).

- **Student phone**: five tabs (Home, Bills, Money, Messages, Assistant). Chat with the assistant; final-confirmation
  cards with a 2-minute ring; **Ask to raise my limit** (one day, with a note for the family).
- **Family phone**: approval inbox (tuition, allowances, monthly rent, one-day limit raises with the student's note,
  new bank accounts with an "I called the number on file" check), a daily limit the family types in (CNY 100–5,000),
  documents, open allowances, and **Stopped for your student**. Labels and buttons switch to Bangla (the Bangla text
  still needs a native speaker's proofreading).
- **Bank**: the simulated bank sets its own daily card limit (USD 100–1,000, default 300) and shows every review.
- **Glass Box**: the 11 workflow steps lighting up as they run, coloured by who acts (student, Qwen, code, simulated
  bank, family), the Gate 1 checks, what the rules reader and Qwen proposed and what code actually used, a Qwen card
  (which reader read each message and what Qwen was sent), and the live audit chain with **Verify** and
  **Tamper test (on a copy)**.

Demo controls in the top bar: the **sandbox clock** (+1 h / +25 h / +73 h shows expiries), **Assistant can** (the
permission tier in plain words: Rates only = PUBLIC, See my wallet = READ, Plan with me = ADVISE, Make payments =
TRANSACT), the Qwen switch, a light/dark switch, Reset, and **Play stories**, which plays any of the 31 stories step by
step through the real app. To start a story on page load, open `http://127.0.0.1:8765/?story=A6`, `?story=B1,B2,B6` or
`?story=all`, optionally with `&speed=2600` (presenter), `1400` (normal) or `500` (fast).

## Features

**Payments and money**

- **Tuition goes only through the student file**: the comparison, the tuition planner and the payment use only routes
  marked `tuition_ok` (the student's AD bank; Bangladesh Bank FEPD-1 Circular No. 40, para 10). Tuition has its own cap
  of BDT 2,500,000 a day (ASSUMPTION), so a full year can be paid in one go.
- **Tuition deadlines** (student Home): days left, the date the money must leave, the provider and amount, whether the
  wallet covers it, and a status chip (On track, Send soon, Send now, Overdue). A scheduler stores deadlines and reminders
  in a small SQLite database (`studybridge/deadlines.py`); **Get advice** gives up to three sentences in which code fills
  every number.
- **Allowances are "up to" an amount** at one shop, for one purchase; the family can add 5% or 10% headroom (ASSUMPTION).
- **Money tab**: **Credit building** (on-time payments, a readiness index and a downloadable payment record; neither is
  a credit score), the family's **tuition reserve**, **This month** (spending by category with tips written by code),
  activity with receipts, and rates.
- **Route recommendation** in the remittance comparison: cheapest, fastest, what speed costs, and a recommendation.
- **Every refusal says who can change it** (your family, the payee, you, time, or nobody), with the one-tap next step.

**Scam protection**

- **Scam bills arrive as messages**: Bills shows only payees the family saved. Six sample scam bills arrive in Messages
  with "Check this bill", "Pay it" and **Report as scam**; a reported bill cannot be paid (`REPORTED_AS_SCAM`).
- **Invoice X-ray**: **Why?** on a suspicious bill shows the wrong digit, the missing letter, pressure wording and
  instructions aimed at the AI. After a blocked bill, the chat offers one tap to pay the payee's own bill instead.
- **Check a bill with the university**: compares the account numbers and SWIFT codes in a pasted bill with the
  university's official payment page on its `.edu.cn` address. Five universities are listed (Shenzhen University,
  SWUFE, SJTU, SJTU School of Medicine, Soochow University Medical College); saved copies are in
  `data/official_pages/`, so it works without internet. A match is strong evidence, not proof.
- **Scam check** (student Home): paste a message and see which words look like a scam. It never says "safe", never sends
  the text to Qwen and never logs it. **Spot the scam** is an 8-message quiz.
- **Risk check** on the family's approval card: possible duplicates, scam wording, large amounts, new payees, a bank
  account change and an approval mismatch. It never blocks by itself; the gates do.
- **Family safe word**, **family PIN** and a **48-hour wait for new payees**; only salted hashes are kept.

**For judges**

- **Try to scam StudyBridge**: 35 ready-made attacks in seven groups, labelled with the OWASP Top 10 for LLM
  Applications (2025): payment scams, five patterns from public reports (each links to its source), prompt injection
  (spaced letters, leetspeak, Banglish, base64, role-play, a hidden instruction in a bill), secret requests, excessive
  agency, markup and floods, plus a free-text box. A scoreboard shows "money moved without both" staying at 0.
  Attacks are stopped *before* Qwen, and the screen turns red with a banner naming the threat.
- **Invoice lab**: build any bill and try to pay it, or let the code make random bills, each a genuine bill changed in
  one known way. "Check 100 random bills" compares every result with what the plan requires.
- Banglish and Bangla input work with Qwen off; with Qwen on, some Bangla messages end as a question back.

### Optional: local LLM

```bash
ollama pull qwen2.5:7b
python -m studybridge --llm --today 2026-10-13 --tier TRANSACT web
```

If Ollama is not reachable, StudyBridge logs a warning and runs rules-only. Every feature still works.
In the web UI, the **Qwen** button in the top bar switches the model on and off without a restart; if
Ollama is not running, switching on is refused and the app stays rules-only.

### Options

| Flag | Meaning |
|---|---|
| `--tier PUBLIC\|READ\|ADVISE\|TRANSACT` | Permission tier granted to the session (default `TRANSACT` for `web`, where the student still confirms every payment; `ADVISE`, which cannot move money, for the other commands) |
| `--llm` / `--model` / `--llm-url` | Use Qwen through local Ollama for intent parsing and explanations (`STUDYBRIDGE_LLM=1` is the same as `--llm`) |
| `--today YYYY-MM-DD` | Start the sandbox clock on this date (09:00) for reproducible runs (the `STUDYBRIDGE_TODAY` variable does the same) |
| `--profile path.json` | Use another sandbox profile |
| `--audit path.jsonl` | Audit log location (default `var/audit.jsonl`) |
| `web --port N --host H` | Web UI port (default 8765, or the `PORT` variable)  and bind address (keep `127.0.0.1` outside a container) |

`python -m studybridge --audit <file> verify-audit` checks the hash chain. It exits 1 if a record was
changed, and 2 if there is no log at that path.

## Deployment

**Local (recommended for the sandbox):** the commands above. The web server binds to `127.0.0.1` only.

**Docker (optional packaging, not required):**

```bash
docker build -t studybridge .
docker run --rm -p 127.0.0.1:8765:8765 studybridge
```

Do not expose the web UI to the internet. It has no user authentication, because it is a
single-user sandbox (see the known-risk list).

## Example requests

```
pay invoice INV-0003                         tuition: family approves, then you confirm
pay 38 CNY at the canteen                    food: inside the family daily limit
request an allowance for quote Q-TM-0042     fridge: bank review, then family approval
pay quote Q-TM-0042                          uses the allowance; you confirm last
pay rent bill RENT-2026-11                   above the daily limit -> request an allowance
request a monthly allowance for RENT-2026-11 one family approval covers one rent bill a month
pay rent bill RENT-2026-11B                  changed bank details -> report them to the family
pay invoice INV-0004                         look-alike account -> BLOCKED
pay invoice INV-0011                         agent + "pay today or lose your seat" -> BLOCKED
show my payment status
plan my tuition payment
compare the cheapest way to send 50000 BDT to CNY within 1 day
```

## Repository layout

```
studybridge/
  agent.py          the 11-step workflow; Glass Box cases
  payments.py       payee types, Gate 1, allowances, limit raises, account changes, bank review
  reasons.py        reason codes with meaning and fix step
  sandbox.py        one session, three actors (student, family, operator); story runner
  stories.py        the 31 test stories as data
  clock.py          sandbox clock (approval windows, expiries)
  config.py         sandbox rates, provider archetypes, limits
  money.py fx.py    Decimal money and FX quotes
  remittance.py     provider comparison + closed-form inverse
  tuition.py        tuition planner (one full transfer per invoice)
  credit.py         credit-building readiness index
  budget.py         spending insights, runway, anomaly and memo scan
  wallet.py         sandbox multi-currency wallet (idempotent operations)
  llm.py            model clients: Ollama and hosted OpenAI-style API, `make_client` (stdlib urllib)
  security/
    permissions.py  tiers, actor permissions, allowlist, limits
    guard.py        grounding guard, injection and pressure-wording detectors, de-obfuscation
    threats.py      names an attack (OWASP LLM Top 10 ids) for refusals, the red alert and the score
    audit.py        hash-chained audit log, PII masking
  challenge.py      the 35 ready-made attacks of "Try to scam StudyBridge"
  cases.py          scam patterns from public reports, with the page each was read on; quiz messages
  scamcheck.py      "is this message a scam?" (rules only) and the Spot-the-scam quiz
  invoicelab.py     make a test bill, seeded random bills with the answer the plan requires
  web.py static/    local web UI (strict CSP, CSRF header, textContent rendering)
  demo.py           scripted run of the 31 stories that writes the evidence
tests/              348 unit tests
docs/               technical documentation, security self-assessment, problem research
tools/              opinion_collect.py (run by hand on a team computer; not part of the app)
evidence/           sandbox operation logs
data/               fictional sample profile, invoices and payees
```

## The 31 test stories

| Group | Stories |
|---|---|
| A. Normal payments (7) | yearly tuition approved (+ replay refused); tuition rejected; food; QR; rent with a monthly allowance; fridge allowance full chain; raise the limit for a birthday |
| B. Fraud and blocks (9) | agent account; look-alike account; changed account details; amount mismatch; duplicate invoice; "pay today or lose your seat"; the "food" label trick; personal wallet on a tuition invoice; university "changed bank details" caught by the phone check |
| C. Documents and approvals (6) | progress proof missing; invoice not found; family approval expired; allowance expired; wrong merchant; new bank details checked by phone |
| D. Attacks (6) | instruction hidden in an invoice; "ignore your rules"; student approves as family; allowance reused; badly formed AI output; the two readers disagree |
| E. Edge cases (3) | insufficient balance; unclear request; daily bank limit |

`tests/test_payments.py` plays all 31 and checks every expected outcome code.
`tests/test_security.py` and `tests/test_core.py` cover tiers, confirmation flow,
injection, LLM hardening, grounding guard, audit tamper detection, algorithms. `tests/test_data.py`
checks the sample data and that every reason code is exercised.

## Team

East West University, Bangladesh

- Rafikul Islam Provat
- Mehazabin Hossain Lamiha
- Ariana Ziauddin
- Nura Alam

## Licence

MIT. Sample data is fictional.
