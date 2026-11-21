import unittest

from riskminer import analysis

PROTOCOL = """PROTOKÓŁ KONIECZNOŚCI nr 1 – wykonanie robót dodatkowych
3. Zakres proponowanej zmiany
Dotychczasowy termin zakończenia realizacji zadania: 30.10.2025 r.
Proponowany nowy termin zakończenia realizacji zadania: 05.12.2025 r.
Koszt robót dodatkowych ustala się na kwotę: 151 481,54 zł brutto
3. Wartość ewentualnych dodatkowych robót nie przekracza limitów określonych w art. 455 ust. 1 pkt 3 Pzp."""


class BudgetExtractionTests(unittest.TestCase):
    def test_change_protocol_cost_and_deadline(self):
        f = analysis.extract_features(PROTOCOL)
        self.assertIsNone(f["budget_pln"])
        self.assertEqual([o["value"] for o in f["extra_costs"]], [151481.54])
        self.assertEqual(f["extra_costs"][0]["tax"], "brutto")
        self.assertEqual(f["deadline_change"]["days"], 36)

    def test_budget_with_words_between_keyword_and_amount(self):
        for text, value in [("Wartość zamówienia wynosi ok. 4,5 mln zł brutto.", 4.5e6),
                            ("Wynagrodzenie Wykonawcy ustala się na kwotę 3 210 000 zł brutto.", 3.21e6),
                            ("Kwota dofinansowania 2 mln zł. Wartość umowy: 7 300 000,00 zł brutto.", 7.3e6)]:
            with self.subTest(text=text):
                self.assertEqual(analysis.extract_features(text)["budget_pln"]["value"], value)

    def test_amounts_that_are_not_budget(self):
        for text in ("Kara umowna w wysokości 5 000 zł.", "Zwiększenie wynagrodzenia o kwotę 120 000 zł."):
            with self.subTest(text=text):
                self.assertIsNone(analysis.extract_features(text)["budget_pln"])


if __name__ == "__main__":
    unittest.main()
