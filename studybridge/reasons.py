"""Reason codes: every refusal has a code, a plain meaning and a fix step.

The student and the family always see the same three things: what was
refused (code), why (meaning) and what to do next (fix). Status codes for
outcomes that are not refusals live in STATUS.
"""

REASONS = {
    # Gate 1: invoice, payee, documents
    "INVOICE_REQUIRED": ("This payee type needs a stored invoice, bill or quote.",
                         "Pick the bill under Bills, or ask the payee to send one."),
    "INVOICE_NOT_FOUND": ("No stored invoice has that id.", "Pick the bill under Bills, or ask the payee to send one."),
    "INVOICE_ALREADY_PAID": ("This invoice is already settled.", "Nothing to pay."),
    "QUOTE_EXPIRED": ("The shop's price quote is past its valid-until date.", "Ask the shop for a new quote."),
    "PAYEE_NOT_MATCHING_INVOICE": ("The payee in the request is not the payee on the invoice.",
                                   "Pay the bill exactly as stored: the payee and amount printed on it."),
    "AMOUNT_NOT_MATCHING_INVOICE": ("The amount in the request is not the amount on the invoice.",
                                    "Pay the bill exactly as stored: the payee and amount printed on it."),
    "PAYEE_NOT_VERIFIED": ("The account is an agent, look-alike, personal or unsaved account, "
                           "not the payee's verified account.", "Do not pay this bill. Pay the payee's own bill instead, or ask the payee for one, and tell your family."),
    "ACCOUNT_CHANGED": ("The account on this bill differs from the saved account for this payee.",
                        "Do not pay the new account. Report it: the family checks it by calling the payee on the "
                        "number already on file (never a number on the bill), then a 24-hour wait follows."),
    "ACCOUNT_ON_HOLD": ("The family checked the new account by phone, but the 24-hour wait has not passed.",
                        "Wait until the hold ends."),
    "PHONE_CHECK_REQUIRED": ("A new account can only be approved after the family calls the payee on the number "
                             "already on file.", "Call that number, tick 'I called the number on file', then approve."),
    "DOCS_MISSING": ("A required document is not ready.", "Ask the family to mark the missing document ready."),
    # Everyday path
    "EXEMPT_LIMIT_EXCEEDED": ("A food or QR payment is above the fixed CNY 300 cap for each payment. The family "
                              "cannot change this cap.",
                              "Pay CNY 300 or less, or ask the shop for a bill or quote and request an allowance."),
    "DAILY_LIMIT_REACHED": ("This food or QR payment is more than what is left of today's family daily limit.",
                            "Ask the family to raise your limit for the day, with a short reason."),
    "SPLIT_PAYMENT_SUSPECTED": ("Several small payments to the same payee today add up past the cap.",
                                "Pay with one bill for the full amount, or wait until tomorrow."),
    "ALLOWANCE_NEEDED": ("The payment is above what is left of today's family daily limit.",
                         "Request an allowance."),
    "BANK_DAILY_LIMIT_REACHED": ("Card spending today would pass the simulated daily bank card limit (USD 300 unless "
                                 "the bank changed it), and no bank review covers this payment.",
                                 "Wait until tomorrow, or request an allowance for a bill or quote so the simulated "
                                 "bank reviews it first."),
    "BANK_REVIEW_REJECTED": ("The simulated bank review did not accept the quote or purpose.",
                             "Ask the shop for a correct quote with the item and price, then request the allowance again."),
    "MONTHLY_ALREADY_OPEN": ("A monthly rent allowance for this landlord is already open or waiting.",
                             "Pay this month's bill with it; the family can cancel it to set a new one."),
    "MONTHLY_ONLY_FOR_RENT": ("A monthly allowance is only for rent bills from a saved landlord.",
                              "Request a single-use allowance instead."),
    "ALLOWANCE_EXPIRED": ("The allowance for this purchase has expired.", "Request again."),
    "ALLOWANCE_USED": ("The allowance for this merchant was already used.", "Request again."),
    "ALLOWANCE_MISMATCH": ("An open allowance exists, but for a different merchant, or for less than this amount.",
                           "Request again for this merchant and amount."),
    "ALLOWANCE_NOT_FOR_TUITION": ("Tuition never uses an allowance.", "Pay the tuition invoice instead."),
    "ALLOWANCE_NOT_NEEDED": ("This payment fits inside today's family daily limit.", "Pay it directly."),
    "ALLOWANCE_LIMIT_REACHED": ("Three allowances are already open or waiting.",
                                "Use an open allowance first, or ask the family to cancel one."),
    "APPROVAL_EXPIRED": ("The family approval window has passed.", "Request again."),
    "FAMILY_APPROVAL_NEEDED": ("This university payment needs the family's approval.",
                               "Ask again: the request goes to your family."),
    # Existing guardrails
    "AMOUNT_NOT_POSITIVE": ("The amount to pay is zero or negative.", "Enter an amount above zero."),
    "ABOVE_HARD_CAP": ("The payment is above the BDT per-payment or daily hard cap.", "Pay a smaller amount, or wait until tomorrow when the daily total starts again."),
    "INSUFFICIENT_BALANCE": ("The wallet does not hold enough to fund this payment.", "Ask your family to add money to the wallet, or pay a smaller amount."),
    # Security
    "INJECTION_DETECTED": ("The request contains instruction-override or 'pay everything' wording.",
                           "State a plain request, e.g. 'pay invoice INV-0003'."),
    "SECRET_REQUEST": ("The message asks for something the assistant never gives out: its own instructions, "
                       "passwords or keys, full account numbers, phone numbers or internal files.",
                       "Ask about your payments instead. Bills show the last 4 digits of an account, and the Glass "
                       "Box shows exactly what Qwen is sent."),
    "INPUT_TOO_LONG": ("The message is longer than 600 characters.", "Write a shorter request."),
    "TOO_MANY_MESSAGES": ("More than 30 messages in one minute.", "Wait a minute, then ask again."),
    "ACTOR_NOT_PERMITTED": ("This role cannot perform this action.",
                            "The right person must do it from their own screen."),
    "TIER_TOO_LOW": ("The assistant does not have permission to do this.",
                     "Give it that permission under “Assistant can” at the top, then ask again."),
    "MODEL_OUTPUT_INVALID": ("The language model returned output the code could not use, "
                             "so no money action was prepared (fail closed).", "Ask again."),
    "LIMIT_OUT_OF_RANGE": ("A limit must be a whole amount inside its range: the family daily limit CNY 100 to "
                           "5,000, the bank's daily card limit USD 100 to 1,000.",
                           "Choose a value in range."),
    "INVALID_CHOICE": ("A value sent from the screen is not one of the allowed choices.",
                       "Choose one of the options shown."),
    "DATE_OUT_OF_RANGE": ("A limit raise is for one day: today or up to 7 days ahead.", "Choose a date in range."),
    "NOT_FOUND": ("No such request, allowance or document.", "Check the id."),
    "CONFIRMATION_INVALID": ("No open confirmation has that id. It may have been used already.",
                             "Start the payment again."),
    "CONFIRMATION_LOCKED": ("Too many confirmations with an unknown id in a short time, so confirming is locked.",
                            "Wait a minute, then start the payment again."),
    "CONFIRMATION_EXPIRED": ("The 2-minute confirmation window passed.", "Start the payment again."),
    "TOOL_ERROR": ("The request could not be completed.", "Check the request and try again."),
    "SAFE_WORD_REQUIRED": ("The family set a safe word, and this approval needs it (a large payment, a changed bank "
                           "account, or a request with warnings).",
                           "Ask the person who is asking for the money for the safe word, on a call you start "
                           "yourself. Type it here. If they cannot say it, reject the request."),
    "SAFE_WORD_WRONG": ("That is not the family's safe word. Nothing was approved.",
                        "Check the word with your student by calling them yourself. After 3 wrong tries the "
                        "safe word locks for 15 minutes."),
    "SAFE_WORD_LOCKED": ("Too many wrong safe words in a short time, so approving is locked for a few minutes.",
                         "Wait, then call your student yourself before trying again. Rejecting is still possible."),
    "PAYEE_COOLING_OFF": ("A payee the family saved less than 48 hours ago cannot be paid yet. The wait gives the "
                          "family time to notice a mistake or a scam.",
                          "Wait until the time shown, and check the account with the payee in the meantime."),
    "REPORTED_AS_SCAM": ("The student reported this bill's message as a scam, so it cannot be paid.",
                         "Do not pay it. If the report was a mistake, undo it in Messages, then check the bill "
                         "with the payee on a number you already have."),
    "FAMILY_LOCKED": ("The Family screen is locked with the family PIN.", "Type the PIN to unlock it."),
    "PIN_WRONG": ("That is not the family PIN. Nothing changed.", "Try again. After 5 wrong tries it locks for 15 "
                                                                    "minutes."),
    "PIN_LOCKED": ("Too many wrong PINs, so the Family screen is locked for a while.",
                   "Wait, then try again. If you forgot the PIN, reset the sandbox."),
    "LLM_UNAVAILABLE": ("Qwen cannot be reached from this server, so it cannot be switched on.",
                        "Start Ollama with the qwen2.5:7b model, or set the hosted-model key on the server, then "
                        "switch Qwen on again."),
}

