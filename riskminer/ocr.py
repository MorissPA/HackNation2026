"""OCR skanów (PDF bez warstwy tekstowej, zdjęcia dokumentów) – Tesseract, język polski.

Tesseract (Apache-2.0) działa lokalnie, dokument nie opuszcza komputera. Instalacja:
- macOS:  brew install tesseract tesseract-lang
- Debian/Docker: apt-get install tesseract-ocr tesseract-ocr-pol (w Dockerfile)
Ścieżkę programu można wskazać zmienną TESSERACT_CMD, a katalog z pol.traineddata – TESSDATA_PREFIX.

Skan PDF to zwykle jeden obraz na stronę: wyciągamy obrazy stron przez pypdf (bez renderowania), skalujemy małe
skany do ~300 dpi i rozpoznajemy tekst. Wynik oznaczamy jako OCR, bo może zawierać błędy rozpoznania (np. cyfry).
"""
import io
import os
import shutil
import subprocess
import tempfile
from functools import lru_cache

IMAGE_TYPES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")
MAX_PAGES = int(os.environ.get("OCR_MAX_PAGES", "30"))
TIMEOUT = 120  # s na stronę


class OCRError(ValueError):
    """Komunikat dla użytkownika (API zwraca 400/422)."""


def _cmd():
    return os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")


@lru_cache(maxsize=1)
def languages():
    cmd = _cmd()
    if not cmd:
        return ()
    try:
        out = subprocess.run([cmd, "--list-langs"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return ()
    return tuple(line.strip() for line in out.splitlines()[1:] if line.strip())


def available():
    return bool(_cmd())


def _lang():
    langs = languages()
    if "pol" in langs:
        return "pol"
    raise OCRError("OCR wymaga polskiego modelu Tesseracta (pol). Zainstaluj: brew install tesseract-lang "
                   "(macOS) lub apt-get install tesseract-ocr-pol (Linux).")


def image_to_text(image):
    """Obraz PIL → tekst. Skan w niskiej rozdzielczości powiększamy (Tesseract potrzebuje ~300 dpi)."""
    from PIL import Image, ImageOps
    cmd = _cmd()
    if not cmd:
        raise OCRError("Dokument jest skanem, a OCR (Tesseract) nie jest zainstalowany. "
                       "macOS: brew install tesseract tesseract-lang; Linux/Docker: tesseract-ocr tesseract-ocr-pol.")
    lang = _lang()
    image = ImageOps.exif_transpose(image).convert("L")
    if image.width < 1800:  # strona A4 ~ 2480 px przy 300 dpi
        scale = 2480 / image.width
        image = image.resize((int(image.width * scale), int(image.height * scale)), Image.LANCZOS)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "page.png")
        image.save(path)
        try:
            done = subprocess.run([cmd, path, "stdout", "-l", lang, "--psm", "1"],
                                  capture_output=True, text=True, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            raise OCRError("OCR strony trwał zbyt długo. Wklej opis jako tekst.")
        except OSError as exc:
            raise OCRError(f"Nie udało się uruchomić Tesseracta: {exc}")
    if done.returncode != 0:
        raise OCRError("Tesseract zakończył się błędem: " + (done.stderr or "").strip()[:200])
    return done.stdout


def pdf_to_text(reader):
    """Skan PDF: obrazy z kolejnych stron → tekst. Zwraca tekst stron rozdzielony pustym wierszem."""
    from PIL import Image
    pages = []
    for number, page in enumerate(reader.pages[:MAX_PAGES], 1):
        images = list(page.images)
        if not images:
            continue
        # największy obraz na stronie to skan strony (mniejsze to np. pieczątki, logo)
        best = max(images, key=lambda im: im.image.width * im.image.height if im.image else 0)
        image = best.image or Image.open(io.BytesIO(best.data))
        pages.append(image_to_text(image).strip())
    text = "\n\n".join(p for p in pages if p)
    if not text.strip():
        raise OCRError("PDF nie ma warstwy tekstowej, a OCR nie rozpoznał tekstu na obrazach stron. Wklej opis jako tekst.")
    return text


def file_to_text(content):
    from PIL import Image, UnidentifiedImageError
    try:
        image = Image.open(io.BytesIO(content))
    except UnidentifiedImageError:
        raise OCRError("Nie udało się odczytać obrazu. Obsługiwane: PNG, JPG, TIFF.")
    return image_to_text(image)
