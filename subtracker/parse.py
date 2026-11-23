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
    stem = re.sub(r"\d+", lambda m: " " if len(m.group()) in (4, 5, 6, 8) else m.group(), path.stem)
    words = [w for w in re.split(r"[\s_\-.]+", stem) if w]
    words = [w for w in words if w.lower() not in MONTHS]  # "January2026_0470.csv"
    words = [ISSUERS.get(w.lower(), w.capitalize() if w.islower() else w) for w in words]
    return " ".join(words) or "Card"


def load_formats(path: Path | None) -> dict:
    if path and path.exists():
        return json.loads(path.read_text(encoding="utf-8-sig"))
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


def _issuer_from_header(header: list[str], preamble: list[list[str]]) -> str:
    """Which bank wrote this file, judged by its column names (file names
    are often just 'activity (3).csv' or 'transaction_download.csv')."""
    h = set(header)
    above = " ".join(" ".join(r) for r in preamble).lower()
    if "barclays" in above or {"card last 4 digits", "purchased by"} & h:
        return "Barclays"
    if {"reference number", "payee"} <= h:
        return "Bank of America"
    if "card no." in h:
        return "Synchrony" if "item" in h else "Capital One"
    if {"post date", "type"} <= h:
        return "Chase"
    if {"status", "member name"} <= h:
        return "Citi"
    if header[:2] == ["date", "description"] and "amount" in h:
        return "Amex"
    return ""


def _account_in_preamble(preamble: list[list[str]]) -> str:
    """'Account Number: XXXXXXXXXXXX1488' above the header (Barclays)."""
    for row in preamble:
        m = re.search(r"account (?:number|no\.?|#)\s*:?\s*[x*•.\- ]*(\d{4,})", " ".join(row), re.I)
        if m:
            return m.group(1)[-4:]
    return ""


def _norm_card_names(card_names: dict | None) -> dict:
    return {(k[-4:] if k.isdigit() else k.lower()): v for k, v in (card_names or {}).items()}


def card_label(issuer: str, last4: str, card_names: dict) -> str:
    """The name shown for a card: the overrides.json name, else 'Chase x1234'."""
    if last4 in card_names:
        return card_names[last4]
    return f"{issuer or 'Card'} x{last4}"


def read_csv(path: Path, formats: dict | None = None,
             card_names: dict | None = None, files: dict | None = None) -> list[Transaction]:
    """card_names maps a card's last four digits, or the card name taken from
    the file name (for files with no card number), to the name to show.
    files maps file names (wildcards allowed) to a card, for files that have
    no card number at all."""
    txns, issuer, known = _read(path, formats, card_names, files)
    if not known:
        name = _fallback_name(path, issuer, _norm_card_names(card_names)) or f"{issuer or 'Card'} (card not named)"
        for t in txns:
            t.card = name
    return txns


def _read(path: Path, formats: dict | None, card_names: dict | None,
          files: dict | None) -> tuple[list[Transaction], str, bool]:
    """Returns the transactions, the bank, and whether the card is known.
    When it isn't, every transaction's card is left empty."""
    spec = _format_for(path, formats or {})
    card_names = _norm_card_names(card_names)
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

    from_name = card_name_from_file(path)
    issuer = spec.get("card") or _issuer_from_header(
        [_norm(h) for h in rows[header_idx]], rows[:header_idx])
    named_issuer = next((ISSUERS[w.lower()] for w in re.split(r"[\s_\-.()]+", path.stem)
                         if w.lower() in ISSUERS), "")
    if named_issuer.startswith(issuer or "~"):  # "CitiBusiness" is more exact than "Citi"
        issuer = named_issuer
    issuer = issuer or named_issuer or from_name

    # The card for the whole file, when the rows don't say.
    file_card = re.sub(r"\D", "", spec.get("last4", "")) or _account_in_preamble(rows[:header_idx])
    if not file_card:
        found = re.findall(r"(?<!\d)\d{4,6}(?!\d)", re.sub(r"(?<!\d)(19|20)\d{2}(?!\d)", "", path.stem))
        file_card = found[0][-4:] if found else ""
    whole_file_name = "" if file_card else _name_for_file(path.name, files, card_names, wildcards=False)
    if not whole_file_name and not file_card and from_name.lower() in card_names:
        whole_file_name = card_names[from_name.lower()]  # "CitiBusiness" for citibusiness_2026.csv

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
            amt = parse_amount(cell("amount").lstrip("="))
        else:
            debit, credit = parse_amount(cell("debit")), parse_amount(cell("credit"))
            amt = abs(debit) if debit else (-abs(credit) if credit else None)
        if amt is None:
            continue
        if whole_file_name:
            name = whole_file_name
        else:
            # An account number above the header covers every card on it.
            last4 = file_card if _account_in_preamble(rows[:header_idx]) else (
                re.sub(r"\D", "", cell("card"))[-4:] or file_card)
            name = card_label(issuer, last4, card_names) if last4 else ""
            if not name and "card" in cols:  # a card column, but empty on this row
                name = _name_for_file(path.name, files, card_names, wildcards=False)
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
    known = all(t.card for t in out)
    if not known:
        for t in out:
            t.card = ""
    return out, issuer, known


