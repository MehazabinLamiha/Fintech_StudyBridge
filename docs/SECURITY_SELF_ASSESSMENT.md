# StudyBridge — Security Self-Assessment Report

Version 0.6.0 (plan v4: three-gate safe payments, plus the v0.6 changes) · scope: the sandbox build in this repository

## 1. Assets and threat model

| Asset | Why it matters |
|---|---|
| Wallet balances and transfer capability | Direct financial loss if misused |
| Beneficiary account numbers, transaction history | Personal and financial data |
| Audit log | Evidence of what the agent did, and why |
| Advice correctness | A wrong number in advice can cause real loss, such as a late tuition payment or an expensive provider |

Threat actors and vectors considered:

1. **Prompt injection, direct** — the user's own text tries to override the rules.
2. **Prompt injection, indirect** — third-party text the agent reads (transaction memos,
   beneficiary names, in future news or emails) contains instructions.
3. **LLM error** — hallucinated amounts, units, dates or labels; misread intent.
4. **Over-privileged agent** — the model triggers money movement the user did not intend.
5. **Local web attacks** — CSRF from another site in the same browser, DNS rebinding (a web page
   that re-points its own name at 127.0.0.1), XSS through model output.
6. **Log tampering** — someone edits the audit trail to hide an action.
7. **Replay / double execution** — the same confirmation is used twice.
8. **Payment fraud** — look-alike invoices, agent or personal accounts on a tuition invoice,
   changed bank details (including a request that pushes the family to "update" the account),
   wrong amounts, duplicate invoices, "pay today or lose your seat" pressure, splitting spending to
   stay under the food/QR cap or the family limit, expired quotes.
9. **Approval bypass** — the student (or text pretending to be the family) approves a family
   decision; an allowance is reused, used at another merchant, or used after it expired.
10. **Time-of-check / time-of-use** — something changes between approval and payment (account,
    documents, allowance cancelled).

## 2. Permission-tier implementation

Source: `studybridge/security/permissions.py`, enforced in `agent.py`.

| Tier | Tools | Money moves? | Confirmation |
|---|---|---|---|
| 0 PUBLIC | `help`, `fx_quote` | no | — |
| 1 READ | `wallet_overview`, `spending_insights` | no | — |
| 2 ADVISE (default outside the web app) | `compare_remittance`, `tuition_plan`, `credit_plan` | no | — |
| 1 READ | `payment_status` | no | — |
| 3 TRANSACT (default in the web app since v0.6) | `convert_currency`, `pay`, `request_allowance` | sandbox only | **required, every time** |
| 4 ADMIN | configuration | — | **not reachable through the agent** |

How it is enforced:

1. **Allowlist.** Any tool name not in `TOOL_TIERS` is denied (test: `test_unknown_tool_denied`).
2. **Tier check before every assistant tool.** The session tier is set by the CLI flag at server
   start or by the demo operator's "Assistant can" menu, never by the LLM (tests: `test_tier_blocks_money_movement`,
   `test_tier_too_low_blocks_payment`). Tiers govern what the assistant may do from chat; actions on the
   phone screens are governed by the actor permissions (§2a). Even at a low tier no money moves,
   because the confirmation re-checks the tier (`test_tier_too_low_rechecked_at_confirmation`).
