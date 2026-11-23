"""Find subscriptions: charges from the same merchant, on the same card, at
a steady price and a regular interval."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median

from .parse import Transaction

# Well-known services. A match gives a clean name, merges spelling variants
# ("NETFLIX.COM", "NETFLIX INC") and lets a service count with fewer charges.
KNOWN_SERVICES = [
    # More specific names first: "YOUTUBE TV" before "YOUTUBE", and so on.
    ("YOUTUBE TV", "YouTube TV"), ("YOUTUBETV", "YouTube TV"), ("DROPBOX SIGN", "Dropbox Sign"),
    ("GSUITE", "Google Workspace"), ("WORKSPACE_SM", "Google Workspace"),
    ("FAX.COM", "Fax.com"), ("HUMBLEFAX", "HumbleFax"), ("EFAX", "eFax"),
    ("GOOGLE *TV", "Google TV"), ("MSBILL", "Microsoft"),
    ("EXTRA SPACE", "Extra Space Storage"), ("PUBLIC STORAGE", "Public Storage"),
    ("CUBESMART", "CubeSmart"), ("LIFE STORAGE", "Life Storage"), ("STORAGE RENTALS", "Storage Rentals"),
    ("AMAZON GROCERY", "Amazon Grocery subscription"), ("AMAZON DIGI", "Amazon Digital"),
    ("SHAADI", "Shaadi.com"), ("TELLO", "Tello mobile"), ("VCC COUNSELING", "VCC Counseling"),
    ("FAMILY HANDYMAN", "Family Handyman magazine"),
    ("ASTRA-ADDON", "Astra add-on"), ("CRICUT", "Cricut"), ("ZEE5", "ZEE5"), ("SPLASHTOP", "Splashtop"), ("REMOTEPC", "RemotePC"),
    ("ALLIANCE VIRTUAL", "Alliance Virtual Offices"), ("VOIP.MS", "VoIP.ms"),
    ("KEEPERSECURITY", "Keeper"), ("HOSTGATOR", "HostGator"), ("NAMESILO", "NameSilo"),
    ("GODADDY", "GoDaddy"), ("SQUARESPACE", "Squarespace"), ("BLOOMBERG", "Bloomberg"),
    ("NETFLIX", "Netflix"), ("SPOTIFY", "Spotify"), ("HULU", "Hulu"),
    ("DISNEY", "Disney+"), ("HBO", "Max"), ("MAX.COM", "Max"),
    ("YOUTUBE", "YouTube Premium"), ("APPLE.COM/BILL", "Apple (App Store / iCloud)"),
    ("ICLOUD", "iCloud"), ("AMAZON PRIME", "Amazon Prime"), ("PRIME VIDEO", "Prime Video"),
    ("AMZN DIGITAL", "Amazon Digital"), ("KINDLE", "Kindle Unlimited"), ("AUDIBLE", "Audible"),
    ("ADOBE", "Adobe"), ("MICROSOFT", "Microsoft"), ("MSFT", "Microsoft"),
    ("XBOX", "Xbox"), ("PLAYSTATION", "PlayStation"), ("NINTENDO", "Nintendo"),
    ("DROPBOX", "Dropbox"), ("GOOGLE ONE", "Google One"), ("GOOGLE STORAGE", "Google One"),
    ("GOOGLE *G1", "Google One"), ("GOOGLE *SVCS", "Google services"),
    ("GOOGLE *YOUTUBE", "YouTube Premium"), ("GOOGLE *WORKSPACE", "Google Workspace"),
    ("PARAMOUNT", "Paramount+"), ("PEACOCK", "Peacock"), ("SIRIUSXM", "SiriusXM"),
    ("NYTIMES", "New York Times"), ("NYT ", "New York Times"), ("WSJ", "Wall Street Journal"),
    ("PATREON", "Patreon"), ("OPENAI", "ChatGPT"), ("CHATGPT", "ChatGPT"),
    ("ANTHROPIC", "Claude"), ("CLAUDE.AI", "Claude"), ("NORDVPN", "NordVPN"),
    ("EXPRESSVPN", "ExpressVPN"), ("DUOLINGO", "Duolingo"), ("HEADSPACE", "Headspace"),
    ("CALM.COM", "Calm"), ("PELOTON", "Peloton"), ("PLANET FITNESS", "Planet Fitness"),
    ("COSTCO MEMBERSHIP", "Costco Membership"), ("COSTCO *ANNUAL", "Costco Membership"),
    ("COSTCO ANNUAL", "Costco Membership"), ("SAMS CLUB MEMBER", "Sam's Club Membership"),
    ("LINKEDIN", "LinkedIn Premium"), ("CANVA", "Canva"), ("NOTION", "Notion"),
    ("1PASSWORD", "1Password"), ("LASTPASS", "LastPass"), ("GITHUB", "GitHub"),
    ("ZOOM.US", "Zoom"), ("CRUNCHYROLL", "Crunchyroll"), ("STARZ", "Starz"),
    ("BARRONS", "Barron's"), ("RENDER.COM", "Render"), ("AIRTABLE", "Airtable"),
    ("DEEPBRAIN", "DeepBrain"),
    ("UBER *ONE", "Uber One"), ("UBER ONE", "Uber One"), ("EVERNOTE", "Evernote"),
    ("DOORDASH DASHPASS", "DashPass"), ("DASHPASS", "DashPass"), ("INSTACART+", "Instacart+"),
    ("WALMART+", "Walmart+"), ("GRUBHUB+", "Grubhub+"), ("TIDAL", "Tidal"),
    ("ESPN", "ESPN+"), ("SLING", "Sling TV"), ("FUBO", "Fubo"),
    ("IL TOLLWAY-AUTO", "Illinois Tollway I-PASS"), ("EZPASS", "E-ZPass"),
    ("E-ZPASS", "E-ZPass"), ("FASTRAK", "FasTrak"), ("SUNPASS", "SunPass"),
]

# Payment processors that put their name in front of the real merchant.
PREFIXES = re.compile(r"^(D J|SQ|TST|SP|PP|PAYPAL|DD|IN|PY|CKO|FS|BT|BTS|WCI|GOOGLE|APLPAY|AMZN MKTP US)\s*\*\s*")

# Household bills: amounts vary from bill to bill, so they're matched on
# timing alone and listed apart from subscriptions.
# Household bill names that banks shorten in different ways.
KNOWN_BILLS = [("WCI*", "WCI waste service")]

BILL_CATEGORIES = re.compile(r"utilit|insurance", re.I)
BILL_NAMES = re.compile(
    r"\b(VILLAGE OF|CITY OF|TOWN OF|COUNTY OF|WATER|SEWER|WASTE|ELECTRIC|ENERGY|POWER|"
    r"GAS CO|COMED|NICOR|PG&E|DUKE ENERGY|XFINITY|COMCAST|SPECTRUM|AT&T|VERIZON|"
    r"T-MOBILE|TMOBILE|INSURANCE|GEICO|STATE FARM|PROGRESSIVE|ALLSTATE|WCI\*)",
    re.I,
)

US_STATES = set(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV "
    "NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split()
)

# name, typical days, (shortest, longest) gap accepted, fewest charges needed
FREQUENCIES = [
    ("Weekly", 7, (5, 9), 4),
    ("Every 2 weeks", 14, (12, 17), 3),
    ("Monthly", 30.44, (25, 37), 3),
    ("Every 2 months", 60.9, (55, 67), 3),
    ("Quarterly", 91.3, (82, 100), 2),
    ("Every 4 months", 121.75, (110, 135), 2),
    ("Every 6 months", 182.6, (170, 195), 2),
    ("Yearly", 365.25, (340, 390), 2),
]


@dataclass
class Subscription:
    name: str
    card: str
    amount: float
    frequency: str
    period_days: float
    first_charged: date
    last_charged: date
    next_renewal: date
    active: bool
    charges: list[Transaction] = field(repr=False, default_factory=list)
    price_changed: bool = False
    is_bill: bool = False

    @property
    def average(self) -> float:
        recent = self.charges[-6:]
        return sum(t.amount for t in recent) / len(recent)

    @property
    def typical(self) -> float:
        """What to budget per charge: the latest price for subscriptions,
        the recent average for bills that vary."""
        return self.average if self.is_bill else self.amount

    @property
    def monthly_cost(self) -> float:
        return self.typical * 365.25 / self.period_days / 12

    @property
    def yearly_cost(self) -> float:
        return self.typical * 365.25 / self.period_days


@dataclass
class Possible:
    """A known service without a clear billing pattern (often charged once)."""
    name: str
    card: str
    amount: float
    charged: date
    times: int = 1
    overdue: bool = False  # a yearly renewal should have shown up by now

    @property
    def renews_if_yearly(self) -> date:
        return self.charged + timedelta(days=365)


def merchant_name(description: str) -> tuple[str, bool]:
    """Return a grouping name for a charge and whether it is a known service."""
    s = re.sub(r"\s+", " ", description.upper().strip())
    s = re.sub(r"\s*-\s*VIRTUAL ACCOUNT NUMBER.*$", "", s)  # Citi virtual card numbers
    for needle, name in KNOWN_BILLS:
        if s.startswith(needle):
            return name, False
    for needle, name in KNOWN_SERVICES:
        if needle in s + " ":
            return name, True
    s = PREFIXES.sub("", s)
    s = s.split("*")[0]
    tokens = [t for t in re.split(r"\s+", s) if t and not re.search(r"\d", t) and t != "#"]
    while len(tokens) > 1 and tokens[-1] in US_STATES:
        tokens.pop()
    name = " ".join(tokens[:4]) or description.strip()
    return name.title().replace(".Com", ".com"), False


def _cluster_by_price(charges: list[Transaction], loose: bool) -> list[list[Transaction]]:
    """Split one merchant's charges into groups of similar price, so two
    different plans from the same company are tracked separately. Known
    services get a loose match (taxes and small price changes); other
    merchants need a near-identical price, so regular shopping isn't
    mistaken for a subscription."""
    clusters: list[list[Transaction]] = []
    for t in sorted(charges, key=lambda t: t.amount):
        if clusters:
            base = clusters[-1][0].amount
            limit = max(1.0, base * 0.15) if loose else max(0.10, base * 0.02)
            if t.amount - base <= limit:
                clusters[-1].append(t)
                continue
        clusters.append([t])
    return [sorted(c, key=lambda t: t.date) for c in clusters]


def _match_frequency(charges: list[Transaction], known: bool, forced: bool):
    if len(charges) < 2:
        return None
    gaps = [(b.date - a.date).days for a, b in zip(charges, charges[1:])]
    typical = median(gaps)
    for name, days, (lo, hi), min_count in FREQUENCIES:
        if not lo <= typical <= hi:
            continue
        needed = 2 if (known or forced) and days >= 28 else min_count
        if len(charges) == 2 and len({t.amount for t in charges}) == 1 and days <= 31:
            needed = 2
        if len(charges) < needed:
            return None
        # A skipped month (gap of two periods) is fine; random gaps are not.
        ok = sum(1 for g in gaps if lo <= g <= hi or 2 * lo <= g <= 2 * hi)
        if forced or ok / len(gaps) >= 0.75:
            return name, days
        return None
    if forced:
        name, days, _, _ = min(FREQUENCIES, key=lambda f: abs(f[1] - typical))
        return name, days
    # Auto top-ups (tolls, transit cards) charge the same amount whenever the
    # balance runs low, so the gap varies but the price never does.
    if len(charges) >= 4 and len({t.amount for t in charges}) == 1 and 20 <= typical <= 120:
        return _about(typical), typical
    return None


def _about(days: float) -> str:
    if days < 45:
        return f"About every {round(days / 7)} weeks (auto top-up)"
    return f"About every {round(days / 30.44)} months (auto top-up)"


def _make(name, card, charges, freq, as_of, today, price_changed=False, is_bill=False):
    label, days = freq
    last = charges[-1]
    first = charges[0]
    if not is_bill and abs(last.amount - first.amount) > max(0.10, first.amount * 0.02):
        price_changed = True
    # Still active if the next charge isn't overdue in this card's data.
    active = (as_of - last.date).days <= days + max(7, days * 0.25)
    nxt = last.date + timedelta(days=round(days))
    if active:
        while nxt < today:
            nxt += timedelta(days=round(days))
    return Subscription(
        name=name, card=card, amount=last.amount, frequency=label, period_days=days,
        first_charged=charges[0].date, last_charged=last.date, next_renewal=nxt,
        active=active, charges=charges, price_changed=price_changed and not is_bill,
        is_bill=is_bill,
    )


def find_subscriptions(
    transactions: list[Transaction],
    today: date | None = None,
    overrides: dict | None = None,
) -> tuple[list[Subscription], list[Possible]]:
    today = today or date.today()
    overrides = overrides or {}
    ignore = [s.lower() for s in overrides.get("ignore", [])]
    include = [s.lower() for s in overrides.get("include", [])]
    rename = {k.lower(): v for k, v in overrides.get("rename", {}).items()}

    def listed(name, desc, patterns):
        return any(p in name.lower() or p in desc.lower() for p in patterns)

    # The latest date each card's data covers, to judge whether a
    # subscription has stopped.
    # An additional card on an account comes in the same file as the main
    # card, so a card's data runs to the end of the files it appears in.
    file_end: dict[str, date] = {}
    card_files: dict[str, set] = defaultdict(set)
    groups: dict[tuple[str, str], list[Transaction]] = defaultdict(list)
    known_names: dict[tuple[str, str], bool] = {}
    bills: set[tuple[str, str]] = set()
    for t in transactions:
        file_end[t.source] = max(file_end.get(t.source, t.date), t.date)
        card_files[t.card].add(t.source)
        if t.is_fee or t.is_payment or is_loan(t.card):
            continue
        name, known = merchant_name(t.description)
        if listed(name, t.description, ignore):
            continue
        groups[(name, t.card)].append(t)
        known_names[(name, t.card)] = known
        if not known and (BILL_CATEGORIES.search(t.category) or BILL_NAMES.search(t.description)):
            bills.add((name, t.card))
    as_of = _data_end_by_card(card_files, file_end)

    # A household bill sometimes goes on one card and sometimes another, so
    # bills are tracked across all cards.
    for name in {n for n, _ in bills}:
        keys = [k for k in list(groups) if k[0] == name]
        if len(keys) > 1:
            label = " + ".join(sorted(c for _, c in keys))
            groups[(name, label)] = sorted((t for k in keys for t in groups.pop(k)), key=lambda t: t.date)
            as_of[label] = max(as_of[c] for _, c in keys)
            known_names[(name, label)] = False
            bills.add((name, label))

    subs: list[Subscription] = []
    possible: list[Possible] = []
    for (name, card), charges in groups.items():
        charges.sort(key=lambda t: t.date)
        known = known_names[(name, card)]
        forced = listed(name, charges[0].description, include)
        display = rename.get(name.lower(), name)

        if (name, card) in bills:
            freq = _match_frequency(charges, known=True, forced=False)
            if not freq and len(charges) >= 3:
                gap = median((b.date - a.date).days for a, b in zip(charges, charges[1:]))
                freq = (f"About every {max(1, round(gap / 30.44))} months", gap)
            if freq:
                subs.append(_make(display, card, charges, freq, as_of[card], today, is_bill=True))
            continue

        found = []
        for cluster in _cluster_by_price(charges, loose=known or forced):
            # A store visited all the time will now and then show two
            # same-price purchases a year apart. That's shopping, not a plan.
            if not (known or forced) and len(charges) > 2 * len(cluster) + 2:
                continue
            freq = _match_frequency(cluster, known, forced=False)
            if freq:
                found.append(_make(display, card, cluster, freq, as_of[card], today))
            elif known or forced:
                # Two accounts with one company bill on different days of the
                # month at the same price: split them by billing day.
                split = []
                for series in _split_by_day(cluster):
                    freq = _match_frequency(series, known, forced=False)
                    if freq and freq[1] >= 28:
                        split.append(_make(display, card, series, freq, as_of[card], today))
                # Only if the series explain nearly every charge; otherwise
                # it's top-ups or usage at random times.
                if sum(len(x.charges) for x in split) >= 0.8 * len(cluster):
                    found.extend(split)
        found = _join_price_changes(found, as_of[card], today)
        found = _fold_odd_months(found, as_of[card], today)
        if not found:
            # Maybe the price went up partway through: try all charges together.
            freq = _match_frequency(charges, known, forced)
            # Two charges far apart are convincing only if the price is close
            # (a yearly plan that went up), not wildly different (one-off buys).
            if freq and len(charges) == 2 and not forced:
                lo_amt, hi_amt = sorted(t.amount for t in charges)
                if hi_amt > lo_amt * 1.5:
                    freq = None
            # An unknown merchant whose price changed once or twice (a rent or
            # plan increase) rather than on every visit (shopping).
            steady = len(charges) >= 4 and len({t.amount for t in charges}) <= 3
            if freq and (known or forced or steady):
                changed = len({t.amount for t in charges}) > 1
                found.append(_make(display, card, charges, freq, as_of[card], today, changed))
        if found:
            subs.extend(found)
        elif known:
            t = charges[-1]
            overdue = (as_of[card] - t.date).days > 365 + 14
            possible.append(Possible(display, card, t.amount, t.date, len(charges), overdue))

    subs.sort(key=lambda s: (s.is_bill, not s.active, s.name.lower(), s.card))
    possible.sort(key=lambda p: p.charged, reverse=True)
    return subs, possible



def _data_end_by_card(card_files: dict[str, set], file_end: dict[str, date]) -> dict[str, date]:
    """How far each card's data runs. Cards that ever share a file are on one
    account (an additional card member, say), so they share all its files:
    a month with no charge on the extra card still counts as covered."""
    accounts: list[tuple[set, set]] = []  # (cards, files)
    for card, files in card_files.items():
        cards, files = {card}, set(files)
        for acc in [a for a in accounts if a[1] & files]:
            accounts.remove(acc)
            cards |= acc[0]
            files |= acc[1]
        accounts.append((cards, files))
    return {c: max(file_end[f] for f in files) for cards, files in accounts for c in cards}


def _split_by_day(charges: list[Transaction]) -> list[list[Transaction]]:
    groups: list[list[Transaction]] = []
    for t in sorted(charges, key=lambda t: t.date.day):
        if groups and t.date.day - groups[-1][-1].date.day <= 3:
            groups[-1].append(t)
        else:
            groups.append([t])
    if len(groups) < 2:
        return []
    return [sorted(g, key=lambda t: t.date) for g in groups if len(g) >= 2]


def _fold_odd_months(found: list[Subscription], as_of: date, today: date) -> list[Subscription]:
    """A monthly plan that charges a different amount in some months (say a
    higher February bill) shows up as a second, sparse series landing in
    exactly the months the main series skips. Fold it back in."""
    monthly = [s for s in found if s.frequency == "Monthly"]
    if not monthly:
        return found
    out = list(found)
    for main in monthly:
        if main not in out:
            continue
        months = {(t.date.year, t.date.month) for t in main.charges}
        day = median(t.date.day for t in main.charges)
        for other in [s for s in out if s is not main and len(s.charges) < len(main.charges)]:
            if all((t.date.year, t.date.month) not in months and abs(t.date.day - day) <= 4
                   for t in other.charges):
                out.remove(other)
                out.remove(main)
                charges = sorted(main.charges + other.charges, key=lambda t: t.date)
                main = _make(main.name, main.card, charges, ("Monthly", main.period_days), as_of, today, True)
                out.append(main)
                months = {(t.date.year, t.date.month) for t in main.charges}
    return out


def _join_price_changes(found: list[Subscription], as_of: date, today: date) -> list[Subscription]:
    """If one plan stops and another at a new price starts right on schedule,
    it's the same subscription after a price change."""
    found = sorted(found, key=lambda s: s.first_charged)
    out: list[Subscription] = []
    for s in found:
        prev = next((p for p in reversed(out) if p.frequency == s.frequency
                     and p.last_charged < s.first_charged
                     and (s.first_charged - p.last_charged).days <= p.period_days * 1.5), None)
        if prev:
            out.remove(prev)
            charges = prev.charges + s.charges
            s = _make(s.name, s.card, charges, (s.frequency, s.period_days), as_of, today, True)
        out.append(s)
    return out


