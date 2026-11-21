"""Dopasowanie rekordu KPO (bez numeru BZP) do postępowania w BZP.

Zgodnie z treścią zadania (pkt 3 i 5): „gdy jednoznacznego klucza nie ma, rozwiązanie może dopasować
rekordy na podstawie nazwy, zamawiającego, miejsca, CPV, wartości i dat oraz pokazać podstawę
i poziom pewności dopasowania”.

- zamawiający (NIP) – warunek konieczny: kandydatów szukamy tylko wśród ogłoszeń tego NIP-u,
- pozostałe kryteria: nazwa, miejsce, CPV, wartość, daty – każde: pasuje / nie pasuje / brak danych,
- poziom pewności wynika z liczby spełnionych kryteriów (bez wag i punktów).
"""
import re
import unicodedata
from datetime import date

from .bzp import parser as P

# podsektor -> (słowa w nazwie, prefiksy CPV robót budowlanych z tego podsektora)
SUBSECTORS = {
    "kanalizacja sanitarna": (r"kanaliz\w*\s+sanitarn|kanalizac\w* (?!deszcz)|ściek|przepompown|tłoczn",
                              ("452324", "4523241", "4523242", "45231300", "45232423")),
    "kanalizacja deszczowa": (r"kanaliz\w*\s+deszcz|wód opadowych|retencj", ("4523213", "45247")),
    "wodociąg": (r"wodociąg|sieci wodn|przyłącz\w* wod", ("4523215", "45231300", "4523110")),
    "oczyszczalnia": (r"oczyszczal", ("452521", "45232421", "452522")),
    "stacja uzdatniania wody": (r"uzdatniani\w* wody|\bSUW\b", ("45252126", "452521", "45232150")),
}
SEARCH_STEMS = {"kanalizacja sanitarna": "kanalizac", "kanalizacja deszczowa": "deszczow", "wodociąg": "wodociąg",
                "oczyszczalnia": "oczyszczal", "stacja uzdatniania wody": "uzdatniani"}
NOT_PLACES = {"budowa", "rozbudowa", "przebudowa", "modernizacja", "gmina", "gminie", "gminy", "gm", "stacji",
              "stacja", "uzdatniania", "wody", "etap", "ii", "iii", "i", "kpo", "ul", "projekt"}
STOP = {"w", "i", "na", "z", "ze", "do", "oraz", "wraz", "terenie", "miejscowości", "miejscowościach", "gminy",
        "gminie", "gmina", "dla", "o", "od", "po", "przy", "pn", "się", "budowa", "zadania"}
DESIGN_ONLY = r"dokumentacj\w* projektow|opracowani\w* dokumentacj|koncepcj"


