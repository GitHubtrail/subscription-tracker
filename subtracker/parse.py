"""Read credit card CSV exports into a common list of transactions.

Every bank names its columns differently, so columns are found by matching
the header against the alias lists below. To support a new bank, add its
column name to the right list, or describe the file in ``formats.json``
(see ``formats.example.json``).
"""

from __future__ import annotations

import csv
import fnmatch
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

# Checked in order, so the first alias found wins (transaction date beats
# posted date, for example).
COLUMN_ALIASES = {
    "date": [
        "transaction date", "trans. date", "trans date", "date",
        "purchase date", "posted date", "post date", "posting date",
    ],
    "description": [
        "description", "merchant", "merchant name", "payee", "name",
        "details", "transaction description", "original description",
    ],
    "amount": ["amount", "transaction amount", "amount (usd)", "amount usd"],
    "debit": ["debit", "debits", "withdrawal", "withdrawals", "charge", "charges"],
    "credit": ["credit", "credits", "deposit", "deposits", "payment"],
    "category": ["category", "transaction category"],
    "card": ["card no.", "card number", "card last 4 digits", "card last four digits", "card", "account number", "account #", "account no.", "card member"],
}

DATE_FORMATS = [
    "%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%Y/%m/%d", "%m-%d-%Y",
    "%b %d, %Y", "%d %b %Y", "%B %d, %Y",
]

# Rows that are payments to the card, not purchases.
NOT_PURCHASES = re.compile(
    r"PAYMENT ?- ?THANK ?YOU|PAYMENT THANK YOU|AUTOPAY|ONLINE PA?YMT|ONLINE PAYMENT|"
    r"PAYMENT RECEIVED|ELECTRONIC PAYMENT|ONLINE/MOBILE RECURRING|MOBILE PA?YMT|MOBILE PAYMENT|MINIMUM PAYMENT|CASH BACK|"
    r"REWARDS? REDEMPTION",
    re.I,
)

# Interest and card fees. Kept apart from subscriptions and shown on their own.
FEES = re.compile(
    r"INTEREST CHARGE|LATE FEE|ANNUAL FEE|MEMBERSHIP FEE|FOREIGN TRANSACTION FEE|"
    r"CASH ADVANCE FEE|BALANCE TRANSFER FEE|RETURNED PAYMENT FEE|OVERLIMIT FEE",
    re.I,
)
FEE_CREDITS = re.compile(
    r"INTEREST ADJ|CREDIT INTEREST|FEE REVERSAL|FEE ADJ|INTEREST CREDIT|FEE CREDIT|REFUND.*(FEE|INTEREST)|"
    r"(FEE|INTEREST).*REFUND",
    re.I,
)

MONTHS = {m.lower() for m in (
    "January February March April May June July August September October November December "
    "Jan Feb Mar Apr Jun Jul Aug Sep Sept Oct Nov Dec Statement Activity Transactions Export"
).split()}

# Short names some banks use in their export file names.
ISSUERS = {
    "capitalone": "Capital One", "amex": "Amex", "americanexpress": "American Express",
    "bofa": "Bank of America", "bankofamerica": "Bank of America", "citi": "Citi", "citibusiness": "CitiBusiness",
    "chase": "Chase", "discover": "Discover", "wellsfargo": "Wells Fargo", "usbank": "US Bank",
}


@dataclass
class Transaction:
    date: date
    description: str
    amount: float  # positive = money spent
    card: str
    source: str
    is_fee: bool = False
    category: str = ""
    is_payment: bool = False  # a payment to the card or loan (amount shown positive)


def _norm(header: str) -> str:
    return re.sub(r"\s+", " ", header.strip().strip("﻿").lower())


def parse_amount(text: str) -> float | None:
    s = (text or "").strip()
    if not s:
        return None
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    if s.upper().endswith("CR"):
        negative, s = True, s[:-2]
    s = s.replace("$", "").replace(",", "").replace(" ", "")
    if s.startswith("-"):
        negative, s = not negative, s[1:]
    if s.startswith("+"):
        s = s[1:]
    try:
        value = float(s)
    except ValueError:
        return None
    return -value if negative else value


def parse_date(text: str, fmt: str | None = None) -> date | None:
    s = (text or "").strip()
    for f in [fmt] if fmt else DATE_FORMATS:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            continue
    return None


def card_name_from_file(path: Path) -> str:
    """'chase-sapphire-2025.csv' -> 'Chase Sapphire'. Years and card numbers
    are dropped (the card number is added back from the file's own column)."""
    stem = re.sub(r"(?<!\d)(19|20)\d{2}(?!\d)|(?<!\d)\d{4,6}(?!\d)", " ", path.stem)
    words = [w for w in re.split(r"[\s_\-.]+", stem) if w]
    words = [w for w in words if w.lower() not in MONTHS]  # "January2026_0470.csv"
    words = [ISSUERS.get(w.lower(), w.capitalize() if w.islower() else w) for w in words]
    return " ".join(words) or "Card"


def load_formats(path: Path | None) -> dict:
    if path and path.exists():
        return json.loads(path.read_text())
    return {}


