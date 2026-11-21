import unittest

from riskminer import analysis, llm_extract

DOC = """Przedmiotem zamówienia będzie wybudowanie sieci wodociągowej rozdzielczej o długości ok. 3,5 km z rur PE.
Dodatkowo planuje się dołożenie ok. 600 m sieci kanalizacji sanitarnej.
Całkowity koszt inwestycji oszacowano na 18 500 000 zł brutto. Dotacja z UE: 10 000 000 zł.
Podpisanie umowy: 1 lutego 2027 r. Zakończenie robót budowlanych: 30 listopada 2027 r.
Wykonawca musi wykazać doświadczenie z ostatnich 12 miesięcy."""


def body(values=(), **lists):
    return {"wartosci": [{"pole": k, "wartosc": str(v), "cytat": q} for k, v, q in values],
            "ograniczenia": lists.get("ograniczenia", []), "sprzecznosci": [], "braki": lists.get("braki", [])}


class VerifyTests(unittest.TestCase):
    def test_quote_must_come_from_document(self):
        res = llm_extract.verify(body([("budzet_brutto", 18_500_000, "Koszt inwestycji wynosi 25 mln zł")]), DOC)
        self.assertNotIn("budzet", res["fields"])
        self.assertTrue(res["rejected"])

    def test_number_must_be_in_quote(self):
        res = llm_extract.verify(body([("budzet_brutto", 20_000_000, "Całkowity koszt inwestycji oszacowano na 18 500 000 zł brutto")]), DOC)
        self.assertNotIn("budzet", res["fields"])

    def test_unit_conversion_and_dates(self):
        res = llm_extract.verify(body([
            ("dlugosc_sieci_km", 3.5, "sieci wodociągowej rozdzielczej o długości ok. 3,5 km"),
            ("czas_realizacji_mies", 10, "Zakończenie robót budowlanych: 30 listopada 2027 r."),
            ("rlm", 0, "Brak informacji o RLM")]), DOC)
        self.assertEqual(set(res["fields"]), {"dlugosc_sieci_km", "czas_realizacji_mies"})

    def test_answer_key_is_not_sent_to_model(self):
        (text,), _ = llm_extract.model_text(DOC + "\nKlucz testowy (co powinien wykryć Risk Miner)\nDługość 4,2 km")
        self.assertNotIn("Klucz testowy", text)


class BudgetAndLongDocTests(unittest.TestCase):
    def test_two_total_amounts_become_inconsistency(self):
        doc = "Szacunkowa wartość zamówienia 4 200 000 zł netto. Na zadanie przeznaczono łącznie 4 500 000 zł."
        res = llm_extract.verify(body([("budzet_netto", 4_200_000, "Szacunkowa wartość zamówienia 4 200 000 zł netto"),
                                       ("budzet_bez_vat", 4_500_000, "Na zadanie przeznaczono łącznie 4 500 000 zł")]), doc)
        self.assertEqual(res["fields"]["budzet"]["kwota_zl"], 4_500_000)
        self.assertEqual(len(res["sprzecznosci"]), 1)

    def test_long_document_is_split_into_relevant_chunks(self):
        filler = "\n\n".join(f"Akapit {i} opisuje historię gminy i jej mieszkańców bez danych technicznych." for i in range(400))
        doc = "Budowa sieci wodociągowej.\n\n" + filler + "\n\nBudżet inwestycji 8 mln zł.\n\n" + filler
        chunks, skipped = llm_extract.model_text(doc)
        self.assertLessEqual(len(chunks), llm_extract.MAX_CHUNKS)
        self.assertTrue(any("Budżet inwestycji 8 mln zł" in c for c in chunks))
        self.assertTrue(all(len(c) <= llm_extract._limit() + 1600 for c in chunks))


class MergeTests(unittest.TestCase):
    def test_model_fills_gaps_and_disagreement_goes_to_expert(self):
        f = analysis.extract_features(DOC)
        self.assertEqual(f["duration_months"]["value"], 10)  # reguła: z dat, nie z „ostatnich 12 miesięcy”
        res = llm_extract.verify(body(
            [("czas_realizacji_mies", 12, "doświadczenie z ostatnich 12 miesięcy")],
            ograniczenia=[{"kategoria": "niepewne finansowanie", "cytat": "Dotacja z UE: 10 000 000 zł"}],
            braki=["Brak badań geotechnicznych"]), DOC)
        analysis.merge_model(f, res, {})
        self.assertIsNone(f["duration_months"])
        self.assertEqual([o["value"] for o in f["conflicts"]["duration_months"]], [10, 12])
        self.assertIn("niepewne finansowanie", [c["value"] for c in f["constraints"]])
        self.assertEqual(f["model_findings"]["gaps"], ["Brak badań geotechnicznych"])
        f2 = analysis.extract_features(DOC)
        analysis.merge_model(f2, res, {"duration_months": 10})
        self.assertEqual(f2["duration_months"]["rejected"][0]["value"], 12)
        self.assertEqual(f2["duration_months"]["value"], 10)
        self.assertNotIn("duration_months", f2["conflicts"])


if __name__ == "__main__":
    unittest.main()
