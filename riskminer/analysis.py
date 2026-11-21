"""Analiza nowej inwestycji: cechy z opisu → podobne przypadki z bazy → koszty, terminy, ryzyka, rekomendacje.

Zasady (z materiału eksperckiego organizatora):
- każda cecha i każdy wniosek wskazuje źródło (fragment opisu albo ogłoszenie/zdarzenie z bazy),
- przy małej próbie pokazujemy wartości per przypadek i mówimy, czego brakuje do przedziału,
- kwota projektu ≠ kwota umowy; porównujemy wielkości tego samego rodzaju,
- wiedza zatwierdzona przez eksperta (zaakceptowane/poprawione ryzyka) waży więcej niż propozycje,
  a odrzucone propozycje nie są brane pod uwagę.
"""
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
    ("Kanalizacja sanitarna", r"kanalizac\w*\s+sanitarn|kanalizacj\w*(?!\s+deszcz)|przepompowni\w* ście|kanał\w* (sanitarn|grawitacyjn|tłoczn)|przewod\w* tłoczn|tłoczn\w* kanaliz"),
    ("Sieć wodociągowa", r"sie(ć|ci)\s+wodociąg|wodociąg|przyłącz\w* wod|magistral\w* wod"),
    ("Uzdatnianie i zaopatrzenie w wodę", r"uzdatniani\w* wody|\bSUW\b|stacj\w* uzdatniania|ujęci\w* wody|studni\w* głębin|zbiornik\w* wody czystej|hydrofor"),
    ("Kanalizacja deszczowa i retencja", r"kanalizac\w*\s+deszcz|wód opadowych|retencj|odwodnieni|zbiornik\w* retencyjn"),
]
CONSTRAINTS = [
    ("pozwolenie wodnoprawne / odbiornik ścieków", r"pozwoleni\w* wodnoprawn|odbiornik\w*|wylot\w* (ścieków|do)|zrzut\w*|wody polskie|jezior|rzek|cieku?|potoku"),
    ("decyzja środowiskowa / ochrona przyrody", r"decyzj\w* (o )?środowiskow|natura 2000|obszar\w* chronion|ochron\w* przyrody|RDOŚ"),
    ("grunty prywatne / dostęp do terenu", r"grunt\w* prywatn|własnoś\w* prywatn|służebnoś|wejści\w* w teren|zgod\w* właściciel|prawo do dysponowania"),
    ("kolizje i istniejące uzbrojenie", r"kolizj|istniejąc\w* (uzbrojeni|sieci|infrastruktur)|uzbrojeni\w* teren"),
    ("przekroczenia: droga, kolej, ciek", r"przejści\w* (pod|przez)|przewiert|przecisk|drog\w* (krajow|wojewódzk|powiatow)|lini\w* kolejow|kolej"),
    ("istniejący obiekt w eksploatacji", r"ciągłoś\w* pracy|istniejąc\w* oczyszczal|w trakcie eksploatacji|bez przerw\w* w dostawie|rozbiórk\w* istniejąc"),
    ("azbest / stan istniejących sieci", r"azbest|cementowo-azbestow|inspekcj\w* TV|stan techniczn"),
    ("warunki gruntowo-wodne", r"geotechn|grunt\w* (słab|nienośn|organiczn)|wod\w* gruntow|odwodnieni\w* wykop"),
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
CONSTRAINT_RISK = {
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
def text_from_file(filename: str, content: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        if len(text.strip()) < 50:
            raise ValueError("PDF nie ma warstwy tekstowej (skan) – OCR nie jest obsługiwany. Wklej opis jako tekst.")
        return text
    if name.endswith(".docx"):
        xml = zipfile.ZipFile(io.BytesIO(content)).read("word/document.xml").decode("utf-8")
        paras = []
        for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
            t = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p))
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
    return float(s.replace(" ", "").replace("\xa0", "").replace(",", "."))


def extract_features(text: str) -> dict:
    """Cechy inwestycji z opisu; każda z fragmentem źródłowym (albo None, gdy brak danych)."""
    t = text or ""
    f = {}
    hits = []
    for name, rx in SUBSECTORS:
        ms = list(re.finditer(rx, t, re.I))
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
    km = [(_num(m.group(1)) * (1 if m.group(2).lower().startswith("km") else 0.001), m)
          for m in re.finditer(r"(\d[\d\s]*(?:[.,]\d+)?)\s*(km|mb|m)\b(?!\s*[23³²])", t, re.I)]
    if km:
        total = sum(v for v, _ in km)
        scale["length_km"] = {"value": round(total, 3), "source": "; ".join(_snip(t, m, 40) for _, m in km[:3])}
    for key, rx, unit in [("rlm", r"(\d[\d\s]*)\s*RLM", "RLM"), ("flow_m3d", r"(\d[\d\s]*(?:[.,]\d+)?)\s*m\s*[3³]\s*/\s*(d|dob)", "m³/d"),
                          ("connections", r"(\d+)\s*(przyłącz|przykanalik)", "szt."),
                          ("buildings", r"(\d+)\s*(budynk|gospodarstw|nieruchomoś)", "szt.")]:
        m = re.search(rx, t, re.I)
        if m:
            scale[key] = {"value": _num(m.group(1)), "unit": unit, "source": _snip(t, m, 40)}
    f["scale"] = scale

    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(mln|milion\w*)\s*(zł|pln)?", t, re.I) or \
        re.search(r"(?:budżet|wartoś\w*|kwot\w*|koszt\w*)[^.\d]{0,40}?(\d[\d\s]{4,}(?:[.,]\d{2})?)\s*(zł|pln)", t, re.I)
    if m:
        val = _num(m.group(1)) * (1e6 if (m.group(2) or "").lower().startswith(("mln", "milion")) else 1)
        f["budget_pln"] = {"value": round(val, 2), "source": _snip(t, m, 50),
                           "note": "traktowane jako kwota brutto (jak wartość umowy); szacunek netto bywa niższy o VAT"}
    else:
        f["budget_pln"] = None
    m = re.search(r"(\d+)\s*(miesi\w+|mies\.)", t, re.I)
    f["duration_months"] = {"value": int(m.group(1)), "source": _snip(t, m, 50)} if m else None

    f["constraints"] = []
    for name, rx in CONSTRAINTS:
        m = re.search(rx, t, re.I)
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
        link = con.execute("SELECT * FROM project_link WHERE project_id=? AND status<>'odrzucone'", (p["project_id"],)).fetchone()
        texts, desc_src = [p["name"]], None
        if link:
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
            "SELECT c.* FROM contract c JOIN project_link l ON l.ocid=c.ocid AND (l.part_no=0 OR l.part_no=c.part_no) "
            "WHERE l.project_id=? AND l.status<>'odrzucone' ORDER BY c.part_no", (p["project_id"],))]
        value = sum(c["value"] or 0 for c in contracts) or None
        paid = sum(c["paid_total"] or 0 for c in contracts) if contracts and all(c["paid_total"] for c in contracts) else None
        planned = [_months(c["signed_date"], c["planned_end"]) for c in contracts]
        delays = [(date.fromisoformat(c["actual_end"]) - date.fromisoformat(c["planned_end"])).days
                  for c in contracts if c["actual_end"] and c["planned_end"]]
        evs = [dict(e) for e in con.execute(
            "SELECT id, title, expert_title, status, event_date, source_notice, source_url, source_section, quote "
            "FROM event WHERE project_id=? AND kind='propozycja' AND status<>'odrzucone'", (p["project_id"],))]
        risk_hits = {}
        for e in evs:
            code = (e["expert_title"] or e["title"]).split()[0]
            w = 1.0 if e["status"] in ("zaakceptowane", "poprawione") else 0.5
            r = risk_hits.setdefault(code, {"weight": 0, "confirmed": False, "evidence": []})
            r["weight"] = max(r["weight"], w)
            r["confirmed"] = r["confirmed"] or w == 1.0
            r["evidence"].append(e)
        out.append({
            "project_id": p["project_id"], "name": p["name"], "recipient": p["recipient_name"],
            "link_status": link["status"] if link else None, "ocid": link["ocid"] if link else None,
            "text": text, "description_source": desc_src or ("arkusz (adnotacja KPO)" if m else "nazwa przedsięwzięcia"),
            "features": feats, "n_contracts": len(contracts),
            "contract_value": value, "paid_total": paid,
            "growth_pct": round((paid / value - 1) * 100, 1) if value and paid else None,
            "planned_months": round(sum(x for x in planned if x) / len([x for x in planned if x]), 1) if any(planned) else None,
            "delay_days": max(delays) if delays else None, "risks": risk_hits,
            "n_offers": next((f["value_num"] for f in con.execute(
                "SELECT value_num FROM fact WHERE project_id=? AND key='liczba_ofert'", (p["project_id"],))), None),
        })
    return out


