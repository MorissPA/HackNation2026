import io
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

import api
from riskminer import analysis, config


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
        with patch.object(config, "DB_PATH", ":memory:"):
            r = TestClient(api.app).post("/api/analysis/file", files={"file": ("opis.txt", text, "text/plain")})
        self.assertEqual(r.status_code, 200, r.text)

    def test_pdf_uses_same_minimum_as_plain_text(self):
        for text, status, detail in (
            ("Budowa wodociagu o dlugosci 5 kilometrow.", 200, ""),
            ("Budowa wodociagu", 400, "30 znaków"),
            ("", 400, "warstwy tekstowej"),
        ):
            with self.subTest(text=text):
                writer = PdfWriter()
                page = writer.add_blank_page(595, 842)
                name = NameObject
                page[name("/Resources")] = DictionaryObject({
                    name("/Font"): DictionaryObject({
                        name("/F1"): DictionaryObject({
                            name("/Type"): name("/Font"), name("/Subtype"): name("/Type1"),
                            name("/BaseFont"): name("/Helvetica"),
                        }),
                    }),
                })
                stream = DecodedStreamObject()
                stream.set_data(f"BT /F1 12 Tf 50 720 Td ({text}) Tj ET".encode("ascii"))
                page.replace_contents(stream)
                payload = io.BytesIO()
                writer.write(payload)
                with patch.object(config, "DB_PATH", ":memory:"):
                    response = TestClient(api.app).post("/api/analysis/file", files={
                        "file": ("opis.pdf", payload.getvalue(), "application/pdf"),
                    })
                self.assertEqual(response.status_code, status)
                if detail:
                    self.assertIn(detail, response.json()["detail"])
                else:
                    self.assertEqual(response.json()["input_text"].strip(), text)


if __name__ == "__main__":
    unittest.main()
