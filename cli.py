"""CLI: import arkusza i pobranie danych z BZP.

  python cli.py import ../Risk_Miner_dane_projekty.xlsx
  python cli.py fetch RM-2026-003            # jeden projekt
  python cli.py fetch --all                  # wszystkie rekordy
  python cli.py show RM-2026-003             # podsumowanie karty
"""
import argparse
import sys
from pathlib import Path

from riskminer import db, importer, pipeline
from riskminer.bzp.client import BZPClient


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("import"); a.add_argument("path")
    f = sub.add_parser("fetch"); f.add_argument("ids", nargs="*"); f.add_argument("--all", action="store_true")
    f.add_argument("--offline", action="store_true")
    s = sub.add_parser("show"); s.add_argument("id")
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
    elif args.cmd == "show":
        pid = args.id
        for t, q in [
            ("POWIĄZANIA", "SELECT ocid, method, status, evidence FROM project_link WHERE project_id=?"),
            ("UMOWY", "SELECT c.part_no, contractor_name, signed_date, value, planned_end, actual_end, on_time, paid_total, n_changes, performing_notice FROM contract c JOIN project_link l ON l.ocid=c.ocid WHERE l.project_id=?"),
            ("FAKTY", "SELECT kind, part_no, label, COALESCE(value_num, value_text) v, unit, source_notice, source_section FROM fact WHERE project_id=? ORDER BY kind, key"),
            ("ZDARZENIA", "SELECT event_date, event_type, kind, title, details FROM event WHERE project_id=? ORDER BY COALESCE(event_date,'9999'), id"),
            ("BRAKI", "SELECT key, message FROM gap WHERE project_id=?"),
        ]:
            print(f"\n## {t}")
            for r in con.execute(q, (pid,)):
                print("  ", " | ".join("" if v is None else str(v)[:110] for v in tuple(r)))


if __name__ == "__main__":
    sys.exit(main())
