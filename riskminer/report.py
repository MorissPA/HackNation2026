"""Raport z testu: jakość połączeń arkusz ↔ BZP (poprawne / niepewne / błędne) i wyniki analizy nowego projektu.

Każde połączenie jest weryfikowane z danymi podmiotu i zamówienia (treść zadania, pkt 5):
- NIP zamawiającego z arkusza = NIP zamawiającego w ogłoszeniach postępowania,
- nazwa przedsięwzięcia ≈ tytuł zamówienia (udział słów nazwy w tytule),
- dla rekordów „część N” – umowa przypisana do właściwej części,
- kompletność: ogłoszenie o wyniku i o wykonaniu umowy.
"""
import csv
import io
import json
import re
from datetime import date

from . import analysis, matcher

SAMPLES = {
    "Nowa oczyszczalnia ścieków": (
        "Gmina planuje budowę nowej biologicznej oczyszczalni ścieków dla 1200 RLM w formule zaprojektuj i wybuduj, "
        "wraz z przebudową kolektora kanalizacji sanitarnej. Oczyszczone ścieki będą odprowadzane do rzeki. "
        "Istniejąca oczyszczalnia musi pracować bez przerwy w trakcie budowy. Budżet 4,5 mln zł, termin realizacji 18 miesięcy."),
    "Rozbudowa sieci wodociągowej": (
        "Rozbudowa sieci wodociągowej o długości 6,5 km w trzech miejscowościach wraz z 80 przyłączami. "
        "Trasa w pasie drogi powiatowej i częściowo przez grunty prywatne, przejście pod linią kolejową. "
        "Zasilanie z istniejącej SUW. Budżet 3 mln zł, termin 12 miesięcy."),
}
# uwagi o jakości danych – nie podważają samego połączenia, ale ekspert powinien je znać
DATA_GAPS = ("perf_unmatched", "brak_wyniku", "brak_ogloszenia_bazowego", "perf_duplikat", "niejednoznaczna", "bip_nieczytelne")


def _digits(s):
    return re.sub(r"\D", "", s or "")


def _title_share(name, title):
    a = {matcher.stem(matcher._fold(t)) for t in matcher.tokens(name)}
    b = {matcher.stem(matcher._fold(t)) for t in matcher.tokens(title)}
    return len(a & b) / len(a) if a else 0


def link_rows(con):
    rows = []
    for p in con.execute("SELECT * FROM project ORDER BY project_id"):
        p = dict(p)
        link = con.execute("SELECT * FROM project_link WHERE project_id=? AND status<>'odrzucone'", (p["project_id"],)).fetchone()
        r = {"project_id": p["project_id"], "name": p["name"], "id_type": p["public_id_type"], "public_id": p["public_id"],
             "scope": p["scope"], "method": link["method"] if link else None, "link_status": link["status"] if link else None,
             "ocid": link["ocid"] if link else None, "checks": [], "problems": [], "uncertain": [], "data_notes": []}
        if not link:
            r["problems"].append("brak powiązania z postępowaniem")
            r["verdict"] = "błędne"
            rows.append(r)
            continue
        metas = [json.loads(m["meta_json"]) for m in con.execute(
            "SELECT meta_json FROM notice WHERE ocid=? ORDER BY publication_date", (link["ocid"],))]
        types = {m.get("noticeType") for m in metas}
        # NIP
        nips = {_digits(m.get("organizationNationalId")) for m in metas if m.get("organizationNationalId")}
        if _digits(p["recipient_id"]) in nips:
            r["checks"].append("NIP zgodny")
        else:
            r["problems"].append(f"NIP z arkusza {p['recipient_id']} ≠ NIP w ogłoszeniach {', '.join(sorted(nips)) or '—'}")
        # numer ogłoszenia (rekordy BZP)
        if "BZP" in (p["public_id_type"] or ""):
            numbers = {m.get("noticeNumber") for m in metas}
            if p["public_id"] in numbers:
                r["checks"].append("numer BZP z arkusza w postępowaniu")
            elif link["method"] == "odwołanie_w_ogłoszeniu":
                r["uncertain"].append("ogłoszenie z arkusza niedostępne w API – powiązanie przez odwołanie w innym ogłoszeniu")
            else:
                r["problems"].append("numer BZP z arkusza nie występuje wśród ogłoszeń postępowania")
        # tytuł
        share = max((_title_share(p["name"], m.get("orderObject")) for m in metas), default=0)
        (r["checks"] if share >= 0.5 else r["uncertain"]).append(f"tytuł zamówienia zawiera {share:.0%} słów nazwy")
        # część
        parts = [c["part_no"] for c in con.execute(
            "SELECT part_no FROM contract WHERE ocid=? AND (?=0 OR part_no=?)", (link["ocid"], p["part_no"] or 0, p["part_no"] or 0))]
        if p["part_no"]:
            (r["checks"] if parts == [p["part_no"]] else r["problems"]).append(
                f"umowa części {p['part_no']}" + ("" if parts == [p["part_no"]] else f" – przypisane części: {parts}"))
        r["contracts"] = len(parts)
        # kompletność
        r["has_result"], r["has_performance"] = "TenderResultNotice" in types, "ContractPerformingNotice" in types
        if not r["has_performance"]:
            r["uncertain"].append("brak ogłoszenia o wykonaniu umowy")
        if link["status"] == "proponowane":
            cand = con.execute("SELECT matched, checked, confidence FROM link_candidate WHERE project_id=? AND ocid=?",
                               (p["project_id"], link["ocid"])).fetchone()
            r["uncertain"].append("powiązanie KPO zaproponowane automatycznie, czeka na eksperta"
                                  + (f" ({cand['matched']}/{cand['checked']} kryteriów, pewność {cand['confidence']})" if cand else ""))
        for g in con.execute("SELECT key, message FROM gap WHERE project_id=?", (p["project_id"],)):
            if any(k in g["key"] for k in DATA_GAPS):
                r["data_notes"].append(g["message"][:160])
        r["verdict"] = "błędne" if r["problems"] else "niepewne" if r["uncertain"] else "poprawne"
        rows.append(r)
    return rows


