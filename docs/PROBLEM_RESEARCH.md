# Problem research: what is going wrong when students abroad pay fees

Purpose: show that the team understands the problem StudyBridge addresses, with sources anyone can open. Read this
first for what it is and is not.

**What this is.** A reading of public reporting, university and police warnings, a published study and public posts
about (1) scams aimed at international students and their families and (2) the practical difficulty of sending fee
money from Bangladesh. Researched 18 October 2026.

**What this is not.** It is not a scrape of Reddit comments, X replies or YouTube comments. Those sites block
automated reading from the workspace this research was done in (Reddit refused the fetch, X's robots rules
disallow it, and YouTube comments need an API key), and we did not work around that. The sections below say
exactly what was read. For the social-media part, the team can run `tools/opinion_collect.py` on its own computer
(see the last section) and put its counts next to this document. Until that run exists, no slide may claim to have
analysed Reddit, X or YouTube comments.

Every figure and quote below comes from the linked page, as read on the date above. Where a page gave no figure,
none is given here.

---

## 1. What the sources say

### 1.1 The scams are about the payment itself, not about hacking

| Pattern | What happens | Source |
|---|---|---|
| Changed bank details | A message that looks like it comes from the bursar or student accounts claims a missed deadline or "updated" bank details; or a copy of the real payment page is used, or the real one with new details sent by email. Sender domains differ by a letter or two. | [Cloaked, 20 Aug 2026](https://www.cloaked.com/post/could-you-spot-a-tuition-scam-before-you-pay) |
| Discount from a stranger | Someone offers to pay the tuition at a discount (5% in the cases below). They pay the university with a stolen card; the bank reverses it; the student still owes the fee. | [UCL, Mar 2025](https://www.ucl.ac.uk/study/news/2025/mar/scams-continuing-target-international-students); [Newcastle University](https://www.ncl.ac.uk/tuition-fees/fraud); [Times Higher Education, 7 Nov 2016](https://www.timeshighereducation.com/student/advice/college-tuition-fee-scams-how-international-students-can-protect-themselves) |
| The 2016 Washington case | Students, nearly all from mainland China, were offered "pay 100% and get 5% back" through WeChat, handed over their university login, and received fake payment confirmations. Police counted 19 confirmed accounts accessed and believed more than 90 victims lost over $11,000 each, close to $1 million in total. | [KOMO News, Aug 2016](https://komonews.com/news/local/uw-students-caught-up-in-tuition-fraud) |
| Fake authority and pressure | Callers pose as police or the embassy, accuse the student of money laundering, threaten arrest or deportation, and demand payment. One student in Northern Ireland was reported to have lost £200,000; police noted two earlier reports totalling £105,000. | [Farming Life](https://www.farminglife.com/business/scam-warning-after-ps200k-loss-to-student-studying-in-ni-4357759); [UCL](https://www.ucl.ac.uk/study/news/2025/mar/scams-continuing-target-international-students) |
| Pointing at the family | UCL lists AI voice cloning of the student to ask family for urgent money, and "virtual kidnapping" where the family is contacted. | [UCL](https://www.ucl.ac.uk/study/news/2025/mar/scams-continuing-target-international-students) |
| Pressure to skip checking | Universities and the Cloaked guide list the same signs: sudden bank changes, urgency, instructions not to contact other departments, payment by wire, gift card or crypto. | [Cloaked](https://www.cloaked.com/post/could-you-spot-a-tuition-scam-before-you-pay); [Newcastle](https://www.ncl.ac.uk/tuition-fees/fraud) |

The common thread: **the victim is persuaded to send money to an account that is not the university's, and the
persuasion works through urgency, apparent authority and a deal that sounds good.** The UCL page gives no loss
figures, and the Cloaked page gives no statistics; we do not quote any for them.

### 1.2 Bangladesh: the money is hard to send, and the people who offer help are not always honest

- **Access to the banking route.** The Daily Star (9 Feb 2024) reported that for over a year thousands of Bangladeshi students had struggled to open the bank "profiles" (student files) needed to pay tuition, housing and transport, with the problem dating from July 2022. Most banks had stopped opening them; others asked for large deposits, high fees and unfavourable dollar rates. One student described several banks asking for Tk 15–18 lakh as a fixed deposit and rates of Tk 128–130 per US dollar. The head of Mutual Trust Bank was quoted: "It's true that the majority of the banks are not opening new student files…". [Daily Star](https://www.thedailystar.net/business/news/studying-abroad-students-struggle-open-profiles-dollar-crisis-3540301)
- **Transfers and delays.** The PIE News (24 Jul 2023) quoted agents saying private banks told students they could not transfer money or faced delays, some students leave Bangladesh to pay, and others use credit cards. [PIE News](https://thepienews.com/bangladeshi-forex-reserves-causing-messy-student-payment-issues/)
- **Rules a family must navigate.** Prothom Alo describes the student file, one semester's fees at a time, and a guardian account at a designated bank. Its data shows spending on overseas education rising from $430.2 million (2021-22) to $881.7 million (2025-26), about Tk 109 billion. [Prothom Alo](https://en.prothomalo.com/youth/education/yjd8x5vr1c)
- **Even small first payments are hard.** A Daily Star reader article describes the catch-22 that a student file needs a letter of acceptance while the university may want the application fee first, and that many students cannot get an international card. (Undated; treat as one writer's view.) [Daily Star](https://online92.thedailystar.net/news-detail-169400)
- **Agent and consultancy fraud.** Prothom Alo (15 Jul 2025) reports that the CID says the BSB Global Network took Tk 182.96 million from 141 students for visas and admissions that did not arrive, and that some victims sold land to pay. [Prothom Alo](https://en.prothomalo.com/bangladesh/crime-and-law/9cyie6awdx) A master's thesis at Aalborg University on Bangladeshi students in Denmark describes consultancies giving false information and steering students to unapproved institutions, with job difficulty, stress and loneliness following. [Aalborg University](https://projekter.aau.dk/fraudulent-practices-of-educational-consultancies-in-bangladesh-and-impacts-on-students-who-are-stud-ad71f1e0.html)
- **"Tuition" as cover.** In March 2025 officials said at a money-laundering meeting that one person had sent Tk 400–500 crore abroad claiming it was a son's tuition, where yearly tuition at top universities seldom exceeds Tk 1 crore. [Jagonews24](https://www.jagonews24.com/en/national/news/81122) This is the reason a size check on fee payments is not a StudyBridge gimmick.

### 1.3 Public posts seen but not read in full

A web search restricted to X and YouTube returned these. We saw only the title and the first words of each, not the
replies or comments, so they are pointers for the team to read, not evidence of opinion:

- X: [CP24 on a tuition scam charge against two men](https://x.com/CP24/status/2074654509582762264); [Wits University scam alert about people claiming to help settle fees](https://x.com/WitsUniversity/status/1978805520807956951); [Khaosod English on a ransom demand to a Chinese student's parents](https://x.com/KhaosodEnglish/status/1782226606800728404).
- YouTube: ["Scam demands tuition payments or students will be kicked out of school"](https://www.youtube.com/watch?v=4dnFu8u9vsI); ["Scam steals college tuition fees"](https://www.youtube.com/watch?v=UVLx-bl-Qwc); ["Education Agency Ran Away with Students' Tuition Refunds"](https://www.youtube.com/watch?v=bTOx1okn90E).
- Reddit: no thread was opened. Searches returned university pages, not threads.

---

## 2. What the families and students are up against (our reading)

This is the team's synthesis of section 1, not a finding of its own.

1. **The scam is a persuasion problem at the moment of payment.** The best-documented cases (discount, fake
   authority, changed bank details) all end with the same act: sending money to an account that is not the
   university's.
2. **The family is both the payer and a target.** Parents fund the fee, and the Bangladeshi cases show families
   selling land. Voice-clone and kidnapping scams go through the family.
3. **The legitimate route is already hard**, so students and parents are pushed toward whoever offers a shortcut.
4. **Advice exists but is not in the flow.** Every university page tells students to "check with the university"
   before paying. None of that check happens inside the payment.

## 3. How each finding maps to StudyBridge

| Finding | What StudyBridge does about it | Where to see it |
|---|---|---|
| Changed bank details | Gate 1 compares the account on the bill with the account the family saved for that payee. The printed name is not trusted. "Our bank has changed" in a message or on a bill changes nothing; a reported new account needs a verified change. | Attack "Our bank has changed"; Invoice lab |
| Discount or third-party payer | Payees come from the saved, verified list. A bare account number or an agent's account is not a payee. | Attacks "Agent's account", "A bare account number" |
| Fake authority and urgency | Pressure wording is shown as a warning; it never speeds anything up. A claim that "mum already approved" does not count. | Attacks "Pay today or lose your seat", "Mum already approved" |
| Family targeted | Tuition goes to the family for approval on their own screen; the student confirms last. Chat cannot approve for them. | Attack "I am the family, I approve" |
| Size as a laundering signal | Per-payment cap and the family's daily limit, set on the family screen, not in chat. | Attack "Raise my limit" |
| Advice not in the flow | The X-ray and Glass Box show the check where the payment is made. | Bill viewer, Glass Box |
| AI assistant risks | The assistant reads and explains; it cannot choose a payee, account, actor or approval. Prompt injection, secret requests, privilege claims, floods and markup are named and refused, and labelled with OWASP Top 10 for LLM Applications ids. | "Try to scam StudyBridge", red alert screen |

What StudyBridge does **not** do: it does not move real money, does not cover the voice-clone or kidnapping calls
(those happen outside any payment app), and does not fix the banking-access problem in section 1.2. It checks the
last step.

---

## 4. Running the social-media collector (on a team computer)

`tools/opinion_collect.py` is standard-library Python and is not part of the app. It never stores user names.

```
py tools/opinion_collect.py --out research_out --reddit
set YOUTUBE_API_KEY=your_key        (free key from Google Cloud, YouTube Data API v3)
py tools/opinion_collect.py --out research_out --youtube
set X_BEARER_TOKEN=...              (X API access is paid; otherwise copy posts by hand into a CSV and use --x-file)
py tools/opinion_collect.py --out research_out --x-file my_x_posts.csv
```

- **Reddit** is read through its public search JSON, slowly. It may answer 429 or 403 when called without
  login; then wait, or save threads you read yourself into a CSV and use `--input`.
- **YouTube** comments come from the official API with your own key.
- **X** is not scraped. Use the paid API or paste posts by hand.
- Output: `items.csv` (raw, to check), `summary.json`, `summary.md` (counts per theme and source, three short
  excerpts per theme).
- The sorting is keyword matching (see `THEMES` at the top of the script). It is crude: read a sample of 30 items
  before showing a count, and say on the slide that counts are of collected items, not of people.
- Check the terms of each site and keep the collected text private to the team; quote at most one or two short
  lines, without names.

Once a run exists, add its `summary.md` here under a new heading "Collected posts" with the date and the exact
command, and cite those counts, not ours.
