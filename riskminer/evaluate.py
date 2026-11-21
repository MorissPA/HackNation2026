"""Ocena modelu językowego na zbiorze testowym (docs/llm_zbior_testowy.csv + decyzje eksperta).

Zbiór testowy wiąże tekst źródła (skrót SHA-1 znormalizowanego tekstu) z oczekiwaną kategorią przyczyny.
Etykiety „zespół” to ocena zespołu; decyzja eksperta w kolejce (zatwierdzenie lub poprawka propozycji modelu)
ma pierwszeństwo i oznacza wiersz jako „ekspert”. Przykłady eksperta z tego samego projektu są pomijane,
żeby model nie dostał gotowej odpowiedzi.
"""
import csv
import hashlib
import time
from pathlib import Path

from . import config, db, llm, risks

GOLD = Path(__file__).resolve().parent.parent / "docs" / "llm_zbior_testowy.csv"
FIELDS = ["project_id", "tekst_sha1", "oczekiwane", "czesciowo", "etykieta", "uzasadnienie", "fragment"]
SOURCES_SQL = """SELECT * FROM visible_event WHERE event_type IN ('zmiana_umowy','dokument BIP')
    AND quote IS NOT NULL AND trim(quote)<>'' AND source_section IS NOT NULL ORDER BY project_id, id"""


def text_key(quote):
    return hashlib.sha1(llm.normalize(quote).encode()).hexdigest()[:12]


def unique_sources(con):
    """Jedno źródło na (projekt, tekst) – duplikaty sekcji 5.3 / 5.4.4 liczymy raz."""
    out, seen = [], set()
    for s in con.execute(SOURCES_SQL):
        k = (s["project_id"], text_key(s["quote"]))
        if k not in seen:
            seen.add(k)
            out.append(s)
    return out


def load_gold(con, path=GOLD):
    gold = {}
    if Path(path).is_file():
        with open(path, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                gold[(r["project_id"], r["tekst_sha1"])] = {
                    "expected": set(filter(None, r["oczekiwane"].split("|"))),
                    "partial": set(filter(None, (r.get("czesciowo") or "").split("|"))),
                    "label": r.get("etykieta") or "zespół", "why": r.get("uzasadnienie") or ""}
    # decyzje eksperta mają pierwszeństwo nad etykietą zespołu
    for r in con.execute("""SELECT s.project_id, s.quote, e.status, COALESCE(e.expert_title, e.title) AS t
            FROM llm_run l JOIN event s ON s.id=l.source_id JOIN event e ON e.id=l.proposal_id
            WHERE e.status IN ('zaakceptowane','poprawione')"""):
        gold[(r["project_id"], text_key(r["quote"]))] = {
            "expected": {r["t"].split()[0]}, "partial": set(), "label": "ekspert", "why": f"decyzja eksperta: {r['status']}"}
    return gold


def evaluate(con, path=GOLD, log=print):
    gold = load_gold(con, path)
    rules = db.get_setting(con, "llm_rules", "")
    rows, t0 = [], time.time()
    for s in unique_sources(con):
        g = gold.get((s["project_id"], text_key(s["quote"])))
        if not g:
            continue
        context = llm.source_context(con, s)
        examples = llm.expert_examples(con, s["quote"], exclude_project=s["project_id"])
        try:
            res = llm.infer(s["quote"], context, rules, examples) or []
            err = None
        except llm.ModelError as exc:
            res, err = [], str(exc)
        pred = res[0][0] if res else "brak"
        if err:
            verdict = "błąd modelu"
        elif pred in g["expected"]:
            verdict = "trafne"
        elif pred in g["partial"]:
            verdict = "częściowo"
        else:
            verdict = "błędne"
        rule_codes = {c for c, _ in risks.propose(s["quote"])}
        rows.append({"project_id": s["project_id"], "source_id": s["id"], "section": s["source_section"],
                     "expected": "|".join(sorted(g["expected"])), "label": g["label"], "pred": pred,
                     "second": res[1][0] if len(res) > 1 else "", "verdict": verdict,
                     "confidence": "" if pred == "brak" else ("wysoka" if pred in rule_codes else "niska"),
                     "cause": res[0][1] if res else (err or ""), "fragment": llm.normalize(s["quote"])[:140]})
        log(f"{len(rows):>3}. {s['project_id']} źr.{s['id']}: {pred:<5} oczek. {rows[-1]['expected']:<10} {verdict}")
    return summarize(rows, time.time() - t0)


def summarize(rows, seconds):
    n = len(rows)
    count = lambda v: sum(r["verdict"] == v for r in rows)
    abst = [r for r in rows if r["expected"] == "brak"]
    wrong = [r for r in rows if r["verdict"] == "błędne"]
    return {
        "model": f"{config.LLM_PROVIDER} / {config.LLM_MODEL}", "n": n, "seconds": round(seconds),
        "correct": count("trafne"), "partial": count("częściowo"), "wrong": len(wrong), "errors": count("błąd modelu"),
        "score_pct": round(100 * (count("trafne") + 0.5 * count("częściowo")) / n, 1) if n else None,
        "abstain_expected": len(abst), "abstain_correct": sum(r["pred"] == "brak" for r in abst),
        "wrong_low_confidence": sum(r["confidence"] in ("niska", "") for r in wrong),
        "rows": rows,
    }


def to_markdown(rep):
    lines = [f"# Ocena modelu: {rep['model']}", "",
             f"Zbiór testowy: {rep['n']} unikalnych fragmentów · czas {rep['seconds']} s", "",
             f"- trafne: **{rep['correct']}**, częściowo: {rep['partial']}, błędne: {rep['wrong']}, błędy modelu: {rep['errors']}",
             f"- wynik (trafne + ½ częściowo): **{rep['score_pct']}%**",
             f"- poprawne wstrzymania: {rep['abstain_correct']} z {rep['abstain_expected']} fragmentów bez przyczyny",
             f"- błędne z niską pewnością lub bez kategorii: {rep['wrong_low_confidence']} z {rep['wrong']}", "",
             "| Projekt | Źródło | Oczekiwane | Model | Druga | Ocena | Pewność | Fragment |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rep["rows"]:
        frag = r["fragment"].replace("|", "/")
        lines.append(f"| {r['project_id']} | {r['source_id']} | {r['expected']} ({r['label']}) | {r['pred']} | {r['second']} "
                     f"| {r['verdict']} | {r['confidence']} | {frag} |")
    return "\n".join(lines) + "\n"
