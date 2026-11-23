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
    ("AMAZON GROCERY", "Amazon Grocery subscription"), ("AMAZON DIGI", "Amazon Digital"), ("DIGITAL PURCHASE SEATTLE", "Amazon Digital"),
    ("SHAADI", "Shaadi.com"), ("TELLO", "Tello mobile"), ("VCC COUNSELING", "VCC Counseling"),
    ("FAMILY HANDYMAN", "Family Handyman magazine"),
    ("BUFFALOGROVEORTHO", "Buffalo Grove Ortho"),
    ("MY CHART", "Northwestern MyChart"),
    ("TRADINGVIEW", "TradingView"), ("FINVIZ", "Finviz"), ("CNBC SUBSCRIPTION", "CNBC"), ("CNBC PRO", "CNBC"),
    ("PICTORY", "Pictory"), ("WAVE.CO AI NOTE", "Wave AI note taker"), ("BLINK ", "Blink"),
    ("ELEMENTOR", "Elementor"), ("LEARNDASH", "LearnDash"), ("TAXDOME", "TaxDome"),
    ("ACCOUNTANTSWORLD", "AccountantsWorld"), ("AICPA", "AICPA insurance"),
    ("USPS PO BOX", "USPS PO Box"),
    ("INTUIT", "Intuit QuickBooks"), ("QUICKBOOKS", "Intuit QuickBooks"),
    ("CORPORATE FILINGS", "Corporate Filings"), ("COR*PRATE FILINGS", "Corporate Filings"),
    ("CORPORATEFILINGS", "Corporate Filings"), ("TESLA SUBSCRIPTION", "Tesla Premium Connectivity"),
    ("AMAZON WEB SERVICES", "Amazon Web Services"), ("AWS EMEA", "Amazon Web Services"),
    ("DIGITALOCEAN", "DigitalOcean"), ("CLOUDFLARE", "Cloudflare"), ("WALMART+", "Walmart+"),
    ("WMT PLUS", "Walmart+"), ("OURARING", "Oura membership"), ("PRIME VIDEO CHANNELS", "Prime Video Channels"),
    ("FOREIGN POLICY", "Foreign Policy magazine"), ("FOREIGN AFFAIRS", "Foreign Affairs magazine"),
    ("TOPSTEP", "TopstepTrader"), ("CLEAR *", "CLEAR"), ("CLEARME", "CLEAR"),
    ("CORPORATE SUITES", "Corporate Suites Network"),
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
# Instalments toward a bill (orthodontist, hospital, lawyer), shown apart
# from subscriptions. Add others under "payment_plans" in overrides.json.
PAYMENT_PLAN = re.compile(
    r"PAYMENT PLAN|ORTHO|DENTAL|DENTIST|HOSPITAL|MYCHART|MY CHART|MEDICAL|LAW FIRM|ATTORNEY|LEGAL",
    re.I,
)

# Government filing and licence fees: required, irregular, not subscriptions.
# Trips, not plans: in-flight Wi-Fi, airfare and hotels can repeat at the
# same price without being a subscription.
TRAVEL = re.compile(
    r"UAL\*WIFI|\bWI-?FI ONBOARD|GOGOAIR|GOGO AIR|INFLIGHT|IN-FLIGHT|VIASAT|AA WIFI|DELTA WIFI|"
    r"^UNITED \d|^UNITED AIRLINES|AMERICAN AIR|^DELTA AIR|SOUTHWEST AIR|ALASKA AIR|SPIRIT AIRL|"
    r"FRONTIER AIRL|JETBLUE|EMIRATES AIR|AIR INDIA|LUFTHANSA|BRITISH AIRWAYS|"
    r"HILTON HOTEL|HAMPTON INN|HOLIDAY INN|MARRIOTT|HYATT|AIRBNB|EXPEDIA|BOOKING\.COM|HOTELS\.COM",
    re.I,
)

GOV_FEES = re.compile(
    r"SECRETARY OF STATE|SEC OF STATE|\bSOS\b|S\.O\.S\.|ILSOS|LICENSE FEE|LICENCE FEE|\bDMV\b|VEH RENEWAL",
    re.I,
)

KNOWN_BILLS = [
    ("LEXINGTON FAYETTE", "Lexington Fayette sewer/water"), ("CITY OF NAPERVILLE", "City of Naperville utilities"),
    ("CITYOFNAP", "City of Naperville utilities"), ("NICOR", "Nicor Gas"),
    ("WCI*", "WCI waste service"), ("ATT*", "AT&T"), ("AT&T", "AT&T"),
    ("COMCAST", "Comcast Xfinity"), ("XFINITY", "Comcast Xfinity"), ("STATE FARM", "State Farm insurance"),
]