def _fold(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def stem(word, n=6):
    """Prosty rdzeń na potrzeby polskiej fleksji (Modlikowice / Modlikowicach)."""
    w = word.lower()
    return w[: max(4, min(n, len(w) - 2))] if len(w) > 4 else w


def tokens(text):
    return [t for t in re.findall(r"[A-Za-zÀ-žĄĆĘŁŃÓŚŹŻąćęłńóśźż]{3,}", text or "") if t.lower() not in STOP]


def places(name: str):
    """Nazwy miejscowości z nazwy przedsięwzięcia: wyrazy z wielkiej litery (poza pierwszym), bez słów ogólnych."""
    words = re.findall(r"[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+(?:-[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)?", name or "")
    out = []
    for i, w in enumerate(words):
        if w.lower() in NOT_PLACES or (i == 0 and (name or "").startswith(w)):
            continue
        if w not in out:
            out.append(w)
    return out


def subsectors(text):
    return {k for k, (rx, _) in SUBSECTORS.items() if re.search(rx, text or "", re.I)}


def kpo_since(kpo_id: str):
    """KPOD.03.15-IW.13-0004/25 -> nabór 2025 -> postępowania szukamy od 2024-01-01."""
    m = re.search(r"/(\d{2})\s*$", kpo_id or "")
    year = 2000 + int(m.group(1)) if m else 2023
    return f"{year - 1}-01-01"


def kpo_value(annotation):
    m = re.search(r"Wartość przedsięwzięcia:\s*([\d\s\xa0]+,\d{2})", annotation or "")
    return P.parse_money(m.group(1)) if m else None


def collect_candidates(client, project, log=lambda m: None, max_pages=3):
    nip = re.sub(r"\D", "", project.get("recipient_id") or "")
    since = kpo_since(project.get("public_id"))
    name = project.get("name") or ""
    pl = places(name)
    phrases = [stem(p, 7) for p in pl] + [SEARCH_STEMS[s] for s in subsectors(name)]
    phrases = list(dict.fromkeys(phrases)) or [None]
    notices, queries = {}, []
    for ph in phrases:
        queries.append(ph or "(bez frazy)")
        for page in range(1, max_pages + 1):
            items = client.search(OrganizationNationalId=nip, OrderObject=ph, PublicationDateFrom=since, PageNumber=page)
            for n in items:
                if re.sub(r"\D", "", n.get("organizationNationalId") or "") == nip and n.get("tenderId"):
                    notices.setdefault(n["noticeNumber"], n)
            if len(items) < 10:
                break
    by_ocid = {}
    for n in notices.values():
        by_ocid.setdefault(n["tenderId"], []).append(n)
    log(f"[{project['project_id']}] Kandydaci KPO: {len(notices)} ogłoszeń w {len(by_ocid)} postępowaniach "
        f"(frazy: {', '.join(queries)}; NIP {nip}; od {since})")
    return by_ocid, {"queries": queries, "since": since, "nip": nip, "places": pl}


# ---------------------------------------------------------------- kryteria z treści zadania
def criteria(project, notices, contract_values=None):
    """Kryteria dopasowania: lista {name, status: pasuje | nie pasuje | brak danych, detail}."""
    name = project.get("name") or ""
    title = max((n.get("orderObject") or "" for n in notices), key=len).replace("\n", " ")
    out = []

    def add(n, ok, detail):
        out.append({"name": n, "status": "brak danych" if ok is None else ("pasuje" if ok else "nie pasuje"),
                    "detail": detail})

    nip = re.sub(r"\D", "", project.get("recipient_id") or "")
    add("Zamawiający", True, f"NIP {nip} – kandydatów szukamy tylko wśród ogłoszeń tego zamawiającego")

    tp, tc = {stem(_fold(t)) for t in tokens(name)}, {stem(_fold(t)) for t in tokens(title)}
    common = tp & tc
    design_only = bool(re.search(DESIGN_ONLY, title, re.I))
    out_share = len(common) / len(tp) if tp else 0
    add("Nazwa", (len(common) >= 0.5 * len(tp) and not design_only) if tp else None,
        f"{len(common)} z {len(tp)} słów nazwy przedsięwzięcia w tytule zamówienia"
        + (" – ale to zamówienie na dokumentację projektową, nie na roboty" if design_only else ""))

    pl = places(name)
    hit = [p for p in pl if stem(_fold(p)) in _fold(title)]
    add("Miejsce", bool(hit) if pl else None, f"w tytule: {', '.join(hit) or '—'}; z arkusza: {', '.join(pl) or '—'}")

    cpvs = sorted({c for n in notices for c in re.findall(r"\d{8}", n.get("cpvCode") or "")})
    wanted = subsectors(name) or subsectors(project.get("annotation") or "")
    prefixes = [p for s in wanted for p in SUBSECTORS[s][1]]
    cpv_hit = [c for c in cpvs if any(c.startswith(p) for p in prefixes)]
    add("CPV", bool(cpv_hit) if cpvs and prefixes else None,
        f"kody robót {', '.join(cpv_hit[:3])} zgodne z zakresem: {', '.join(sorted(wanted))}" if cpv_hit else
        f"brak kodów robót dla zakresu {', '.join(sorted(wanted)) or '—'}; kody postępowania: {', '.join(cpvs[:4]) or '—'}")

    kv = kpo_value(project.get("annotation"))
    if kv and contract_values:
        tot = sum(contract_values)
        add("Wartość", 0.3 <= tot / kv <= 1.25,
            f"umowy {tot:,.0f} zł = {tot / kv:.0%} wartości przedsięwzięcia KPO {kv:,.0f} zł".replace(",", " "))
    else:
        add("Wartość", None, "brak wartości umowy lub wartości przedsięwzięcia KPO")

    first = min(n["publicationDate"][:10] for n in notices)
    since, until = kpo_since(project.get("public_id")), project.get("record_date") or date.today().isoformat()
    add("Daty", since <= first <= until, f"pierwsze ogłoszenie {first}; okres naboru KPO {since[:4]}–{until[:4]}")
    out[1]["share"] = round(out_share, 2)  # udział słów nazwy w tytule – rozstrzyga remisy
    return out, title


def summarize(crit):
    """(spełnione, sprawdzalne) – kryteria bez danych nie są liczone."""
    checked = [c for c in crit if c["status"] != "brak danych"]
    return sum(c["status"] == "pasuje" for c in checked), len(checked)


def confidence(crit):
    """wysoka: wszystkie sprawdzalne kryteria spełnione (i co najmniej 5 sprawdzalnych);
    średnia: najwyżej jedno niespełnione lub brak danych dla dwóch; niska: pozostałe."""
    ok, checked = summarize(crit)
    failed = checked - ok
    if failed == 0 and checked >= 5:
        return "wysoka"
    if failed <= 1 and checked >= 4:
        return "średnia"
    return "niska"


def name_share(c):
    return next((x.get("share", 0) for x in c["criteria"] if x["name"] == "Nazwa"), 0)


def _order(c):
    """Najpierw liczba spełnionych kryteriów, przy remisie – więcej wspólnych słów z nazwą przedsięwzięcia."""
    ok, checked = summarize(c["criteria"])
    return (-ok, -name_share(c), -checked)


def rank(client, project, log=lambda m: None, fetch_values_top=3):
    by_ocid, info = collect_candidates(client, project, log)
    ranked = []
    for ocid, notices in by_ocid.items():
        crit, title = criteria(project, notices)
        ranked.append({"ocid": ocid, "criteria": crit, "title": title, "notices": notices})
    ranked.sort(key=_order)
    # dla najlepszych pobieramy wartość umowy (ogłoszenie o wyniku albo o wykonaniu) – kryterium „Wartość”
    for c in ranked[:fetch_values_top]:
        vals = []
        res = [n for n in c["notices"] if n["noticeType"] == "TenderResultNotice"]
        perf = [n for n in c["notices"] if n["noticeType"] == "ContractPerformingNotice"]
        try:
            if res:
                ext = P.extract("TenderResultNotice", client.fetch_full(res[-1]).get("htmlBody") or "")
                vals = [P.parse_money(d["value"]["value"]) for d in ext["by_part"].values() if d.get("value")]
            elif perf:
                for n in perf:
                    ext = P.extract("ContractPerformingNotice", client.fetch_full(n).get("htmlBody") or "")
                    if ext.get("value"):
                        vals.append(P.parse_money(ext["value"]["value"]))
        except Exception as e:  # brak treści nie blokuje rankingu
            log(f"  nie udało się pobrać wartości dla {c['ocid']}: {e}")
        c["criteria"], c["title"] = criteria(project, c["notices"], [v for v in vals if v])
    ranked.sort(key=_order)
    for c in ranked:
        c["matched"], c["checked"] = summarize(c["criteria"])
        c["confidence"] = confidence(c["criteria"])
        c["score"] = round(100 * c["matched"] / c["checked"]) if c["checked"] else 0
    return ranked, info


def base_notice(notices):
    """Ogłoszenie reprezentujące postępowanie: najwcześniejsze ogłoszenie o zamówieniu, inaczej najwcześniejsze."""
    cn = sorted([n for n in notices if n["noticeType"] == "ContractNotice"], key=lambda n: n["publicationDate"])
    return cn[0] if cn else sorted(notices, key=lambda n: n["publicationDate"])[0]
