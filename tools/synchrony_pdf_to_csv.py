#!/usr/bin/env python3
"""Turn Synchrony (Amazon store card) PDF statements into one CSV the
tracker can read.

    python3 tools/synchrony_pdf_to_csv.py statements/*.pdf -o data/synchrony_1234.csv

Needs the free `pdftotext` program (Mac: `brew install poppler`,
Windows: install "Xpdf command line tools"). Each PDF's file name must end
in its statement date, like "Synchrony Bank Statement 20260123.pdf", so the
year of each transaction is known.
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
from pathlib import Path

LINE = re.compile(
    r"^\s*(\d{2})/(\d{2})\s+(?:([A-Z0-9]{12,})\s+)?(.+?)\s+(-?)\$([\d,]+\.\d{2})\s*$"
)
ITEM_CODE = re.compile(r"^[A-Za-z0-9]{10,14}$")  # the random code under each Amazon order
STATEMENT_DATE = re.compile(r"(20\d{2})(\d{2})(\d{2})")
ACCOUNT = re.compile(r"Account Number ending in (\d{4})")


def statement_lines(pdf: Path) -> list[str]:
    text = subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                          check=True, capture_output=True, text=True).stdout
    return text.splitlines()


def parse_statement(pdf: Path) -> tuple[list[dict], str]:
    m = STATEMENT_DATE.search(pdf.stem)
    if not m:
        raise SystemExit(f"{pdf.name}: file name needs the statement date, like ..._20260123.pdf")
    year, month = int(m.group(1)), int(m.group(2))
    lines = statement_lines(pdf)
    account = next((a.group(1) for l in lines if (a := ACCOUNT.search(l))), "")
    rows, in_detail = [], False
    for i, line in enumerate(lines):
        if line.strip().startswith("Transaction Detail"):
            in_detail = True
            continue
        if in_detail and ("Year-to-Date Fees" in line or "Interest Charge Calculation" in line):
            in_detail = False
        if not in_detail:
            continue
        t = LINE.match(line)
        if not t:
            continue
        mm, dd, _, desc, minus, amount = t.groups()
        # A January statement includes late-December charges.
        y = year - 1 if int(mm) > month else year
        # Amazon orders have a code line and then the item name.
        item = ""
        following = [l.strip() for l in lines[i + 1:i + 3]]
        if len(following) > 1 and ITEM_CODE.match(following[0]) and following[1] \
                and "$" not in following[1] and "Continued" not in following[1] \
                and not LINE.match(lines[i + 2]):
            item = following[1]
        value = float(amount.replace(",", "")) * (-1 if minus else 1)
        rows.append({
            "Date": f"{mm}/{dd}/{y}",
            "Description": desc,
            "Item": item,
            "Amount": f"{value:.2f}",
        })
    return rows, account


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdfs", nargs="+", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True, help="CSV to write, e.g. data/synchrony_1234.csv")
    args = ap.parse_args()
    all_rows, account = [], ""
    for pdf in sorted(args.pdfs):
        rows, acct = parse_statement(pdf)
        all_rows.extend(rows)
        account = account or acct
    with args.out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Date", "Description", "Amount", "Card No.", "Item"])
        w.writeheader()
        for r in all_rows:
            w.writerow({**r, "Card No.": account})
    print(f"Wrote {len(all_rows)} transactions from {len(args.pdfs)} statements to {args.out}")


if __name__ == "__main__":
    main()
