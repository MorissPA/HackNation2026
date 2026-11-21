import unittest

from riskminer import db, expert, risks


class CategoryTests(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(":memory:")
        self.addCleanup(self.con.close)
        self.addCleanup(lambda: (risks.CATALOG.__setitem__(slice(None), risks.BASE_CATALOG),
                                 risks.NAMES.clear(), risks.NAMES.update({c: n for c, n, _ in risks.BASE_CATALOG})))

    def test_proposed_category_enters_catalog_only_after_approval(self):
        code = expert.propose_category(self.con, "Brak mocy przyłączeniowej", "opóźnienie rozruchu")
        self.assertEqual(code, "R16")
        self.assertNotIn("R16", risks.NAMES)
        expert.decide_category(self.con, code, "approve")
        self.assertEqual(risks.NAMES["R16"], "Brak mocy przyłączeniowej")

    def test_explicit_code_and_duplicates(self):
        self.assertEqual(expert.propose_category(self.con, "R20 Kolizja z siecią gazową"), "R20")
        with self.assertRaises(ValueError):
            expert.propose_category(self.con, "R20 Inna nazwa kategorii")


if __name__ == "__main__":
    unittest.main()
