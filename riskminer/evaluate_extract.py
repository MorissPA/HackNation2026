"""Ocena odczytu cech z dokumentów: same reguły vs reguły + model językowy (docs/ekstrakcja/oczekiwane.json).

Dla każdego pola: „trafne” (wartość końcowa oczekiwana albo – gdy dozwolone – wybór z oczekiwaną wartością),
„częściowo” (oczekiwana wartość jest wśród opcji, ale wybór nie był oczekiwany), „brak”, „błędne”.
Ograniczenia liczone jako odsetek oczekiwanych kategorii, które rozpoznano.
"""
import json
import time
from pathlib import Path

from . import analysis, config, llm, llm_extract

DIR = Path(__file__).resolve().parent.parent / "docs" / "ekstrakcja"
SCALE = {"length_km", "flow_m3d", "rlm", "connections", "recipients"}


def _close(a, b):
    return a is not None and abs(float(a) - float(b)) <= 0.01 * max(1.0, abs(float(b)))


def _value(f, key):
    if key in SCALE:
        return (f["scale"].get(key) or {}).get("value")
    if key == "extra_cost":
        return [o["value"] for o in f.get("extra_costs", [])]
    if key == "deadline_days":
        return (f.get("deadline_change") or {}).get("days")
    return (f.get(key) or {}).get("value")


def score_field(f, key, spec):
    if isinstance(spec, list):  # pole tekstowe
        v = _value(f, key)
        return "brak" if v is None else "trafne" if v in spec else "błędne"
    expected, conflict_ok = spec["wartosc"], spec.get("konflikt", False)
    v = _value(f, key)
    if isinstance(v, list):
        return "trafne" if any(_close(x, e) for x in v for e in expected) else "brak" if not v else "błędne"
    if v is not None:
        return "trafne" if any(_close(v, e) for e in expected) else "błędne"
    options = [o["value"] for o in f["conflicts"].get(key, [])]
    if any(_close(o, e) for o in options for e in expected):
        return "trafne" if conflict_ok else "częściowo"
    return "błędne" if options else "brak"


def score(f, doc):
    fields = {k: score_field(f, k, v) for k, v in doc.items() if k not in ("plik", "ograniczenia")}
    found = {c["value"] for c in f["constraints"]}
    want = doc.get("ograniczenia", [])
    return fields, [c for c in want if c in found], [c for c in want if c not in found]


def evaluate(con, use_llm=True, log=print):
    spec = json.loads((DIR / "oczekiwane.json").read_text(encoding="utf-8"))
    rows, t0 = [], time.time()
    for doc in spec["dokumenty"]:
        text = (DIR / doc["plik"]).read_text(encoding="utf-8")
        variants = {"reguły": analysis.extract_features(text)}
        if use_llm:
            f = analysis.extract_features(text)
            try:
                analysis.merge_model(f, llm_extract.extract(con, text), {})
                variants["reguły + model"] = f
            except llm.ModelError as exc:
                log(f"{doc['plik']}: model niedostępny – {exc}")
        for name, f in variants.items():
            fields, hit, miss = score(f, doc)
            rows.append({"plik": doc["plik"], "wariant": name, "pola": fields, "ograniczenia_ok": hit, "ograniczenia_brak": miss})
            log(f"{doc['plik']:<40} {name:<15} " + " ".join(f"{k}={v}" for k, v in fields.items())
                + f" | ograniczenia {len(hit)}/{len(hit) + len(miss)}")
    return summarize(rows, time.time() - t0)


def summarize(rows, seconds):
    out = {"model": f"{config.LLM_PROVIDER} / {config.LLM_MODEL}", "seconds": round(seconds), "rows": rows, "warianty": {}}
    for name in dict.fromkeys(r["wariant"] for r in rows):
        rs = [r for r in rows if r["wariant"] == name]
        verdicts = [v for r in rs for v in r["pola"].values()]
        ok, part = verdicts.count("trafne"), verdicts.count("częściowo")
        hit = sum(len(r["ograniczenia_ok"]) for r in rs)
        total = hit + sum(len(r["ograniczenia_brak"]) for r in rs)
        out["warianty"][name] = {"pola": len(verdicts), "trafne": ok, "częściowo": part,
                                 "błędne": verdicts.count("błędne"), "brak": verdicts.count("brak"),
                                 "wynik_pol_pct": round(100 * (ok + 0.5 * part) / max(1, len(verdicts)), 1),
                                 "ograniczenia_pct": round(100 * hit / max(1, total), 1)}
    return out


def to_markdown(rep):
    lines = [f"# Odczyt cech z dokumentów – {rep['model']}", "", f"Czas: {rep['seconds']} s", "",
             "| Wariant | Pola | Trafne | Częściowo | Błędne | Brak | Wynik pól | Ograniczenia rozpoznane |", "|---|---|---|---|---|---|---|---|"]
    for name, s in rep["warianty"].items():
        lines.append(f"| {name} | {s['pola']} | {s['trafne']} | {s['częściowo']} | {s['błędne']} | {s['brak']} "
                     f"| **{s['wynik_pol_pct']}%** | {s['ograniczenia_pct']}% |")
    lines += ["", "| Dokument | Wariant | Pola | Nierozpoznane ograniczenia |", "|---|---|---|---|"]
    for r in rep["rows"]:
        lines.append(f"| {r['plik']} | {r['wariant']} | " + ", ".join(f"{k}: {v}" for k, v in r["pola"].items())
                     + f" | {', '.join(r['ograniczenia_brak']) or '—'} |")
    return "\n".join(lines) + "\n"