# Who can change each refusal, in the student's words: the first line a blocked student reads (with the one-tap next
# step the screen offers). Every code in REASONS has one (a test checks).
WHO_TEXT = {
    "family": "Your family can change this, on their own screen.",
    "payee": "The payee can fix this: ask them for a new bill or quote.",
    "you": "You can fix this yourself.",
    "wait": "Nobody needs to do anything: it clears with time.",
    "safety": "Nobody can change this. It is a safety rule: do not try to get around it.",
    "operator": "The person running this sandbox can change this.",
}
WHO = {code: who for who, codes in {
    "family": ("DOCS_MISSING", "DAILY_LIMIT_REACHED", "ALLOWANCE_NEEDED", "ALLOWANCE_USED", "ALLOWANCE_EXPIRED",
               "ALLOWANCE_MISMATCH", "ALLOWANCE_LIMIT_REACHED", "MONTHLY_ALREADY_OPEN", "FAMILY_APPROVAL_NEEDED",
               "APPROVAL_EXPIRED", "INSUFFICIENT_BALANCE", "ACCOUNT_CHANGED", "PHONE_CHECK_REQUIRED",
               "SAFE_WORD_REQUIRED", "SAFE_WORD_WRONG", "FAMILY_LOCKED", "PIN_WRONG"),
    "payee": ("INVOICE_REQUIRED", "INVOICE_NOT_FOUND", "QUOTE_EXPIRED", "BANK_REVIEW_REJECTED"),
    "you": ("REPORTED_AS_SCAM", "PAYEE_NOT_MATCHING_INVOICE", "AMOUNT_NOT_MATCHING_INVOICE", "AMOUNT_NOT_POSITIVE", "INJECTION_DETECTED",
            "INPUT_TOO_LONG", "TIER_TOO_LOW", "INVALID_CHOICE", "LIMIT_OUT_OF_RANGE", "DATE_OUT_OF_RANGE", "NOT_FOUND",
            "CONFIRMATION_INVALID", "CONFIRMATION_EXPIRED", "TOOL_ERROR", "MODEL_OUTPUT_INVALID",
            "MONTHLY_ONLY_FOR_RENT", "ALLOWANCE_NOT_FOR_TUITION", "ALLOWANCE_NOT_NEEDED", "INVOICE_ALREADY_PAID",
            "SECRET_REQUEST", "ACTOR_NOT_PERMITTED"),
    "wait": ("ACCOUNT_ON_HOLD", "PAYEE_COOLING_OFF", "TOO_MANY_MESSAGES", "CONFIRMATION_LOCKED", "SAFE_WORD_LOCKED",
             "SPLIT_PAYMENT_SUSPECTED", "BANK_DAILY_LIMIT_REACHED", "PIN_LOCKED"),
    "safety": ("PAYEE_NOT_VERIFIED", "EXEMPT_LIMIT_EXCEEDED", "ABOVE_HARD_CAP"),
    "operator": ("LLM_UNAVAILABLE",),
}.items() for code in codes}


