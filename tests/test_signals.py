import unittest

from riskminer import signals
from riskminer.bzp import parser as P


CANCELLED_RESULT = """<html><body>
<h2>SEKCJA V ZAKOŃCZENIE POSTĘPOWANIA</h2>
<h3>5.1.) Postępowanie zakończyło się zawarciem umowy albo unieważnieniem postępowania: Postępowanie/cześć postępowania zakończyła się unieważnieniem</h3>
<h3>5.2.) Podstawa prawna unieważnienia postępowania: art. 255 pkt 3 ustawy</h3>
<h3>5.2.1.) Przyczyna unieważnienia postępowania: Złożona oferta z najniższą ceną przewyższa kwotę, którą Zamawiający zamierza przeznaczyć na sfinansowanie zamówienia</h3>
</body></html>"""


class SignalTests(unittest.TestCase):
    def test_cancellation_from_real_result_notice_fields(self):
        d = P.extract("TenderResultNotice", CANCELLED_RESULT)["by_part"][0]
        c = signals.cancellation(d["result"]["value"], d["cancel_basis"]["value"], d["cancel_reason"]["value"])
        self.assertEqual(c["code"], "R13")
        self.assertIn("przewyższa kwotę", c["reason"])

    def test_cancellation_basis_mapping_and_contract_concluded(self):
        self.assertEqual(signals.cancellation("zakończyła się unieważnieniem", "art. 255 pkt 1 ustawy")["code"], "R11")
        self.assertEqual(signals.cancellation("zakończyła się unieważnieniem", "art. 255 pkt 7 ustawy")["code"], "R12")
        self.assertIsNone(signals.cancellation("Postępowanie zakończyła się zawarciem umowy", None))

    def test_contractor_change_only_for_point_2(self):
        self.assertTrue(signals.contractor_change("art. 455 ust. 1 pkt 2 ustawy"))
        for basis in ("art. 455 ust. 1 pkt 1 ustawy", "art. 455 ust. 2 ustawy", "art. 455 ust. 1 pkt 3 ustawy", None):
            self.assertFalse(signals.contractor_change(basis))

    def test_termination_and_not_executed(self):
        self.assertEqual(signals.termination("Zamawiający odstąpił od umowy z winy wykonawcy"), "odstąpił")
        self.assertTrue(signals.termination("rozwiązanie umowy za porozumieniem stron"))
        self.assertIsNone(signals.termination("zmiana terminu wykonania umowy"))
        self.assertTrue(signals.not_executed("Nie"))
        self.assertFalse(signals.not_executed("Tak"))

    def test_similar_title_for_repeated_procedure(self):
        self.assertTrue(signals.similar_title("Budowa oczyszczalni ścieków w miejscowości Steklin",
                                              "„Budowa oczyszczalni ścieków w miejscowości Steklin” – postępowanie II"))
        self.assertFalse(signals.similar_title("Budowa oczyszczalni ścieków w miejscowości Steklin",
                                               "Dowóz uczniów niepełnosprawnych z terenu Gminy Czernikowo"))


if __name__ == "__main__":
    unittest.main()
