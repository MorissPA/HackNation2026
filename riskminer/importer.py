"""Import arkusza projektów (XLSX/CSV).

- identyfikatory zawsze jako tekst (NIP, TERYT '02', numery BZP),
- błąd w jednym wierszu nie zatrzymuje pozostałych – raport na poziomie rekordu,
- ponowny import aktualizuje rekord po `Identyfikator rekordu` (bez duplikatów).
"""
import csv
import io
import re
from pathlib import Path

from . import db

# nagłówek w arkuszu -> kolumna w tabeli project
COLUMN_MAP = {
    "lp.": "lp",
    "identyfikator rekordu": "project_id",
    "rodzaj identyfikatora odbiorcy": "recipient_id_type",
    "identyfikator odbiorcy": "recipient_id",
    "nazwa odbiorcy": "recipient_name",
    "typ odbiorcy": "recipient_type",
    "kraj": "country",
    "kod województwa (teryt)": "teryt_voiv",
    "województwo": "voivodeship",
    "siedziba odbiorcy": "city",
    "nazwa przedsięwzięcia": "name",
    "zakres rekordu": "scope",
    "rodzaj identyfikatora publicznego": "public_id_type",
    "identyfikator publiczny": "public_id",
    "obszar tematyczny": "theme",
    "rodzaj zamówienia": "order_type",
    "reżim prawny": "legal_regime",
    "waluta rozliczeń": "currency",
    "status przedsięwzięcia": "status",
    "źródło rekordu": "record_source",
    "data sporządzenia rekordu": "record_date",
    "wersja rekordu": "record_version",
    "adnotacja instytucji": "annotation",
}
REQUIRED = ("project_id", "name")
BZP_RE = re.compile(r"^\d{4}/BZP \d{8}/\d{2}$")
KPO_RE = re.compile(r"^KPO[A-Z]?\.\d{2}\.\d{2}-[A-Z]{2}\.\d{2}-\d{4}/\d{2}$")


def _norm_header(h) -> str:
    return re.sub(r"\s+", " ", str(h or "")).strip().lower()


def _as_text(v):
    """Wartość komórki -> tekst bez utraty zer wiodących i bez '.0'."""
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if hasattr(v, "isoformat"):
        return v.isoformat()[:10]
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s or None


def parse_part_no(scope):
    if not scope:
        return 0
    m = re.search(r"cz(?:ęść|esc)\s*(?:nr\s*)?(\d+)", scope, re.I)
    return int(m.group(1)) if m else 0


def read_rows(filename: str, content: bytes):
    """Zwraca (lista (row_no, dict nagłówek->wartość), lista ostrzeżeń o pliku)."""
    ext = Path(filename).suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb["Projekty"] if "Projekty" in wb.sheetnames else wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        header = next(it)
        rows = [(i, dict(zip(header, r))) for i, r in enumerate(it, start=2)]
    elif ext in (".csv", ".txt"):
        text = content.decode("utf-8-sig")
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        rows = [(i, r) for i, r in enumerate(reader, start=2)]
    else:
        raise ValueError(f"Nieobsługiwany format pliku: {ext}")
    return rows


def map_row(raw: dict):
    out, unknown = {}, []
    for k, v in raw.items():
        col = COLUMN_MAP.get(_norm_header(k))
        if col:
            out[col] = _as_text(v)
        elif k is not None and _norm_header(k):
            unknown.append(str(k))
    return out, unknown


def validate(rec: dict):
    errors, warnings = [], []
    for f in REQUIRED:
        if not rec.get(f):
            errors.append(f"brak wymaganego pola '{f}'")
    pid_type, pid = rec.get("public_id_type") or "", rec.get("public_id") or ""
    if not pid:
        warnings.append("brak identyfikatora publicznego – dopasowanie tylko po nazwie")
    elif "BZP" in pid_type and not BZP_RE.match(pid):
        warnings.append(f"nietypowy format numeru BZP: {pid}")
    elif "KPO" in pid_type and not KPO_RE.match(pid):
        warnings.append(f"nietypowy format numeru KPO: {pid}")
    if rec.get("recipient_id_type") == "NIP" and rec.get("recipient_id"):
        nip = re.sub(r"\D", "", rec["recipient_id"])
        if len(nip) != 10:
            warnings.append(f"NIP ma {len(nip)} cyfr")
    return errors, warnings


def import_file(con, filename: str, content: bytes) -> dict:
    """Importuje plik i zwraca raport: {run_id, counts, rows:[...]}"""
    started = db.now()
    cur = con.execute(
        "INSERT INTO import_run(started_at, kind, source) VALUES (?,?,?)", (started, "excel", filename)
    )
    run_id = cur.lastrowid
    report_rows, counts = [], {"nowy": 0, "zaktualizowany": 0, "bez_zmian": 0, "błąd": 0}

    try:
        rows = read_rows(filename, content)
    except Exception as e:  # cały plik nieczytelny
        con.execute(
            "INSERT INTO import_row(run_id,row_no,project_id,status,message) VALUES (?,?,?,?,?)",
            (run_id, None, None, "błąd", f"Nie można odczytać pliku: {e}"),
        )
        con.execute("UPDATE import_run SET finished_at=?, n_error=1 WHERE id=?", (db.now(), run_id))
        con.commit()
        return {"run_id": run_id, "counts": {"błąd": 1}, "rows": [{"row_no": None, "status": "błąd", "message": str(e)}]}

    for row_no, raw in rows:
        if all(v in (None, "") for v in raw.values()):
            continue  # pusty wiersz
        try:
            rec, unknown = map_row(raw)
            errors, warnings = validate(rec)
            if unknown:
                warnings.append("pominięte kolumny: " + ", ".join(unknown))
            if errors:
                raise ValueError("; ".join(errors))
            rec["part_no"] = parse_part_no(rec.get("scope"))
            raw_json = db.dumps(rec)
            existing = con.execute(
                "SELECT raw_json FROM project WHERE project_id=?", (rec["project_id"],)
            ).fetchone()
            ts = db.now()
            if existing is None:
                status = "nowy"
            elif existing["raw_json"] == raw_json:
                status = "bez_zmian"
            else:
                status = "zaktualizowany"
            if status != "bez_zmian":
                row = dict(rec, raw_json=raw_json, source_file=filename, source_row=row_no,
                           created_at=ts, updated_at=ts)
                db.upsert(con, "project", row, ["project_id"], preserve=("created_at",))
            counts[status] += 1
            msg = "; ".join(warnings) if warnings else None
            report_rows.append({"row_no": row_no, "project_id": rec["project_id"], "status": status, "message": msg})
        except Exception as e:
            counts["błąd"] += 1
            report_rows.append({"row_no": row_no, "project_id": (raw.get("Identyfikator rekordu") if isinstance(raw, dict) else None),
                                "status": "błąd", "message": str(e)})
    for r in report_rows:
        con.execute(
            "INSERT INTO import_row(run_id,row_no,project_id,status,message) VALUES (?,?,?,?,?)",
            (run_id, r["row_no"], r["project_id"], r["status"], r["message"]),
        )
    con.execute(
        "UPDATE import_run SET finished_at=?, n_ok=?, n_updated=?, n_unchanged=?, n_error=? WHERE id=?",
        (db.now(), counts["nowy"], counts["zaktualizowany"], counts["bez_zmian"], counts["błąd"], run_id),
    )
    con.commit()
    return {"run_id": run_id, "counts": counts, "rows": report_rows}
