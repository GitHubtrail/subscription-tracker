# Subscription tracker

Finds your subscriptions in credit card CSV exports and shows what each one
costs, how often it bills, which card it is on, and when it next renews (or
when it stopped). Everything runs on your own computer. Nothing is uploaded
anywhere and there is no database.

It needs only Python 3.10 or newer. There is nothing to install.

## Use it

1. Download CSV exports from each credit card website and put them in the
   `data` folder. Any number of files, any years, any cards. Keep the names
   the bank gave them; there's no need to rename anything.
2. Run:

   ```
   python3 tracker.py --open
   ```

   (On Windows, type `python` instead of `python3`.) It prints a summary,
   then saves and opens `report.html`. It also saves `report.csv` if you want
   the list in a spreadsheet.

To have it update by itself while you add files, run
`python3 tracker.py --watch`. It rebuilds the report whenever a file in
`data` changes. Press Ctrl+C to stop.

Overlapping downloads are fine: a charge that appears in more than one file
is counted once, and all the files for one card are treated as one card.

The card is read from inside each file (Capital One's "Card No.", Amex's
"Account #", the account number at the top of a Barclays file) or from the
bank's own file name (Chase and Bank of America put the last four digits
there). Some downloads have no card number at all, such as Amex files
without card member details and Citi files. Such a file takes the card of
another file that has the same charges. If there isn't one, the report says
which files they are. Either name them under `files` in `overrides.json`
(see below), or put a word from the card's name in the file name, for
example `Citi Costco 2026.csv` for a card named "Citi Costco" in `cards`.

## Windows quick-start

1. On the GitHub page, click **Code**, then **Download ZIP**. Right-click
   the downloaded file and choose **Extract All**.
2. Install Python from https://www.python.org/downloads/. On the first
   screen of the installer, tick **Add python.exe to PATH**, then click
   **Install Now**.
3. Put your CSV files in the `data` folder inside the extracted folder, and
   `overrides.json` (if you have one) next to `tracker.py`.
4. Open the extracted folder in File Explorer, click the address bar, type
   `cmd` and press Enter. In the window that opens, type:

   ```
   python tracker.py --open
   ```

If Windows says Python was not found, run the installer again and make sure
**Add python.exe to PATH** is ticked. Typing `py tracker.py --open` also
works.

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
  "files": { "activity*.csv": "5678" },
  "ignore": ["Twilio"],
  "include": ["Corner Gym"],
  "rename": { "Foxmetrowrd": "Fox Metro water" }
}
```

- `cards`: a name for each card, by its last four digits.
- `files`: the card for files that have no card number in them, by file
  name. `*` matches anything, so `"activity*.csv": "1234"` puts every such
  Amex download on card 1234. A file with its own card number is never moved
  by a pattern, and an exact file name wins over a pattern. The right side
  can be the last four digits from `cards`, or a name.
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
