"""Writes the fake sample CSVs in tests/fixtures. No real data here."""
import csv, random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).parent / "fixtures"
random.seed(7)

def months(start, n, day):
    y, m = start
    for _ in range(n):
        yield date(y, m, min(day, 28))
        m += 1
        if m > 12: y, m = y + 1, 1

def capital_one():
    rows = []
    for d in months((2025, 1), 23, 3):
        rows.append((d, "NETFLIX.COM", 15.49 if d < date(2025, 7, 1) else 17.99))
    for d in months((2025, 1), 23, 14):
        rows.append((d, "SPOTIFY USA 877-778-1161 NY", 11.99))
    for d in months((2025, 2), 8, 20):          # cancelled in Sept 2025
        rows.append((d, "PLANET FITNESS #1234 AUSTIN TX", 24.99))
    rows.append((date(2025, 3, 9), "COSTCO MEMBERSHIP RENEWAL", 65.00))
    rows.append((date(2026, 3, 9), "COSTCO MEMBERSHIP RENEWAL", 65.00))
    for i in range(120):                          # everyday shopping noise
        d = date(2025, 1, 1) + timedelta(days=random.randint(0, 680))
        rows.append((d, random.choice(["HEB #455 AUSTIN TX", "SHELL OIL 5741", "TARGET 00012345"]),
                     round(random.uniform(8, 140), 2)))
    rows.sort()
    with open(OUT / "capital-one-2025.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Transaction Date", "Posted Date", "Card No.", "Description", "Category", "Debit", "Credit"])
        for d, desc, amt in rows:
            w.writerow([d.isoformat(), (d + timedelta(days=1)).isoformat(), "4821", desc, "Other", f"{amt:.2f}", ""])
        w.writerow(["2025-06-01", "2025-06-01", "4821", "CAPITAL ONE MOBILE PYMT", "Payment/Credit", "", "500.00"])

def chase():
    rows = []
    for d in months((2025, 1), 23, 22):
        rows.append((d, "APPLE.COM/BILL 866-712-7753 CA", -2.99))
        rows.append((d, "APPLE.COM/BILL 866-712-7753 CA", -10.99))
    for d in months((2025, 5), 19, 1):
        rows.append((d, "OPENAI *CHATGPT SUBSCR", -20.00))
    rows.append((date(2026, 10, 5), "DISNEY PLUS 888-905-7888 CA", -13.99))
    for i in range(80):
        d = date(2025, 1, 1) + timedelta(days=random.randint(0, 680))
        rows.append((d, random.choice(["STARBUCKS STORE 0381", "WHOLEFDS ARB 10234", "UBER *TRIP"]),
                     -round(random.uniform(4, 60), 2)))
    rows.sort()
    with open(OUT / "chase-freedom.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Transaction Date", "Post Date", "Description", "Category", "Type", "Amount", "Memo"])
        for d, desc, amt in rows:
            w.writerow([d.strftime("%m/%d/%Y"), d.strftime("%m/%d/%Y"), desc, "Shopping", "Sale", f"{amt:.2f}", ""])
        w.writerow(["07/15/2025", "07/15/2025", "Payment Thank You-Mobile", "", "Payment", "800.00", ""])

def amex():
    with open(OUT / "amex-gold-2026.csv", "w", newline="") as f:
        f.write("Account Summary,Amex Gold\nStatement period,2026\n\n")
        w = csv.writer(f)
        w.writerow(["Date", "Description", "Card Member", "Amount"])
        for d in [date(2026, 1, 10), date(2026, 4, 10), date(2026, 7, 10), date(2026, 10, 10)]:
            w.writerow([d.strftime("%m/%d/%Y"), "NYTIMES*NYTDIGITAL", "SARITA", "25.00"])
        for d in months((2026, 1), 10, 7):
            w.writerow([d.strftime("%m/%d/%Y"), "SQ *CORNER BAKERY CLUB", "SARITA", "30.00"])
        w.writerow(["03/02/2026", "SAFEWAY 1122", "SARITA", "54.10"])
        w.writerow(["05/02/2026", "AUTOPAY PAYMENT - THANK YOU", "SARITA", "-300.00"])

OUT.mkdir(exist_ok=True)
capital_one(); chase(); amex()