# ================================================================ podobieństwo
STOP = {"w", "i", "na", "z", "ze", "do", "oraz", "wraz", "dla", "pn", "o", "od", "po", "przy", "się", "jest", "będzie",
        "terenie", "gminy", "gmina", "gminie", "miejscowości", "zadania", "zamówienia", "przedmiotem", "ramach", "wykonanie"}


def _stems(text):
    return {w[:6] for w in re.findall(r"[a-ząćęłńóśźż]{4,}", (text or "").lower()) if w not in STOP}


def _ratio_points(a, b, pts):
    if not a or not b:
        return None
    r = min(a, b) / max(a, b)
    return round(pts * r, 1), r


def compare(new: dict, case: dict, new_text: str):
    """Zwraca (wynik 0–100, lista cech: pasuje/różni się/brak danych)."""
    cf, feats, total, max_total = case["features"], [], 0.0, 0.0

    def add(name, status, detail, pts, mx):
        nonlocal total, max_total
        feats.append({"name": name, "status": status, "detail": detail, "points": round(pts, 1), "max": mx})
        total += pts
        if status != "brak danych":
            max_total += mx

    nm, cm = (new.get("subsector_main") or {}).get("value"), (cf.get("subsector_main") or {}).get("value")
    if nm and cm:
        all_c = {cm} | {x["value"] for x in cf["subsector_extra"]}
        if nm == cm:
            add("Podsektor główny", "pasuje", nm, 35, 35)
        elif nm in all_c:
            add("Podsektor główny", "częściowo", f"nowy: {nm}; w przypadku jako dodatkowy (główny: {cm})", 18, 35)
        else:
            add("Podsektor główny", "różni się", f"nowy: {nm}; przypadek: {cm}", 0, 35)
    else:
        add("Podsektor główny", "brak danych", f"nowy: {nm or '—'}; przypadek: {cm or '—'}", 0, 35)

    ne = {x["value"] for x in new.get("subsector_extra", [])}
    ce = {x["value"] for x in cf.get("subsector_extra", [])} | ({cm} if cm else set())
    if ne:
        common = ne & ce
        add("Podsektory dodatkowe", "pasuje" if common else "różni się",
            f"wspólne: {', '.join(sorted(common)) or '—'}", 5 * len(common) / len(ne), 5)

    nw, cw = (new.get("work_type") or {}).get("value"), (cf.get("work_type") or {}).get("value")
    if nw and cw:
        same = nw == cw or "+" in nw or "+" in cw
        add("Rodzaj prac", "pasuje" if same else "różni się", f"nowy: {nw}; przypadek: {cw}", 10 if same else 0, 10)
    else:
        add("Rodzaj prac", "brak danych", f"nowy: {nw or '—'}; przypadek: {cw or '—'}", 0, 10)

    nf, cfm = (new.get("formula") or {}).get("value"), (cf.get("formula") or {}).get("value")
    if nf and cfm:
        add("Formuła realizacji", "pasuje" if nf == cfm else "różni się", f"nowy: {nf}; przypadek: {cfm}", 15 if nf == cfm else 0, 15)
    else:
        add("Formuła realizacji", "brak danych", f"nowy: {nf or '—'}; przypadek: {cfm or '—'}", 0, 15)

    # skala: budżet vs wartość umów, długość sieci
    nb = (new.get("budget_pln") or {}).get("value")
    rp = _ratio_points(nb, case["contract_value"], 10)
    if rp:
        add("Skala: budżet vs wartość umów", "pasuje" if rp[1] >= 0.5 else "różni się",
            f"{nb:,.0f} zł vs {case['contract_value']:,.0f} zł (stosunek {rp[1]:.2f})".replace(",", " "), rp[0], 10)
    else:
        add("Skala: budżet vs wartość umów", "brak danych",
            "brak budżetu w opisie" if not nb else "brak wartości umowy w przypadku", 0, 10)
    nl = (new.get("scale", {}).get("length_km") or {}).get("value")
    cl = (cf.get("scale", {}).get("length_km") or {}).get("value")
    rp = _ratio_points(nl, cl, 5)
    if rp:
        add("Skala: długość sieci", "pasuje" if rp[1] >= 0.4 else "różni się", f"{nl} km vs {cl} km", rp[0], 5)
    elif nl or cl:
        add("Skala: długość sieci", "brak danych", f"nowy: {nl or '—'} km; przypadek: {cl or '—'} km", 0, 5)

    # podobieństwo opisu
    a, b = _stems(new_text), _stems(case["text"])
    jac = len(a & b) / len(a | b) if a and b else 0
    add("Podobieństwo opisu", "pasuje" if jac >= 0.15 else "częściowo" if jac >= 0.07 else "różni się",
        f"wspólne rdzenie słów: {len(a & b)} (Jaccard {jac:.2f})", 20 * min(1, jac / 0.25), 20)

    # ograniczenia
    nc = {x["value"] for x in new.get("constraints", [])}
    cc = {x["value"] for x in cf.get("constraints", [])}
    if nc:
        common = nc & cc
        add("Znane ograniczenia", "pasuje" if common else "różni się",
            f"wspólne: {', '.join(sorted(common)) or '—'}", 5 * len(common) / len(nc), 5)

    score = round(100 * total / max_total, 1) if max_total else 0
    return score, feats


