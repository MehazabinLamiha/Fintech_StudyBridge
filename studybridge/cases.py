"""Scam patterns taken from public reports, each with the page it was read on.

Used by the "Try to scam StudyBridge" panel (each case has an attack that replays its pattern as a chat message) and
by the scam-message checker and the Spot-the-scam quiz. `what` is a short summary in the team's own words of what the
cited page says; nothing here is a quotation, and no figure is given that the page did not give (see
docs/PROBLEM_RESEARCH.md for the reading notes). The messages in ATTACKS and QUIZ are made up for the sandbox: they
copy the *pattern* of a case, not any real person's words, and the account numbers are fictional.
"""

CASES = {
    "discount-stranger": {
        "title": "Discount from a stranger",
        "what": "A person offers to pay a student's tuition at a discount (5% off in the reports), asks for the "
                "student's money or login, and pays the university with a stolen card. The bank reverses it later "
                "and the student still owes the fee.",
        "source_title": "KOMO News: scammers target University of Washington students (2016)",
        "source_url": "https://komonews.com/news/local/uw-students-caught-up-in-tuition-fraud",
    },
    "police-call": {
        "title": "\"Police\" say you laundered money",
        "what": "Callers in uniform say they are police, accuse the student of money laundering and demand a "
                "transfer. In the reported Northern Ireland case the callers disappeared after the money was sent.",
        "source_title": "Farming Life: scam warning after a £200k loss to a student",
        "source_url": "https://www.farminglife.com/business/scam-warning-after-ps200k-loss-to-student-studying-in-ni-4357759",
    },
    "refund-back": {
        "title": "\"You were overcharged, send some back\"",
        "what": "The student is told they overpaid or are owed a refund, is shown a fake confirmation, and is asked "
                "to send part of the money back by transfer.",
        "source_title": "Cloaked: could you spot a tuition scam before you pay? (20 Aug 2026)",
        "source_url": "https://www.cloaked.com/post/could-you-spot-a-tuition-scam-before-you-pay",
    },
    "agent-deposit": {
        "title": "An agent's deposit",
        "what": "An education agent takes a large payment for a visa or admission and does not deliver or refund. "
                "Some families sold land to pay.",
        "source_title": "Prothom Alo: trapped by BSB Global Network (15 Jul 2025)",
        "source_url": "https://en.prothomalo.com/bangladesh/crime-and-law/9cyie6awdx",
    },
    "student-tariff": {
        "title": "A made-up government charge",
        "what": "Someone posing as a government agency demands an \"international student tariff\" and threatens the "
                "visa unless the student pays by a hard-to-trace method.",
        "source_title": "Times Higher Education: college tuition fee scams (7 Nov 2016)",
        "source_url": "https://www.timeshighereducation.com/student/advice/college-tuition-fee-scams-how-international-students-can-protect-themselves",
    },
    "new-bank-details": {
        "title": "\"Our bank details have changed\"",
        "what": "A message that looks like it comes from the bursar says payment instructions have changed, or a "
                "copy of the payment page sends the money to a different account.",
        "source_title": "Cloaked: could you spot a tuition scam before you pay? (20 Aug 2026)",
        "source_url": "https://www.cloaked.com/post/could-you-spot-a-tuition-scam-before-you-pay",
    },
    "voice-clone": {
        "title": "A cloned voice calls the family",
        "what": "Scammers copy a student's voice to phone the family with an urgent request for money, or claim the "
                "student has been kidnapped.",
        "source_title": "UCL: scams continuing to target international students (Mar 2025)",
        "source_url": "https://www.ucl.ac.uk/study/news/2025/mar/scams-continuing-target-international-students",
    },
}

# Messages for the Spot-the-scam quiz. `scam` is the answer; `case` is the CASES id it copies (None for a genuine
# message). Written for the sandbox, so the account numbers and names are fictional.
QUIZ = [
    {"id": "q-discount", "scam": True, "case": "discount-stranger",
     "text": "Hi Ayesha, I help students pay fees cheaper. Send me 95% of your tuition and I will pay the "
             "university today with my company card. Only for this week, many students already did it."},
    {"id": "q-genuine-reminder", "scam": False, "case": None,
     "text": "Reminder from the Finance Office: tuition invoice INV-0003 is due on 30 November. Please pay from "
             "the payment page you reach by typing the university's address yourself. We never ask for fees by chat."},
    {"id": "q-police", "scam": True, "case": "police-call",
     "text": "This is Officer Zhang of the police bureau. A bank account in your name was used for money laundering. "
             "Do not tell your family or the school. Transfer your savings to the safe account below today or you "
             "will be arrested."},
    {"id": "q-bank-change", "scam": True, "case": "new-bank-details",
     "text": "Dear student, our university bank account has changed. Please pay the tuition to the new account "
             "6222020200998877661 and reply with the receipt. The old account is closed."},
    {"id": "q-genuine-receipt", "scam": False, "case": None,
     "text": "Your payment of CNY 22,800 for invoice INV-0003 was received by the university. A receipt is in the "
             "student portal. No further action is needed."},
    {"id": "q-refund", "scam": True, "case": "refund-back",
     "text": "Finance office: you were charged twice and we owe you a refund. First send back the extra CNY 4,000 "
             "to our account to unlock the refund. See the attached confirmation."},
    {"id": "q-tariff", "scam": True, "case": "student-tariff",
     "text": "Immigration notice: international students must pay an international student tariff of CNY 3,000 by "
             "wire within 24 hours or the visa will be cancelled."},
    {"id": "q-family-voice", "scam": True, "case": "voice-clone",
     "text": "Mum, it's me, my phone broke and I am using a friend's. I am in trouble and need money sent right now "
             "to this number. Please don't call me back, don't tell Dad."},
]
