"""Analiza nowej inwestycji: cechy z opisu → podobne przypadki z bazy → koszty, terminy, ryzyka, rekomendacje.

Zasady (z materiału eksperckiego organizatora):
- każda cecha i każdy wniosek wskazuje źródło (fragment opisu albo ogłoszenie/zdarzenie z bazy),
- przy małej próbie pokazujemy wartości per przypadek i mówimy, czego brakuje do przedziału,
- kwota projektu ≠ kwota umowy; porównujemy wielkości tego samego rodzaju,
- wiedza zatwierdzona przez eksperta (zaakceptowane/poprawione ryzyka) waży więcej niż propozycje,
  a odrzucone propozycje nie są brane pod uwagę.
"""
import html
import io
import json
import re
import statistics
import zipfile
from datetime import date

from . import risks
from .bzp import parser as P

# ---------------------------------------------------------------- taksonomia organizatora (podsektory)
SUBSECTORS = [
    ("Oczyszczalnia ścieków", r"oczyszczal\w*\s+ście|oczyszczalni|\bRLM\b|osad\w* czynn|złoż\w* biologiczn|reaktor\w* biologiczn"),
    ("Kanalizacja sanitarna", r"kanalizac\w*\s+sanitarn|kanalizacj\w*\b(?!\s+deszcz)|(?:prze)?pompowni\w*|kanał\w* (sanitarn|grawitacyjn|tłoczn)|przewod\w* tłoczn|tłoczn\w* kanaliz"),
    ("Sieć wodociągowa", r"sie(ć|ci)\s+wodociąg|wodociąg|przyłącz\w* wod|magistral\w* wod"),
    ("Uzdatnianie i zaopatrzenie w wodę", r"uzdatnian\w* wod\w*|\bfiltr(?:y|ów|a|ach)?\b|złoż\w* filtracyjn|odżelazi|odmanganiani|\bSUW\b|stacj\w* uzdatniania|ujęci\w* wody|studni\w* głębin|zbiornik\w* wody czystej|hydrofor"),
    ("Kanalizacja deszczowa i retencja", r"kanalizac\w*\s+deszcz|wód opadowych|retencj|odwodnieni|zbiornik\w* retencyjn"),
]
CONSTRAINTS = [
    ("pozwolenie wodnoprawne / odbiornik ścieków", r"pozwoleni\w* wodnoprawn|odbiornik\w*\s+ściek\w*|wylot\w* (ścieków|do)|zrzut\w*|wody polskie|\b(?:jezior|rzek|ciek|potok)\w*\b"),
    ("decyzja środowiskowa / ochrona przyrody", r"decyzj\w* (o )?środowiskow|natura 2000|obszar\w* chronion|ochron\w* przyrody|RDOŚ"),
    ("grunty prywatne / dostęp do terenu", r"grunt\w* prywatn|własnoś\w* prywatn|służebnoś|wejści\w* w teren|zgod\w* właściciel|prawo do dysponowania"),
    ("kolizje i istniejące uzbrojenie", r"kolizj|istniejąc\w* (uzbrojeni|sieci|infrastruktur)|uzbrojeni\w* teren"),
    ("przekroczenia: droga, kolej, ciek", r"przejści\w* (pod|przez)|przewiert|przecisk|drog\w* (krajow|wojewódzk|powiatow)|lini\w* kolejow|kolej"),
    ("istniejący obiekt w eksploatacji", r"ciągłoś\w* pracy|istniejąc\w* oczyszczal|w trakcie eksploatacji|bez przerw\w* w dostawie|rozbiórk\w* istniejąc"),
    ("azbest / stan istniejących sieci", r"azbest|cementowo-azbestow|inspekcj\w* TV|stan techniczn"),
    # ogólne zwroty z dokumentów przygotowawczych (PFU, koncepcje) – pozostałe okoliczności rozpoznaje model
    ("nieustalony operator / podział odpowiedzialności",
     r"nie\s+rozstrzygnięto[^.]{0,80}(?:zarządza|eksploat|operator)|nieustalon\w* (?:operator|zarządc|eksploatator)"
     r"|obciążają w całości wykonawc|po stronie wykonawcy w całości"),
    ("wynagrodzenie ryczałtowe przy niepewnym zakresie", r"wynagrodzeni\w* ryczałtow|ryczałt\w* wynagrodzeni"),
    ("brak procedur prób, rozruchu i odbioru",
     r"nie\s+określono[^.]{0,80}(?:prób|odbior|rozruch|badań|próbek|laborator)|procedur\w* (?:prób|odbioru)[^.]{0,80}zostaną ustalone"),
    ("zawężające warunki udziału lub wskazanie marki",
     r"wyłącznie mark\w*|tej samej technologii|na terenie województwa|wyłącznie (?:producent|firm)"),
    ("długi czas dostaw / dostępność urządzeń", r"czas\w* oczekiwania|poza UE|na indywidualne zamówienie"),
    ("niepewne finansowanie",
     r"nabór\w* (?:jeszcze )?nie|wniosek\w* (?:jeszcze )?nie|planuje\w* pozyska\w* dofinans|w przypadku braku uzyskania dotacji"),
    ("nierealny harmonogram / zależność od innej inwestycji",
     r"nieterminow\w* przebieg|do czasu[^.]{0,80}(?:inwestycji|budow)|zależn\w* od (?:innej|realizacji)|skrócon\w* do minimum"),
    ("warunki gruntowo-wodne", r"geotechn|grunt\w* (słab|nienośn|organiczn)|w[oó]d\w* gruntow|odwodnieni\w* wykop|podtopie"),
]
DESIGN_BUILD = r"zaprojektuj\s+i\s+(wy)?buduj|projektuj\s+i\s+buduj|PFU|program\w* funkcjonalno"
WORK_NEW = r"\bbudow\w*|\brozbudow\w*|nowo\s*projektowan"
WORK_MOD = r"\bprzebudow\w*|\bmodernizac\w*|\bremont\w*|\brenowac\w*|\bwymian\w*"

