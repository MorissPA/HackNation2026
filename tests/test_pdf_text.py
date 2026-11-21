import unittest

from fastapi.testclient import TestClient

import api
from riskminer import analysis


class PdfTextTests(unittest.TestCase):
    """Tekst z PDF łamany po każdej liczbie („1\\n\\n200\\n\\nRLM”) – zgłoszony błąd 500 przy imporcie PDF."""

    def test_number_with_line_breaks_does_not_crash(self):
        self.assertEqual(analysis._num("1\n\n200\n\n"), 1200.0)
        f = analysis.extract_features("Oczyszczalnia ścieków 1\n\n200\n\nRLM, budżet 4,5 mln zł")
        self.assertIn("rlm", f["scale"])

    def test_split_thousands_are_rejoined_only_before_a_unit(self):
        self.assertEqual(analysis.clean_pdf_text("Oczyszczalnia 1\n\n200\n\nRLM"), "Oczyszczalnia 1 200 RLM")
        self.assertEqual(analysis.clean_pdf_text("Lp.\n1\n200 m kanału"), "Lp.\n1\n200 m kanału")  # pozycja listy
        self.assertEqual(analysis.clean_pdf_text("rozdział 1\n\n2023 rok"), "rozdział 1\n\n2023 rok")
        f = analysis.extract_features(analysis.clean_pdf_text("Oczyszczalnia 1\n\n200\n\nRLM"))
        self.assertEqual(f["scale"]["rlm"]["value"], 1200.0)

    def test_file_endpoint_returns_analysis_not_500(self):
        text = ("Budowa oczyszczalni ścieków dla 1\n\n200\n\nRLM w formule zaprojektuj i wybuduj, "
                "budżet 4,5 mln zł, termin 18 miesięcy.").encode()
        r = TestClient(api.app).post("/api/analysis/file", files={"file": ("opis.txt", text, "text/plain")})
        self.assertEqual(r.status_code, 200, r.text)


if __name__ == "__main__":
    unittest.main()