# ================================================================ raport
def _stat(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return {"n": 0}
    s = {"n": len(vals), "values": vals}
    if len(vals) >= 3:
        s.update(min=min(vals), max=max(vals), median=round(statistics.median(vals), 1))
    return s


def analyze(con, text: str, top_k: int = 5, min_score: float = 35.0) -> dict:
    feats = extract_features(text)
    cases = case_profiles(con)
    ranked = []
    for c in cases:
        if not c["n_contracts"] and not c["risks"]:
            continue  # brak danych o realizacji – nie ma czego porównać
        score, fs = compare(feats, c, text)
        ranked.append((score, c, fs))
    ranked.sort(key=lambda x: -x[0])
    chosen = [x for x in ranked if x[0] >= min_score][:top_k] or ranked[:3]

    similar = []
    for score, c, fs in chosen:
        similar.append({
            "project_id": c["project_id"], "name": c["name"], "recipient": c["recipient"], "score": score,
            "link_status": c["link_status"], "description_source": c["description_source"],
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
    for key, label in (("growth_pct", "wzrostu wypłaty"), ("delay_days", "opóźnienia")):
        st = comparison[key]
        if st["n"] < 3:
            comparison["notes"].append(
                f"Przedział {label} wymaga co najmniej 3 przypadków z ogłoszeniem o wykonaniu umowy; jest {st['n']}. "
                "Pokazujemy wartości per przypadek. Do wyliczenia przedziału potrzeba ogłoszeń o wykonaniu umowy "
                "dla kolejnych podobnych przypadków.")
    low = [s["project_id"] for s in similar if s["growth_pct"] is not None and s["growth_pct"] < -10]
    if low:
        comparison["notes"].append(
            f"Wypłata wyraźnie niższa niż wartość umowy w: {', '.join(low)}. To zwykle nie oszczędność, tylko ograniczenie "
            "zakresu, kary albo nienależyte wykonanie – sprawdź kartę przypadku przed użyciem tej wartości do budżetu.")
    if feats.get("budget_pln") and growth.get("n"):
        b = feats["budget_pln"]["value"]
        ref = growth.get("median", statistics.median(growth["values"]))
        comparison["budget_after_growth"] = {
            "value": round(b * (1 + ref / 100), 2), "basis": f"budżet × (1 + {ref}% – mediana/wartość wzrostu w podobnych przypadkach)"}

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
    flag_list = sorted(flags.values(), key=lambda f: -f["weight"])
    for fl in flag_list:
        fl["weight"] = round(fl["weight"], 2)
        fl["strength"] = ("silna" if fl["confirmed_cases"] and (fl["from_description"] or len(fl["cases"]) >= 2)
                          else "średnia" if fl["confirmed_cases"] or len(fl["cases"]) >= 2 or fl["from_description"]
                          else "słaba")
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
    return {"input_text": text, "features": feats, "missing_inputs": missing_inputs, "similar": similar,
            "n_candidates": len(ranked), "comparison": comparison, "flags": flag_list, "water_checklist": checklist}


def to_csv(result: dict) -> str:
    import csv
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["project_id", "nazwa", "wynik_podobienstwa", "pasuje", "rozni_sie", "brak_danych", "wartosc_umow_pln",
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
