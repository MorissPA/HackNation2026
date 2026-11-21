"""Dopasowanie rekordu KPO (bez numeru BZP) do postępowania w BZP.

Kandydaci: wyszukiwarka BZP filtrowana NIP-em zamawiającego (OrganizationNationalId) i datą,
z frazami: rdzenie nazw miejscowości z nazwy przedsięwzięcia + słowa kluczowe podsektora.
Ogłoszenia grupujemy po OCID i oceniamy postępowanie jako całość.

Punktacja (0–100) jest jawna – każdy składnik ma opis „pasuje / różni się / brak danych”,
żeby ekspert widział, dlaczego kandydat jest wysoko. Wynik zawsze jest propozycją do akceptacji.
"""
import re
import unicodedata

from .bzp import parser as P

SUBSECTORS = {
    "kanalizacja sanitarna": r"kanaliz\w*\s+sanitarn|kanalizac\w* (?!deszcz)|ściek|przepompown|tłoczn",
    "kanalizacja deszczowa": r"kanaliz\w*\s+deszcz|wód opadowych",
    "wodociąg": r"wodociąg|sieci wodn|przyłącz\w* wod",
    "oczyszczalnia": r"oczyszczal",
    "stacja uzdatniania wody": r"uzdatniani\w* wody|\bSUW\b",
}
SEARCH_STEMS = {"kanalizacja sanitarna": "kanalizac", "kanalizacja deszczowa": "deszczow", "wodociąg": "wodociąg",
                "oczyszczalnia": "oczyszczal", "stacja uzdatniania wody": "uzdatniani"}
# słowa z wielkiej litery, które nie są nazwami miejscowości
NOT_PLACES = {"budowa", "rozbudowa", "przebudowa", "modernizacja", "gmina", "gminie", "gminy", "gm", "stacji",
              "stacja", "uzdatniania", "wody", "etap", "ii", "iii", "i", "kpo", "ul", "projekt"}
DESIGN_ONLY = r"dokumentacj\w* projektow|opracowani\w* dokumentacj|koncepcj|projektu budowlanego(?!.*wykonani)"
STOP = {"w", "i", "na", "z", "ze", "do", "oraz", "wraz", "terenie", "miejscowości", "miejscowościach", "gminy",
        "gminie", "gmina", "dla", "o", "od", "po", "przy", "pn", "się", "budowa", "zadania"}


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
    return {k for k, rx in SUBSECTORS.items() if re.search(rx, text or "", re.I)}


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
    phrases = [stem(p, 7) for p in pl]
    phrases += [SEARCH_STEMS[s] for s in subsectors(name)]
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