def _loose(file_name: str) -> str:
    """'Year to date (1).CSV' and 'year_to_date 1.csv' compare the same."""
    return re.sub(r"[\s_\-]+", " ", re.sub(r"[()]", " ", file_name.lower())).strip().replace(" .", ".")


def _name_for_file(file_name: str, files: dict | None, card_names: dict, wildcards: bool = True) -> str:
    """The card named for this file in overrides.json "files". Exact names
    are checked first; patterns like "activity*.csv" only when wildcards."""
    name = _loose(file_name)
    for pattern, card in (files or {}).items():
        if _loose(pattern) == name or (wildcards and fnmatch.fnmatch(name, _loose(pattern))):
            key = card[-4:] if card.isdigit() else card.lower()
            return card_names.get(key, card)
    return ""


# Words banks put in default download names ("Year to date (1).csv").
def _loan_name(txns: list[Transaction], issuer: str, card_names: dict) -> str:
    """A file with interest and payments but no purchases is a loan account
    (the Amex personal loan, say). Use the one loan named in overrides.json
    for this bank, else a name with "loan" in it so it lands under Loans."""
    payments = {t.amount for t in txns if t.is_payment}
    if not txns or any(not t.is_payment and not t.is_fee for t in txns) or len(payments) != 1:
        return ""  # a loan is paid the same instalment each time
    first = (issuer or "Card").split()[0].lower()
    loans = {v for v in card_names.values() if "loan" in v.lower() and first in v.lower()}
    return loans.pop() if len(loans) == 1 else f"{issuer or 'Card'} loan (card not named)"


GENERIC_WORDS = {
    "last", "this", "year", "years", "month", "months", "days", "date", "to", "from", "ytd", "all",
    "recent", "current", "period", "history", "summary", "activity", "transactions", "transaction",
    "download", "downloads", "statement", "statements", "export", "data", "file", "card", "credit",
    "creditcard", "account", "copy",
}


def _fallback_name(path: Path, issuer: str, card_names: dict) -> str:
    """A name for a file with no card number, from words in its file name:
    a matching card in overrides.json, else the file name itself when it is
    more than a bank's default ('amex-gold-2026.csv' -> 'Amex Gold')."""
    hit = _name_from_words(path, issuer, card_names)
    if hit:
        return hit
    words = [w for w in re.findall(r"[A-Za-z]+", path.stem)
             if w.lower() not in GENERIC_WORDS and w.lower() not in MONTHS]
    issuer_words = {w.lower() for w in re.findall(r"[A-Za-z]+", issuer)} | set(ISSUERS)
    if not any(w.lower() not in issuer_words for w in words):
        return ""
    return " ".join(ISSUERS.get(w.lower(), w.capitalize() if w.islower() else w) for w in words)


