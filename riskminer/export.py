"""Eksport bazy przypadków (treść zadania: „wyniki muszą być zapisywane jako rekordy możliwe do filtrowania,
aktualizacji i eksportu, np. do JSON lub CSV”).

- JSON: jeden plik, projekt po projekcie, z relacjami (powiązanie → postępowanie → umowy → zmiany,
  ogłoszenia, fakty, zdarzenia, braki, dokumenty BIP, decyzje eksperta),
- CSV: archiwum ZIP z tabelami (separator „;”, UTF-8 z BOM – otwiera się w Excelu).
Bez surowego HTML ogłoszeń i treści dokumentów – są w bazie, a w eksporcie zostają link i cytat.
Fakty i zdarzenia oparte na dokumentach odrzuconych przez eksperta są pominięte (widoki visible_*).
"""
import csv
import io
import json
import zipfile

from . import db

# tabela -> (zapytanie, opis)
TABLES = {
    "projekty": ("SELECT project_id, lp, name, recipient_name, recipient_id_type, recipient_id, recipient_type, voivodeship, "
                 "city, scope, part_no, public_id_type, public_id, theme, order_type, status, record_date, annotation, "
                 "last_fetch_at, last_fetch_status, last_fetch_message FROM project ORDER BY project_id",
                 "rekordy z arkusza organizatora i stan ostatniego pobrania"),
    "powiazania": ("SELECT project_id, ocid, part_no, method, score, status, evidence, created_at, updated_at "
                   "FROM project_link ORDER BY project_id", "projekt ↔ postępowanie (OCID): metoda, pewność, status eksperta"),
    "kandydaci_kpo": ("SELECT project_id, ocid, rank, title, base_notice, confidence, matched, checked, features_json AS kryteria "
                      "FROM link_candidate ORDER BY project_id, rank", "kandydaci dopasowania rekordów KPO z kryteriami"),
    "postepowania": ("SELECT * FROM procedure ORDER BY ocid", "postępowania BZP"),
    "ogloszenia": ("SELECT notice_number, notice_type, ocid, publication_date, order_object, organization_name, "
                   "organization_nip, source_url, fetched_at FROM notice ORDER BY ocid, publication_date",
                   "ogłoszenia BZP (bez treści HTML)"),
    "umowy": ("SELECT * FROM contract ORDER BY ocid, part_no", "umowy (część zamówienia, wartość, terminy, wypłata)"),
    "zmiany_umow": ("SELECT ch.*, c.ocid, c.part_no FROM contract_change ch JOIN contract c ON c.id=ch.contract_id "
                    "ORDER BY c.ocid, ch.source_notice, ch.change_no", "zmiany umów z podstawą prawną i przyczyną"),
    "fakty": ("SELECT * FROM visible_fact ORDER BY project_id, kind, key", "fakty, obliczenia i propozycje z dowodem"),
    "zdarzenia": ("SELECT * FROM visible_event ORDER BY project_id, COALESCE(event_date, '9999-12-31'), id",
                  "oś czasu, sygnały i propozycje ryzyk ze statusem eksperta"),
    "braki": ("SELECT * FROM gap ORDER BY project_id, key", "braki danych i niepewności"),
    "dokumenty": ("SELECT url, source, title, section, published_at, ext, status, fetched_at FROM document ORDER BY url",
                  "dokumenty z BIP (bez treści)"),
    "dokumenty_projektow": ("SELECT * FROM document_link ORDER BY project_id, url", "powiązania dokumentów BIP z projektami"),
    "decyzje_eksperta": ("SELECT * FROM expert_decision ORDER BY id", "historia decyzji eksperta"),
}


def _rows(con, sql, args=()):
    try:
        return [dict(r) for r in con.execute(sql, args)]
    except Exception:  # baza bez tabel BIP/LLM – eksport i tak powstaje
        return []


def to_json(con) -> dict:
    out = {"wygenerowano": db.now(), "zrodlo": "Risk Miner – baza przypadków",
           "opis_tabel": {k: v[1] for k, v in TABLES.items()}, "projekty": []}
    for p in _rows(con, TABLES["projekty"][0]):
        pid = p["project_id"]
        links = _rows(con, "SELECT ocid, part_no, method, score, status, evidence FROM active_project_link WHERE project_id=?", (pid,))
        for l in links:
            l["postepowanie"] = (_rows(con, "SELECT * FROM procedure WHERE ocid=?", (l["ocid"],)) or [None])[0]
            l["ogloszenia"] = _rows(con, "SELECT notice_number, notice_type, publication_date, order_object, source_url "
                                         "FROM notice WHERE ocid=? ORDER BY publication_date", (l["ocid"],))
            l["umowy"] = _rows(con, "SELECT * FROM contract WHERE ocid=? AND (?=0 OR part_no=?) ORDER BY part_no",
                               (l["ocid"], l["part_no"] or 0, l["part_no"] or 0))
            for c in l["umowy"]:
                c["zmiany"] = _rows(con, "SELECT change_no, change_date, legal_basis, reason, description, value_change, "
                                         "price_increase, source_notice, source_section FROM contract_change "
                                         "WHERE contract_id=? ORDER BY source_notice, change_no", (c["id"],))
        p["powiazania"] = links
        p["fakty"] = _rows(con, "SELECT kind, key, label, value_num, value_text, unit, level, part_no, formula, "
                                "source_notice, source_url, source_section, quote, fetched_at, status "
                                "FROM visible_fact WHERE project_id=? ORDER BY kind, key", (pid,))
        p["zdarzenia"] = _rows(con, "SELECT id, event_date, event_type, kind, title, details, status, expert_title, "
                                    "expert_comment, source_notice, source_url, source_section, quote "
                                    "FROM visible_event WHERE project_id=? ORDER BY COALESCE(event_date,'9999-12-31'), id", (pid,))
        p["braki"] = _rows(con, "SELECT key, message FROM gap WHERE project_id=?", (pid,))
        p["dokumenty"] = _rows(con, "SELECT d.url, d.source, d.title, d.section, d.published_at, d.status, l.* "
                                    "FROM document_link l JOIN document d ON d.url=l.url WHERE l.project_id=?", (pid,))
        out["projekty"].append(p)
    out["decyzje_eksperta"] = _rows(con, TABLES["decyzje_eksperta"][0])
    return out


def to_csv_zip(con) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        readme = ["Risk Miner – eksport bazy przypadków (CSV, separator ;, UTF-8 z BOM)", f"Wygenerowano: {db.now()}", ""]
        for name, (sql, desc) in TABLES.items():
            rows = _rows(con, sql)
            s = io.StringIO()
            if rows:
                w = csv.DictWriter(s, fieldnames=list(rows[0]), delimiter=";")
                w.writeheader()
                w.writerows(rows)
            z.writestr(f"{name}.csv", "﻿" + s.getvalue())
            readme.append(f"{name}.csv – {desc} ({len(rows)} wierszy)")
        z.writestr("CZYTAJ_MNIE.txt", "\n".join(readme) + "\n")
    return buf.getvalue()