3. **Money never moves directly.** A payment or conversion creates a `PendingAction` (tuition and
   allowance requests first go to the family, and the student's confirmation comes after):
   - 48-bit random id from `secrets.token_hex`
   - 2-minute TTL
   - single-use
4. **Confirmation arrives on a separate channel** — the `/confirm <id>` command or the web
   button, which calls `/api/confirm`. Text written by the model cannot confirm anything.
5. **Re-check at execution.** Tier, BDT hard caps and every payment gate are evaluated again when the
   user confirms, which closes the time-of-check / time-of-use gap (tests:
   `test_tier_rechecked_at_confirmation`, `test_gate_rechecked_at_execution`).
6. **Limits.** Per transaction BDT 450,000; per day BDT 600,000, reset at the date change
   (test: `test_limits`).
7. **Saved payees only.** The agent cannot add a payee or pay a raw account number
   (test: `test_unsaved_beneficiary_refused`).
8. **Exact amounts only.** "all" / "everything" is refused (test: `test_send_everything_refused`).
9. **Idempotency.** Wallet operations are keyed by the action id, and a replayed
   confirmation is refused (tests: `test_idempotency`, `test_prepare_then_confirm_then_replay`).

## 2a. Actors, gates and approvals (v0.3)

| Control | How | Evidence |
|---|---|---|
| Actor separate from tier | `ACTOR_ACTIONS` in `security/permissions.py`; the actor comes from the screen or CLI command, never from chat text or Qwen. There is no login (R1): any local caller can name an actor, so this separates roles in the demo but does not authenticate them | `test_actor_matrix`; story D3 (the student screen calling the family action, and a chat claim to be the family, are both refused) |
| Gate 1 on stored data | Payee, amount, account and payee type come from the stored invoice and payee record (`payments.py`) | stories B1–B7, C1, C2; `test_payee_type_and_amount_come_from_stored_data` |
| Verified account | Invoice account must equal the saved, verified account; agents blocked for tuition | B1 (agent account), B2 (look-alike), B3 (changed details), B6, B8 (personal wallet) |
| Changed account details | The student reports the change; the family must tick that they called the payee on the number already on file (never the number on the bill); then a 24-hour hold before the new account becomes the saved one. The new number is masked in the UI and the audit log | C6, B9 (university "changed bank details": the phone check catches it); `test_account_change_needs_phone_check_then_waits_24_hours`, `test_university_claiming_new_bank_details_goes_to_the_phone_check`, `test_look_alike_agent_and_wallet_cannot_be_reported_as_a_change`, `test_account_change_rejected_changes_nothing`, `test_new_account_number_never_in_snapshot_or_audit` |
| Family approval for tuition, 24 h | Approval request expires; nothing moves without it. An approval stays valid 24 h; the student's 2-minute confirmation starts only when they open it, and only the student can open it | A1, A2, C3; `test_confirmation_starts_when_the_student_opens_the_approval`, `test_approval_still_expires_after_24_hours`, `test_only_the_student_opens_the_approval` |
| Allowance | Created only by the family's decision; fixed merchant. Single-use: fixed amount, 72 h default / 7 d max. Monthly rent: landlord rent bills only, up to a fixed amount, one bill per calendar month, ≤ 6 months. ≤ 3 open | A5, A6, C4, C5, D4; `test_max_three_open`, `test_validity_capped_at_seven_days`, `test_monthly_allowance_one_bill_per_month`, `test_monthly_only_for_rent` |
| One-day limit raise | Requested by the student with a note; approved only by the family; one day, at most CNY 5,000. The note is displayed as the student's words, never parsed, and instruction-like text is flagged | A7; `test_limit_raise_lasts_one_day`, `test_limit_raise_range_date_and_actor`, `test_limit_raise_note_is_data_not_instructions` |
| Simulated daily bank limit and review | Card spending is totalled per day; a payment that would pass USD 300 needs a simulated bank review, otherwise only that payment is blocked. Quote kind, purpose and validity checked in code | E3; `test_bank_limit_is_a_daily_total`, `test_second_purchase_on_the_same_day_gets_a_bank_review`, `test_bank_limit_rechecked_at_execution`, `test_bank_review_rejects_expired_quote` |
| Re-check at execution | Gate 1 (including quote validity), approval, allowance, family limit, the bank review's 72-hour window and the daily bank limit re-evaluated when the student confirms; the payment executes against the payee record the gates checked | `test_lapsed_bank_review_no_longer_covers_the_payment`, `test_expired_quote_cannot_be_paid_with_an_allowance`, `test_payment_after_account_change_uses_the_new_account`, | `test_gate_rechecked_at_execution`, `test_cancelled_allowance_is_rechecked_at_execution`, `test_bank_limit_rechecked_at_execution` |
| Student confirms last | 2-minute single-use confirmation after all permissions | A1 replay refused; `test_confirmation_lasts_two_minutes` |
| Scam signals | Pressure wording in invoice memos or messages is shown as a warning to the student and the family (never changes a decision by itself) | B6 |

## 3. LLM-specific controls

| Risk | Control | Evidence |
|---|---|---|
| Invented amount in the parsed intent | `amount_grounded_in()`: an LLM amount must appear in the user's message, otherwise it is dropped | `test_hallucinated_amount_dropped` |
| Misread intent causes a transfer | Dual agreement: a money-moving intent needs the rules reader **and** the LLM to agree, on the intent and on every field both read (payee, invoice id, amount); the LLM's payee must be named in the message (`test_field_disagreement_asks_the_student`, `test_qwen_payee_must_be_named_in_the_message`). On disagreement nothing is prepared; the student confirms the rules reader's reading (built from stored data) or is asked to rephrase. A confirmed reading still passes the injection check and every gate | `test_llm_cannot_create_money_movement_alone`, `test_disagreement_asks_the_student`, `test_confirmed_reading_still_checks_injection`, story D6; real case in `evidence/archive_v0.1/run_B_llm_guard_v1` (request 2) |
| Hallucinated numbers, units, dates in explanations | `enforce_grounding()` cuts the sentence in code | `test_guard_cuts_invented_number` plus 3 regression tests built from real qwen2.5:7b output |
| Misleading claims | Forbidden terms: "guarantee", "risk-free", "no risk"; per tool, "credit score" | `test_forbidden_terms_cut` |
| Direct injection | `looks_like_injection()` blocks money movement for that message | `test_direct_injection_blocks_money_movement` |
| Indirect injection (memo t16, invoice memos, the student's limit-raise note) | Free text is never parsed for intent and never sent to the LLM: the explanation prompt gets structured fields only (no memos, invoice purposes, notes or warnings). Memos are scanned and reported | `test_note_purpose_and_memos_never_reach_qwen` (records every prompt), `test_memo_injection_reported_not_followed` |
| LLM offline or failing | Information requests fall back to rules-only; **money actions fail closed** with `MODEL_OUTPUT_INVALID` | `test_llm_offline_falls_back`, `test_fail_closed_for_money_only`, story D5 |
| Qwen switch on the screen | Operator only (`set_llm`); switching on re-checks that the model answers (Ollama, or the hosted API with its key and model id) and otherwise refuses with `LLM_UNAVAILABLE`, staying rules-only; every switch is audit-logged. Switching never changes a rule, limit or approval | `TestQwenSwitch` |
| Student cancels an allowance | Refused (`ACTOR_NOT_PERMITTED`); the student can only ask the family to cancel (`ask_cancel`, a flag the family sees), which changes nothing by itself | `TestAskFamilyToCancel`, `test_student_cannot_cancel_an_allowance` |
| Invented or shortened invoice id | An LLM invoice id must equal a whole id written in the message, otherwise it is dropped (real case: Qwen shortened `RENT-2026-11B` to `RENT-2026-11`) | `test_invented_invoice_id_dropped`, `test_partial_invoice_id_rejected` |
| False payment or approval claims in explanations | Status words (e.g. "paid", "complete", "went through", "successful", "approved", "gave approval") are cut unless the outcome says so; information answers never claim a payment, and claim an approval only if the data says "approved"; a small number (0–10) with a currency must be grounded like any other amount; `$` amounts are checked as USD (real cases: "is approved with an allowance of $3000" for a pending CNY request; "the allowance request is now processed" for a request only sent) | `test_guard_cuts_false_payment_claim`, `test_false_approval_and_dollar_label_cut`, `test_status_words_need_the_right_outcome`, `test_false_approval_on_status_is_cut` (real qwen2.5:7b sentence), `test_more_false_payment_claims_are_cut`, `test_small_number_with_a_currency_must_be_grounded` |
| A real number under the wrong label | A number next to "balance", "limit", "left", "fee" or "cap" must sit next to the same word in the facts | `test_number_must_keep_its_label` |
| Instructions hidden in an invoice | Invoice memos are data: flagged, never followed, never used to skip a gate | story D1 |
| Data leaving the device | Local Ollama: nothing leaves. Hosted option (off unless a key or URL is set): what Qwen already sees goes to the provider, i.e. the student's chat message and the structured result fields; the key stays in the environment and is cut from error texts; a local budget caps calls | `llm.py`, `tests/test_hosted_llm.py` |

## 3a. OWASP Top 10 for LLM Applications (2025): where each item stands (v0.4)

The "Try to scam StudyBridge" panel labels its attacks with these ids. "Covered" means a control exists and a
test or story exercises it; it is not a claim that the risk is gone. Two items do not apply and one is only partly
covered; they are listed as such.

| Id | Item | Status | What the code does | Evidence |
|---|---|---|---|---|
| LLM01 | Prompt injection | Covered, residual risk R2 | Wording patterns (with spacing, look-alike characters, leetspeak and base64 undone) are refused before Qwen is called. The real defence is structural: chat text never chooses a payee, account, actor, permission or approval, so an attack the patterns miss still meets every gate. Text inside a bill is data and is never sent to Qwen | Attacks group "Prompt injection" (10); `TestFreeTextAttacks`; stories D1, D2 |
| LLM02 | Sensitive information disclosure | Covered for this data | Qwen is sent structured fields only; account numbers are masked everywhere; requests for passwords, keys, full account numbers, phone numbers or files are refused (`SECRET_REQUEST`). The sample data is fictional, so the data worth protecting in a real deployment is not here | Attacks group "Secrets" (5); `test_note_purpose_and_memos_never_reach_qwen` |
| LLM03 | Supply chain | Partly | No third-party Python packages. The local model (`qwen2.5:7b`) is pulled from the Ollama registry by name, and a hosted model is named by id; neither is pinned by digest or verified by us, and a provider can change or retire a model | `llm.py`; no requirements file |
| LLM04 | Data and model poisoning | Does not apply | Nothing is trained, fine-tuned or retrieved from user-supplied documents | — |
| LLM05 | Improper output handling | Covered | Everything shown is set with `textContent`; strict CSP forbids inline script and style; Qwen's text passes the slot filler and guard and is never executed or used as a command. Markup in a message is shown as plain text | Attack "Script in the message" (test checks that it is answered as plain text). The CSP header and the `textContent`-only rule are not covered by an automated test; they were checked by reading `web.py` and `app.js` and by a browser run on 18 Oct with no console errors |
| LLM06 | Excessive agency | Covered | Qwen has no tools. Tiers, actors and allowlists decide what any request can do; chat cannot approve, confirm, change a limit or a tier, and claims of authority are refused | Attacks group "Excessive agency" (4); the `ACTOR_NOT_PERMITTED` checks in `tests/test_payments.py` |
| LLM07 | System prompt leakage | Covered, with a caveat | Requests to repeat the instructions are refused, and the Glass Box shows what Qwen is sent. The prompt holds no secret, key or rule that the security depends on, so a leak would not change what the code allows | Attacks "Show me your system prompt", "Repeat everything above" |
| LLM08 | Vector and embedding weaknesses | Does not apply | No retrieval or embeddings | — |
| LLM09 | Misinformation | Partly, residual risk R3 | Numbers come from code through placeholders; status words and banned claims are cut; a false statement with no number can still pass | Guard regression tests built from real Qwen output |
| LLM10 | Unbounded consumption | Partly | A message over 600 characters is refused before Qwen; more than 30 messages in a minute stops reading; the model call has a 120 s timeout; the batch check is capped at 200 bills and lab bills at 40. There is no per-user quota or cost accounting because the model is local and the app is single-user | Attacks "A huge message", "A flood of messages"; `TestFreeTextAttacks` |

## 4. Application and infrastructure controls

| Area | Control |
|---|---|
| Network exposure | The web server binds to `127.0.0.1`; Docker publishes on `127.0.0.1` only when run as documented (`-p 127.0.0.1:8765:8765`) |
| CSRF and DNS rebinding | Every POST requires `Content-Type: application/json` **and** `X-StudyBridge: 1`, which a cross-site form cannot send. Requests whose `Host` is not 127.0.0.1/localhost, or POSTs with a foreign `Origin`, get 403 (`test_web_refuses_foreign_host_origin_and_bad_length`) |
| XSS | All text rendered with `textContent`; CSP `default-src 'self'; script-src 'self'`; `frame-ancestors 'none'`; `nosniff` |
| Input size | Request body ≤ 8 KB (a missing, negative or non-numeric length is refused); chat messages are cut to 1,000 characters on the web entry point (the terminal CLI is not capped); bad tier, clock or validity values are refused (`INVALID_CHOICE`) |
| Money precision | `Decimal` everywhere, rounded half-up to cents |
| Audit integrity | SHA-256 hash chain; `verify-audit` exits 1 on tamper and 2 when there is no log; the demo shows detection on a modified copy and records the final record count and head hash |
| Privacy in logs | Account numbers (also written with spaces or dashes), other runs of 8+ digits and fields named like account or phone are masked to `****1234` (`test_grouped_account_numbers_and_phones_are_masked`). The live screen (`/api/state`) echoes the user's own chat text back to the same local user |
| Supply chain | Zero third-party Python dependencies; the container runs as a non-root user |
| Secrets | None are required (local model, sandbox data) |

## 5. Known-risk list

| # | Risk | Severity | Status / mitigation | Residual action |
|---|---|---|---|---|
| R1 | **No user authentication on the web UI.** The student and family screens share one page, and the actor and tier are named by the screen that sends the request, so anyone at the keyboard (or any local program) can act as the family or the operator | High if exposed | Bound to localhost; Host/Origin checks stop other websites (including DNS rebinding) from using it; single-user sandbox; labelled as a demo control. Since v0.6 an optional **family PIN** locks every family action until the Family screen is unlocked (10 minutes; 5 wrong tries lock it for 15 minutes; salted PBKDF2 hash only, never logged or shown), so a student holding the phone cannot approve their own request without it. It does not stop a local program, and it is not a login | Separate logins for student and family (OIDC + HttpOnly, SameSite=Strict cookies), family approval on the family's own device with 2FA |
| R2 | Injection detection is pattern-based, so a reworded attack can bypass the detector | Medium | The detector is only one layer: money still needs TRANSACT tier, a saved beneficiary, limits, dual-reader agreement and human confirmation | Add a classifier-based detector; red-team regularly |
| R3 | Qwen's explanation can state a wrong number, or a false claim without numbers. Observed in `evidence/archive_v0.1/run_C_llm_guard_v2`: "rent … around 40,000 BDT" (actual 62,563.94) passed the old guard | Medium → Low for numbers | Since 17 Oct, Qwen must write every number as a placeholder from a list built from the facts ({amount}, {debit_home_bdt}…); code fills in the values, and a sentence with a typed digit or an unknown placeholder is cut (`slots.py`, `TestNumberPlaceholders`). A live test with qwen2.5:7b (17 Oct, 9 requests) used placeholders in every request, and every number shown came from code. Still open: Qwen can put a real placeholder next to the wrong word, and a false claim with no number passes (seen in the same test: "rent and food, each taking up about half of your spending"; actual 40.44% and 25.95%). The facts section is always written by code | Add an NLI check (e.g. MiniCheck) that each sentence is entailed by the tool JSON |
| R4 | Sandbox rates and fees are static | Medium (advice quality) | Every quote is labelled "SANDBOX snapshot (illustrative)" | Integrate a licensed rate feed with timestamps and a staleness check |
| R5 | Regulatory rules (Bangladesh Bank student-file limits, such as the reported one-semester-at-a-time release, and KYC/AML in China) are not modelled | Medium | Not claimed; transfers are sandbox-only | Add a compliance rule module per corridor; human compliance review |
| R6 | Audit log is tamper-**evident**, not tamper-**proof**: someone with write access can rewrite the whole chain (and its `.head` file) | Low–Medium | Any edit, deletion or reordering inside the chain is detected. Every append also writes the record count and head hash to `<log>.head`, so a log with its newest records cut off fails `verify-audit` with exit code 1 (`test_truncated_audit_log_is_detected_by_the_head_file`); evidence runs also record the head in `summary.json` | Periodically anchor the head hash externally (WORM storage or a signed timestamp) |
| R7 | Pending actions, approvals, allowances, limit raises, account holds and **today's spending totals** (family limit, the daily bank-limit card total and the BDT 600,000 daily cap) are held in memory by default, so restarting the app or pressing Reset clears them | Medium | Pending actions fail safe; the BDT 450,000 per-payment cap still applies. Optional: `web --state FILE` (or `STUDYBRIDGE_STATE`) saves them as JSON after every action, readable by the owner only, and restores them at start, including after a restart in the middle of any of the 31 stories (`test_saved_state_survives_a_restart_at_every_story_step`); an unreadable file means a fresh sandbox. The Glass Box history and the Qwen switch are not saved | Persist counters and approvals (with expiry) in a database |
| R8 | Profile JSON (balances, transactions) is stored unencrypted on disk | Low (fictional data) | Sample data only | Encrypt at rest with an OS keystore for real data |
| R9 | A 7B local model is slower than rules-only (about 6–10 s per request with explanations on the team's Mac; the v0.2 Qwen run took 198 s for 34 requests) | Low (usability) | Rules-only mode is instant | Smaller or faster model for parsing; cache explanations |
| R10 | Credit index could be mistaken for an official score | Low | Disclaimer in every answer; "credit score" wording is cut from the LLM text | User research on wording |
| R11 | Confirmation attempts are limited only for unknown ids | Low | 48-bit ids with a 2-minute TTL stop accidental or model-made confirmations. After 5 confirmations with an unknown id inside 60 seconds, confirming is locked for that window (`CONFIRMATION_LOCKED`, `test_confirmation_locks_after_repeated_unknown_ids`). The ids are not a secret from a local program, which can read them from the screen state (see R1) | Add per-session attempt limiting with login |
| R12 | The bank review is simulated in code. Applying USD 300 as a *daily* total is a team design (ASSUMPTION), stricter than the public rule found (per transaction) | Medium (realism) | Labelled as simulated everywhere | Confirm with a bank; replace with the bank's real limit-increase API |
| R13 | Food and QR payments rely on a name-only check | Low | Capped at CNY 300 each, counted in the family limit, split check on the same payee | Merchant category codes from the QR payload |
| R14 | Family approval depends on the family's judgement; a convincing scam could still be approved if its account were saved as verified | Medium | Only saved, verified accounts pass Gate 1; agents are blocked for tuition; scam signals are shown on the family's screen; a changed account needs a phone check on the stored number and a 24-hour hold | Verified-account registry supplied by the university |
| R15 | The phone check for a changed account is a tick box: the app cannot confirm a call really happened | Medium | The number to call comes from stored data and is shown next to the box; the 24-hour hold still applies; the decision is audit-logged | Call-back through the bank, or a code read out by the payee on the stored number |
| R16 | A student could write a persuasive or manipulative note in a limit-raise request | Low | The note never decides anything and is never sent to the LLM; it is labelled as the student's own words; instruction-like text is flagged; the raise is one day and at most CNY 1,000 | — |
| R17 | The Banglish and Bangla word lists are short, and so are the override phrases in those languages: real students spell things many ways, and an attacker can pick a spelling that is not listed | Medium | A word only helps the rules reader pick an intent; money still needs a stored invoice or saved payee, the family's approval and the student's own confirmation, so a missed word ends as help or a question, and a missed attack phrase still meets every gate (tests send Banglish attacks and check that nothing moves). With Qwen on, some Bangla messages end as a question back because the two readers disagree | Native-speaker word lists and a multilingual classifier checked against the same gates |
| R18 | The invoice X-ray shows which account positions match the saved account, which tells a viewer that the bill copies part of the real number | Low | Only positions and the last four digits (already shown by `mask_account`) leave the server; a test checks that no full account number is in the snapshot; the data is fictional sample data | — |
| R19 | The scam counter could be read as a measured result | Low | It is computed by code from the session, counts each scam once, and is cleared by Reset; it counts the sandbox's own sample scams only | Real counts from a pilot, shown with the date range |
| R20 | The attack patterns in `threats.py` are wording-based, so a reworded or unusual-language attack is not named or refused early | Medium | Naming is not the defence. An attack that is not recognised goes to the normal reading and meets every gate, and a test checks that none of the 35 attacks moves money. With Qwen on, an attack that slips past the patterns is sent to Qwen, which only reads it into a form that the gates then judge | Classifier-based detector; regular red-team rounds; native-speaker Bangla patterns |
| R21 | Qwen's offered reading (a money request only Qwen reads) is a model output shown to the student as a question | Low–Medium | The question is written by code from stored data, is single-use and tied to the message, and nothing runs until the student agrees; the injection check and every gate still apply. This path has been tested with a fake model only; it has not been observed with real qwen2.5:7b | Run it against the real model and add any bad output as a regression test |
| R22 | The Invoice lab can show only the kinds of bill change that the team thought of | Low | 15 scenarios, seeded and repeatable, with expectations derived from the plan; a sabotage test shows the check can fail. Slides must say "200 of 200 seeded random bills got the required result", not "every bill is safe" | Add scenarios as new scams are found (`docs/PROBLEM_RESEARCH.md` is the source) |
| R23 | The red alert and counters could be read as a detector's accuracy | Low | They report what the code did with a message in this session, not a measured detection rate | A labelled test set of real student messages from a pilot |
| R24 | The Bangla text for the new refusal reasons is a first draft | Low | The reasons also exist in English; the Bangla needs native proofreading before any claim of Bangla support for these codes | Native speaker review |
| R25 | The family safe word does not prove who is calling: a person who is pressured can still tell a caller the word, and a family member who is being manipulated can type it | Medium | It is a speed bump and a prompt to ask the caller: approving the risky requests is never one tap, three wrong tries lock it, only a salted hash is stored and it never reaches the audit log, the screen data, Qwen or chat. It is not a login and does not replace the phone check for a changed account | Real accounts with separate devices; a code the student reads out from their own device |
| R26 | A hosted demo has no login, so anyone with the link can press every screen (family approval, operator controls) | High if public | Host and Origin checks refuse other sites; only named host names are accepted (`STUDYBRIDGE_ALLOWED_HOSTS`, `RENDER_EXTERNAL_HOSTNAME`); everything is fictional sandbox data; share the link only for judging and shut the service down afterwards | Separate logins (see R1) |
| R27 | The scam checker is keyword-based: a scam in other words, other languages or with spacing tricks can get "No warning signs found", and a genuine message can be flagged | Medium | The result never says "safe", always tells the student to check with the university, and decides nothing about money; the same message pasted into chat as a payment still meets every gate | A multilingual classifier; user testing with real student messages |
| R28 | A payee the family saves is trusted once the 48 hours pass: a scammer who persuades the family to save an account and wait can still be paid | Medium | The family must tick that they checked the details themselves; the wait gives time to notice; the payee type decides what it can be paid for (tuition only to an institution); limits, approval and the student's confirmation still apply | Verified-account registry from the university (see R14) |
| R29 | With the hosted model option, the provider sees the student's chat message and the structured fields sent to Qwen, the key could leak through a misconfigured server, and an unauthenticated public page lets anyone switch Qwen on and spend the free quota | Medium | Only fictional sandbox data is sent (never invoice notes, memos or pasted scam-check text); the key is read from the environment, sent only in a header and removed from error texts; the local call budget stops calls before the free limit and the app falls back to rules-only; gates never depend on the model | Per-user logins (see R1); a provider agreement for real data; pinning a model version |
| R30 | The duplicate check compares only the payee, amount and currency of open requests within 24 hours, so a scammer's near-duplicate (a different amount, or after a day) is not flagged; the Home deadline card and the risk check are guidance, not detection | Low | A flag adds a warning and the safe word; it never approves or blocks; Gate 1, the family approval, the limits and the student's confirmation decide as before | Beyond-the-rules anomaly scoring on real history |
| R31 | The deadline scheduler is clock-driven (the sandbox clock, and a 5-second thread in the web server), not a real notification service; the SQLite database is a mirror, lost on restart when it is in memory; with a hosted model, the invoice facts used for advice (ids, dates, rounded figures as placeholders) go to that provider | Low | The database never decides a payment; advice is cached, guarded (digits and payment claims cut) and falls back to code text; account numbers and names of people never go in the prompt | A real notification channel and a signed-in user store |
| R32 | The university check trusts the listed official pages: a page can be out of date, a university site could be compromised, and only five universities are listed | Medium | Only team-checked URLs on the university's own `.edu.cn` domain are fetched (no URL from a bill or a user), off-site redirects are refused, each page's date and hash are shown and logged, and the result never says "safe" and always names the official addresses to confirm with | More universities; a university-provided signed account list |
| R33 | The tuition cap (BDT 2,500,000 a day, v0.6) is larger than the everyday caps, so a scam bill marked as tuition could be large | Medium | It applies only to a stored tuition invoice on the verified university account (Gate 1), with the family's approval and the student's confirmation; tuition goes only through the student-file route; the size is still capped, far below laundering-sized "tuition" (`docs/PROBLEM_RESEARCH.md` §1.2) | A per-university fee schedule to compare against |
| R34 | An "up to" allowance (v0.6) covers any one purchase at that shop up to the amount, not only the quoted item | Low | One use, one shop, the family chooses the headroom (at most 10%), the shop must have a stored, valid quote, and the student confirms; the receipt shows what was bought | Tie the allowance to an item category from the quote |
| R35 | The tuition reserve and the payment record could be read as a bank product or a credit report | Low | The reserve is a marker inside the sandbox wallet, enforced by code, set only by the family; a real deployment would need the family's AD bank to hold it, and the app makes no claim that it can lock real money; the record says it is not a credit score, not a bank statement and not checked by any bank; receipts say no real money moved | — |
| R36 | Judge mode hides the Glass Box from students and families, which could look like hiding the workings | Low | One button shows everything; `?judge=1` opens it; the code and the audit log are unchanged by the view | — |

## 6. Test summary

`python -m unittest discover -s tests -t .` runs 348 tests, all passing: 16 core tests, 27 security
tests in `tests/test_security.py`, 155 payment tests in `tests/test_payments.py` (one of which
plays all 31 stories and checks every expected outcome code; others send the 35 attacks, the free-text attacks
and the random bills), 24 data tests in `tests/test_data.py` (the sample data is consistent, every reason
code is exercised by a test or story, and every refusal says who can change it), 6 tests of the research collector in `tests/test_research_tool.py`
(fake network, made-up posts) and 39 tests in `tests/test_extras.py` (scam checker and quiz, safe word, new-payee wait,
hosted host names, deadline guardian, risk check, route recommendation) 14 tests in `tests/test_official.py` (university check, no network), 10 tests in `tests/test_hosted_llm.py` (hosted model client, fake server) and 19 tests in `tests/test_guardian_store.py` (deadline database and scheduler, advice, beneficiary-change and mismatch reasons), 15 tests in `tests/test_bills.py` (bills by message or typed in, the sample scam bills arriving as messages, reporting a message as a scam, the bank's own card limit), 18 tests in `tests/test_money.py` (v0.6: receipts, monthly summary, payment record, tuition reserve, family PIN, university check), and 2 tests in `tests/test_submission.py` (the submission zip leaves out junk, `.git` and `var/`).

## 7. Conclusion

The sandbox meets its security goals for a single-user, local deployment. The LLM cannot
move money, change permissions, act as the family or approve anything. The guard cuts invented
numbers, mislabelled numbers and listed false status claims from its explanations (limits in R3), and
free text from invoices or notes never reaches it. Every payment passes up to three gates, and the
student always confirms last. R1, R4, R5 and R15 must be resolved before any real-money or multi-user use.