BILL_CATEGORIES = re.compile(r"utilit|insurance", re.I)
BILL_NAMES = re.compile(
    r"\b(STATE FARM|ATT\*|VILLAGE OF|CITY OF|TOWN OF|COUNTY OF|WATER|SEWER|WASTE|ELECTRIC|ENERGY|POWER|"
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
    is_plan: bool = False  # paying off a debt in instalments (medical, legal), not a service

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
    moved_to: tuple[str, date, float] | None = None  # renewed on another card instead
    likely_yearly: bool = False  # one charge about a year ago, renewal due soon

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
            limit = max(0.5, base * 0.15) if loose else max(0.10, base * 0.02)
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
        # Two charges are enough only for a yearly plan of a well-known
        # service. Anything billed every 6 months or more often needs three,
        # so two same-price purchases months apart don't count.
        needed = 2 if forced or (known and days >= 340) else max(min_count, 3)
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
    days = max(days, 1)
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
    # "same_as": charges under one name that belong to another service.
    aliases = {k.lower(): v for k, v in overrides.get("same_as", {}).items()}

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
        if t.is_fee or t.is_payment or is_loan(t.card) or GOV_FEES.search(t.description):
            continue
        if TRAVEL.search(t.description) and not listed(t.description, t.description, include):
            continue
        name, known = merchant_name(t.description)
        if name.lower() in aliases:
            name, known = aliases[name.lower()], True
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
            # A steady monthly premium can hide among one-off payments to
            # the same company: look for it first.
            steady = [c for c in _cluster_by_price(charges, loose=False) if len(c) >= 3]
            found_bill = False
            for cluster in steady:
                freq = _match_frequency(cluster, known=False, forced=False)
                if freq:
                    subs.append(_make(display, card, cluster, freq, as_of[card], today, is_bill=True))
                    found_bill = True
            if found_bill:
                continue
            freq = _match_frequency(charges, known=True, forced=False)
            if not freq and len(charges) >= 3:
                gap = median((b.date - a.date).days for a, b in zip(charges, charges[1:]))
                if gap >= 20:
                    freq = (f"About every {max(1, round(gap / 30.44))} months", gap)
            if freq:
                freq = (freq[0].replace(" (auto top-up)", ""), freq[1])
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
        if known or forced:
            found = _extend_on_schedule(found, charges, as_of[card], today)
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
            # Renewed on a different card about a year later?
            moved_to = None
            renewals = [r for (n, c), rows in groups.items() if n == name and c != card
                        for r in rows if 120 <= (r.date - t.date).days <= 430
                        and max(r.amount, t.amount) <= 1.5 * min(r.amount, t.amount)]
            if renewals:
                r = min(renewals, key=lambda r: abs((r.date - t.date).days - 365))
                moved_to = (r.card, r.date, r.amount)
                overdue = False
            # One charge about a year old from a well-known service: most
            # likely a yearly plan that is about to renew.
            likely = (len(charges) == 1 and not overdue and not moved_to
                      and (as_of[card] - t.date).days >= 300)
            possible.append(Possible(display, card, t.amount, t.date, len(charges), overdue, moved_to, likely))

    plans = [p.lower() for p in overrides.get("payment_plans", [])]
    for sub in subs:
        desc = sub.charges[-1].description
        if PAYMENT_PLAN.search(sub.name) or PAYMENT_PLAN.search(desc) or listed(sub.name, desc, plans):
            sub.is_plan = True
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


def stale_cards(transactions: list[Transaction], today: date, days: int = 45) -> list[str]:
    """Cards whose files stop well before today, so newer exports are missing."""
    file_end: dict[str, date] = {}
    card_files: dict[str, set] = defaultdict(set)
    for t in transactions:
        file_end[t.source] = max(file_end.get(t.source, t.date), t.date)
        card_files[t.card].add(t.source)
    ends = _data_end_by_card(card_files, file_end)
    return [f"{card}: the files only go up to {_d(end)}. Download newer statements to see what's current."
            for card, end in sorted(ends.items()) if (today - end).days > days]


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


def _extend_on_schedule(found: list[Subscription], charges: list[Transaction],
                        as_of: date, today: date) -> list[Subscription]:
    """A price rise can leave the newest charge outside its plan's price
    group. Pull in charges that land right on schedule at a similar price."""
    used = {id(t) for s in found for t in s.charges}
    out = []
    for s in found:
        series = list(s.charges)
        grew = True
        while grew:
            grew = False
            expected = series[-1].date + timedelta(days=round(s.period_days))
            for t in charges:
                if id(t) in used or abs((t.date - expected).days) > 7:
                    continue
                lo, hi = sorted((t.amount, series[-1].amount))
                if hi <= lo * 1.5:
                    series.append(t)
                    used.add(id(t))
                    grew = True
                    break
        if len(series) > len(s.charges):
            s = _make(s.name, s.card, series, (s.frequency, s.period_days), as_of, today, True)
        out.append(s)
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
    active = [s for s in subs if s.active and not s.is_bill and not s.is_plan]
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
    ended = [(s.name, s.card, s.last_charged) for s in subs if not s.active and not s.is_bill and not s.is_plan]
    ended += [(p.name, p.card, p.charged) for p in possible]
    notes = []
    for s in subs:
        if not s.active or s.is_bill or s.is_plan:
            continue
        for name, card, last in ended:
            if name == s.name and card != s.card and s.first_charged >= last - timedelta(days=7):
                notes.append(f"{name} moved from {card} to {s.card} "
                             f"(last on the old card {_d(last)}, first on the new one {_d(s.first_charged)}).")
    for p in possible:
        if p.moved_to:
            new_card, when, amount = p.moved_to
            notes.append(f"{p.name} renewed on {new_card} instead of {p.card} "
                         f"({_money(p.amount)} on {_d(p.charged)}, then {_money(amount)} on {_d(when)}).")
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
