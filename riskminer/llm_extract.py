"""Odczyt cech inwestycji modelem językowym – uzupełnienie reguł z analysis.extract_features.

Model czyta cały opis i zwraca wartości z kontekstem (który budżet jest całkowity, która długość dotyczy
głównej sieci, która przepustowość jest docelowa, czas trwania z dat), sprzeczności i braki w dokumencie.
Zasady bezpieczeństwa – jak przy ryzykach:
- każda wartość musi mieć dosłowny cytat; cytat musi występować w dokumencie,
- liczba w polu musi występować w cytacie (z dopuszczalną zmianą jednostki: m→km, mln, tys.),
- wynik niezweryfikowany jest odrzucany i liczony w „rejected”,
- model niczego nie zatwierdza: wartość różna od reguł trafia do wyboru eksperta (konflikt).
Wynik zapamiętujemy w bazie (skrót tekstu + model), więc ponowne przeliczenie po wyborze eksperta jest natychmiastowe.
"""
import hashlib
import json
import re
import time

import requests

from . import analysis, config, llm, local_model

SUBSECTOR_NAMES = [name for name, _ in analysis.SUBSECTORS]
CONSTRAINT_NAMES = [name for name, _ in analysis.CONSTRAINTS] + list(analysis.MODEL_CONSTRAINTS)

TEXT_VALUES = {
    "podsektor_glowny": SUBSECTOR_NAMES,
    "rodzaj_prac": ["budowa/rozbudowa", "przebudowa/modernizacja", "budowa/rozbudowa + przebudowa/modernizacja"],
    "formula": ["zaprojektuj i wybuduj", "wybuduj (wg dokumentacji zamawiającego)"],
    "wynagrodzenie": ["ryczałtowe", "kosztorysowe", "mieszane"],
}
NUMBER_FIELDS = ["budzet_brutto", "budzet_netto", "budzet_bez_vat", "koszt_zmiany_umowy", "dlugosc_sieci_km", "rlm",
                 "przepustowosc_m3d", "przylacza_szt", "odbiorcy", "czas_realizacji_mies", "zmiana_terminu_dni"]

# Jednozdaniowe opisy kategorii – model myli kategorie, gdy widzi same nazwy.
CONSTRAINT_HELP = {
    "pozwolenie wodnoprawne / odbiornik ścieków": "zrzut ścieków, wylot, przejście przez ciek wymagające pozwolenia wodnoprawnego",
    "decyzja środowiskowa / ochrona przyrody": "Natura 2000, obszar chroniony, decyzja o środowiskowych uwarunkowaniach",
    "grunty prywatne / dostęp do terenu": "trasa przez działki prywatne, brak zgód właścicieli lub służebności",
    "kolizje i istniejące uzbrojenie": "kolizja z istniejącą siecią lub niezinwentaryzowanym uzbrojeniem",
    "przekroczenia: droga, kolej, ciek": "przejście pod drogą, koleją lub ciekiem (przewiert, przecisk)",
    "istniejący obiekt w eksploatacji": "roboty na czynnym obiekcie, który musi pracować bez przerwy",
    "azbest / stan istniejących sieci": "zły lub nieznany stan techniczny istniejących urządzeń, azbest",
    "warunki gruntowo-wodne": "brak badań geotechnicznych, wody gruntowe, podtopienia, słaby grunt",
    "niepełny lub niespójny zakres": "zakres opcjonalny, do decyzji wykonawcy, brak parametrów, sprzeczne ilości",
    "nieustalony operator / podział odpowiedzialności": "nie wiadomo, kto będzie eksploatował; ryzyka przerzucone na wykonawcę",
    "nierealny harmonogram / zależność od innej inwestycji": "za krótki czas na projekt i decyzje albo czekanie na inną inwestycję",
    "wynagrodzenie ryczałtowe przy niepewnym zakresie": "ryczałt mimo braku rozpoznania terenu lub zakresu",
    "ogólnikowe wymagania techniczne": "„odpowiednie ciśnienie”, „możliwie najniższe zużycie” bez liczb",
    "brak procedur prób, rozruchu i odbioru": "nieokreślone badania, rozruch, kryteria odbioru",
    "zawężające warunki udziału lub wskazanie marki": "wymagana konkretna marka, region, wąskie doświadczenie",
    "długi czas dostaw / dostępność urządzeń": "urządzenia na zamówienie, spoza UE, długi czas oczekiwania",
    "niepewne finansowanie": "dotacja lub pożyczka jeszcze nieprzyznana, nabór nieogłoszony",
}

