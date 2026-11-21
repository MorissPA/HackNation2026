"""Parser treści ogłoszeń BZP (htmlBody) -> lista pól z lokalizacją.

Ogłoszenia BZP mają stałą strukturę: <h2> = sekcja, <h3> = pole „4.4.) Wartość umowy: 2131590,00 PLN”.
Numeracja pól różni się między typami ogłoszeń, dlatego ekstrakcja dopasowuje pola po
treści etykiety (regex), a numer pola zapisuje jako lokalizację dowodu.
W ogłoszeniach wieloczęściowych nagłówki „Część N” / „(dla części N)” ustawiają kontekst części.
"""
import re
from html.parser import HTMLParser

_BLOCK = {"h1", "h2", "h3", "h4", "p", "li", "div", "br", "tr", "ul", "ol", "table"}
FIELD_RE = re.compile(r"^(?P<code>\d+(?:\.\d+)*\.?\)?)\s*(?P<rest>.*)$", re.S)
FOOTER_RE = re.compile(r"\s*\d{4}-\d{2}-\d{2}\s*Biuletyn Zamówień Publicznych.*$", re.S)
PART_HDR_RE = re.compile(r"^Część\s+(\d+)\s*$", re.I)
PART_IN_SECTION_RE = re.compile(r"\(dla części\s+(\d+)\)", re.I)


