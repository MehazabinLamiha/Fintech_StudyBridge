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

- The LLM (**Ollama `qwen2.5:7b`** locally, or a hosted Qwen such as Groq's; optional) only (1) reads the request into a strict form
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
git clone https://github.com/MehazabinLamiha/StudyBridge.git && cd StudyBridge
python -m unittest discover -s tests -t .                      # 348 tests
python -m studybridge --today 2026-10-13 web                    # http://127.0.0.1:8765 (payments on by default)
python -m studybridge --today 2026-10-13 demo                   # the 31 stories -> evidence/
python -m studybridge stories                                   # list the 31 stories
python -m studybridge --tier TRANSACT chat                      # terminal chat
```

On macOS and Linux, use `python3` if `python` is not found. On Windows, use `py` if `python` opens the Microsoft Store.

### The web UI

One page with three screens:

- **Student phone** (left): chat with the assistant; a notification when the family approves tuition
  (the 2-minute confirmation starts when the student opens it); final-confirmation cards with a
  2-minute ring; **Ask to raise my limit** (one day, with a note for the family).
- **Glass Box** (centre): the 11 workflow steps lighting up as they run, coloured by who acts
  (student, Qwen, code, simulated bank, family). It also shows the Gate 1 checks, what the rules
  reader and Qwen proposed and what code actually used, the limits, and the live audit chain with
  **Verify** and **Tamper test (on a copy)**.
- **Family phone** (right): approval inbox (tuition, allowances, monthly rent, one-day limit raises
  with the student's note, new bank accounts with an "I called the number on file" check), a daily
  limit the family types in (CNY 100–5,000), documents, open allowances. Its labels and buttons switch to Bangla
  (invoice details, document names and warnings stay in English; the Bangla text still needs a native
  speaker's proofreading).

Also on screen (built by Nura, merged 17 October): **Try to scam it** (ready-made attacks and a
free-text box, each sent through the normal student chat, with a scoreboard where "money moved without both"
stays 0); the **Invoice X-ray** (**Why?** on a suspicious bill: the wrong digit, the missing letter, pressure
wording and instructions aimed at the AI); a **scams stopped** counter beside the logo; the family phone's
**Stopped for your student** list with every reason in Bangla; and Banglish/Bangla input (works fully with
Qwen off; with Qwen on, some Bangla messages end as a question back). After a blocked scam bill, the chat
offers one tap to pay the payee's own bill instead.

New in v0.4 (18 October):

- **What Qwen does is visible, and its absence is too.** The Glass Box has a Qwen card: which reader (rules or
  Qwen) read each message, whether Qwen was asked, and what it was sent. With Qwen on, a money request that only
  Qwen reads (the rules reader finds no payment) is offered back to the student as a question written by code,
  never run on Qwen's say-so. Attacks are stopped *before* Qwen and the Glass Box says so.
- **Try to scam StudyBridge** now has 35 ready-made attacks in seven groups, labelled with the OWASP Top 10 for LLM
  Applications (2025) where one applies: payment scams, five patterns copied from public reports (each links to its
  source page), prompt injection (spaced letters, leetspeak, Banglish, base64, role-play,
  a hidden instruction in a bill), secret and system-prompt requests, excessive agency (claiming to be the family
  or admin), markup, and floods. Free text is recognised and named. When an attack is caught the whole screen
  turns dark red with a banner naming the threat; it clears by itself after a few seconds.
- **Invoice lab** (second tab of the same panel): build any bill (payee, amount, issuer name, account, note) and
  try to pay it, or let the code make random bills. A random bill is a genuine bill changed in one known way; the
  plan decides what must happen, and the code compares. "Check 100 random bills" runs in a throwaway sandbox.
- **Scam check** (student Home → "Check a message"): paste a message and see which words look like a scam
  (pressure, a stranger offering to pay, fake police, secrecy, changed bank details, a refund that needs money first,
  account numbers the family never saved). It never says "safe", never sends the pasted text to Qwen and never writes
  it to the audit log. **Spot the scam** is an 8-message quiz that reveals what gave each message away, with the
  public report it copies.
- **Family safe word** (family Settings): the family agrees a word with the student offline. With it set, approving
  CNY 10,000 or more, a changed bank account, or a request with warnings needs it; three wrong tries lock it for
  15 minutes; only a salted hash is kept. The app cannot tell who is calling: it stops one-tap approval under pressure.
- **Save a new payee** (family Settings): a payee saved now can be paid only after 48 hours.
- **Save report (.md)** in the scam panel: a plain-text record of the session's attempts (not demo evidence).
- **Tuition deadlines** (student Home): the unpaid tuition invoices on the university's verified account, how many
  days are left, the date the money must leave (`Send by`), the provider and amount to send, and whether the wallet
  covers it (with a top-up suggestion if not). A coloured chip shows On track, Send soon (within 7 days of the send-by
  date), Send now, or Overdue. A **scheduler** checks the deadlines (when the sandbox clock moves, from the operator's
  `run_scheduler` action, and every 5 seconds in the web server) and stores them in a small **SQLite database**
  (`studybridge/deadlines.py`: `deadlines`, `reminders`, `advice`). Each level raises one reminder per invoice, shown on
  the card with a **Got it** button (it pays nothing). **Get advice** gives up to three plain sentences: when Qwen is on
  it writes them from the facts only and code fills every number (typed digits and claims of payment are cut); with Qwen
  off, or if its answer is rejected, code writes the advice. The database is in memory unless `--db` /
  `STUDYBRIDGE_DB` (or `--state`, which uses `<state>.db`) names a file.
- **Risk check** on the family's approval card: plain reasons a request might be unsafe: a possible duplicate (same
  payee and amount as another open request in the last 24 hours), scam wording, a large amount, a payee saved in the last
  week, a **bank account change** for the payee (on hold, or applied within a week) and an **approval mismatch** (the bill's
  amount or account no longer matches the request, or the saved account changed after the request was made). The last two
  are re-checked every time the card is drawn and also ask for the safe word. A duplicate or a warning also asks for the safe word when one is set. It never blocks by itself; the gates do.
- **Route recommendation** in the remittance comparison: the cheapest route, the fastest route, what speed costs, and a
  recommendation that switches to the faster route when the deadline is tight.
- **Problem research** with sources: [docs/PROBLEM_RESEARCH.md](docs/PROBLEM_RESEARCH.md), and a collector for
  Reddit, YouTube and X posts to run on a team computer (`tools/opinion_collect.py`).

Demo controls in the top bar: the **sandbox clock** (+1 h / +25 h / +73 h shows expiries),
**Assistant can** (the permission tier in plain words: Rates only = PUBLIC, See my wallet = READ, Plan
with me = ADVISE, Make payments = TRANSACT; a refused request offers the missing permission in one
click), the Qwen switch, a light/dark switch (light by default), Reset, and **Play stories**, which plays any of the 31 stories step by step through
the real app. To start a story on page load (useful for recording the video), open
`http://127.0.0.1:8765/?story=A6`, `?story=B1,B2,B6` or `?story=all`, optionally with `&speed=2600`
(presenter), `1400` (normal) or `500` (fast).

### v0.6: what changed after testing as a student and a family (19 October)

- **Product view and Judge mode.** Students and families see only the Student and Family screens. The **Judge mode**
  button adds the Glass Box, stories, "Try to scam it", the Bank screen, the sandbox clock, the Qwen and permission
  switches and Reset (`?judge=1`, `?tour=1` and `?story=…` turn it on; `?tab=family` opens the Family screen).
- **Tuition goes only through the student file.** The comparison, the tuition planner and the payment itself use only
  routes marked `tuition_ok` (the student's AD bank; Bangladesh Bank FEPD-1 Circular No. 40, para 10). Other routes
  are labelled "not for tuition". When the bank cannot deliver before the due date, the plan says to ask the
  university for an extension in writing.
- **Tuition has its own cap**: BDT 2,500,000 a day (ASSUMPTION, illustrative), so a full year at a dearer programme
  such as MBBS can be paid in one go. Everyday payments keep the BDT 450,000 / 600,000 caps.
- **Allowances are "up to" an amount** at one shop, for one purchase. The family can add 5% or 10% headroom
  (ASSUMPTION) for a price change; a lower price at the same shop is covered; another shop or a higher price is not.
- **Every refusal says who can change it** (your family, the payee, you, time, or nobody: a safety rule), before the
  details, with the one-tap next step.
- **A Money tab**, so Home keeps only the wallet, the quick actions, the next tuition deadline, today's limits and the
  scam check. Money holds **Credit building** (on-time payments, the readiness index, next steps, and the payment
  record to download; neither is a credit score), the **tuition reserve** (read-only for the student: the family puts money
  aside and takes it out on the Family screen; only tuition can use it; it shows how much of the next tuition it covers,
  what the family should set aside each month, and how much a 2% exchange-rate move changes its value, since it is kept
  in taka), **This month** (by category against last month, tips written by
  code), activity with receipts, and rates. The **University check** (facts from stored bills plus checks to make
  yourself; it predicts nothing) sits in Bills, and "Paid the wrong account?" in Messages.
- **Scam bills arrive as messages.** Bills shows only bills from payees the family saved. The six sample scam bills
  (look-alike, agent, personal wallet, new bank details, seat-fee pressure, changed rent account) arrive in Messages
  from their senders, with "Check this bill", "Pay it" and **"Report as scam"**: the student has to spot them, and
  paying still meets every gate. A reported message folds into "Reported as scam" (with Undo), its bill cannot be paid
  (`REPORTED_AS_SCAM`), the family sees it under "Stopped for your student", and it counts as a scam stopped. In the
  sample data these bills are marked `arrives_as`.
- **Family PIN**: once set, every family action needs the Family screen unlocked (10 minutes; 5 wrong tries lock it for
  15 minutes; only a salted hash is kept). It makes self-approval harder; it is not a login.
- Spot-the-scam quiz moved inside the message check. THB and EUR removed.

### Packaging the submission

Do not use Finder's "Compress": it adds `__MACOSX/`, `.DS_Store`, `__pycache__`, the `.git` folder and `var/`.
Run `python tools/make_submission.py` instead; it zips only the files git tracks or would track (so `.gitignore`
applies) into `../StudyBridge-submission.zip`.

### Check a bill with the university

On the student's Home, **Check a bill** (or the "Check a bill with the university" tab of the scam check) compares a
pasted bill with the university's own website. Code reads the account numbers, SWIFT codes and e-mail addresses in the
bill, reads the university's official payment page on its `.edu.cn` address, and says whether each account and SWIFT
code appears there, with the place it was found and the page's latest date. Five universities are listed (Shenzhen
University, SWUFE, SJTU, SJTU School of Medicine, Soochow University Medical College); their pages were checked by the
team and saved copies (fetched 19 Oct 2026) are in `data/official_pages/`, so the check also works without internet.
A match is strong evidence, not proof: pages can be years old, so the result always lists the official addresses to
confirm with. Re-fetch the saved copies with `python -m studybridge refresh-official`.

### Optional: local LLM

```bash
ollama pull qwen2.5:7b
python -m studybridge --llm --today 2026-10-13 --tier TRANSACT web
```

If Ollama is not reachable, StudyBridge logs a warning and runs rules-only. Every feature still works.
In the web UI, the **Qwen** button in the top bar switches the model on and off without a restart; if
Ollama is not running, switching on is refused and the app stays rules-only.

### Optional: hosted Qwen (for a public demo such as Render)

A server without Ollama can use a hosted OpenAI-style API instead. Groq has a free tier (read 16 Oct 2026: 30
requests a minute, 1,000 a day, no card). Set the key as an environment variable, never in the repo or on the command line:

```bash
export GROQ_API_KEY=...                      # from console.groq.com
python -m studybridge --llm --tier TRANSACT web          # Qwen starts on; the top-bar switch works too
```

- With only the key set, the client uses `https://api.groq.com/openai/v1` and the model in `config.HOSTED_LLM`
  (`qwen/qwen3.8-27b`). Check the exact model id in your Groq console; if it is not listed, the switch is refused and
  the screen says so. Use `--model` or `STUDYBRIDGE_LLM_MODEL` to change it, and `--llm-url` or
  `STUDYBRIDGE_LLM_URL` for another provider (OpenRouter, Together, Ollama's `/v1`); the key is read from
  `STUDYBRIDGE_LLM_KEY` or `GROQ_API_KEY`.
- A local budget (`STUDYBRIDGE_LLM_PER_MINUTE`, default 20; `STUDYBRIDGE_LLM_PER_DAY`, default 800) stops calls before the
  free quota does. When it is used up, or the service fails, the app runs rules-only for that message.
- What leaves the server: everything Qwen already sees, which is the student's own chat message plus the
  structured fields of the result (never invoice notes or memos, never pasted scam-check text). With the hosted option
  on, the "Qwen runs locally" claim no longer holds; say so on any slide that uses it. Everything is fictional sandbox data. The hosted model is a different Qwen from the evidence run's
  `qwen2.5:7b`: say which one a screenshot came from.
- On Render: set `GROQ_API_KEY` (and optionally `STUDYBRIDGE_LLM=1` to start with Qwen on) under Environment, and
  redeploy. `PORT` is read automatically.

### Options

| Flag | Meaning |
|---|---|
| `--tier PUBLIC\|READ\|ADVISE\|TRANSACT` | Permission tier granted to the session (default `TRANSACT` for `web`, where the student still confirms every payment; `ADVISE`, which cannot move money, for the other commands) |
| `--llm` / `--model` / `--llm-url` | Use a model for intent parsing and explanations: Ollama, or a hosted API when a key or URL is set (`STUDYBRIDGE_LLM=1` is the same as `--llm`) |
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

**Hosted demo (Render, for judges):** the server answers only to `localhost` unless a host name is named on purpose, so
that another website cannot use it (DNS rebinding). On Render, `RENDER_EXTERNAL_HOSTNAME` is set automatically and
is allowed; on any other host, or with a custom domain, set `STUDYBRIDGE_ALLOWED_HOSTS` to the comma-separated host
names. If the page shows `{"error": "unexpected host"}`, the host is not on the list. Because there are no logins, a
public deployment lets anyone press every button: share the link only for the judging period.

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
evidence/           sandbox operation logs; v0.1 runs in evidence/archive_v0.1
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
`tests/test_security.py` and `tests/test_core.py` keep the v0.1 checks (tiers, confirmation flow,
injection, LLM hardening, grounding guard, audit tamper detection, algorithms). `tests/test_data.py`
(ported from Nura's data tests) checks the sample data and that every reason code is exercised.

## Team

East West University, Bangladesh

- Rafikul Islam Provat
- Mehazabin Hossain Lamiha
- Ariana Ziauddin
- Nura Alam

## Licence

MIT. Sample data is fictional.
