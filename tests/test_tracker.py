import tempfile
import unittest
from datetime import date
from pathlib import Path

from subtracker.detect import fees_by_card, find_subscriptions, merchant_name
from subtracker.parse import card_name_from_file, parse_amount, read_csv, read_folder
from subtracker.report import html_report, text_report

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 23)


def subs_by_name(subs):
    return {(s.name, s.amount): s for s in subs}


class ParseTests(unittest.TestCase):
    def test_amounts(self):
        self.assertEqual(parse_amount("$1,234.50"), 1234.5)
        self.assertEqual(parse_amount("(12.00)"), -12.0)
        self.assertEqual(parse_amount("-5"), -5.0)
        self.assertEqual(parse_amount("7.25 CR"), -7.25)
        self.assertIsNone(parse_amount(""))

    def test_card_name_from_file(self):
        self.assertEqual(card_name_from_file(Path("chase-sapphire-2025.csv")), "Chase Sapphire")
        self.assertEqual(card_name_from_file(Path("capitalone_1234_2026.csv")), "Capital One")

    def test_capital_one_debit_credit_columns(self):
        rows = read_csv(FIXTURES / "capital-one-2025.csv")
        self.assertTrue(rows)
        self.assertTrue(all(t.amount > 0 for t in rows))
        self.assertEqual(rows[0].card, "Capital One ••4821")
        self.assertFalse(any("PYMT" in t.description for t in rows))

    def test_card_names_from_overrides(self):
        rows = read_csv(FIXTURES / "capital-one-2025.csv", card_names={"4821": "Family card"})
        self.assertEqual(rows[0].card, "Family card")

    def test_negative_purchases_are_flipped(self):
        rows = read_csv(FIXTURES / "chase-freedom.csv")
        self.assertTrue(all(t.amount > 0 for t in rows))
        self.assertFalse(any("Payment" in t.description for t in rows))

    def test_citi_format(self):
        rows = read_csv(FIXTURES / "citi_1234_2025.csv")
        self.assertEqual(rows[0].card, "Citi ••1234")
        self.assertFalse(any("PAYMENT" in t.description for t in rows))
        self.assertEqual(sum(t.is_fee for t in rows), 2)

    def test_card_name_by_file_name_when_no_number(self):
        rows = read_csv(FIXTURES / "amex-gold-2026.csv", card_names={"Amex Gold": "Family Amex"})
        self.assertEqual(rows[0].card, "Family Amex")

    def test_header_after_summary_lines(self):
        rows = read_csv(FIXTURES / "amex-gold-2026.csv")
        self.assertEqual(rows[0].card, "Amex Gold")
        self.assertFalse(any("AUTOPAY" in t.description for t in rows))

    def test_unreadable_file_is_reported_not_fatal(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "junk.csv").write_text("a,b,c\n1,2,3\n")
            Path(d, "amex-gold-2026.csv").write_text((FIXTURES / "amex-gold-2026.csv").read_text())
            rows, problems = read_folder(Path(d))
            self.assertTrue(rows)
            self.assertEqual(len(problems), 1)

    def test_overlapping_exports_are_not_double_counted(self):
        with tempfile.TemporaryDirectory() as d:
            text = (FIXTURES / "amex-gold-2026.csv").read_text()
            Path(d, "amex-gold-2025.csv").write_text(text)
            Path(d, "amex-gold-2026.csv").write_text(text)
            rows, _ = read_folder(Path(d))
            self.assertEqual(len(rows), len(read_csv(FIXTURES / "amex-gold-2026.csv")))


class DetectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, _ = read_folder(FIXTURES)
        cls.subs, cls.possible = find_subscriptions(cls.rows, TODAY)
        cls.by = subs_by_name(cls.subs)

    def test_merchant_names(self):
        self.assertEqual(merchant_name("NETFLIX.COM 866-579-7172 CA")[0], "Netflix")
        self.assertEqual(merchant_name("KINDLE UNLTD*NK54U3EH1")[0], "Kindle Unlimited")
        self.assertEqual(merchant_name("SQ *CORNER BAKERY CLUB")[0], "Corner Bakery Club")

    def test_monthly_with_price_change(self):
        s = self.by[("Netflix", 17.99)]
        self.assertTrue(s.active)
        self.assertTrue(s.price_changed)
        self.assertEqual(s.frequency, "Monthly")
        self.assertEqual(s.next_renewal, date(2026, 12, 3))

    def test_two_plans_same_company(self):
        self.assertIn(("Apple (App Store / iCloud)", 2.99), self.by)
        self.assertIn(("Apple (App Store / iCloud)", 10.99), self.by)

    def test_cancelled_shows_as_stopped(self):
        s = self.by[("Planet Fitness", 24.99)]
        self.assertFalse(s.active)
        self.assertEqual(s.last_charged, date(2025, 9, 20))

    def test_yearly_and_quarterly(self):
        self.assertEqual(self.by[("Costco Membership", 65.0)].frequency, "Yearly")
        self.assertEqual(self.by[("New York Times", 25.0)].frequency, "Quarterly")

    def test_unknown_merchant_detected_by_pattern(self):
        self.assertIn(("Corner Bakery Club", 30.0), self.by)

    def test_shopping_is_not_a_subscription(self):
        names = {s.name for s in self.subs}
        for shop in ["Heb", "Shell Oil", "Target", "Starbucks Store", "Wholefds Arb", "Uber", "Safeway"]:
            self.assertFalse(any(shop in n for n in names), shop)

    def test_single_charge_of_known_service_is_flagged(self):
        self.assertEqual(sorted(p.name for p in self.possible), ["Airtable", "Disney+"])

    def test_citi_virtual_account_suffix_ignored(self):
        s = self.by[("Barron's", 15.0)]
        self.assertEqual(s.frequency, "Monthly")
        self.assertFalse(s.active)

    def test_annual_card_fee(self):
        fees = {f.card: f for f in fees_by_card(self.rows)}
        self.assertEqual(fees["Citi ••1234"].annual_fee, 50.0)
        self.assertEqual(fees["Citi ••1234"].annual_fee_next, date(2026, 4, 21))

    def test_overrides(self):
        subs, _ = find_subscriptions(self.rows, TODAY, {
            "ignore": ["spotify"], "rename": {"netflix": "Netflix Premium"}})
        names = {s.name for s in subs}
        self.assertNotIn("Spotify", names)
        self.assertIn("Netflix Premium", names)

    def test_auto_top_up(self):
        from subtracker.parse import Transaction
        days = [date(2026, 1, 5), date(2026, 2, 20), date(2026, 3, 25), date(2026, 5, 15), date(2026, 6, 28)]
        rows = [Transaction(d, "IL TOLLWAY-AUTOREPLENISH", 99.0, "Card", "x") for d in days]
        subs, _ = find_subscriptions(rows, date(2026, 7, 1))
        self.assertEqual(len(subs), 1)
        self.assertIn("auto top-up", subs[0].frequency)


    def test_bills_with_varying_amounts(self):
        from subtracker.parse import Transaction
        bills = [(date(2026, 1, 10), 40.85), (date(2026, 3, 8), 40.85), (date(2026, 5, 9), 46.95),
                 (date(2026, 7, 8), 46.95), (date(2026, 9, 8), 66.35)]
        rows = [Transaction(d, "VILLAGE OF NORTH AURORA", a, "Card", "x", False, "Utilities") for d, a in bills]
        subs, _ = find_subscriptions(rows, date(2026, 10, 1))
        self.assertEqual(len(subs), 1)
        self.assertTrue(subs[0].is_bill)
        self.assertEqual(subs[0].frequency, "Every 2 months")

    def test_spacing_in_description(self):
        self.assertEqual(merchant_name("UBER   *ONE MEMBERSHIP")[0], "Uber One")


    def _monthly(self, desc, amount, day, months, overrides=None):
        from subtracker.parse import Transaction
        return [Transaction(date(2026, m, day), desc, overrides.get(m, amount) if overrides else amount,
                            "Card", "x") for m in months]

    def test_two_accounts_billed_on_different_days(self):
        rows = self._monthly("Fax.com (888)429-4615 CA", 11.99, 10, range(1, 11)) + \
            self._monthly("Fax.com (888)429-4615 CA", 11.99, 16, range(1, 11))
        subs, _ = find_subscriptions(rows, date(2026, 10, 20))
        self.assertEqual(sorted(s.charges[0].date.day for s in subs), [10, 16])

    def test_odd_month_price_folds_into_monthly(self):
        rows = self._monthly("GOOGLE *WORKSPACE_SMCC@GOOGLE.COM CA", 28.0, 1, range(1, 11), {2: 34.0})
        subs, _ = find_subscriptions(rows, date(2026, 10, 20))
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0].frequency, "Monthly")

    def test_yearly_price_increase(self):
        from subtracker.parse import Transaction
        rows = [Transaction(date(2025, 2, 26), "AIRTABLE.COM/BILL", 204.98, "Card", "x"),
                Transaction(date(2026, 2, 26), "AIRTABLE.COM/BILL", 240.00, "Card", "x")]
        subs, _ = find_subscriptions(rows, TODAY)
        self.assertEqual(subs[0].frequency, "Yearly")
        self.assertTrue(subs[0].price_changed)


    def test_extra_card_member_judged_by_whole_account(self):
        from subtracker.parse import Transaction
        # The extra card's plan stops in July, but the account's files run to November.
        rows = [Transaction(date(2026, m, 13), "GOOGLE *GOOGLE ONE", 1.99, "Extra", "a.csv") for m in range(1, 8)]
        rows += [Transaction(date(2026, m, 6), "CRICUT", 9.99, "Main", "a.csv") for m in range(1, 8)]
        rows += [Transaction(date(2026, m, 6), "CRICUT", 9.99, "Main", f"{m}.csv") for m in range(8, 12)]
        subs, _ = find_subscriptions(rows, TODAY)
        by = {s.name: s for s in subs}
        self.assertFalse(by["Google One"].active)
        self.assertTrue(by["Cricut"].active)

    def test_account_column_names_card(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "amex_99999_1.csv").write_text(
                "Date,Description,Card Member,Account #,Amount\n"
                "01/06/2026,CRICUT SOUTH JORDAN UT,ALEX,-99999,9.99\n"
                "01/13/2026,GOOGLE *GOOGLE ONE,SAM,-88888,1.99\n")
            rows, _ = read_folder(Path(d), card_names={"99999": "Main", "88888": "Extra"})
            self.assertEqual({t.card for t in rows}, {"Main", "Extra"})


    def test_overlaps(self):
        from subtracker.detect import find_overlaps
        rows = self._monthly("Fax.com (888)429-4615 CA", 11.99, 10, range(1, 11)) + \
            self._monthly("HUMBLEFAX RIDGEWOOD NJ", 10.0, 22, range(1, 11))
        subs, possible = find_subscriptions(rows, date(2026, 10, 25))
        notes = find_overlaps(subs, possible)
        self.assertEqual(len(notes), 1)
        self.assertIn("Fax.com, HumbleFax", notes[0])