def _name_from_words(path: Path, issuer: str, card_names: dict) -> str:
    """'Citi Costco Last year (2025).csv' -> the one card named with 'Costco'
    and 'Citi' in overrides.json."""
    words = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", path.stem)}
    words -= GENERIC_WORDS
    words -= set(ISSUERS) - {"citibusiness"}  # 'Citi' alone says nothing about which Citi card
    names = {v for v in card_names.values() if issuer.split()[0].lower() in v.lower()} if issuer else set()
    hits = {v for v in names if words & {w.lower() for w in re.findall(r"[A-Za-z]+", v)}}
    return hits.pop() if len(hits) == 1 else ""


def _csv_files(folder: Path) -> list[Path]:
    # Chase on a Mac saves .CSV, so don't rely on the case of the extension.
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".csv") \
        if folder.is_dir() else []


def read_folder(folder: Path, formats: dict | None = None,
                card_names: dict | None = None,
                files: dict | None = None) -> tuple[list[Transaction], list[str]]:
    """Read every CSV in a folder. Returns transactions and any problems found.

    Files keep the names the bank gave them. The card comes from the file's
    own columns where it has one. Files with no card number take the card of
    another file they overlap with, a name in overrides.json "files", or a
    card name that matches words in the file name."""
    problems = []
    read: list[tuple[Path, list[Transaction], str, bool]] = []
    for path in _csv_files(folder):
        try:
            read.append((path, *_read(path, formats, card_names, files)))
        except Exception as exc:  # one bad file shouldn't hide the rest
            problems.append(str(exc))

    names = _norm_card_names(card_names)
    known = [(issuer, txns) for _, txns, issuer, ok in read if ok]
    unknown = [r for r in read if not r[3]]
    changed = True
    while unknown and changed:  # one match can lead to the next
        changed = False
        for item in list(unknown):
            path, txns, issuer, _ = item
            card = _overlapping_card(txns, issuer, known)
            if card:
                for t in txns:
                    t.card = card
                known.append((issuer, txns))
                unknown.remove(item)
                changed = True

    by_issuer: dict[str, list[Path]] = {}
    for path, txns, issuer, _ in unknown:
        name = (_loan_name(txns, issuer, names) or _name_for_file(path.name, files, names)
                or _fallback_name(path, issuer, names))
        if name:
            for t in txns:
                t.card = name
            continue
        name = f"{issuer or 'Card'} (card not named)"
        for t in txns:
            t.card = name
        by_issuer.setdefault(name, []).append(path)
    for name, paths in sorted(by_issuer.items()):
        shown = ", ".join(p.name for p in paths[:4]) + (f" and {len(paths) - 4} more" if len(paths) > 4 else "")
        problems.append(
            f"{len(paths)} file{'s' if len(paths) > 1 else ''} with no card number ({shown}) "
            f"{'are' if len(paths) > 1 else 'is'} shown as \"{name}\". To name the card, add each file to "
            f"\"files\" in overrides.json, for example \"files\": {{\"{paths[0].name}\": \"1234\"}}."
        )

    transactions = []
    seen: dict[tuple, str] = {}
    for _, txns, _, _ in read:
        for t in txns:
            # The same charge can appear in two overlapping exports.
            key = (t.date, t.description, t.amount, t.card)
            if seen.get(key, t.source) != t.source:
                continue
            seen[key] = t.source
            transactions.append(t)
    return transactions, problems


def _overlapping_card(txns: list[Transaction], issuer: str,
                      known: list[tuple[str, list[Transaction]]]) -> str:
    """The card of a known file from the same bank that has the same charges.
    Payments are left out, since two cards are often paid the same amount on
    the same day, and a real overlap shares a good part of the smaller file."""
    def charges(rows):
        return {(t.date, t.description, t.amount) for t in rows if not t.is_payment}

    mine = charges(txns)
    best, best_shared = "", 0
    for other_issuer, other in known:
        if other_issuer != issuer:
            continue
        theirs = charges(other)
        shared = [t.card for t in other if not t.is_payment and (t.date, t.description, t.amount) in mine]
        if len(shared) >= max(2, 0.25 * min(len(mine), len(theirs))) and len(shared) > best_shared:
            best, best_shared = max(set(shared), key=shared.count), len(shared)
    return best