# ---------------------------------------------------------------- rekomendacje (ryzyko → działania, zapisy)
ACTIONS = {
    "R01": ("Zweryfikować kompletność zakresu w PFU/OPZ (inwentaryzacja, przedmiar, granice zadania) przed ogłoszeniem.",
            "W umowie: mechanizm wyceny robót dodatkowych/zamiennych i hierarchia dokumentów (PFU > oferta)."),
    "R02": ("Rozpoznać stan istniejący: inwentaryzacja sieci, inspekcja TV, badania geotechniczne, materiały (np. azbest).",
            "W SWZ: wyniki rozpoznania jako załącznik; ryzyko stanu nieujawnionego – po stronie zamawiającego z limitem."),
    "R03": ("Potwierdzić prawo do dysponowania gruntem na całej trasie i zinwentaryzować kolizje z uzbrojeniem.",
            "W umowie: procedura postępowania przy kolizjach i przedłużenie terminu przy braku dostępu do terenu."),
    "R04": ("Ustalić, kto i kiedy uzyskuje decyzje (pozwolenie wodnoprawne, środowiskowa, pozwolenie na budowę), i ująć ich czas w harmonogramie.",
            "W umowie: przypisanie odpowiedzialności za decyzje oraz przesłanka zmiany terminu przy przedłużającym się postępowaniu organu."),
    "R05": ("Rozpisać podział odpowiedzialności: inwestor, projektant, wykonawca, operator sieci.",
            "W umowie: macierz odpowiedzialności i obowiązki przekazania danych wejściowych."),
    "R06": ("Zweryfikować realność terminu względem procedur, sezonu robót i prób/rozruchu.",
            "W umowie: harmonogram z kamieniami milowymi i zasady jego aktualizacji."),
    "R07": ("Zaplanować rezerwę budżetową na roboty nieprzewidziane (na podstawie wzrostu wypłat w podobnych przypadkach).",
            "W umowie: zmiany na podstawie art. 455 ust. 1 pkt 1 Pzp opisane z góry (zakres, sposób wyceny, limit)."),
    "R08": ("Dobrać model wynagrodzenia do pewności zakresu (ryczałt tylko przy kompletnym rozpoznaniu).",
            "W umowie: przy niepewnym zakresie – wynagrodzenie kosztorysowe lub ryczałt z pozycjami obmiarowymi."),
    "R09": ("Określić mierzalne parametry techniczne i sposób ich weryfikacji.", "W PFU/OPZ: parametry docelowe i kryteria odbioru."),
    "R10": ("Opisać próby, rozruch i odbiór (parametry, czas trwania, badania akredytowane).",
            "W umowie: rozruch technologiczny i raport porealizacyjny jako warunek odbioru końcowego."),
    "R11": ("Sprawdzić warunki udziału i kryteria pod kątem ograniczania konkurencji.", "W SWZ: proporcjonalne warunki i jasne kryteria."),
    "R12": ("Sprawdzić zdolność wykonawców i dostępność urządzeń na rynku.", "W umowie: zasady zamiany urządzeń i podwykonawstwa."),
    "R13": ("Potwierdzić finansowanie i terminy rozliczenia dofinansowania.", "W umowie: harmonogram płatności spójny z dofinansowaniem."),
    "R14": ("Uwzględnić koszty eksploatacji w wyborze rozwiązania.", "W PFU: wymagania dotyczące kosztów eksploatacji i serwisu."),
    "R15": ("Zdefiniować wymagany efekt (parametry ścieków/wody) i sposób jego potwierdzenia.",
            "W umowie: osiągnięcie efektu ekologicznego potwierdzone badaniami jako warunek odbioru."),
}
# Okoliczności, które rozpoznaje model językowy (trudne do uchwycenia regułą) → ryzyko z katalogu.
MODEL_CONSTRAINTS = {
    "niepełny lub niespójny zakres": "R01",
    "nieustalony operator / podział odpowiedzialności": "R05",
    "nierealny harmonogram / zależność od innej inwestycji": "R06",
    "wynagrodzenie ryczałtowe przy niepewnym zakresie": "R08",
    "ogólnikowe wymagania techniczne": "R09",
    "brak procedur prób, rozruchu i odbioru": "R10",
    "zawężające warunki udziału lub wskazanie marki": "R11",
    "długi czas dostaw / dostępność urządzeń": "R12",
    "niepewne finansowanie": "R13",
}
CONSTRAINT_RISK = {
    **MODEL_CONSTRAINTS,
    "pozwolenie wodnoprawne / odbiornik ścieków": "R04", "decyzja środowiskowa / ochrona przyrody": "R04",
    "grunty prywatne / dostęp do terenu": "R03", "kolizje i istniejące uzbrojenie": "R03",
    "przekroczenia: droga, kolej, ciek": "R04", "istniejący obiekt w eksploatacji": "R06",
    "azbest / stan istniejących sieci": "R02", "warunki gruntowo-wodne": "R02",
}

# ---------------------------------------------------------------- checklista organizatora (sieć wodociągowa)
WATER_CHECKLIST = [
    ("Konkretny problem zaopatrzenia w wodę i oczekiwany efekt inwestycji.", "1.1–1.2",
     r"brak dostępu|niedobor|jakoś\w* wody|przerw\w* w dostaw|ciśnieni|cel\w* (projektu|inwestycji)|zapewnieni\w* dostaw"),
    ("Obszar obsługi oraz przybliżona liczba i charakter odbiorców.", "1.3–1.4",
     r"\d+\s*(mieszkańc|budynk|gospodarstw|nieruchomoś|odbiorc|osób)|miejscowoś|ulic"),
    ("Przewidywani odbiorcy początkowi i wiarygodne przesłanki dalszego przyłączania nieruchomości.", "2.1–2.3",
     r"deklaracj|zainteresowan\w* przyłącz|odbiorc\w* początkow|planowan\w* zabudow|rozw[oó]j"),
    ("Orientacyjny przebieg i długość sieci oraz zakres przewidywanych przyłączy.", "3.1–3.4",
     r"\d+[,.]?\d*\s*(km|m\b|mb)|długoś|przyłącz"),
    ("Przewidywane miejsce zasilania i wstępne stanowisko operatora o możliwości dostawy wody.", "4.1–4.4",
     r"zasilani|włączeni\w* do|operator|przedsiębiorstw\w* wodociąg|SUW|stacj\w* uzdatniania"),
    ("Wstępna trasa sieci, rodzaj własności gruntów i znane trudności z dostępem.", "5.1–5.4",
     r"tras|pas\w* drog|grunt|działk|własnoś"),
    ("Główne przeszkody lokalizacyjne i zależności od innych inwestycji.", "5.4; 6.1–6.2",
     r"przeszkod|kolizj|przejści|ciek|kolej|zależn\w* od|plan\w* miejscow"),
    ("Wstępne rozpoznanie potrzeby decyzji środowiskowej i ograniczeń ochrony przyrody.", "6.3–6.5",
     r"środowiskow|natura 2000|ochron\w* przyrody|obszar\w* chronion"),
    ("Podział odpowiedzialności za przygotowanie, projekt, nieruchomości, decyzje i eksploatację oraz główne ryzyka.", "7.1–7.5",
     r"odpowiedzialn|eksploatac|właściciel\w* sieci|projektant|ryzyk"),
]


# ================================================================ wejście: tekst z PDF/DOCX
_UNIT_AFTER = r"\s*(?:RLM|km\b|mb?\b|m[23³²]|zł|PLN|mln|tys|szt|przyłącz|przykanalik|budynk|osób|mieszkańc)"


def clean_pdf_text(text: str) -> str:
    """Tekst z PDF bywa łamany po każdym słowie lub liczbie (tabele, duże nagłówki): „1\n\n200\n\nRLM”.
    Grupy tysięcy rozbite łamaniem wiersza sklejamy, gdy dalej stoi jednostka – „1 200 RLM”."""
    text = text.replace("\r", "")
    # tylko przy pustym wierszu między grupami (tak rozbija je ekstrakcja); pojedyncze łamanie to zwykle osobna pozycja listy
    rx = re.compile(r"(?<![\d.,])(\d{1,3})[ \t\xa0]*\n[ \t\xa0]*\n\s*(?=\d{3}(?:\s*\d{3})*(?!\d)" + _UNIT_AFTER + ")", re.I)
    prev = None
    while prev != text:
        prev, text = text, rx.sub(r"\1 ", text)
    # liczba oddzielona od jednostki samymi łamaniami wiersza – jedna spacja
    return re.sub(r"(\d)[ \t\xa0]*\n\s*(?=(?:RLM|zł|PLN|mln|tys\.?|km|m3|m³)\b)", r"\1 ", text, flags=re.I)


def _broken_pdf_text(text: str) -> bool:
    lines = [line for line in text.split("\n") if line.strip()]
    return len(lines) > 20 and sum(len(line.split()) <= 1 for line in lines) / len(lines) > 0.6


