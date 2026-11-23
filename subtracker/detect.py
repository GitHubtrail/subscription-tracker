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
    ("COSTCO MEMBERSHIP", "Costco Membership"), ("SAMS CLUB MEMBER", "Sam's Club Membership"),
    ("LINKEDIN", "LinkedIn Premium"), ("CANVA", "Canva"), ("NOTION", "Notion"),
    ("1PASSWORD", "1Password"), ("LASTPASS", "LastPass"), ("GITHUB", "GitHub"),
    ("ZOOM.US", "Zoom"), ("CRUNCHYROLL", "Crunchyroll"), ("STARZ", "Starz"),
    ("BARRONS", "Barron's"), ("RENDER.COM", "Render"), ("AIRTABLE", "Airtable"),
    ("DEEPBRAIN", "DeepBrain"),
    ("UBER *ONE", "Uber One"), ("UBER ONE", "Uber One"), ("EVERNOTE", "Evernote"),
    ("DOORDASH DASHPASS", "DashPass"), ("DASHPASS", "DashPass"), ("INSTACART+", "Instacart+"),
    ("WALMART+", "Walmart+"), ("GRUBHUB+", "Grubhub+"), ("TIDAL", "Tidal"),
    ("ESPN", "ESPN+"), ("SLING", "Sling TV"), ("FUBO", "Fubo"),
    ("IL TOLLWAY-AUTOREPLENISH", "Illinois Tollway I-PASS"), ("EZPASS", "E-ZPass"),
    ("E-ZPASS", "E-ZPass"), ("FASTRAK", "FasTrak"), ("SUNPASS", "SunPass"),
]

# Payment processors that put their name in front of the real merchant.
PREFIXES = re.compile(r"^(D J|SQ|TST|SP|PP|PAYPAL|DD|IN|PY|CKO|FS|BT|BTS|WCI|GOOGLE|APLPAY|AMZN MKTP US)\s*\*\s*")

# Household bills: amounts vary from bill to bill, so they're matched on
# timing alone and listed apart from subscriptions.
BILL_CATEGORIES = re.compile(r"utilit|insurance", re.I)
BILL_NAMES = re.compile(
    r"\b(VILLAGE OF|CITY OF|TOWN OF|COUNTY OF|WATER|SEWER|WASTE|ELECTRIC|ENERGY|POWER|"
    r"GAS CO|COMED|NICOR|PG&E|DUKE ENERGY|XFINITY|COMCAST|SPECTRUM|AT&T|VERIZON|"
    r"T-MOBILE|TMOBILE|INSURANCE|GEICO|STATE FARM|PROGRESSIVE|ALLSTATE)\b",
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

    @property
    def renews_if_yearly(self) -> date:
        return self.charged + timedelta(days=365)


def merchant_name(description: str) -> tuple[str, bool]:
    """Return a grouping name for a charge and whether it is a known service."""
    s = re.sub(r"\s+", " ", description.upper().strip())
    s = re.sub(r"\s*-\s*VIRTUAL ACCOUNT NUMBER.*$", "", s)  # Citi virtual card numbers
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
        needed = 2 if known or forced else min_count
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
    as_of: dict[str, date] = {}
    groups: dict[tuple[str, str], list[Transaction]] = defaultdict(list)
    known_names: dict[tuple[str, str], bool] = {}
    bills: set[tuple[str, str]] = set()
    for t in transactions:
        as_of[t.card] = max(as_of.get(t.card, t.date), t.date)
        if t.is_fee:
            continue
        name, known = merchant_name(t.description)
        if listed(name, t.description, ignore):
            continue
        groups[(name, t.card)].append(t)
        known_names[(name, t.card)] = known
        if not known and (BILL_CATEGORIES.search(t.category) or BILL_NAMES.search(t.description)):
            bills.add((name, t.card))

    subs: list[Subscription] = []
    possible: list[Possible] = []
    for (name, card), charges in groups.items():
        charges.sort(key=lambda t: t.date)
        known = known_names[(name, card)]
        forced = listed(name, charges[0].description, include)
        display = rename.get(name.lower(), name)

        if (name, card) in bills:
            freq = _match_frequency(charges, known=True, forced=False)
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
        found = _join_price_changes(found, as_of[card], today)
        if not found:
            # Maybe the price went up partway through: try all charges together.
            freq = _match_frequency(charges, known, forced)
            # Two charges at different prices are only convincing when close together.
            if freq and len(charges) == 2 and freq[1] > 40 and not forced:
                freq = None
            if freq and (known or forced):
                changed = len({t.amount for t in charges}) > 1
                found.append(_make(display, card, charges, freq, as_of[card], today, changed))
        if found:
            subs.extend(found)
        elif known:
            t = charges[-1]
            possible.append(Possible(display, card, t.amount, t.date, len(charges)))

    subs.sort(key=lambda s: (s.is_bill, not s.active, s.name.lower(), s.card))
    possible.sort(key=lambda p: p.charged, reverse=True)
    return subs, possible



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
        if t.is_fee:
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