def score_candidate(project, notices, contract_values=None):
    """Zwraca (score, features[]) – features: {name, status: pasuje|różni się|brak danych, detail, points}."""
    name = project.get("name") or ""
    ann = project.get("annotation") or ""
    title = max((n.get("orderObject") or "" for n in notices), key=len).replace("\n", " ")
    types = {n["noticeType"] for n in notices}
    feats = []

    def add(fname, status, detail, pts):
        feats.append({"name": fname, "status": status, "detail": detail, "points": pts})

    # 1. miejscowości (35 pkt)
    pl = places(name)
    if pl:
        hit = [p for p in pl if stem(_fold(p)) in _fold(title)]
        pts = round(35 * len(hit) / len(pl))
        add("Miejscowość", "pasuje" if hit else "różni się",
            f"w tytule: {', '.join(hit) or '—'}; z arkusza: {', '.join(pl)}", pts)
    else:
        add("Miejscowość", "brak danych", "w nazwie przedsięwzięcia nie rozpoznano miejscowości", 0)

    # 2. podsektor / typ robót (25 pkt)
    # podsektor z nazwy; opis KPO tylko gdy nazwa nic nie mówi (opis wspomina też obiekty powiązane,
    # np. „wpięta do realizowanej oczyszczalni” – to nie jest zakres tego projektu)
    sp, sc = subsectors(name) or subsectors(ann), subsectors(title)
    if sp and sc:
        common = sp & sc
        add("Podsektor", "pasuje" if common else "różni się",
            f"projekt: {', '.join(sorted(sp))}; postępowanie: {', '.join(sorted(sc))}",
            round(25 * len(common) / len(sp)) if common else 0)
    else:
        add("Podsektor", "brak danych" if not sc else "różni się",
            f"projekt: {', '.join(sorted(sp)) or '—'}; postępowanie: {', '.join(sorted(sc)) or '—'}", 0)

    # 3. podobieństwo nazwy (20 pkt)
    tp = {stem(_fold(t)) for t in tokens(name)}
    tc = {stem(_fold(t)) for t in tokens(title)}
    jac = len(tp & tc) / len(tp | tc) if tp and tc else 0
    add("Podobieństwo nazwy", "pasuje" if jac >= 0.5 else "różni się" if jac < 0.25 else "częściowo",
        f"wspólne rdzenie {len(tp & tc)}/{len(tp | tc)} (Jaccard {jac:.2f})", round(20 * min(1, jac / 0.7)))

    # 4. rodzaj zamówienia – roboty budowlane, nie sama dokumentacja (10 pkt, kara −30)
    order_types = {n.get("orderType") for n in notices}
    if re.search(DESIGN_ONLY, title, re.I):
        add("Rodzaj zamówienia", "różni się", "postępowanie na dokumentację projektową, a nie na roboty", -30)
    elif "Works" in order_types:
        add("Rodzaj zamówienia", "pasuje", "roboty budowlane", 10)
    else:
        add("Rodzaj zamówienia", "różni się", f"{', '.join(t for t in order_types if t) or '?'}", 0)

    # 5. kompletność ścieżki postępowania (5 pkt)
    have = [t for t in ("ContractNotice", "TenderResultNotice", "ContractPerformingNotice") if t in types]
    add("Ogłoszenia w BZP", "pasuje" if len(have) == 3 else "częściowo",
        ", ".join({"ContractNotice": "o zamówieniu", "TenderResultNotice": "o wyniku",
                   "ContractPerformingNotice": "o wykonaniu"}[t] for t in have) or "tylko inne ogłoszenia",
        len(have) * 5 // 3)

    # 6. skala: wartość umów vs wartość przedsięwzięcia KPO (5 pkt, kara −15)
    kv = kpo_value(ann)
    if kv and contract_values:
        tot = sum(contract_values)
        ratio = tot / kv
        if 0.3 <= ratio <= 1.25:
            add("Skala (wartość)", "pasuje", f"umowy {tot:,.0f} zł vs przedsięwzięcie KPO {kv:,.0f} zł ({ratio:.0%})".replace(",", " "), 5)
        else:
            add("Skala (wartość)", "różni się", f"umowy {tot:,.0f} zł vs przedsięwzięcie KPO {kv:,.0f} zł ({ratio:.0%})".replace(",", " "), -15)
    else:
        add("Skala (wartość)", "brak danych", "brak wartości umowy w wyszukiwarce lub wartości KPO", 0)

    score = max(0, min(100, sum(f["points"] for f in feats)))
    return score, feats, title


def rank(client, project, log=lambda m: None, fetch_values_top=3):
    by_ocid, info = collect_candidates(client, project, log)
    ranked = []
    for ocid, notices in by_ocid.items():
        s, feats, title = score_candidate(project, notices)
        ranked.append({"ocid": ocid, "score": s, "features": feats, "title": title, "notices": notices})
    ranked.sort(key=lambda c: -c["score"])
    # dla najlepszych pobieramy treść ogłoszenia o wyniku/wykonaniu, żeby porównać skalę
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
        vals = [v for v in vals if v]
        c["score"], c["features"], c["title"] = score_candidate(project, c["notices"], vals)
        c["contract_values"] = vals
    ranked.sort(key=lambda c: -c["score"])
    return ranked, info


def base_notice(notices):
    """Ogłoszenie reprezentujące postępowanie: najwcześniejsze ogłoszenie o zamówieniu, inaczej najwcześniejsze."""
    cn = sorted([n for n in notices if n["noticeType"] == "ContractNotice"], key=lambda n: n["publicationDate"])
    return cn[0] if cn else sorted(notices, key=lambda n: n["publicationDate"])[0]