def text_from_file(filename: str, content: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        if _broken_pdf_text(text):
            # PDF z Google Docs / Worda: pypdf zwraca jedno słowo na wiersz („URZĄD\n \nGMINY”) – tryb układu
            # odtwarza wiersze; wielokrotne spacje (wyrównanie kolumn) zastępujemy jedną.
            text = "\n".join(re.sub(r"[ \t]{2,}", " ", page.extract_text(extraction_mode="layout") or "")
                             for page in reader.pages)
            text = "\n".join(line.strip() for line in text.split("\n"))
        text = clean_pdf_text(text)
        if not text.strip():
            raise ValueError("PDF nie ma warstwy tekstowej (skan) – OCR nie jest obsługiwany. Wklej opis jako tekst.")
        return text
    if name.endswith(".docx"):
        xml = zipfile.ZipFile(io.BytesIO(content)).read("word/document.xml").decode("utf-8")
        paras = []
        for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
            p = re.sub(r"<w:(?:tab|br|cr)\b[^>]*/>", "<w:t> </w:t>", p)
            t = html.unescape("".join(re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", p)))
            if t.strip():
                paras.append(t)
        return "\n".join(paras)
    if name.endswith(".txt"):
        return content.decode("utf-8", errors="replace")
    raise ValueError("Obsługiwane formaty: PDF z warstwą tekstową, DOCX, TXT")


# ================================================================ cechy
def _snip(text, m, width=70):
    a, b = max(0, m.start() - width), min(len(text), m.end() + width)
    return ("…" if a else "") + re.sub(r"\s+", " ", text[a:b]).strip() + ("…" if b < len(text) else "")


def _num(s):
    """Liczba z tekstu („1 200”, „1\xa0200,5”). Odstępy tysięcy to spacje; łamanie wiersza z PDF też usuwamy."""
    return float(re.sub(r"\s+", "", s).replace(",", "."))


NUMBER = r"(?<![\d.,])(?:\d{1,3}(?:[ \xa0]\d{3})+|\d+)(?:[.,]\d+)?"
PLN = r"PLN|zł(?:ot(?:y|e|ych|ego))?"
FOREIGN = (r"EUR|euro|USD|GBP|CHF|CZK|JPY|CAD|AUD|SEK|NOK|DKK|UAH|dolar\w*|funt\w*|frank\w*"
           r"|(?-i:[A-Z]{3})(?!\s*[/\d])")
AMOUNT = (r"(?P<amount>" + NUMBER + r")"
          r"(?:\s*(?P<unit>mln\.?|milion\w*|tys\.?|tysiąc\w*|tysięc\w*)(?!\w))?"
          r"(?:\s*(?P<currency>(?:" + PLN + "|" + FOREIGN + r")(?!\w)|[€$£¥]))?"
          r"(?:\s+(?P<tax>netto|brutto)\b)?")
BUDGET = re.compile(
    r"\b(?P<head>(?:budżet\w*|kwot\w*|wynagrodzeni\w*|(?:całkowit\w*\s+)?(?:koszt\w*|wartoś\w*)(?:\s+całkowit\w*)?)"
    # do 7 słów między słowem kluczowym a kwotą: „Koszt robót dodatkowych ustala się na kwotę: 151 481,54 zł”
    r"(?:(?:[ \t\xa0]*\n[ \t\xa0]*|[ \t\xa0]+)(?:ok\.|[^\s.;!?:,\d()]+)){0,7}?)"
    r"\s*[:=–-]?\s*(?:od\s+)?" + AMOUNT, re.I)
# Kwoty, które nie są budżetem inwestycji (dofinansowanie, kary, zabezpieczenia…).
NOT_BUDGET = re.compile(r"dofinansow|dotacj|wkład|dopłat|kar[ayę]?\b|kar\s|wadi|zabezpiecz|zaliczk|pożyczk|kredyt|odsetk"
                        r"|podatk|vat\b|limit|próg|progu|ogłoszon|unijn", re.I)
# Kwoty zmian umowy: koszt robót dodatkowych / zamiennych, zwiększenie wynagrodzenia, aneks.
EXTRA_COST = re.compile(r"dodatkow|zamienn|uzupełniając|nieprzewidzian|zwiększ|zmian|aneks", re.I)
DATE = r"(?P<{0}>\d{{1,2}})[./-](?P<{1}>\d{{1,2}})[./-](?P<{2}>\d{{4}})"
OLD_DEADLINE = re.compile(r"\b(?:dotychczasow\w*|pierwotn\w*|obecn\w*|umown\w*)\s+termin\w*[^\n.:]{0,80}?[:–-]?\s*"
                          + DATE.format("d", "m", "y"), re.I)
NEW_DEADLINE = re.compile(r"\b(?:now\w*|zmienion\w*|wydłużon\w*)\s+termin\w*[^\n.:]{0,80}?[:–-]?\s*"
                          + DATE.format("d", "m", "y"), re.I)
ALTERNATIVE = re.compile(r"\s*(?:lub\b|albo\b|bądź\b|do\b|[–—-])\s*" + AMOUNT, re.I)
LENGTH_UNIT = r"(?:km|mb|m)\b(?!\s*[23³²])"
LENGTH = re.compile(
    r"(?:(?:\bod\s+)?(?P<start>" + NUMBER + r")\s*(?P<start_unit>" + LENGTH_UNIT + r")?"
    r"\s*(?:do\b|[–—-])\s*)?"
    r"(?P<end>" + NUMBER + r")\s*(?P<end_unit>" + LENGTH_UNIT + r")", re.I)
CLAUSE = re.compile(r"[.!?;,\n]|\b(?:ale|lecz|jednak|natomiast)\b", re.I)
NEGATED_BEFORE = re.compile(
    r"\b(?:bez|brak|nie\s+ma|nie\s+stwierdzono|nie\s+wykazano|nie\s+występuj\w*|"
    r"nie\s+przewiduj\w*|nie\s+wymaga\b)(?:\s+\w+){0,5}\s*$", re.I)
NEGATED_AFTER = re.compile(r"^\s+(?:nie\s+występuj\w*|nie\s+stwierdzono|nie\s+jest\s+wymagan\w*)\b", re.I)


def _constraint_match(text, pattern):
    for match in re.finditer(r"(?:" + pattern + r")\w*", text, re.I):
        near = text[max(0, match.start() - 40):match.start()]
        if "„" in near and "”" not in near.rsplit("„", 1)[1]:
            continue  # wewnątrz nazwy własnej („CZYSTA RZEKA”, „Zielone Tarasy”)
        before = CLAUSE.split(text[max(0, match.start() - 100):match.start()])[-1]
        after = CLAUSE.split(text[match.end():match.end() + 100], maxsplit=1)[0]
        if not NEGATED_BEFORE.search(before) and not NEGATED_AFTER.search(after):
            return match
    return None


def _length_options(text):
    lengths, totals = [], []
    for m in LENGTH.finditer(text):
        before = text[max(0, m.start()-65):m.start()]
        if re.search(r"(?:średnic\w*|głębokoś\w*|szerokoś\w*|wysokoś\w*)\s*[:=]?\s*$", before, re.I):
            continue
        end_unit = m["end_unit"]
        bounds = [(m["end"], end_unit)]
        if m["start"]:
            bounds.insert(0, (m["start"], m["start_unit"] or end_unit))
        options = [{"value": round(_num(value) * (1 if unit.lower() == "km" else .001), 3),
                    "source": _snip(text, m, 40)} for value, unit in bounds]
        lengths.extend(options)
        if (re.search(r"(?:łącznie|razem|ogółem|(?:łączn\w*|całkowit\w*)\s+długoś\w*)"
                      r"(?:\s+(?:sieci|wynosi|to|około))*\s*[:=]?\s*$", before, re.I)
                or re.match(r"\s*,?\s*w tym\b[^.\n]{0,40}?\d", text[m.end():], re.I)):  # „5 km, w tym 3 km…”
            totals.extend(options)
    return totals or lengths


def _budget_options(text):
    options, foreign = [], []
    for first in BUDGET.finditer(text):
        # słowa kluczowe plus 3 słowa przed nimi w tym samym zdaniu („Zwiększenie wynagrodzenia o kwotę…”)
        before = re.split(r"[.;!?\n]", text[max(0, first.start() - 40):first.start()])[-1].split()[-3:]
        head = " ".join(before + [first["head"]])
        if NOT_BUDGET.search(head):
            continue
        kind = "extra" if EXTRA_COST.search(head) else "budget"
        amounts = [first]
        while following := ALTERNATIVE.match(text, amounts[-1].end()):
            amounts.append(following)
        shared_unit = next((m["unit"] for m in reversed(amounts) if m["unit"]), "")
        currencies = [m["currency"] for m in amounts if m["currency"]]
        if not shared_unit and not currencies:
            continue
        source = text[first.start():amounts[-1].end()]
        if any(not re.fullmatch(PLN, currency, re.I) for currency in currencies):
            foreign.append(source)
            continue
        heading = text[first.start():first.start("amount")]
        heading_tax = re.search(r"\b(netto|brutto)\b", heading, re.I)
        # Kwalifikator na początku dotyczy wariantów do chwili jawnej zmiany.
        tax = heading_tax[0].lower() if heading_tax else next(
            (m["tax"].lower() for m in amounts if m["tax"]), None)
        for i, m in enumerate(amounts):
            if m["tax"]:
                tax = m["tax"].lower()
            unit = m["unit"] or (shared_unit if not m["currency"] else "")
            factor = 1e6 if unit.lower().startswith(("mln", "milion")) else 1000 if unit else 1
            option = {"value": round(_num(m["amount"]) * factor, 2), "kind": kind,
                      "source": re.sub(r"\s+", " ", text[first.start():m.end()] if i else first.group()).strip()}
            if tax == "netto" and kind == "budget":
                option["note"] = "Kwota netto. Prognoza na podstawie kwot brutto wymaga podania budżetu brutto."
                option["net"] = True
            elif tax:
                option["tax"] = tax
            options.append(option)
    return options, foreign


def _target_options(text, rx):
    """Wielkość docelowa (przepustowość, RLM): pomija stan obecny i progi z warunków udziału, gdy jest wartość docelowa."""
    target, plain, existing = [], [], []
    for m in re.finditer(rx, text, re.I):
        before = text[max(0, m.start() - 90):m.start()].lower()
        option = {"value": _num(m.group(1)), "source": _snip(text, m, 40)}
        if re.search(r"powyżej|co najmniej|minimum|nie mniej niż|doświadczeni|zrealizował", before[-70:]):
            continue
        if re.search(r"docelow|zwiększ\w*[^.]{0,60}\bdo\s*$|po (rozbudowie|modernizacji)", before):
            target.append(option)
        elif re.search(r"obecn|istniejąc|aktualn|wynosząc\w*\s*$|dotychczas", before[-60:]):
            existing.append(option)
        else:
            plain.append(option)
    return target or plain or existing


_MONTHS_PL = ["stycz", "lut", "mar", "kwie", "maj", "czerw", "lip", "sierp", "wrze", "paźdz", "listop", "grud"]
_DATE_WORDS = r"(\d{1,2})\s+(" + "|".join(_MONTHS_PL) + r")\w*\s+(\d{4})"


def _duration(text):
    """Czas realizacji w miesiącach: liczba z kontekstem umowy; inaczej wyliczony z dat podpisania i zakończenia."""
    best = None
    for m in re.finditer(r"(\d+)\s*(miesi\w+|mies\.)", text, re.I):
        before, after = text[max(0, m.start() - 90):m.start()].lower(), text[m.end():m.end() + 40].lower()
        if re.search(r"ostatni\w*\s*$|gwarancj|rękojm|oczekiwani|dostaw|opóźnieni\w*\s*$", before[-50:]):
            continue
        if re.search(r"(przedłuż|wydłuż)\w*[^.]{0,60}\bo\s*(okres\s*)?$", before):
            continue  # „przedłużenie terminu o 1 miesiąc” – to zmiana terminu, nie czas realizacji
        score = (2 * bool(re.search(r"czas\w* trwania|termin\w* realizacji|realizacj|kontrakt|umow|zakończeni|robót|harmonogram", before))
                 + bool(re.search(r"od (dnia )?(zawarcia|podpisania)", after)) + bool(re.search(r"\(\s*$", before)))
        if best is None or score > best[0]:
            best = (score, m)
    if best:
        return {"value": int(best[1].group(1)), "source": _snip(text, best[1], 50)}
    sign = re.search(r"podpisani\w* umowy[^.\n]{0,20}?:?\s*" + _DATE_WORDS, text, re.I)
    end = None
    for end in re.finditer(r"(?:zakończeni\w*|odbi[oó]r\w* końcow\w*)[^\n]{0,80}?(?:do\s+)?" + _DATE_WORDS, text, re.I):
        pass
    if sign and end:
        a = date(int(sign.group(3)), next(i for i, p in enumerate(_MONTHS_PL, 1) if sign.group(2).lower().startswith(p)), int(sign.group(1)))
        b = date(int(end.group(3)), next(i for i, p in enumerate(_MONTHS_PL, 1) if end.group(2).lower().startswith(p)), int(end.group(1)))
        months = round((b - a).days / 30.44)
        if months > 0:
            return {"value": months, "source": _snip(text, sign, 30) + " … " + _snip(text, end, 30), "assumed": True}
    return None


def _deadline_change(text):
    """Zmiana terminu umowy: „Dotychczasowy termin…: 30.10.2025”, „Proponowany nowy termin…: 05.12.2025”."""
    from datetime import date
    old, new = OLD_DEADLINE.search(text), NEW_DEADLINE.search(text)
    if not (old and new):
        m = re.search(r"(?:przedłuż|wydłuż)\w*\s+termin\w*[^.]{0,80}?\bo\s+(?:okres\s+)?(\d+)\s*(miesi\w*|dni|tygodni\w*)", text, re.I)
        if not m:
            return None
        n, unit = int(m.group(1)), m.group(2).lower()
        days = n * (30 if unit.startswith("miesi") else 7 if unit.startswith("tyg") else 1)
        return {"value": f"przedłużenie o {n} {unit} (ok. {days:+d} dni)", "days": days, "source": _snip(text, m, 30)}
    try:
        a, b = (date(int(m["y"]), int(m["m"]), int(m["d"])) for m in (old, new))
    except ValueError:
        return None
    days = (b - a).days
    return {"value": f"{a:%d.%m.%Y} → {b:%d.%m.%Y} ({days:+d} dni)", "days": days,
            "source": re.sub(r"\s+", " ", old.group()) + " · " + re.sub(r"\s+", " ", new.group())}


def _main_network(text, options, main):
    """Długości innej sieci (np. „600 m sieci kanalizacji” przy wodociągu, zakres opcjonalny) nie są długością głównej sieci."""
    if not main or len(options) < 2:
        return options
    rx = dict(SUBSECTORS)
    keep = []
    for o in options:
        at = text.find(o["source"].strip("…")[:30]) if o.get("source") else -1
        ctx = o.get("source", "") if at < 0 else text[max(0, at - 40):at + len(o["source"]) + 10]
        other = any(re.search(r, ctx, re.I) for name, r in SUBSECTORS if name != main["value"])
        own = re.search(rx[main["value"]], ctx, re.I)
        if not (other and not own) and not re.search(r"opcjonaln", ctx, re.I):
            keep.append(o)
    return keep or options


def _resolve(options, key, choices, conflicts):
    values = {option["value"] for option in options}
    if len(values) <= 1:
        return options[0] if options else None
    for option in options:
        if option["value"] == choices.get(key):
            return dict(option, selected=True, rejected=[o for o in options if o["value"] != option["value"]])
    conflicts[key] = options
    return None


def extract_features(text: str, choices=None) -> dict:
    """Cechy inwestycji z opisu; każda z fragmentem źródłowym (albo None, gdy brak danych)."""
    t = text or ""
    f = {"conflicts": {}}
    choices = choices or {}
    hits = []
    for name, rx in SUBSECTORS:
        ms = [m for m in re.finditer(rx, t, re.I)
              if not re.search(r"kolizj\w*\s+z\s+(?:\w+\s+){0,2}$", t[max(0, m.start() - 40):m.start()], re.I)]
        if ms:
            hits.append((len(ms), ms[0].start(), name, _snip(t, ms[0])))
    hits.sort(key=lambda h: (-h[0], h[1]))
    f["subsector_main"] = {"value": hits[0][2], "source": hits[0][3]} if hits else None
    f["subsector_extra"] = [{"value": h[2], "source": h[3]} for h in hits[1:]]

    mn, mm = re.search(WORK_NEW, t, re.I), re.search(WORK_MOD, t, re.I)
    if mn and mm:
        f["work_type"] = {"value": "budowa/rozbudowa + przebudowa/modernizacja", "source": _snip(t, mn)}
    elif mn or mm:
        m = mn or mm
        f["work_type"] = {"value": "budowa/rozbudowa" if mn else "przebudowa/modernizacja", "source": _snip(t, m)}
    else:
        f["work_type"] = None

    m = re.search(DESIGN_BUILD, t, re.I)
    f["formula"] = ({"value": "zaprojektuj i wybuduj", "source": _snip(t, m)} if m else
                    {"value": "wybuduj (wg dokumentacji zamawiającego)", "source": None, "assumed": True}
                    if re.search(r"projekt\w* budowlan|dokumentacj\w* projektow\w* zamawiając|na podstawie projektu", t, re.I) else None)

    scale = {}
    length = _resolve(_main_network(t, _length_options(t), f["subsector_main"]), "length_km", choices, f["conflicts"])
    if length:
        scale["length_km"] = length
    for key, rx, unit in [("rlm", r"(" + NUMBER + r")\s*RLM", "RLM"), ("flow_m3d", r"(" + NUMBER + r")\s*m\s*[3³]\s*/\s*(d|dob)", "m³/d")]:
        value = _resolve(_target_options(t, rx), key, choices, f["conflicts"])
        if value:
            scale[key] = dict(value, unit=unit)
    for key, rx, unit in [("connections", r"(\d+)\s*(przyłącz|przykanalik)|przyłącz\w*(?:[^.\n\d]|ok\.){0,40}?(\d+)\s*szt", "szt."),
                          ("buildings", r"(\d+)\s*(?:\w+\s+)?(budynk|gospodarstw|nieruchomoś|dom(?:ów|y)\b)", "szt.")]:
        ms = list(re.finditer(rx, t, re.I))
        # stan istniejący przed planami („35 istniejących domów” zamiast „deklaruje budowę 40 domów”)
        m = next((x for x in ms if re.search(r"istniejąc|zamieszkan", x.group(), re.I)), ms[0] if ms else None)
        if m:
            scale[key] = {"value": _num(next(g for g in m.groups() if g and g[0].isdigit())), "unit": unit, "source": _snip(t, m, 40)}
    f["scale"] = scale

    all_amounts, foreign_budgets = _budget_options(t)
    budget_options = [o for o in all_amounts if o["kind"] == "budget"]
    f["budget_pln"] = _resolve(budget_options, "budget_pln", choices, f["conflicts"]) if not foreign_budgets else None
    extra, seen = [], set()
    for o in all_amounts:
        if o["kind"] == "extra" and o["value"] not in seen:
            seen.add(o["value"])
            extra.append(o)
    f["extra_costs"] = extra
    f["deadline_change"] = _deadline_change(t)
    if foreign_budgets:
        f["budget_note"] = "Budżet w obcej walucie. Do prognozy podaj kwotę w PLN. Źródło: " + ", ".join(foreign_budgets)
    f["duration_months"] = _duration(t)
    m = re.search(r"wynagrodzeni\w*\s+(ryczałtow|kosztorysow)\w*|(ryczałt|kosztorys)\w*\s+wynagrodzeni", t, re.I)
    f["remuneration"] = ({"value": "ryczałtowe" if (m.group(1) or m.group(2)).lower().startswith("rycz") else "kosztorysowe",
                          "source": _snip(t, m, 40)} if m else None)

    f["constraints"] = []
    for name, rx in CONSTRAINTS:
        m = _constraint_match(t, rx)
        if m:
            f["constraints"].append({"value": name, "source": _snip(t, m, 50)})
    return f


# ================================================================ profile przypadków z bazy
def _months(a, b):
    try:
        d1, d2 = date.fromisoformat(a), date.fromisoformat(b)
        return round((d2 - d1).days / 30.44, 1)
    except (TypeError, ValueError):
        return None


def case_profiles(con) -> list:
    out = []
    for p in con.execute("SELECT * FROM project ORDER BY project_id"):
        p = dict(p)
        if (p.get("status") or "").strip().casefold() not in {"zakończone", "zakończony", "zakończona"}:
            continue
        link = con.execute("SELECT * FROM active_project_link WHERE project_id=? AND status='potwierdzone' ORDER BY id", (p["project_id"],)).fetchone()
        texts, desc_src = [p["name"]], None
        if not link:
            continue
        for n in con.execute("SELECT notice_number, notice_type, fields_json FROM notice WHERE ocid=? "
                                 "AND notice_type IN ('ContractNotice','TenderResultNotice','ContractPerformingNotice') "
                                 "ORDER BY notice_type='ContractNotice' DESC, publication_date", (link["ocid"],)):
            d = P.find(json.loads(n["fields_json"] or "[]"), r"^Krótki opis przedmiotu")
            if d and d["value"]:
                texts.append(d["value"])
                desc_src = n["notice_number"]
                break
        m = re.search(r"Opis:\s*„(.+)”", p.get("annotation") or "", re.S)
        if m:
            texts.append(m.group(1))
        text = "\n".join(texts)
        feats = extract_features(text)
        contracts = [dict(c) for c in con.execute(
            "SELECT c.* FROM contract c JOIN active_project_link l ON l.ocid=c.ocid AND (l.part_no=0 OR l.part_no=c.part_no) "
            "WHERE l.project_id=? AND l.status='potwierdzone' ORDER BY c.part_no", (p["project_id"],))]
        if not contracts or not all(c["performing_notice"] and c["actual_end"] for c in contracts):
            continue
        value = sum(c["value"] for c in contracts) if all(c["value"] for c in contracts) else None
        paid = sum(c["paid_total"] or 0 for c in contracts) if contracts and all(c["paid_total"] is not None for c in contracts) else None
        planned = [_months(c["signed_date"], c["planned_end"]) for c in contracts]
        delays = [(date.fromisoformat(c["actual_end"]) - date.fromisoformat(c["planned_end"])).days
                  for c in contracts if c["actual_end"] and c["planned_end"]]
        evs = [dict(e) for e in con.execute(
            "SELECT id, title, expert_title, status, event_date, source_notice, source_url, source_section, quote, "
            "exemplar FROM visible_event WHERE project_id=? AND kind='propozycja' AND status<>'odrzucone' "
            "AND (ocid IS NULL OR ocid IN (SELECT ocid FROM project_link WHERE project_id=? AND status='potwierdzone'))",
            (p["project_id"], p["project_id"]))]
        risk_hits = {}
        for e in evs:
            code = (e["expert_title"] or e["title"]).split()[0]
            # przykład wzorcowy (oznaczony przez eksperta) > zatwierdzone > propozycja
            w = 1.5 if e.get("exemplar") else 1.0 if e["status"] in ("zaakceptowane", "poprawione") else 0.5
            r = risk_hits.setdefault(code, {"weight": 0, "confirmed": False, "evidence": []})
            r["weight"] = max(r["weight"], w)
            r["confirmed"] = r["confirmed"] or w >= 1.0
            r["evidence"].append(e)
        out.append({
            "project_id": p["project_id"], "name": p["name"], "recipient": p["recipient_name"],
            "link_status": link["status"] if link else None, "ocid": link["ocid"] if link else None,
            "text": text, "description_source": desc_src or ("arkusz (adnotacja KPO)" if m else "nazwa przedsięwzięcia"),
            "features": feats, "n_contracts": len(contracts),
            "contract_value": value, "paid_total": paid,
            "growth_pct": round((paid / value - 1) * 100, 1) if value and paid is not None else None,
            "planned_months": round(sum(x for x in planned if x) / len([x for x in planned if x]), 1) if any(planned) else None,
            "delay_days": max(delays) if delays else None, "risks": risk_hits,
            "n_offers": next((f["value_num"] for f in con.execute(
                "SELECT value_num FROM visible_fact WHERE project_id=? AND key='liczba_ofert' "
                "AND ocid IN (SELECT ocid FROM project_link WHERE project_id=? AND status='potwierdzone')",
                (p["project_id"], p["project_id"]))), None),
        })
    return out


# ================================================================ podobieństwo
STOP = {"w", "i", "na", "z", "ze", "do", "oraz", "wraz", "dla", "pn", "o", "od", "po", "przy", "się", "jest", "będzie",
        "terenie", "gminy", "gmina", "gminie", "miejscowości", "zadania", "zamówienia", "przedmiotem", "ramach", "wykonanie"}


def _stems(text):
    return {w[:6] for w in re.findall(r"[a-ząćęłńóśźż]{4,}", (text or "").lower()) if w not in STOP}


def _ratio(a, b):
    return min(a, b) / max(a, b) if a and b else None


def compare(new: dict, case: dict, new_text: str):
    """Porównanie cech o równej wadze (treść zadania: „łączyć dane strukturalne z treścią opisów
    i wyjaśniać, które cechy przesądziły o podobieństwie”). Każda cecha: pasuje / częściowo / różni się /
    brak danych. Zwraca (wynik %, cechy, czy ten sam podsektor główny, podobieństwo opisu)."""
    cf, feats = case["features"], []

    def add(name, status, detail):
        feats.append({"name": name, "status": status, "detail": detail})

    def val(d, key):
        return (d.get(key) or {}).get("value")

    nm, cm = val(new, "subsector_main"), val(cf, "subsector_main")
    case_all = ({cm} if cm else set()) | {x["value"] for x in cf.get("subsector_extra", [])}
    if nm and cm:
        add("Podsektor główny", "pasuje" if nm == cm else "częściowo" if nm in case_all else "różni się",
            nm if nm == cm else f"nowy: {nm}; przypadek: {cm}" + (" (u nas jako dodatkowy)" if nm in case_all else ""))
    else:
        add("Podsektor główny", "brak danych", f"nowy: {nm or '—'}; przypadek: {cm or '—'}")

    ne = {x["value"] for x in new.get("subsector_extra", [])}
    if ne:
        common = ne & case_all
        add("Podsektory dodatkowe", "pasuje" if common == ne else "częściowo" if common else "różni się",
            f"wspólne: {', '.join(sorted(common)) or '—'}")

    for key, label in (("work_type", "Rodzaj prac"), ("formula", "Formuła realizacji")):
        a, b = val(new, key), val(cf, key)
        if a and b:
            same = a == b or (key == "work_type" and ("+" in a or "+" in b))
            add(label, "pasuje" if same else "różni się", a if a == b else f"nowy: {a}; przypadek: {b}")
        else:
            add(label, "brak danych", f"nowy: {a or '—'}; przypadek: {b or '—'}")

    nb, cv = val(new, "budget_pln"), case["contract_value"]
    r = _ratio(nb, cv)
    if r is not None:
        add("Skala: budżet vs wartość umów", "pasuje" if r >= 0.5 else "częściowo" if r >= 0.25 else "różni się",
            f"{nb:,.0f} zł vs {cv:,.0f} zł (mniejsza to {r:.0%} większej)".replace(",", " "))
    else:
        add("Skala: budżet vs wartość umów", "brak danych", "brak budżetu w opisie" if not nb else "brak wartości umowy w przypadku")
    nl, cl = val(new.get("scale", {}), "length_km"), val(cf.get("scale", {}), "length_km")
    r = _ratio(nl, cl)
    if r is not None:
        add("Skala: długość sieci", "pasuje" if r >= 0.4 else "różni się", f"{nl} km vs {cl} km")
    elif nl or cl:
        add("Skala: długość sieci", "brak danych", f"nowy: {nl or '—'} km; przypadek: {cl or '—'} km")

    a, b = _stems(new_text), _stems(case["text"])
    jac = len(a & b) / len(a | b) if a and b else 0
    add("Treść opisu", "pasuje" if jac >= 0.15 else "częściowo" if jac >= 0.07 else "różni się",
        f"wspólne rdzenie słów: {len(a & b)} (Jaccard {jac:.2f})")

    nc, cc = {x["value"] for x in new.get("constraints", [])}, {x["value"] for x in cf.get("constraints", [])}
    if nc:
        common = nc & cc
        add("Znane ograniczenia", "pasuje" if common == nc else "częściowo" if common else "różni się",
            f"wspólne: {', '.join(sorted(common)) or '—'}")

    checked = [f for f in feats if f["status"] != "brak danych"]
    got = sum(1 if f["status"] == "pasuje" else 0.5 if f["status"] == "częściowo" else 0 for f in checked)
    score = round(100 * got / len(checked)) if checked else 0
    return score, feats, (nm is not None and nm == cm), jac


# ================================================================ raport
def _stat(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return {"n": 0}
    s = {"n": len(vals), "values": vals}
    if len(vals) >= 3:
        s.update(min=min(vals), max=max(vals), median=round(statistics.median(vals), 1))
    return s


def _sectors(features):
    sectors = features["subsector_extra"] + ([features["subsector_main"]] if features["subsector_main"] else [])
    return {sector["value"] for sector in sectors}


def merge_model(f, res, choices):
    """Dokłada do cech z reguł wynik modelu (llm_extract.verify). Reguły mają pierwszeństwo; inna wartość modelu
    nie nadpisuje reguły, tylko trafia do wyboru eksperta (konflikt)."""
    choices = choices or {}
    fields = res.get("fields", {})

    def opt(value, item, **extra):
        return {"value": value, "source": item["cytat"], "origin": "model", **extra}

    def numeric(key, model_option, get, put):
        current = get()
        if key in f["conflicts"]:
            if all(abs(o["value"] - model_option["value"]) > 1e-6 for o in f["conflicts"][key]):
                f["conflicts"][key].append(model_option)
            for o in f["conflicts"][key]:
                if abs(o["value"] - model_option["value"]) <= 1e-6:
                    o["model_pick"] = True
            return
        if current is None:
            put(model_option)
        elif abs(current["value"] - model_option["value"]) > 0.01 * max(1.0, abs(current["value"])):
            options = [current, dict(model_option, model_pick=True)]
            picked = next((o for o in options if o["value"] == choices.get(key)), None)
            if picked:
                put(dict(picked, selected=True, rejected=[o for o in options if o is not picked]))
            else:
                f["conflicts"][key] = options
                put(None)
        else:
            current["model_confirmed"] = True

    if "budzet" in fields:
        item = fields["budzet"]
        o = opt(round(float(item["kwota_zl"]), 2), item)
        if item.get("vat") == "netto":
            o.update(net=True, note="Kwota netto. Prognoza na podstawie kwot brutto wymaga podania budżetu brutto.")
        numeric("budget_pln", o, lambda: f.get("budget_pln"), lambda v: f.__setitem__("budget_pln", v))
    for model_key, key, unit in (("dlugosc_sieci_km", "length_km", "km"), ("rlm", "rlm", "RLM"),
                                 ("przepustowosc_m3d", "flow_m3d", "m³/d"), ("przylacza_szt", "connections", "szt."),
                                 ("odbiorcy", "recipients", "os.")):
        if model_key in fields:
            item = fields[model_key]
            numeric(key, opt(float(item["wartosc"]), item, unit=unit), lambda k=key: f["scale"].get(k),
                    lambda v, k=key: f["scale"].__setitem__(k, v) if v else f["scale"].pop(k, None))
    if "czas_realizacji_mies" in fields:
        item = fields["czas_realizacji_mies"]
        numeric("duration_months", opt(round(float(item["wartosc"])), item), lambda: f.get("duration_months"),
                lambda v: f.__setitem__("duration_months", v))
    for model_key, key in (("podsektor_glowny", "subsector_main"), ("rodzaj_prac", "work_type"), ("formula", "formula"),
                           ("wynagrodzenie", "remuneration")):
        if model_key not in fields:
            continue
        item, current = fields[model_key], f.get(key)
        if current is None or current.get("assumed"):
            f[key] = opt(item["wartosc"], item)
        elif current["value"] != item["wartosc"]:
            f.setdefault("model_notes", []).append(
                f"{key.replace('_', ' ')}: reguły – {current['value']}, model – {item['wartosc']} („{item['cytat']}”)")
    if "koszt_zmiany_umowy" in fields:
        item = fields["koszt_zmiany_umowy"]
        v = round(float(item["kwota_zl"]), 2)
        if all(abs(o["value"] - v) > 0.01 for o in f["extra_costs"]):
            tax = item.get("vat") if item.get("vat") in ("brutto", "netto") else None
            f["extra_costs"].append(opt(v, item, kind="extra", **({"tax": tax} if tax else {})))
    if "zmiana_terminu" in fields and not f.get("deadline_change"):
        item = fields["zmiana_terminu"]
        days = int(item.get("dni") or 0)
        f["deadline_change"] = opt(f"{item.get('opis', '').strip()} ({days:+d} dni)" if days else item.get("opis", ""),
                                   item, days=days)
    have = {c["value"] for c in f["constraints"]}
    for item in res.get("ograniczenia", []):
        if item["kategoria"] not in have:
            have.add(item["kategoria"])
            f["constraints"].append(opt(item["kategoria"], item))
    f["model_findings"] = {"inconsistencies": res.get("sprzecznosci", []), "gaps": res.get("braki", []),
                           "rejected": res.get("rejected", [])}
    return f


def analyze(con, text: str, top_k: int = 5, min_score: float = 50.0, choices=None, use_llm: bool = False) -> dict:
    feats = extract_features(text, choices)
    llm_info = None
    if use_llm:
        from . import llm, llm_extract  # import tutaj: llm_extract korzysta z tego modułu
        try:
            res = llm_extract.extract(con, text)
            merge_model(feats, res, choices)
            llm_info = {k: res.get(k) for k in ("model", "seconds", "cached", "truncated")}
            llm_info["rejected"] = len(res.get("rejected", []))
        except llm.ModelError as exc:
            llm_info = {"error": str(exc)}
    if choices:
        # wybory eksperta w konfliktach uczą model na kolejnych dokumentach (llm_extract.expert_hints)
        from . import llm_extract
        picked = [("budget_pln", feats.get("budget_pln")), ("duration_months", feats.get("duration_months"))]
        picked += list(feats["scale"].items())
        for key, option in picked:
            if option and option.get("selected") and option.get("rejected"):
                llm_extract.record_choice(con, key, option, option["rejected"])
    sectors = _sectors(feats)
    cases = case_profiles(con) if sectors else []
    ranked = []
    for c in cases:
        if not (sectors & _sectors(c["features"])):
            continue
        score, fs, same_sub, jac = compare(feats, c, text)
        ranked.append((score, c, fs, same_sub, jac))
    # kolejność: ten sam podsektor główny, potem odsetek pasujących cech, potem podobieństwo treści
    ranked.sort(key=lambda x: (-x[3], -x[0], -x[4]))
    chosen = [x[:3] for x in ranked if x[0] >= min_score][:top_k]

    similar = []
    for score, c, fs in chosen:
        similar.append({
            "project_id": c["project_id"], "name": c["name"], "recipient": c["recipient"], "score": score,
            "link_status": c["link_status"], "description_source": c["description_source"],
            "matched": sum(f["status"] == "pasuje" for f in fs),
            "partial": sum(f["status"] == "częściowo" for f in fs),
            "checked": sum(f["status"] != "brak danych" for f in fs),
            "matches": [f for f in fs if f["status"] == "pasuje"],
            "differences": [f for f in fs if f["status"] in ("różni się", "częściowo")],
            "missing": [f for f in fs if f["status"] == "brak danych"],
            "features": fs,
            "contract_value": c["contract_value"], "paid_total": c["paid_total"], "growth_pct": c["growth_pct"],
            "planned_months": c["planned_months"], "delay_days": c["delay_days"], "n_offers": c["n_offers"],
            "risks": sorted(c["risks"].keys()),
        })

    # koszty i terminy
    growth = _stat([s["growth_pct"] for s in similar])
    delay = _stat([s["delay_days"] for s in similar])
    planned = _stat([s["planned_months"] for s in similar])
    comparison = {"growth_pct": growth, "delay_days": delay, "planned_months": planned, "notes": []}
    if feats.get("budget_note"):
        comparison["notes"].append(feats["budget_note"])
    if (feats.get("budget_pln") or {}).get("net"):
        comparison["notes"].append(feats["budget_pln"]["note"])
    for item in (feats.get("model_findings") or {}).get("inconsistencies", []):
        comparison["notes"].append(f"Sprzeczność w dokumencie (model): {item['opis']} – „{item['cytat']}”.")
    for note in feats.get("model_notes", []):
        comparison["notes"].append("Model odczytał inaczej niż reguły – " + note)
    if feats.get("extra_costs") or feats.get("deadline_change"):
        comparison["notes"].append(
            "Dokument opisuje zmianę umowy w toku (np. protokół konieczności, aneks): "
            + "; ".join([f"koszt zmiany {o['value']:,.2f}".replace(",", " ").replace(".", ",") + " zł" + (f" {o['tax']}" if o.get("tax") else "")
                         for o in feats.get("extra_costs", [])]
                        + ([f"przesunięcie terminu {feats['deadline_change']['value']}"] if feats.get("deadline_change") else []))
            + ". To nie jest budżet całej inwestycji – do prognozy podaj wartość umowy lub budżet zadania.")
    if not similar:
        comparison["notes"].append("Brak porównywalnych zakończonych inwestycji z potwierdzonym powiązaniem "
                                   "i wystarczającą zgodnością cech.")
    for key, label in (("growth_pct", "wzrostu wypłaty"), ("delay_days", "opóźnienia")):
        st = comparison[key]
        if st["n"] < 3:
            comparison["notes"].append(
                f"Przedział {label} wymaga co najmniej 3 przypadków z ogłoszeniem o wykonaniu umowy; jest {st['n']}. "
                "Pokazujemy wartości per przypadek. Do wyliczenia przedziału potrzeba ogłoszeń o wykonaniu umowy "
                "dla kolejnych podobnych przypadków.")
    # poziom pewności prognozy (treść zadania: „prognoza powinna pokazywać poziom pewności”)
    n = min(growth["n"], delay["n"])
    main = (feats.get("subsector_main") or {}).get("value")
    same = sum(1 for s in similar if any(f["name"] == "Podsektor główny" and f["status"] == "pasuje" for f in s["features"]))
    level = "wysoka" if n >= 5 and same == len(similar) else "średnia" if n >= 3 and same >= 2 else "niska"
    comparison["confidence"] = {
        "level": level,
        "basis": f"próba n = {n} przypadków z ogłoszeniem o wykonaniu; {same} z {len(similar)} ma ten sam podsektor główny"
                 + (f" ({main})" if main else "") + ". Wysoka: n ≥ 5 i wszystkie z tego samego podsektora; średnia: n ≥ 3 "
                 "i co najmniej 2 z tego samego podsektora; niska: pozostałe."}
    low = [s["project_id"] for s in similar if s["growth_pct"] is not None and s["growth_pct"] < -10]
    if low:
        comparison["notes"].append(
            f"Wypłata wyraźnie niższa niż wartość umowy w: {', '.join(low)}. To zwykle nie oszczędność, tylko ograniczenie "
            "zakresu, kary albo nienależyte wykonanie – sprawdź kartę przypadku przed użyciem tej wartości do budżetu.")
    if not similar or feats["conflicts"]:
        comparison["confidence"] = None
    if feats.get("budget_pln") and not feats["budget_pln"].get("net") and growth["n"] >= 3 and not feats["conflicts"]:
        b = feats["budget_pln"]["value"]
        ref = growth["median"]
        comparison["budget_after_growth"] = {
            "value": round(b * (1 + ref / 100), 2), "basis": f"budżet × (1 + {ref}% – mediana wzrostu w podobnych przypadkach)"}

    # flagi ryzyk: z podobnych przypadków (ważone decyzją eksperta) + z ograniczeń w opisie
    flags = {}
    for score, c, _ in chosen:
        for code, r in c["risks"].items():
            fl = flags.setdefault(code, {"code": code, "name": risks.NAMES.get(code, code), "cases": [], "weight": 0.0,
                                         "confirmed_cases": 0, "evidence": [], "from_description": []})
            fl["cases"].append(c["project_id"])
            fl["weight"] += r["weight"] * score / 100
            fl["confirmed_cases"] += int(r["confirmed"])
            for e in r["evidence"][:2]:
                fl["evidence"].append({"project_id": c["project_id"], "event_id": e["id"], "status": e["status"],
                                       "date": e["event_date"], "source_notice": e["source_notice"],
                                       "source_url": e["source_url"], "source_section": e["source_section"],
                                       "quote": e["quote"]})
    for cst in feats.get("constraints", []):
        code = CONSTRAINT_RISK.get(cst["value"])
        if code:
            fl = flags.setdefault(code, {"code": code, "name": risks.NAMES.get(code, code), "cases": [], "weight": 0.0,
                                         "confirmed_cases": 0, "evidence": [], "from_description": []})
            fl["from_description"].append(cst)
            fl["weight"] += 0.3
    for fl in flags.values():
        fl["weight"] = round(fl["weight"], 2)
        fl["strength"] = ("silna" if fl["confirmed_cases"] and (fl["from_description"] or len(fl["cases"]) >= 2)
                          else "średnia" if fl["confirmed_cases"] or len(fl["cases"]) >= 2 or fl["from_description"]
                          else "słaba")
    # najpierw siła sygnału (potwierdzenie eksperta + opis), potem waga
    order = {"silna": 0, "średnia": 1, "słaba": 2}
    flag_list = sorted(flags.values(), key=lambda f: (order[f["strength"]], -f["weight"]))
    for fl in flag_list:
        action, clause = ACTIONS.get(fl["code"], ("", ""))
        fl["action"], fl["clause"] = action, clause
        fl["basis"] = (
            (f"{len(fl['cases'])} z {len(similar)} podobnych przypadków ({', '.join(fl['cases'])})"
             + (f", w tym {fl['confirmed_cases']} potwierdzone przez eksperta" if fl["confirmed_cases"] else ", tylko propozycje")
             if fl["cases"] else "")
            + ("; " if fl["cases"] and fl["from_description"] else "")
            + ("sygnał w opisie nowej inwestycji: " + ", ".join(c["value"] for c in fl["from_description"])
               if fl["from_description"] else ""))

    checklist = None
    main = (feats.get("subsector_main") or {}).get("value")
    if main == "Sieć wodociągowa" or any(x["value"] == "Sieć wodociągowa" for x in feats.get("subsector_extra", [])):
        checklist = []
        for item, ref, rx in WATER_CHECKLIST:
            m = re.search(rx, text, re.I)
            checklist.append({"item": item, "ref": ref, "status": "jest w opisie" if m else "brak w opisie",
                              "source": _snip(text, m, 50) if m else None})

    missing_inputs = [label for key, label in (("subsector_main", "podsektor"), ("work_type", "rodzaj prac"),
                                               ("formula", "formuła realizacji"), ("budget_pln", "budżet"),
                                               ("duration_months", "termin realizacji")) if not feats.get(key)]
    if not feats.get("scale"):
        missing_inputs.append("skala (długość sieci, RLM, przepustowość, liczba przyłączy)")
    return {"input_text": text, "choices": choices or {}, "features": feats, "llm": llm_info, "missing_inputs": missing_inputs, "similar": similar,
            "n_candidates": len(ranked), "comparison": comparison, "flags": flag_list, "water_checklist": checklist}


def to_csv(result: dict) -> str:
    import csv
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["project_id", "nazwa", "cechy_pasujace_proc", "pasuje", "rozni_sie", "brak_danych", "wartosc_umow_pln",
                "wyplacono_pln", "wzrost_wyplaty_pct", "termin_planowany_mies", "opoznienie_dni", "liczba_ofert",
                "ryzyka", "status_powiazania"])
    for s in result["similar"]:
        w.writerow([s["project_id"], s["name"], s["score"], " | ".join(f["name"] for f in s["matches"]),
                    " | ".join(f"{f['name']}: {f['detail']}" for f in s["differences"]),
                    " | ".join(f["name"] for f in s["missing"]), s["contract_value"], s["paid_total"], s["growth_pct"],
                    s["planned_months"], s["delay_days"], s["n_offers"], " ".join(s["risks"]), s["link_status"]])
    w.writerow([])
    w.writerow(["ryzyko", "nazwa", "sila", "podstawa", "dzialanie", "zapis_do_sprawdzenia"])
    for f in result["flags"]:
        w.writerow([f["code"], f["name"], f["strength"], f["basis"], f["action"], f["clause"]])
    return buf.getvalue()