class FeeAndReportTests(unittest.TestCase):
    def test_fees_kept_apart(self):
        from subtracker.parse import Transaction
        rows = [
            Transaction(date(2026, 1, 9), "INTEREST CHARGE:PURCHASES", 500.0, "Card", "x", True),
            Transaction(date(2026, 2, 9), "INTEREST CHARGE:PURCHASES", 480.0, "Card", "x", True),
            Transaction(date(2026, 2, 10), "INTEREST ADJ", -5.0, "Card", "x", True),
        ]
        subs, _ = find_subscriptions(rows, TODAY)
        self.assertEqual(subs, [])
        fees = fees_by_card(rows)
        self.assertEqual(fees[0].last_12_months, 975.0)

    def test_refunded_late_fee_cancels_out(self):
        from subtracker.parse import FEE_CREDITS
        self.assertTrue(FEE_CREDITS.search("REFUND LATE FEE"))

    def test_missed_yearly_renewal(self):
        from subtracker.parse import Transaction
        rows = [Transaction(date(2025, 4, 1), "COSTCO *ANNUAL RENEWAL 800-774-2678 WA", 65.0, "Card", "x"),
                Transaction(date(2026, 11, 1), "COSTCO WHSE #0388", 120.0, "Card", "x")]
        _, possible = find_subscriptions(rows, TODAY)
        self.assertEqual(possible[0].name, "Costco Membership")
        self.assertTrue(possible[0].overdue)

    def test_reports_render(self):
        rows, problems = read_folder(FIXTURES)
        subs, possible = find_subscriptions(rows, TODAY)
        page = html_report(subs, possible, problems, TODAY, fees_by_card(rows))
        self.assertIn("Netflix", page)
        self.assertIn("per month", page)
        self.assertIn("Netflix", text_report(subs, possible, problems))


if __name__ == "__main__":
    unittest.main()