def _format_for(path: Path, formats: dict) -> dict:
    for pattern, spec in formats.items():
        if fnmatch.fnmatch(path.name.lower(), pattern.lower()):
            return spec
    return {}


def _find_columns(header: list[str], forced: dict) -> dict:
    normalized = [_norm(h) for h in header]
    cols = {}
    for key, aliases in COLUMN_ALIASES.items():
        if key in forced:
            wanted = _norm(forced[key])
            if wanted in normalized:
                cols[key] = normalized.index(wanted)
            continue
        for alias in aliases:
            if alias in normalized:
                idx = normalized.index(alias)
                if idx not in cols.values():
                    cols[key] = idx
                    break
    return cols


def _usable(cols: dict) -> bool:
    return "date" in cols and "description" in cols and (
        "amount" in cols or "debit" in cols
    )


def read_csv(path: Path, formats: dict | None = None,
             card_names: dict | None = None) -> list[Transaction]:
    """card_names maps a card's last four digits, or the card name taken from
    the file name (for files with no card number), to the name to show."""
    spec = _format_for(path, formats or {})
    card_names = {(k[-4:] if k.isdigit() else k.lower()): v for k, v in (card_names or {}).items()}
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    rows = list(csv.reader(text.splitlines()))

    # Some banks put a few summary lines above the real header.
    header_idx, cols = None, {}
    for i, row in enumerate(rows[:30]):
        cols = _find_columns(row, spec.get("columns", {}))
        if _usable(cols):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError(
            f"{path.name}: could not find date, description and amount columns. "
            "Add this file to formats.json (see formats.example.json)."
        )

    card = spec.get("card") or card_name_from_file(path)
    raw = []
    for row in rows[header_idx + 1:]:
        if not any(cell.strip() for cell in row):
            continue

        def cell(key):
            i = cols.get(key)
            return row[i] if i is not None and i < len(row) else ""

        d = parse_date(cell("date"), spec.get("date_format"))
        desc = cell("description").strip()
        if not d or not desc:
            continue
        if "amount" in cols:
            amt = parse_amount(cell("amount"))
        else:
            debit, credit = parse_amount(cell("debit")), parse_amount(cell("credit"))
            amt = abs(debit) if debit else (-abs(credit) if credit else None)
        if amt is None:
            continue
        last4 = re.sub(r"\D", "", cell("card"))[-4:] or re.sub(r"\D", "", spec.get("last4", ""))
        if not last4:
            found = re.findall(r"(?<!\d)\d{4,6}(?!\d)", re.sub(r"(?<!\d)(19|20)\d{2}(?!\d)", "", path.stem))
            last4 = found[0][-4:] if found else ""
        if last4 in card_names:
            name = card_names[last4]
        elif not last4 and card.lower() in card_names:
            name = card_names[card.lower()]
        else:
            name = f"{card} ••{last4}" if last4 else card
        raw.append((d, desc, amt, name, cell("category").strip()))

    # With a single amount column, banks disagree on whether purchases are
    # positive or negative. Purchases outnumber payments, so go with the
    # majority unless formats.json says otherwise.
    if "amount" in cols:
        flip = spec.get("purchases_are")
        if flip is None:
            # Payments and interest show which way round this bank writes
            # amounts. Small monthly files have too few rows to go by counts.
            votes = 0
            for _, desc, a, _, _ in raw:
                if NOT_PURCHASES.search(desc):
                    votes += 1 if a > 0 else -1
                elif FEES.search(desc):
                    votes += 1 if a < 0 else -1
            if votes == 0:
                votes = sum(1 if a < 0 else -1 for _, _, a, _, _ in raw)
            flip = "negative" if votes > 0 else "positive"
        if flip == "negative":
            raw = [(d, desc, -a, c, cat) for d, desc, a, c, cat in raw]

    out = []
    for d, desc, a, c, cat in raw:
        if FEES.search(desc) and a > 0:
            out.append(Transaction(d, desc, round(a, 2), c, path.name, True, cat))
        elif FEE_CREDITS.search(desc) and a < 0:
            out.append(Transaction(d, desc, round(a, 2), c, path.name, True, cat))
        elif a > 0 and not NOT_PURCHASES.search(desc):
            out.append(Transaction(d, desc, round(a, 2), c, path.name, False, cat))
        elif a < 0 and NOT_PURCHASES.search(desc):
            out.append(Transaction(d, desc, round(-a, 2), c, path.name, False, cat, is_payment=True))
    return out


def read_folder(folder: Path, formats: dict | None = None,
                card_names: dict | None = None) -> tuple[list[Transaction], list[str]]:
    """Read every CSV in a folder. Returns transactions and any problems found."""
    transactions, problems = [], []
    seen: dict[tuple, str] = {}
    for path in sorted(folder.glob("*.csv")):
        try:
            for t in read_csv(path, formats, card_names):
                # The same charge can appear in two overlapping exports.
                key = (t.date, t.description, t.amount, t.card)
                if seen.get(key, t.source) != t.source:
                    continue
                seen[key] = t.source
                transactions.append(t)
        except Exception as exc:  # one bad file shouldn't hide the rest
            problems.append(str(exc))
    return transactions, problems
