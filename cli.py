"""CLI: import arkusza i pobranie danych z BZP.

  python cli.py import ../Risk_Miner_dane_projekty.xlsx
  python cli.py fetch RM-2026-003            # jeden projekt
  python cli.py fetch --all                  # wszystkie rekordy
  python cli.py show RM-2026-003             # podsumowanie karty
"""
import argparse
import sys
from pathlib import Path

from riskminer import db, importer, llm, pipeline
from riskminer.bzp.client import BZPClient


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("import"); a.add_argument("path")
    f = sub.add_parser("fetch"); f.add_argument("ids", nargs="*"); f.add_argument("--all", action="store_true")
    f.add_argument("--offline", action="store_true")
    s = sub.add_parser("show"); s.add_argument("id")
    ex = sub.add_parser("export", help="Eksport całej bazy przypadków do JSON i CSV (ZIP)")
    ex.add_argument("--out", default="docs/przyklad_eksportu")
    rp = sub.add_parser("report", help="Raport z testu: jakość połączeń i analiza nowego projektu (docs/)")
    rp.add_argument("--out", default="docs")
    model = sub.add_parser("llm", help="Przeanalizuj przyczyny i ryzyka w dowodach projektu")
    model.add_argument("id", nargs="?")
    model.add_argument("--all", action="store_true", help="wszystkie projekty z fragmentami źródłowymi")
    ev = sub.add_parser("eval-llm", help="Ocena modelu na zbiorze testowym docs/llm_zbior_testowy.csv")
    ev.add_argument("--out", default=None, help="plik .md z wynikiem (domyślnie docs/llm_ewaluacja_<model>.md)")
    args = ap.parse_args()
    con = db.connect()

    if args.cmd == "import":
        p = Path(args.path)
        rep = importer.import_file(con, p.name, p.read_bytes())
        print("Wynik:", rep["counts"])
        for r in rep["rows"]:
            if r["status"] != "bez_zmian" or r["message"]:
                print(f"  wiersz {r['row_no']}: {r['project_id']} – {r['status']}" + (f" ({r['message']})" if r["message"] else ""))
    elif args.cmd == "fetch":
        ids = [r["project_id"] for r in con.execute("SELECT project_id FROM project ORDER BY project_id")] if args.all else args.ids
        client = BZPClient(con, offline=args.offline, log=print)
        for pid in ids:
            res = pipeline.fetch_project(con, pid, client, log=print)
            print(f"==> {pid}: {res['status']} – {res['message']} | faktów {res['facts']}, zdarzeń {res['events']}")
        print("Zapytań sieciowych:", client.n_network_calls,
              "| źródła:", ", ".join(sorted(client.sources_used)) or "tylko cache")
    elif args.cmd == "export":
        import json as _json
        from riskminer import export
        out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
        data = export.to_json(con)
        (out / "risk_miner_baza.json").write_text(_json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        (out / "risk_miner_baza_csv.zip").write_bytes(export.to_csv_zip(con))
        print(f"Projektów: {len(data['projekty'])} | zapisano: {out / 'risk_miner_baza.json'} i {out / 'risk_miner_baza_csv.zip'}")
    elif args.cmd == "report":
        from riskminer import report
        rep = report.build(con)
        out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
        (out / "raport_z_testu.md").write_text(report.to_markdown(rep), encoding="utf-8")
        (out / "raport_polaczen.csv").write_text(report.to_csv(rep), encoding="utf-8")
        print("Połączenia:", rep["counts"], "| zapisano:", out / "raport_z_testu.md", "i", out / "raport_polaczen.csv")
    elif args.cmd == "llm":
        if not args.id and not args.all:
            ap.exit(2, "Podaj identyfikator projektu albo --all\n")
        try:
            print(llm.analyze_all(con) if args.all else llm.analyze_project(con, args.id))
        except (llm.ModelError, KeyError) as exc:
            ap.exit(1, f"Analiza LLM: {exc}\n")
    elif args.cmd == "eval-llm":
        import re as _re
        from riskminer import config, evaluate
        rep = evaluate.evaluate(con)
        out = Path(args.out or f"docs/llm_ewaluacja_{_re.sub(r'[^a-z0-9.]+', '_', config.LLM_MODEL.lower())}.md")
        out.write_text(evaluate.to_markdown(rep), encoding="utf-8")
        print({k: v for k, v in rep.items() if k != "rows"}, "| zapisano:", out)
    elif args.cmd == "show":
        pid = args.id
        for t, q in [
            ("POWIĄZANIA", "SELECT ocid, method, status, evidence FROM project_link WHERE project_id=?"),
            ("UMOWY", "SELECT c.part_no, contractor_name, signed_date, value, planned_end, actual_end, on_time, paid_total, n_changes, performing_notice FROM contract c JOIN active_project_link l ON l.ocid=c.ocid AND (l.part_no=0 OR l.part_no=c.part_no) WHERE l.project_id=?"),
            ("FAKTY", "SELECT kind, part_no, label, COALESCE(value_num, value_text) v, unit, source_notice, source_section FROM visible_fact WHERE project_id=? ORDER BY kind, key"),
            ("ZDARZENIA", "SELECT event_date, event_type, kind, title, details FROM visible_event WHERE project_id=? ORDER BY COALESCE(event_date,'9999'), id"),
            ("BRAKI", "SELECT key, message FROM gap WHERE project_id=?"),
        ]:
            print(f"\n## {t}")
            for r in con.execute(q, (pid,)):
                print("  ", " | ".join("" if v is None else str(v)[:110] for v in tuple(r)))


if __name__ == "__main__":
    sys.exit(main())
