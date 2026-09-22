"""Synthetic support-ticket generator with known-correct labels.

Ground truth has to be known by construction, not guessed at. Each ticket is
assembled from independently chosen phrase banks -- which bank we draw from
*is* the label -- so intent, urgency, frustration level, refund request, and
churn risk are all unambiguous, even though the resulting message reads like
a normal email.
"""
import random

INTENTS = {
    "refund": [
        "We were charged twice for our {plan} plan {period}. Please look into the duplicate charge.",
        "I noticed an extra charge of ${amount} on my card that I don't recognize from your service.",
        "Our invoice #{invoice} was billed at the wrong amount -- we were quoted ${quoted} but charged ${charged}.",
        "I canceled last month but you still charged my card ${amount}.",
        "Can you reverse the charge from {date}? I was double billed.",
    ],
    "technical_help": [
        "Our integration with your API has been throwing 500 errors since this morning.",
        "The dashboard has been down for the last two hours and none of my team can log in.",
        "Webhooks stopped firing after your last deploy -- nothing has come through since {date}.",
        "We're getting a 'connection refused' error every time we try to sync data.",
        "The mobile app crashes immediately on launch after the latest update.",
    ],
    "billing_question": [
        "Can you explain the line items on invoice #{invoice}? I don't understand the extra fee.",
        "What payment methods do you accept for annual plans?",
        "Does the {plan} plan include the API add-on or is that billed separately?",
        "I'd like to update the billing address on our account.",
        "When does our current billing cycle renew?",
    ],
    "information": [
        "What's the difference between the {planA} and {planB} plans?",
        "Do you have documentation for setting up SSO?",
        "Is there a free trial available before we commit to a paid plan?",
        "Can you point me to your uptime status page?",
        "How many seats are included in the {plan} plan?",
    ],
    "cancellation": [
        "I'd like to downgrade from {planA} to {planB} starting next cycle.",
        "Please cancel our subscription at the end of this billing period.",
        "We no longer need the {addon} add-on -- please remove it from our plan.",
        "How do I close our account entirely?",
        "We're not renewing next month, please confirm the cancellation.",
    ],
    "other": [
        "Just wanted to say the new dashboard redesign looks great!",
        "Do you have a referral program for existing customers?",
        "Are you hiring for backend engineering roles right now?",
        "Can we schedule a call to discuss a potential partnership?",
        "Loved your talk at the conference last week -- any chance of a recording?",
    ],
}

URGENCY_BANKS = {
    0: [],  # no clause -- "no time pressure"
    1: [
        "It would help to get this looked at soon.",
        "Hoping to hear back in the next day or two.",
        "Not blocking us yet, but we'd like it addressed soon.",
    ],
    2: [
        "This needs to be resolved today.",
        "We have a deadline tomorrow morning and this is blocking us.",
        "Please treat this as urgent -- our team can't work until it's fixed.",
        "Time-sensitive: we need an answer before end of day.",
        "This is blocking a client launch scheduled for tomorrow.",
    ],
}

FRUSTRATION_BANKS = {
    0: [
        "Thanks in advance for your help.",
        "No rush, just wanted to flag it.",
        "Appreciate you looking into this.",
    ],
    1: [
        "This is a bit frustrating, but I understand these things happen.",
        "I'd appreciate a quick resolution when you get a chance.",
        "Hoping we can sort this out soon.",
    ],
    2: [
        "This is really inconvenient and it's the second time this month.",
        "I'm getting pretty frustrated with these repeated issues.",
        "Honestly, this shouldn't be this hard to fix.",
    ],
    3: [
        "This is completely unacceptable and I am furious about it.",
        "I am extremely upset -- this is the last straw.",
        "This is a disaster and I expect this fixed immediately.",
    ],
}

REFUND_CLAUSES = [
    "Please refund the charge as soon as possible.",
    "I'd like my money back for this.",
    "Can you process a refund for this amount?",
    "We expect a full refund.",
]

CHURN_CLAUSES = [
    "If this isn't resolved we'll have to consider canceling and moving to a competitor.",
    "We're seriously evaluating other providers at this point.",
    "Continued issues like this will push us to switch services.",
    "This is close to making us leave for good.",
]

GREETINGS = ["Hi team,", "Hello,", "Hi there,", "Hey,", ""]
SIGNOFFS = ["Thanks,", "Best,", "Regards,", ""]

PLANS = ["Starter", "Pro", "Business", "Enterprise"]
PERIODS = ["this month", "last cycle", "in March", "on our last invoice"]
DATES = ["Monday", "last Tuesday", "the 3rd", "yesterday"]
ADDONS = ["API add-on", "priority support", "extra seats", "advanced analytics"]

FRUSTRATION_WEIGHTS = [0.35, 0.30, 0.20, 0.15]
LOW_STAKES_FRUSTRATION_WEIGHTS = [0.75, 0.25, 0.0, 0.0]
URGENCY_WEIGHTS = [0.65, 0.20, 0.15]
LOW_STAKES_INTENTS = {"information", "other"}


def _fill(template, rng):
    plan_a, plan_b = rng.sample(PLANS, 2)
    return template.format(
        plan=rng.choice(PLANS),
        planA=plan_a,
        planB=plan_b,
        amount=rng.randint(15, 400),
        quoted=rng.randint(15, 200),
        charged=rng.randint(200, 400),
        invoice=rng.randint(10000, 99999),
        date=rng.choice(DATES),
        period=rng.choice(PERIODS),
        addon=rng.choice(ADDONS),
    )


def generate_ticket(rng):
    intent = rng.choice(list(INTENTS.keys()))
    body = _fill(rng.choice(INTENTS[intent]), rng)

    low_stakes = intent in LOW_STAKES_INTENTS
    weights = LOW_STAKES_FRUSTRATION_WEIGHTS if low_stakes else FRUSTRATION_WEIGHTS
    frustration = rng.choices([0, 1, 2, 3], weights=weights)[0]
    urgency_level = 0 if low_stakes else rng.choices([0, 1, 2], weights=URGENCY_WEIGHTS)[0]
    is_urgent = urgency_level >= 2
    refund_requested = False if low_stakes else rng.random() < (0.85 if intent == "refund" else 0.06)
    churn_risk = False if low_stakes else rng.random() < 0.25

    parts = []
    greeting = rng.choice(GREETINGS)
    if greeting:
        parts.append(greeting)
    parts.append(body)
    if refund_requested:
        parts.append(rng.choice(REFUND_CLAUSES))
    if churn_risk:
        parts.append(rng.choice(CHURN_CLAUSES))
    if urgency_level > 0:
        parts.append(rng.choice(URGENCY_BANKS[urgency_level]))
    parts.append(rng.choice(FRUSTRATION_BANKS[frustration]))
    signoff = rng.choice(SIGNOFFS)
    if signoff:
        parts.append(signoff)

    message = " ".join(parts)

    return {
        "message": message,
        "labels": {
            "intent": intent,
            "is_urgent": is_urgent,
            "frustration": frustration,
            "urgency_level": urgency_level,
            "refund_requested": refund_requested,
            "churn_risk": churn_risk,
        },
    }
