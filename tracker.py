#!/usr/bin/env python3
"""Find subscriptions in the credit card CSV files in the data folder.

    python3 tracker.py           build report.html and report.csv once
    python3 tracker.py --watch   rebuild whenever a file in data/ changes
"""

from __future__ import annotations

import argparse
import json
import time
import webbrowser
from datetime import date
from pathlib import Path

from subtracker.detect import fees_by_card, find_loans, find_overlaps, find_subscriptions
from subtracker.parse import load_formats, read_folder
from subtracker.report import html_report, text_report, write_csv

HERE = Path(__file__).resolve().parent


def build(data: Path, out: Path, today: date | None = None, quiet: bool = False) -> None:
    today = today or date.today()
    formats = load_formats(HERE / "formats.json")
    overrides_path = HERE / "overrides.json"
    overrides = json.loads(overrides_path.read_text()) if overrides_path.exists() else {}

    transactions, problems = read_folder(data, formats, overrides.get("cards"))
    if not transactions and not problems:
        problems.append(f"No CSV files found in {data}. Put your card exports there.")
    subs, possible = find_subscriptions(transactions, today, overrides)
    fees = fees_by_card(transactions)
    overlaps = find_overlaps(subs, possible)
    loans = find_loans(transactions, today)

    out.mkdir(parents=True, exist_ok=True)
    (out / "report.html").write_text(html_report(subs, possible, problems, today, fees, overlaps, loans))
    write_csv(subs, out / "report.csv")
    if not quiet:
        print(text_report(subs, possible, problems, fees, overlaps, loans))
        print(f"\nSaved {out / 'report.html'} and {out / 'report.csv'}")


def _snapshot(folder: Path) -> dict:
    files = list(folder.glob("*.csv")) + [HERE / "overrides.json", HERE / "formats.json"]
    return {p: p.stat().st_mtime for p in files if p.exists()}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=HERE / "data", help="folder with CSV files")
    ap.add_argument("--out", type=Path, default=HERE, help="where to save report.html and report.csv")
    ap.add_argument("--watch", action="store_true", help="keep running and rebuild when files change")
    ap.add_argument("--open", action="store_true", help="open the report in your browser")
    args = ap.parse_args()

    build(args.data, args.out)
    if args.open:
        webbrowser.open((args.out / "report.html").resolve().as_uri())
    if args.watch:
        print(f"\nWatching {args.data} for changes. Press Ctrl+C to stop.")
        seen = _snapshot(args.data)
        try:
            while True:
                time.sleep(3)
                now = _snapshot(args.data)
                if now != seen:
                    seen = now
                    print("\nFiles changed, rebuilding...\n")
                    build(args.data, args.out)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
