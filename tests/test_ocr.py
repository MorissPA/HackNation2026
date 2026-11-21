import io
import unittest
from unittest import mock

from PIL import Image

from riskminer import analysis, ocr


def scanned_pdf(pages=1):
    images = [Image.new("RGB", (600, 850), "white") for _ in range(pages)]
    buf = io.BytesIO()
    images[0].save(buf, format="PDF", save_all=True, append_images=images[1:])
    return buf.getvalue()


class OcrRoutingTests(unittest.TestCase):
    def test_scanned_pdf_goes_through_ocr(self):
        with mock.patch.object(ocr, "available", return_value=True), \
             mock.patch.object(ocr, "image_to_text", return_value="Budżet inwestycji 8 mln zł brutto.") as fake:
            text, pages = analysis.read_file("skan.pdf", scanned_pdf(2))
        self.assertEqual(pages, 2)
        self.assertEqual(fake.call_count, 2)
        self.assertEqual(analysis.extract_features(text)["budget_pln"]["value"], 8e6)

    def test_small_scan_is_upscaled_before_ocr(self):
        seen = {}

        def fake_run(args, **kw):
            seen["size"] = Image.open(args[1]).size
            return mock.Mock(returncode=0, stdout="tekst", stderr="")
        with mock.patch.object(ocr, "_cmd", return_value="tesseract"), mock.patch.object(ocr, "languages", return_value=("pol",)), \
             mock.patch.object(ocr.subprocess, "run", side_effect=fake_run):
            self.assertEqual(ocr.image_to_text(Image.new("RGB", (620, 877), "white")), "tekst")
        self.assertGreaterEqual(seen["size"][0], 2400)

    def test_missing_tesseract_gives_install_hint(self):
        with mock.patch.object(ocr, "_cmd", return_value=None):
            with self.assertRaisesRegex(ocr.OCRError, "brew install tesseract"):
                analysis.read_file("skan.png", io.BytesIO(scanned_pdf()).getvalue() and _png())


def _png():
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), "white").save(buf, format="PNG")
    return buf.getvalue()


if __name__ == "__main__":
    unittest.main()