SYSTEM = """Odczytujesz z dokumentu inwestycji wodno-kanalizacyjnej dane do prognozy kosztów, terminów i ryzyk.
Odpowiadasz wyłącznie JSON zgodnym ze schematem, po polsku, ZWIĘŹLE.

Zasady:
1. Tylko informacje zapisane w dokumencie. W "wartosci" wypisz WYŁĄCZNIE pola, które dokument podaje.
   Pola, którego nie ma, POMIŃ – nie pisz „brak informacji” i nie wpisuj 0.
2. "cytat" = dosłownie skopiowany, krótki fragment dokumentu (5–20 słów) zawierający wartość.
3. Liczby w "wartosc" zapisuj cyframi bez spacji (18500000, 3.5).
4. budzet_brutto / budzet_netto / budzet_bez_vat = całkowita wartość lub koszt inwestycji/zamówienia/umowy.
   NIE: dofinansowanie, dotacja, pożyczka, wkład własny, kara. Każdą różną kwotę całkowitą wypisz osobno.
5. koszt_zmiany_umowy = kwota robót dodatkowych/zamiennych lub zwiększenia wynagrodzenia (aneks, protokół).
6. dlugosc_sieci_km = długość sieci głównego podsektora w km (600 m = 0.6); nie zakres opcjonalny innej sieci.
7. przepustowosc_m3d, rlm = wartość DOCELOWA, nie obecna i nie z warunków doświadczenia wykonawcy.
8. czas_realizacji_mies = czas całej umowy; gdy są tylko daty podpisania i zakończenia – wylicz.
   „Z ostatnich 12 miesięcy”, gwarancja, czas dostaw – to NIE czas realizacji.
9. zmiana_terminu_dni = o ile dni przesunięto termin umowy (aneks, protokół).
10. Pola tekstowe – tylko z listy: """ + "; ".join(f"{k}: {' | '.join(v)}" for k, v in TEXT_VALUES.items()) + """.
11. ograniczenia – kategorie (tylko z listy):
""" + "\n".join(f"   - {k}: {v}" for k, v in CONSTRAINT_HELP.items()) + """
12. sprzecznosci = ta sama wielkość podana różnie (tekst vs tabela, netto vs budżet, różne jednostki).
13. braki = do 5 krótkich (do 12 słów) informacji potrzebnych do przygotowania inwestycji, których dokument nie ma."""

QUOTE = {"type": "string", "maxLength": 160}  # krótkie cytaty: odpowiedź mieści się w kontekście modelu
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["wartosci", "ograniczenia", "sprzecznosci", "braki"],
    "properties": {
        "wartosci": {"type": "array", "maxItems": 16, "items": {
            "type": "object", "additionalProperties": False, "required": ["pole", "wartosc", "cytat"],
            "properties": {"pole": {"enum": NUMBER_FIELDS + list(TEXT_VALUES)},
                           "wartosc": {"type": "string", "maxLength": 60}, "cytat": QUOTE}}},
        "ograniczenia": {"type": "array", "maxItems": 8, "items": {
            "type": "object", "additionalProperties": False, "required": ["kategoria", "cytat"],
            "properties": {"kategoria": {"enum": CONSTRAINT_NAMES}, "cytat": QUOTE}}},
        "sprzecznosci": {"type": "array", "maxItems": 4, "items": {
            "type": "object", "additionalProperties": False, "required": ["opis", "cytat"],
            "properties": {"opis": {"type": "string", "maxLength": 140}, "cytat": QUOTE}}},
        "braki": {"type": "array", "maxItems": 5, "items": {"type": "string", "maxLength": 110}},
    },
}

# Część dokumentu z odpowiedziami („Klucz testowy – co powinien wykryć…”) nie trafia do modelu.
_ANSWER_KEY = re.compile(r"^\s*(?:klucz\s+testowy|co\s+powin\w+\s+wykry)", re.I | re.M)
_WS = re.compile(r"\s+")


def _norm(text):
    return _WS.sub(" ", re.sub(r"[„”\"'«»]", "", text or "")).strip().lower()