def build(con):
    rows = link_rows(con)
    counts = {v: sum(r["verdict"] == v for r in rows) for v in ("poprawne", "niepewne", "błędne")}
    analyses = {}
    for label, text in SAMPLES.items():
        a = analysis.analyze(con, text)
        analyses[label] = {
            "similar": [(s["project_id"], s["name"], s["matched"], s["checked"]) for s in a["similar"]],
            "confidence": a["comparison"].get("confidence", {}).get("level"),
            "growth": a["comparison"]["growth_pct"], "delay": a["comparison"]["delay_days"],
            "flags": [(f["code"], f["name"], f["strength"], f["action"]) for f in a["flags"][:4]],
        }
    return {"date": date.today().isoformat(), "rows": rows, "counts": counts, "analyses": analyses}


def to_markdown(rep):
    c = rep["counts"]
    out = [f"# Raport z testu – Risk Miner ({rep['date']})", "",
           "Raport generowany poleceniem `python cli.py report` z aktualnej bazy. Każde połączenie rekordu z arkusza "
           "z postępowaniem w BZP jest sprawdzane z danymi podmiotu i zamówienia: NIP zamawiającego, numer ogłoszenia, "
           "tytuł zamówienia, część zamówienia i kompletność ogłoszeń.", "",
           "## Podsumowanie połączeń", "",
           "| Wynik | Liczba | Znaczenie |", "|---|---|---|",
           f"| poprawne | {c['poprawne']} | wszystkie kontrole spełnione, komplet ogłoszeń |",
           f"| niepewne | {c['niepewne']} | połączenie prawdopodobne, ale wymaga oceny eksperta (propozycja KPO, ogłoszenie niedostępne w API, brak ogłoszenia o wykonaniu, słaba zgodność tytułu) |",
           f"| błędne | {c['błędne']} | niezgodny NIP, numer lub część albo brak powiązania |", "",
           "Uwagi o jakości danych (np. pole „Wartość zmiany” wypełnione nową wartością umowy, kilka ogłoszeń o wykonaniu tej samej "
           "umowy, skany bez warstwy tekstowej) są w osobnej kolumnie – nie podważają połączenia, ale ekspert powinien je znać.", "",
           "## Połączenia rekord po rekordzie", "",
           "| Rekord | Identyfikator z arkusza | Metoda | Status | Wynik | Kontrole spełnione | Do sprawdzenia | Uwagi o danych |",
           "|---|---|---|---|---|---|---|---|"]
    for r in rep["rows"]:
        issues = r["problems"] + r["uncertain"]
        out.append(f"| {r['project_id']} | {r['id_type']}: `{r['public_id']}` | {r['method'] or '—'} | {r['link_status'] or '—'} | "
                   f"**{r['verdict']}** | {'; '.join(r['checks']) or '—'} | {'; '.join(i.replace('|', '/') for i in issues) or '—'} | "
                   f"{'; '.join(i.replace('|', '/') for i in r.get('data_notes', [])) or '—'} |")
    out += ["", "## Analiza nowego projektu – przykłady", ""]
    for label, a in rep["analyses"].items():
        g, d = a["growth"], a["delay"]
        out += [f"### {label}", "", SAMPLES[label], "",
                f"Podobne przypadki (pasujące cechy / porównywalne): " +
                "; ".join(f"{pid} ({m}/{ch})" for pid, _, m, ch in a["similar"]), "",
                f"Wzrost wypłaty: n = {g['n']}" + (f", mediana {g['median']}%, zakres {g['min']}…{g['max']}%" if g.get("median") is not None else "") +
                f". Opóźnienie: n = {d['n']}" + (f", mediana {d['median']} dni, zakres {d['min']}…{d['max']} dni" if d.get("median") is not None else "") +
                f". Pewność prognozy: **{a['confidence']}**.", "",
                "| Ryzyko | Siła sygnału | Rekomendowane działanie |", "|---|---|---|"]
        out += [f"| {code} {name} | {strength} | {action} |" for code, name, strength, action in a["flags"]]
        out.append("")
    return "\n".join(out)


def to_csv(rep):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["project_id", "nazwa", "rodzaj_id", "identyfikator", "metoda", "status_powiazania", "ocid", "wynik",
                "kontrole_spelnione", "problemy", "do_sprawdzenia", "uwagi_o_danych"])
    for r in rep["rows"]:
        w.writerow([r["project_id"], r["name"], r["id_type"], r["public_id"], r["method"], r["link_status"], r["ocid"],
                    r["verdict"], " | ".join(r["checks"]), " | ".join(r["problems"]), " | ".join(r["uncertain"]),
                    " | ".join(r.get("data_notes", []))])
    return "﻿" + buf.getvalue()