class _Flattener(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines = []  # (tag, text)
        self._buf, self._tag, self._skip = [], None, 0

    def _flush(self):
        text = re.sub(r"[ \t\r\f\v\xa0]+", " ", "".join(self._buf)).strip()
        if text:
            self.lines.append((self._tag or "p", text))
        self._buf, self._tag = [], None

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head"):
            self._skip += 1
        if tag in _BLOCK:
            self._flush()
            if tag in ("h1", "h2", "h3", "h4"):
                self._tag = tag

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head"):
            self._skip = max(0, self._skip - 1)
        if tag in ("h1", "h2", "h3", "h4"):
            self._flush()

    def handle_data(self, data):
        if not self._skip:
            self._buf.append(data)

    def close(self):
        super().close()
        self._flush()


def html_to_lines(html: str):
    p = _Flattener()
    p.feed(html or "")
    p.close()
    return p.lines


def html_to_text(html: str) -> str:
    out = []
    for tag, text in html_to_lines(html):
        out.append(("\n" if tag in ("h2",) else "") + text)
    return "\n".join(out).strip()


def parse_fields(html: str):
    """Zwraca listę pól: {idx, section, part, code, label, value}."""
    fields, section, part, cur = [], "", 0, None
    header = []
    for tag, text in html_to_lines(html):
        # stopka ogłoszenia („2026-03-06 Biuletyn Zamówień Publicznych…”) – nie jest częścią żadnego pola
        text = FOOTER_RE.sub("", text).strip()
        if not text:
            continue
        if tag == "h2":
            section = text
            m = PART_IN_SECTION_RE.search(text)
            if m:
                part = int(m.group(1))
            elif section.upper().startswith("SEKCJA"):
                # nowa sekcja bez wskazania części – kontekst części kasujemy,
                # chyba że to sekcja opisu przedmiotu z listą części (ustawiana przez h3)
                part = 0 if "(dla części" not in text else part
            cur = None
            continue
        if tag == "h3":
            m = PART_HDR_RE.match(text)
            if m:
                part = int(m.group(1))
                cur = None
                continue
            fm = FIELD_RE.match(text)
            if fm:
                rest = fm.group("rest").strip()
                if ":" in rest:
                    label, value = rest.split(":", 1)
                else:
                    label, value = rest, ""
                cur = {
                    "idx": len(fields),
                    "section": section,
                    "part": part,
                    "code": fm.group("code").rstrip(")").rstrip("."),
                    "label": label.strip(),
                    "value": value.strip(),
                }
                fields.append(cur)
                continue
        if not section:
            header.append(text)
            continue
        if cur is not None:
            cur["value"] = (cur["value"] + "\n" + text).strip()
        else:
            # tekst poza polem (np. SEKCJA VI INFORMACJE DODATKOWE)
            cur = {"idx": len(fields), "section": section, "part": part, "code": "", "label": "", "value": text}
            fields.append(cur)
    return {"header": header, "fields": fields}


# ---------------------------------------------------------------- konwersje
def parse_money(s):
    if not s:
        return None
    m = re.search(r"(-?\d[\d\s\xa0]*(?:[.,]\d{1,2})?)", s)
    if not m:
        return None
    num = re.sub(r"[\s\xa0]", "", m.group(1)).replace(",", ".")
    try:
        return float(num)
    except ValueError:
        return None


def parse_date(s):
    if not s:
        return None
    m = re.search(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m.group(1)
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return None


def end_date(period_text, signed=None):
    """Termin z pola 'Okres realizacji': data wprost ('do 2025-08-18') albo czas trwania od daty
    zawarcia umowy ('5 miesiące', '120 dni'). Zwraca (data, czy_wyliczona)."""
    d = parse_date(period_text)
    if d:
        return d, False
    m = re.search(r"(\d+)\s*(miesiąc|miesiące|miesięcy|mies|dni|dzień|tygodni)", period_text or "", re.I)
    if not (m and signed):
        return None, False
    from datetime import date, timedelta
    n, unit, s = int(m.group(1)), m.group(2).lower(), date.fromisoformat(signed)
    if unit.startswith("mies"):
        y, mo = divmod(s.month - 1 + n, 12)
        import calendar
        day = min(s.day, calendar.monthrange(s.year + y, mo + 1)[1])
        return date(s.year + y, mo + 1, day).isoformat(), True
    if unit.startswith("tyg"):
        return (s + timedelta(weeks=n)).isoformat(), True
    return (s + timedelta(days=n)).isoformat(), True


def find(fields, pattern, part=None, first=True):
    rx = re.compile(pattern, re.I)
    hits = [f for f in fields if rx.search(f["label"]) and (part is None or f["part"] == part)]
    if first:
        return hits[0] if hits else None
    return hits


def loc(f) -> str:
    """Lokalizacja dowodu w ogłoszeniu."""
    if not f:
        return ""
    sec = re.sub(r"\s+", " ", f["section"]).strip()
    code = f"pkt {f['code']}" if f.get("code") else "tekst sekcji"
    return f"{sec} › {code} {f['label']}".strip()


def quote(f, limit=600) -> str:
    if not f:
        return ""
    s = (f"{f['code']}.) {f['label']}: " if f["code"] else "") + f["value"]
    return s if len(s) <= limit else s[: limit - 1] + "…"


# ------------------------------------------------------------ ekstrakcja
def extract(notice_type: str, html: str) -> dict:
    """Ustrukturyzowane dane z ogłoszenia (zależnie od typu)."""
    parsed = parse_fields(html)
    F = parsed["fields"]
    out = {"fields": F, "parts": sorted({f["part"] for f in F if f["part"]})}

    if notice_type == "ContractNotice":
        out["title"] = find(F, r"^Nazwa zamówienia")
        out["reference_no"] = find(F, r"Numer referencyjny")
        out["deadline_offers"] = find(F, r"Termin składania ofert")
        out["duration"] = find(F, r"Okres realizacji|Czas trwania|Termin realizacji", first=True)
        out["has_parts"] = find(F, r"udziela zamówienia w częściach|możliwe jest składanie ofert częściowych")

    elif notice_type == "TenderResultNotice":
        out["estimated_value"] = find(F, r"^Wartość zamówienia")
        out["reference_no"] = find(F, r"Numer referencyjny")
        parts = out["parts"] or [0]
        out["by_part"] = {}
        for p in parts:
            out["by_part"][p] = {
                "part_value": find(F, r"^Wartość części", part=p),
                "result": find(F, r"zakończyło się zawarciem umowy albo unieważnieniem", part=p),
                "n_offers": find(F, r"^Liczba otrzymanych ofert lub wniosków", part=p),
                "price_min": find(F, r"najniższą ceną", part=p),
                "price_max": find(F, r"najwyższą ceną", part=p),
                "price_winner": find(F, r"wykonawcy, któremu udzielono zamówienia$", part=p)
                or find(F, r"^Cena lub koszt oferty wykonawcy", part=p),
                "contractor": find(F, r"^Nazwa \(firma\) wykonawcy", part=p),
                "contractor_id": find(F, r"^Krajowy Numer Identyfikacyjny", part=p),
                "signed": find(F, r"^Data zawarcia umowy", part=p),
                "value": find(F, r"^Wartość umowy", part=p),
                "period": find(F, r"^Okres realizacji", part=p),
            }

    elif notice_type == "AgreementUpdateNotice":
        out["signed"] = find(F, r"^Data zawarcia umowy")
        out["value"] = find(F, r"^Wartość umowy")
        out["period"] = find(F, r"^Okres realizacji")
        out["contractor"] = find(F, r"^Nazwa \(firma\) wykonawcy")
        cids = find(F, r"^Krajowy Numer Identyfikacyjny", first=False)
        out["contractor_id"] = cids[1] if len(cids) > 1 else None  # [0] = zamawiający
        out["change_date"] = find(F, r"^Data zmiany umowy")
        out["legal_basis"] = find(F, r"^Podstawa prawna zmiany")
        out["reason"] = find(F, r"^Przyczyny dokonania zmian")
        out["description"] = find(F, r"^Krótki opis zmiany")
        out["value_change"] = find(F, r"^Wartość zmiany$")
        out["currency"] = find(F, r"^Kod waluty")
        out["price_increase"] = find(F, r"^Wzrost ceny")

    elif notice_type == "ContractPerformingNotice":
        out["signed"] = find(F, r"^Data zawarcia umowy")
        out["period"] = find(F, r"^Okres realizacji")
        out["contractor"] = find(F, r"^Nazwa \(firma\) wykonawcy")
        cids = find(F, r"^Krajowy Numer Identyfikacyjny", first=False)
        out["contractor_id"] = cids[1] if len(cids) > 1 else None  # [0] = zamawiający
        out["value"] = find(F, r"^Wartość umowy")
        out["result_notice"] = find(F, r"^Numer ogłoszenia o wyniku")
        name = find(F, r"^Nazwa zamówienia")
        m = re.search(r"części\s*(?:nr\s*)?(\d+)", name["value"] if name else "", re.I)
        out["part_hint"] = int(m.group(1)) if m else None
        out["executed"] = find(F, r"^Czy umowa została wykonana:?$|^Czy umowa została wykonana$")
        out["end_actual"] = find(F, r"^Termin wykonania umowy")
        out["on_time"] = find(F, r"pierwotnie określonym terminie")
        out["n_changes"] = find(F, r"^Liczba zmian")
        out["paid_total"] = find(F, r"^Łączna wartość wynagrodzenia")
        out["properly"] = find(F, r"wykonana należycie")
        out["extra_info"] = [f for f in F if "INFORMACJE DODATKOWE" in f["section"].upper()]
        # lista zmian: grupujemy pola od „Numer zmiany” do kolejnego „Numer zmiany”
        changes, cur = [], None
        for f in F:
            if re.match(r"^Numer zmiany", f["label"], re.I):
                cur = {"no": f}
                changes.append(cur)
            elif cur is not None and f["code"].startswith("5.4"):
                lab = f["label"].lower()
                if lab.startswith("podstawa prawna"):
                    cur["legal_basis"] = f
                elif lab.startswith("przyczyny"):
                    cur["reason"] = f
                elif lab.startswith("krótki opis"):
                    cur["description"] = f
                elif lab.startswith("wartość zmiany"):
                    cur["value_change"] = f
                elif lab.startswith("kod waluty"):
                    cur["currency"] = f
                elif lab.startswith("wzrost ceny"):
                    cur["price_increase"] = f
            elif cur is not None and not f["code"].startswith("5.4"):
                cur = None
        out["changes"] = changes
    return out