def find_quote(quote, text):
    """Zwraca fragment dokumentu odpowiadający cytatowi albo None (cytat nie z dokumentu)."""
    q = _norm(quote)
    if len(q) < 8:
        return None
    if q in _norm(text):
        return _WS.sub(" ", quote).strip()
    words, qw = _norm(text).split(" "), q.split(" ")
    need, best, at = set(w for w in qw if len(w) > 2), 0.0, 0
    if not need:
        return None
    for i in range(0, max(1, len(words) - len(qw) + 1)):
        window = set(words[i:i + len(qw) + 2])
        score = len(need & window) / len(need)
        if score > best:
            best, at = score, i
    return " ".join(words[at:at + len(qw)]) if best >= 0.85 else None


def number_in_quote(value, quote):
    """Liczba z pola występuje w cytacie (z przeliczeniem m→km, tys., mln)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    for m in re.finditer(analysis.NUMBER, quote or ""):
        n = analysis._num(m.group())
        for c in (n, n / 1000, n * 1000, n * 1e6):
            if abs(c - v) <= 0.005 * max(1.0, abs(v)):
                return True
    return False


_DATE = re.compile(r"\d{1,2}[./]\d{1,2}[./]\d{4}|\d{1,2}\s+(?:stycz|lut|mar|kwie|maj|czerw|lip|sierp|wrze|paźdz|listop|grud)\w*\s+\d{4}", re.I)


def _cache_table(con):
    con.execute("CREATE TABLE IF NOT EXISTS llm_extract (key TEXT PRIMARY KEY, model TEXT, result TEXT, created_at TEXT)")
    con.execute("""CREATE TABLE IF NOT EXISTS feature_feedback (
        field TEXT NOT NULL, chosen_value REAL, chosen_quote TEXT NOT NULL, rejected TEXT,
        created_at TEXT DEFAULT (datetime('now')), PRIMARY KEY (field, chosen_quote))""")


def _complete(messages, max_tokens):
    provider, model = config.LLM_PROVIDER, config.LLM_MODEL
    if provider == "llama.cpp":
        return local_model.complete(messages, SCHEMA, max_tokens=max_tokens)
    return llm._remote_completion(provider, model, messages, SCHEMA, SYSTEM, max_tokens=max_tokens)


# ------------------------------------------------------------------ długie dokumenty
OUTPUT_TOKENS = 900
CHARS_PER_TOKEN = 2.5  # polski tekst w tokenizerze Bielika – ostrożnie
MAX_CHUNKS = 4
_RELEVANT = re.compile(
    r"\d[\d ,.]*\s*(?:zł|PLN|mln|tys|km|mb?\b|m[23³]|RLM|miesi|dni|szt|przyłącz|mieszk|odbiorc)"
    r"|budżet|koszt|wartoś|wynagrodz|ryczałt|kosztorys|zaprojektuj|formuł|termin|harmonogram|umow"
    r"|przepustow|długoś|zakres|grunt|służebnoś|decyzj|pozwoleni|kolizj|natura 2000|operator|eksploatac"
    r"|odbi[oó]r|rozruch|dostaw|finansowan|dotacj|warunk\w* udziału|ryzyk|brak|nie (?:posiada|określono|ustalono)", re.I)


def _limit():
    if config.LLM_PROVIDER != "llama.cpp":
        return 60000
    return max(3000, int((config.LLM_CONTEXT - 1400 - OUTPUT_TOKENS - 300) * CHARS_PER_TOKEN))


def model_text(text):
    """Tekst dla modelu: bez klucza odpowiedzi. Zwraca (fragmenty, czy pominięto część dokumentu)."""
    m = _ANSWER_KEY.search(text or "")
    text = (text[:m.start()] if m else text or "").strip()
    limit = _limit()
    if len(text) <= limit:
        return [text], False
    # długi dokument (PFU, SWZ): nagłówek + akapity z liczbami i słowami kluczowymi, w kolejności dokumentu
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n(?=\s*(?:\d+(?:\.\d+)*\.?|[●○•–-])\s)", text) if p.strip()]
    head, keep = text[:1200], []
    for p in paras:
        if text.find(p) >= 1200 and _RELEVANT.search(p):
            keep.append(p[:1500])
    chunks, cur = [], head
    for p in keep:
        if len(cur) + len(p) + 2 > limit:
            chunks.append(cur)
            cur = head[:400] + "\n…\n" + p  # tytuł zadania w każdym fragmencie – model wie, czego dotyczy
        else:
            cur += "\n\n" + p
    chunks.append(cur)
    used = sum(len(c) for c in chunks[:MAX_CHUNKS])
    return chunks[:MAX_CHUNKS], len(chunks) > MAX_CHUNKS or used < 0.5 * len(text)


# ------------------------------------------------------------------ uczenie z decyzji eksperta
def record_choice(con, field, chosen, rejected):
    """Wybór eksperta w konflikcie (np. właściwy budżet) – wzorzec dla kolejnych dokumentów."""
    if not chosen.get("source"):
        return
    _cache_table(con)
    con.execute("INSERT OR REPLACE INTO feature_feedback (field, chosen_value, chosen_quote, rejected) VALUES (?,?,?,?)",
                (field, chosen.get("value"), chosen["source"][:300],
                 json.dumps([r.get("source", "")[:300] for r in rejected if r.get("source")], ensure_ascii=False)))
    con.commit()


FIELD_LABEL = {"budget_pln": "budżet", "length_km": "długość sieci", "flow_m3d": "przepustowość docelowa",
               "rlm": "RLM docelowe", "connections": "liczba przyłączy", "recipients": "liczba odbiorców",
               "duration_months": "czas realizacji"}


def expert_hints(con, doc, k=6):
    """Najbardziej podobne wcześniejsze rozstrzygnięcia eksperta (wspólne rdzenie słów z dokumentem)."""
    _cache_table(con)
    rows = con.execute("SELECT field, chosen_quote, rejected FROM feature_feedback ORDER BY created_at DESC LIMIT 200").fetchall()
    stems = llm._stems(doc)
    scored = []
    for i, (field, quote, rejected) in enumerate(rows):
        overlap = len(llm._stems(quote) & stems) / max(1, len(llm._stems(quote)))
        scored.append((overlap, -i, field, quote, json.loads(rejected or "[]")))
    scored.sort(reverse=True)
    hints = []
    for _, _, field, quote, rejected in scored[:k]:
        line = f"{FIELD_LABEL.get(field, field)}: właściwy fragment „{quote}”"
        if rejected:
            line += "; NIE: " + "; ".join(f"„{r}”" for r in rejected[:2])
        hints.append(line)
    return hints


# ------------------------------------------------------------------ wywołanie
def _call(doc, hints):
    user = "Dokument:\n" + doc
    if hints:
        user = ("Wcześniejsze rozstrzygnięcia eksperta w innych dokumentach (wzorzec, jak wybierać – nie dane tego dokumentu):\n- "
                + "\n- ".join(hints) + "\n\n" + user)
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    try:
        raw = _complete(messages, max_tokens=OUTPUT_TOKENS)
        return json.loads(llm._json_part(raw))
    except local_model.LocalModelError as exc:
        raise llm.ModelError(str(exc)) from exc
    except requests.RequestException as exc:
        raise llm.ModelError(f"Błąd połączenia z dostawcą {config.LLM_PROVIDER}.") from exc
    except (ValueError, TypeError) as exc:
        raise llm.ModelError("Model zwrócił niepoprawny JSON – spróbuj ponownie.") from exc


def _combine(parts):
    """Wyniki z kilku fragmentów: pierwsza zweryfikowana wartość pola; inna wartość z dalszego fragmentu → sprzeczność."""
    out = {"fields": {}, "ograniczenia": [], "sprzecznosci": [], "braki": [], "rejected": []}
    for part in parts:
        for key, item in part["fields"].items():
            first = out["fields"].get(key)
            if not first:
                out["fields"][key] = item
                continue
            a = first.get("kwota_zl", first.get("wartosc"))
            b = item.get("kwota_zl", item.get("wartosc"))
            if isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) > 0.01 * max(1, abs(a)):
                out["sprzecznosci"].append({"opis": f"{key.replace('_', ' ')}: {a:g} i {b:g} w różnych miejscach dokumentu",
                                            "cytat": item["cytat"]})
        seen = {c["kategoria"] for c in out["ograniczenia"]}
        out["ograniczenia"] += [c for c in part["ograniczenia"] if c["kategoria"] not in seen]
        out["sprzecznosci"] += part["sprzecznosci"]
        out["braki"] += [g for g in part["braki"] if g not in out["braki"]]
        out["rejected"] += part["rejected"]
    return out


def extract(con, text):
    """Zweryfikowany odczyt modelem – z pamięci podręcznej albo z nowego wywołania (po jednym na fragment)."""
    chunks, truncated = model_text(text)
    hints = expert_hints(con, "\n".join(chunks))
    key = hashlib.sha1("\n".join([config.LLM_MODEL, *hints, *chunks]).encode()).hexdigest()
    row = con.execute("SELECT result FROM llm_extract WHERE key=?", (key,)).fetchone()
    if row:
        return dict(json.loads(row[0]), cached=True)
    t0 = time.time()
    result = _combine([verify(_call(chunk, hints), chunk) for chunk in chunks])
    result.update(model=config.LLM_MODEL, seconds=round(time.time() - t0, 1), truncated=truncated,
                  chunks=len(chunks), hints=len(hints))
    con.execute("INSERT OR REPLACE INTO llm_extract VALUES (?,?,?,datetime('now'))",
                (key, config.LLM_MODEL, json.dumps(result, ensure_ascii=False)))
    con.commit()
    return dict(result, cached=False)


def _to_number(value):
    m = re.search(r"-?\d+(?:[.,]\d+)?", re.sub(r"(?<=\d)[ \xa0](?=\d{3})", "", str(value)))
    return float(m.group().replace(",", ".")) if m else None


def verify(body, text):
    """Zostawia tylko wartości z cytatem z dokumentu i liczbą obecną w cytacie.
    Zwraca {"fields": {klucz: {...}}, ograniczenia, sprzecznosci, braki, rejected} w formacie dla analysis.merge_model."""
    fields, rejected, budgets = {}, [], []
    for item in body.get("wartosci") or []:
        if not isinstance(item, dict):
            continue
        key, raw = item.get("pole"), item.get("wartosc")
        source = find_quote(item.get("cytat", ""), text)
        if not source:
            rejected.append(f"{key}: cytat spoza dokumentu")
            continue
        if key in TEXT_VALUES:
            value = next((v for v in TEXT_VALUES[key] if v.lower() == str(raw).strip().lower()), None)
            if value and key not in fields:
                fields[key] = {"wartosc": value, "cytat": source}
            continue
        number = _to_number(raw)
        if not number or number <= 0:
            continue
        computed = key == "czas_realizacji_mies" and _DATE.search(source)
        if key != "zmiana_terminu_dni" and not number_in_quote(number, source) and not computed:
            rejected.append(f"{key}: wartości {raw} nie ma w cytacie")
            continue
        if key.startswith("budzet_"):
            vat = {"budzet_brutto": "brutto", "budzet_netto": "netto"}.get(key, "nieokreślony")
            budgets.append({"kwota_zl": number, "vat": vat, "cytat": source})
        elif key == "koszt_zmiany_umowy":
            vat = "netto" if re.search(r"\bnetto\b", source, re.I) else "brutto" if re.search(r"\bbrutto\b", source, re.I) else "nieokreślony"
            fields.setdefault(key, {"kwota_zl": number, "vat": vat, "cytat": source})
        elif key == "zmiana_terminu_dni":
            fields.setdefault("zmiana_terminu", {"dni": number, "opis": "przesunięcie terminu", "cytat": source})
        else:
            fields.setdefault(key, {"wartosc": number, "cytat": source})
    lists = {"ograniczenia": [], "sprzecznosci": []}
    if budgets:
        # budżet bez VAT / brutto ma pierwszeństwo przed szacunkiem netto; różne kwoty → sprzeczność do wyboru eksperta
        budgets.sort(key=lambda b: b["vat"] == "netto")
        fields["budzet"] = budgets[0]
        for other in budgets[1:]:
            if abs(other["kwota_zl"] - budgets[0]["kwota_zl"]) > 1:
                lists["sprzecznosci"].append({"opis": f"dwie kwoty całkowite: {budgets[0]['kwota_zl']:,.0f} zł ({budgets[0]['vat']}) "
                                                      f"i {other['kwota_zl']:,.0f} zł ({other['vat']})".replace(",", " "),
                                              "cytat": other["cytat"]})
    for key in lists:
        for item in body.get(key) or []:
            source = find_quote(item.get("cytat", ""), text) if isinstance(item, dict) else None
            if source:
                lists[key].append(dict(item, cytat=source))
            else:
                rejected.append(f"{key}: cytat spoza dokumentu")
    gaps = [g.strip() for g in body.get("braki") or [] if isinstance(g, str) and 5 <= len(g.strip()) <= 200]
    return {"fields": fields, **lists, "braki": gaps, "rejected": rejected}