# Services that do the same job. Paying for two from one group is worth a look.
OVERLAP_GROUPS = {
    "fax service": {"Fax.com", "HumbleFax", "eFax"},
    "TV streaming plan": {"YouTube TV", "YouTube Premium", "Google TV", "Hulu", "Sling TV", "Fubo"},
    "remote desktop tool": {"Splashtop", "RemotePC"},
    "cloud storage plan": {"Dropbox", "Google One", "iCloud"},
    "storage unit": {"Extra Space Storage", "Public Storage", "CubeSmart", "Life Storage",
                      "Storage Rentals"},
    "VPN": {"NordVPN", "ExpressVPN"},
    "password manager": {"1Password", "LastPass", "Keeper"},
}


def find_overlaps(subs: list[Subscription], possible: list[Possible]) -> list[str]:
    """Plain-language notes on active subscriptions that may double up."""
    active = [s for s in subs if s.active and not s.is_bill]
    recent = [p for p in possible if not p.overdue]
    notes = []
    by_name: dict[str, list[Subscription]] = defaultdict(list)
    for s in active:
        by_name[s.name].append(s)
    for name, items in sorted(by_name.items()):
        if len(items) > 1:
            parts = ", ".join(f"{_money(s.amount)} {s.frequency.lower()} on {s.card}" for s in items)
            notes.append(f"{name} is charged {len(items)} ways: {parts}. Separate accounts, or a plan plus an add-on?")
    for label, members in OVERLAP_GROUPS.items():
        names = sorted({s.name for s in active if s.name in members} | {p.name for p in recent if p.name in members})
        if len(names) > 1:
            notes.append(f"More than one {label}: {', '.join(names)}.")
    return notes


