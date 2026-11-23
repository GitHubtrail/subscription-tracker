import unittest
from pathlib import Path
from unittest import mock

from tools import synchrony_pdf_to_csv as syn

SAMPLE = """\
                                               Account Number ending in 9999
Transaction Detail
Date        Reference #                     Description                                   Amount
Payments                                                                                  -$100.00
01/15    F934200CZ00CHGDDA                  AUTOMATIC PAYMENT - THANK YOU                 -$100.00
 Purchases and Other Debits                                                                $36.98
12/29       P934200BDEHMBEMZR             AMAZON MARKETPLACE SEATTLE WA                    $25.00
                                          BdeCjFiapeky
                                          Sample Item Name
01/09       P934200QTEHMQDRWH             AMAZON DIGITAL SEATTLE WA                        $11.99
                                          CWLHfBnkDBOD
Total Fees Charged This Period                                                             $0.00
Total Interest Charged This Period                                                         $5.00
01/23                                        INTEREST CHARGE ON PURCHASES                  $5.00

                                   2026 Year-to-Date Fees and Interest
"""


class SynchronyTests(unittest.TestCase):
    def test_parse_statement(self):
        with mock.patch.object(syn, "statement_lines", return_value=SAMPLE.splitlines()):
            rows, account = syn.parse_statement(Path("Synchrony Bank Statement 20260123.pdf"))
        self.assertEqual(account, "9999")
        self.assertEqual([(r["Date"], r["Amount"]) for r in rows], [
            ("01/15/2026", "-100.00"), ("12/29/2025", "25.00"), ("01/09/2026", "11.99"), ("01/23/2026", "5.00")])
        self.assertEqual(rows[1]["Item"], "Sample Item Name")
        self.assertEqual(rows[2]["Item"], "")


if __name__ == "__main__":
    unittest.main()
