"""Code checks on what a model writes. A model proposes; these checks and the policy decide.

Nothing here trusts a model's text: amounts, ids and promises are checked against the PayPal record and the policy.
Buyer messages are read only as data; a message that tries to give the agent orders is receipted and changes nothing.
"""
import hashlib
import re

INJECTION = {
    "ignore_instructions": r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}\b(instruction|limit|rule|polic|prompt|above|previous|cap)",
    "new_policy": r"\b(new|updated|changed) (polic|rule|instruction|limit)",
    "role_claim": r"\b(system prompt|system message|developer mode|you are now|act as|jailbreak|i am (the )?(owner|admin|merchant|paypal))\b",
    "demands_amount": r"\b(refund|pay|send|offer)\b.{0,25}(\$|usd|us\$)\s?\d|(\$|usd)\s?\d[\d,.]*.{0,25}\b(refund|now|immediately)\b",
    "unlimited": r"\b(unlimited|no limit|without (any )?limit|full amount regardless)\b",
}

PROMISES = re.compile(
    r"\b(replace(ment)?|re-?ship|re-?send|free|guarantee[sd]?|store credit|voucher|coupon|discount|gift card|extra|bonus|compensat\w+|"
    r"in addition|on top of|we will also|we'?ll also|additionally|within \d+ (hours?|days?|minutes?)|by (tomorrow|monday|tuesday|wednesday|thursday|friday)|"
    r"future orders?|next order|full refund)\b", re.I)
MONEY = re.compile(r"(?:(?:US\$|\$|USD)\s?(\d[\d,]*(?:\.\d{1,2})?))|(?:(\d[\d,]*(?:\.\d{1,2})?)\s?(?:USD|dollars?|US\$|\$))", re.I)
ID_LIKE = re.compile(r"\b(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9][A-Za-z0-9_-]{7,}\b")
LINKS = re.compile(r"https?://|www\.|@\w+\.\w+", re.I)


def injection_signals(text):
    """Names of the order-giving patterns found in a buyer message. Empty when the message reads as an ordinary complaint."""
    return [name for name, pattern in INJECTION.items() if re.search(pattern, text or "", re.I | re.S)]


def digest(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def minor(text):
    whole, _, cents = text.replace(",", "").partition(".")
    return int(whole) * 100 + int((cents + "00")[:2])


def amounts_in(text):
    return [minor(a or b) for a, b in MONEY.findall(text or "")]


def check_text(text, offer_minor, currency, allowed_ids, need_amount):
    """Problems with model written text. An empty list means the text may be sent.

    Every money amount in the text must equal the offer (and the offer must be named when need_amount), no promise beyond the
    offer, every id-like token must exist in the record, no links, a length bound."""
    problems = []
    if not isinstance(text, str) or not text.strip():
        return ["empty text"]
    if len(text) > 700:
        problems.append("longer than 700 characters")
    if LINKS.search(text):
        problems.append("contains a link or address")
    found = amounts_in(text)
    wrong = sorted({a for a in found if a != offer_minor})
    if wrong:
        problems.append("amount in text differs from the offer: " + ", ".join(f"{a / 100:.2f}" for a in wrong))
    if need_amount and offer_minor and offer_minor not in found:
        problems.append("offer amount missing from text")
    if need_amount and offer_minor and currency.upper() not in text.upper():
        problems.append("currency missing from text")
    promise = PROMISES.search(text)
    if promise:
        problems.append(f"promise beyond the offer: '{promise.group(0)}'")
    known = {i.lower() for i in allowed_ids if i}
    for token in ID_LIKE.findall(text):
        if token.lower() not in known and not any(token.lower() in k for k in known):
            problems.append(f"id not in the record: {token}")
    return problems


def cited_ids(value):
    ids = (value or {}).get("cited_ids", [])
    return [i for i in ids if isinstance(i, str)] if isinstance(ids, list) else []