def find_moves(subs: list[Subscription], possible: list[Possible]) -> list[str]:
    """Services that stopped on one card and carried on from another."""
    ended = [(s.name, s.card, s.last_charged) for s in subs if not s.active and not s.is_bill]
    ended += [(p.name, p.card, p.charged) for p in possible]
    notes = []
    for s in subs:
        if not s.active or s.is_bill:
            continue
        for name, card, last in ended:
            if name == s.name and card != s.card and s.first_charged >= last - timedelta(days=7):
                notes.append(f"{name} moved from {card} to {s.card} "
                             f"(last on the old card {_d(last)}, first on the new one {_d(s.first_charged)}).")
    return notes


def _d(d: date) -> str:
    return d.strftime("%b %d, %Y").replace(" 0", " ")


def _money(x: float) -> str:
    return f"${x:,.2f}"


def is_loan(card: str) -> bool:
    """Loan accounts are named with the word "loan" in overrides.json."""
    return bool(re.search(r"\bloans?\b", card, re.I))


@dataclass
class Loan:
    card: str
    payment: float | None
    last_paid: date | None
    next_payment: date | None
    interest_per_month: float
    charges: list[Transaction]


def find_loans(transactions: list[Transaction], today: date | None = None) -> list[Loan]:
    today = today or date.today()
    by_card: dict[str, list[Transaction]] = defaultdict(list)
    for t in transactions:
        if is_loan(t.card):
            by_card[t.card].append(t)
    loans = []
    for card, rows in sorted(by_card.items()):
        rows.sort(key=lambda t: t.date)
        payments = [t for t in rows if t.is_payment]
        interest = [t for t in rows if t.is_fee]
        last = payments[-1] if payments else None
        nxt = None
        if last:
            nxt = last.date
            while nxt <= today:
                month = nxt.month % 12 + 1
                year = nxt.year + (nxt.month == 12)
                try:
                    nxt = nxt.replace(year=year, month=month)
                except ValueError:
                    nxt = nxt.replace(year=year, month=month, day=28)
        recent = interest[-3:]
        avg = round(sum(t.amount for t in recent) / len(recent), 2) if recent else 0.0
        loans.append(Loan(card, last.amount if last else None, last.date if last else None, nxt, avg, rows))
    return loans