def who(code: str) -> str:
    """The plain 'who can change this' line for a refusal code ('' for a status that is not a refusal)."""
    return WHO_TEXT[WHO[code]] if code in WHO else ""


STATUS = {
    "OK": "Done.",
    "CLARIFY": "A question back: the request is not clear enough to act on.",
    "READY_TO_CONFIRM": "All checks passed. Waiting for the student's final confirmation.",
    "AWAITING_FAMILY": "Waiting for the family's approval (24 hours).",
    "ALLOWANCE_REQUESTED": "Allowance requested. Waiting for the family's approval (24 hours).",
    "ALLOWANCE_APPROVED": "The family approved the allowance.",
    "TUITION_APPROVED": "The family approved the tuition payment. The student opens the notification to confirm.",
    "LIMIT_RAISE_REQUESTED": "Limit raise requested. Waiting for the family's approval (24 hours).",
    "LIMIT_RAISED": "The family raised the daily limit for one day.",
    "ACCOUNT_CHANGE_REQUESTED": "New account reported. Waiting for the family's phone check (24 hours).",
    "ACCOUNT_CHANGE_APPROVED": "The family checked the new account by phone. It can be paid after a 24-hour wait.",
    "REJECTED_BY_FAMILY": "The family rejected the request. Nothing moves.",
    "EXECUTED": "Executed once in the sandbox.",
    "CANCELLED": "Cancelled.",
    "CANCEL_ASKED": "The student asked the family to cancel. Only the family can cancel.",
    "SETTING_CHANGED": "Setting changed.",
}


def meaning(code: str) -> str:
    if code in REASONS:
        return REASONS[code][0]
    return STATUS.get(code, code)


def fix(code: str) -> str:
    return REASONS[code][1] if code in REASONS else ""


class PaymentBlocked(Exception):
    """Raised by a gate. Carries the reason code and a concrete detail."""

    def __init__(self, code: str, detail: str = ""):
        assert code in REASONS, code
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail
