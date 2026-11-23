# Subscription tracker

Finds your subscriptions in credit card CSV exports and shows what each one
costs, how often it bills, which card it is on, and when it next renews (or
when it stopped). Everything runs on your own computer. Nothing is uploaded
anywhere and there is no database.

It needs only Python 3.10 or newer. There is nothing to install.

## Use it

1. Download CSV exports from each credit card website and put them in the
   `data` folder. Any number of files, any years, any cards.
2. Run:

   ```
   python3 tracker.py --open
   ```

   It prints a summary, then saves and opens `report.html`. It also saves
   `report.csv` if you want the list in a spreadsheet.

To have it update by itself while you add files, run
`python3 tracker.py --watch`. It rebuilds the report whenever a file in
`data` changes. Press Ctrl+C to stop.

Overlapping downloads are fine: a charge that appears in more than one file
is counted once. If your bank gives every download the same name (Amex uses
`activity.csv`), rename each one to start with the card, for example
`amex_8330_1.csv`, `amex_8330_2.csv`. The four digits become the card number.

Your CSV files, `report.html`, `report.csv` and `overrides.json` are listed in
`.gitignore`, so they are never committed.

## What the report shows

- **Active**: subscriptions still charging on schedule, with the next renewal
  date and the cost per month. The totals at the top add up only these.
- **Possible overlaps**: a service charged more than one way, or several
  services that do the same job (two fax services, two storage units).
- **Stopped or expired**: things that used to charge regularly but missed
  their latest charge, with the date of the last one.
- **Check these**: well-known services charged only once so far, with the
  date they would renew if they're yearly.
- **Bills and utilities**: water, trash and similar bills whose amount changes
  each time. Shown with the recent average and kept out of the subscription
  totals.
- **Payment plans**: monthly instalments toward a medical, legal or similar
  bill. Kept out of the subscription totals.
- **Loans**: accounts whose name in `overrides.json` contains "loan", with
  the monthly payment, next payment and interest. Kept out of the totals.
- **Interest and fees**: interest and card fees per card over the latest 12
  months.

A charge counts as a subscription when the same merchant charges the same
card a steady price at a regular interval (weekly up to yearly). Well-known
services such as Netflix or Kindle Unlimited need only two charges, and a
price change is allowed. Auto top-ups that charge the same amount at uneven
times, like I-PASS tolls, are included too.

## Name your cards, hide or add items

Copy `overrides.example.json` to `overrides.json` and edit it:

```json
{
  "cards": { "1234": "My Capital One", "5678": "Partner's Visa" },
  "ignore": ["Twilio"],
  "include": ["Corner Gym"],
  "rename": { "Foxmetrowrd": "Fox Metro water" }
}
```

- `cards`: a name for each card, by its last four digits. For files with no
  card number (some Citi exports), use the card name the report shows instead,
  for example `"CitiBusiness": "Business card"` for `citibusiness_2026.csv`.
- `ignore`: merchants that shouldn't count as subscriptions.
- `include`: merchants that should count even though the pattern isn't clear.
- `payment_plans`: instalments toward a bill (a lawyer, a doctor) that should
  be listed as payment plans rather than subscriptions. Orthodontist,
  dental, hospital and similar names are recognised already.
- `same_as`: charges that belong to another service under a different
  name, for example `{ "Usps Po": "USPS PO Box" }`.
- `rename`: nicer names. The left side is matched against the name shown in
  the report.

## Cards that only give PDF statements

Synchrony (the Amazon store card) gives monthly PDFs. Turn them into one CSV
with:

```
python3 tools/synchrony_pdf_to_csv.py ~/Downloads/Synchrony*.pdf -o data/synchrony_1234.csv
```

Use the card's last four digits in the output name. This needs the free
`pdftotext` program (Mac: `brew install poppler`). Run it again with all the
PDFs whenever a new statement arrives.

## A bank's file isn't read correctly

Columns are found by name, and the common names used by Capital One, Chase,
Amex, Citi, Discover and others are already known. If a file isn't read, the
report says so at the top. Then either add the column name to
`COLUMN_ALIASES` in `subtracker/parse.py`, or copy `formats.example.json` to
`formats.json` and describe the file there.

## Tests

```
python3 -m unittest
```

The tests use made-up sample files in `tests/fixtures`
(`python3 tests/make_fixtures.py` regenerates them).