ANNUAL_FEE = re.compile(r"ANNUAL FEE|MEMBERSHIP FEE", re.I)


def _add_year(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:  # Feb 29
        return d.replace(year=d.year + 1, day=28)


@dataclass
class CardFees:
    card: str
    charges: list[Transaction]
    last_12_months: float
    per_month: float
    annual_fee: float | None = None
    annual_fee_next: date | None = None


def fees_by_card(transactions: list[Transaction]) -> list[CardFees]:
    """Interest and card fees (less any refunds of them), per card, over the
    latest 12 months of that card's data."""
    out = []
    by_card: dict[str, list[Transaction]] = defaultdict(list)
    for t in transactions:
        if t.is_fee and not is_loan(t.card):
            by_card[t.card].append(t)
    for card, fees in sorted(by_card.items()):
        fees.sort(key=lambda t: t.date)
        latest = fees[-1].date
        cutoff = latest - timedelta(days=365)
        recent = [t for t in fees if t.date > cutoff]
        span_months = max(1, round(((latest - max(recent[0].date, cutoff)).days) / 30.44) + 1)
        total = round(sum(t.amount for t in recent), 2)
        yearly = [t for t in fees if ANNUAL_FEE.search(t.description)]
        if yearly:
            last = yearly[-1]
            out.append(CardFees(card, fees, total, round(total / span_months, 2),
                                last.amount, _add_year(last.date)))
        else:
            out.append(CardFees(card, fees, total, round(total / span_months, 2)))
    return out
