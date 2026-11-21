"""SQLite: schemat i pomocnicze funkcje.

Zasady modelu:
- projekt (wiersz z arkusza) ≠ postępowanie (OCID) ≠ umowa ≠ ogłoszenie ≠ zmiana ≠ zdarzenie,
- każdy fakt/zdarzenie ma źródło (numer ogłoszenia, URL, sekcja), datę pobrania i status weryfikacji,
- rozróżniamy rodzaj wpisu: 'fakt' (odczyt z dokumentu), 'obliczenie', 'propozycja' (do oceny eksperta),
- powtórny import robi UPSERT po kluczach naturalnych, więc nie mnoży rekordów.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config, risks

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS project (
    project_id          TEXT PRIMARY KEY,         -- 'Identyfikator rekordu', np. RM-2026-003
    lp                  TEXT,
    recipient_id_type   TEXT,
    recipient_id        TEXT,                      -- NIP jako tekst (zera wiodące!)
    recipient_name      TEXT,
    recipient_type      TEXT,
    country             TEXT,
    teryt_voiv          TEXT,
    voivodeship         TEXT,
    city                TEXT,
    name                TEXT NOT NULL,
    scope               TEXT,                      -- 'całe postępowanie' / 'część 1' ...
    part_no             INTEGER,                   -- wyliczone ze 'scope'
    public_id_type      TEXT,                      -- 'Ogłoszenie BZP' / 'Projekt KPO'
    public_id           TEXT,
    theme               TEXT,
    order_type          TEXT,
    legal_regime        TEXT,
    currency            TEXT,
    status              TEXT,
    record_source       TEXT,
    record_date         TEXT,
    record_version      TEXT,
    annotation          TEXT,
    raw_json            TEXT,
    source_file         TEXT,
    source_row          INTEGER,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    last_fetch_at       TEXT,
    last_fetch_status   TEXT,
    last_fetch_message  TEXT
);

CREATE TABLE IF NOT EXISTS import_run (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    kind        TEXT NOT NULL,                     -- 'excel' / 'bzp'
    source      TEXT,
    n_ok        INTEGER DEFAULT 0,
    n_updated   INTEGER DEFAULT 0,
    n_unchanged INTEGER DEFAULT 0,
    n_error     INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS import_row (
    run_id      INTEGER NOT NULL REFERENCES import_run(id) ON DELETE CASCADE,
    row_no      INTEGER,
    project_id  TEXT,
    status      TEXT NOT NULL,                     -- nowy / zaktualizowany / bez_zmian / błąd / ostrzeżenie
    message     TEXT
);

CREATE TABLE IF NOT EXISTS http_cache (
    url         TEXT PRIMARY KEY,
    fetched_at  TEXT NOT NULL,
    status      INTEGER,
    body        TEXT
);

CREATE TABLE IF NOT EXISTS notice (
    notice_number     TEXT PRIMARY KEY,            -- '2024/BZP 00349631/01'
    bzp_number        TEXT,
    notice_type       TEXT NOT NULL,
    ocid              TEXT,
    object_id         TEXT,
    publication_date  TEXT,
    order_object      TEXT,
    organization_name TEXT,
    organization_id   TEXT,
    organization_nip  TEXT,
    meta_json         TEXT,                        -- metadane z wyszukiwarki
    html              TEXT,
    text              TEXT,
    fields_json       TEXT,                        -- sparsowane pola [{code,label,value,section}]
    source_url        TEXT,
    fetched_at        TEXT
);
CREATE INDEX IF NOT EXISTS ix_notice_ocid ON notice(ocid);

CREATE TABLE IF NOT EXISTS procedure (
    ocid              TEXT PRIMARY KEY,
    title             TEXT,
    organization_name TEXT,
    organization_id   TEXT,
    base_notice       TEXT,
    reference_no      TEXT,
    estimated_value   REAL,                        -- wartość zamówienia z ogł. o wyniku
    has_parts         INTEGER,
    updated_at        TEXT
);

-- Powiązanie projekt ↔ postępowanie (z metodą dopasowania i statusem weryfikacji).
CREATE TABLE IF NOT EXISTS project_link (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT NOT NULL REFERENCES project(project_id) ON DELETE CASCADE,
    ocid        TEXT NOT NULL,
    part_no     INTEGER,
    method      TEXT NOT NULL,                     -- 'numer_bzp' / 'nazwa+zamawiający' / 'ekspert'
    score       REAL,
    evidence    TEXT,
    status      TEXT NOT NULL DEFAULT 'proponowane', -- proponowane / potwierdzone / odrzucone
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE(project_id, ocid)
);

-- Kandydaci dopasowania rekordu KPO do postępowania (ranking z uzasadnieniem).
CREATE TABLE IF NOT EXISTS link_candidate (
    project_id      TEXT NOT NULL REFERENCES project(project_id) ON DELETE CASCADE,
    ocid            TEXT NOT NULL,
    rank            INTEGER,
    score           REAL,
    title           TEXT,
    base_notice     TEXT,
    base_meta_json  TEXT,
    features_json   TEXT,                          -- kryteria: [{name, status, detail}]
    notices_json    TEXT,
    created_at      TEXT,
    confidence      TEXT,                          -- wysoka / średnia / niska
    matched         INTEGER,                       -- spełnione kryteria
    checked         INTEGER,                       -- kryteria możliwe do sprawdzenia
    PRIMARY KEY (project_id, ocid)
);

CREATE TABLE IF NOT EXISTS contract (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ocid              TEXT NOT NULL,
    part_no           INTEGER NOT NULL DEFAULT 0,  -- 0 = całe postępowanie
    contractor_name   TEXT,
    contractor_id     TEXT,
    signed_date       TEXT,
    value             REAL,
    currency          TEXT,
    planned_end       TEXT,                        -- termin z umowy pierwotnej
    actual_end        TEXT,                        -- z ogłoszenia o wykonaniu
    on_time           TEXT,                        -- 'Tak'/'Nie'
    paid_total        REAL,
    properly_executed TEXT,
    n_changes         INTEGER,
    source_notice     TEXT,
    performing_notice TEXT,
    updated_at        TEXT,
    UNIQUE(ocid, part_no)
);

CREATE TABLE IF NOT EXISTS contract_change (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id     INTEGER NOT NULL REFERENCES contract(id) ON DELETE CASCADE,
    change_no       TEXT,                          -- nr zmiany (z ogł. o wykonaniu) lub data
    change_date     TEXT,
    legal_basis     TEXT,
    reason          TEXT,
    description     TEXT,
    value_change    REAL,
    currency        TEXT,
    price_increase  TEXT,
    source_notice   TEXT NOT NULL,
    source_section  TEXT,
    updated_at      TEXT,
    UNIQUE(contract_id, source_notice, change_no)
);

-- Fakty, obliczenia i propozycje – każdy z dowodem.
CREATE TABLE IF NOT EXISTS fact (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      TEXT NOT NULL REFERENCES project(project_id) ON DELETE CASCADE,
    ocid            TEXT,
    part_no         INTEGER NOT NULL DEFAULT 0,
    kind            TEXT NOT NULL CHECK (kind IN ('fakt','obliczenie','propozycja')),
    key             TEXT NOT NULL,
    label           TEXT,
    value_num       REAL,
    value_text      TEXT,
    unit            TEXT,
    level           TEXT,                          -- 'umowa' / 'postępowanie' / 'projekt'
    source_notice   TEXT,
    source_url      TEXT,
    source_section  TEXT,
    quote           TEXT,
    formula         TEXT,                          -- dla obliczeń
    fetched_at      TEXT,
    status          TEXT NOT NULL DEFAULT 'do_weryfikacji',
    updated_at      TEXT,
    UNIQUE(project_id, key, part_no, source_notice)
);

CREATE TABLE IF NOT EXISTS event (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      TEXT NOT NULL REFERENCES project(project_id) ON DELETE CASCADE,
    ocid            TEXT,
    part_no         INTEGER NOT NULL DEFAULT 0,
    event_date      TEXT,
    event_type      TEXT NOT NULL,
    title           TEXT NOT NULL,
    details         TEXT,
    kind            TEXT NOT NULL DEFAULT 'fakt',
    source_notice   TEXT,
    source_url      TEXT,
    source_section  TEXT,
    quote           TEXT,
    status          TEXT NOT NULL DEFAULT 'do_weryfikacji',
    expert_title    TEXT,                          -- kategoria/tytuł po decyzji eksperta
    expert_comment  TEXT,
    updated_at      TEXT,
    UNIQUE(project_id, event_type, part_no, source_notice, title)
);


CREATE TABLE IF NOT EXISTS llm_run (
    source_id INTEGER PRIMARY KEY REFERENCES event(id) ON DELETE CASCADE,
    signature TEXT NOT NULL,
    proposal_id INTEGER REFERENCES event(id) ON DELETE CASCADE
);
CREATE TRIGGER IF NOT EXISTS invalidate_pending_llm AFTER UPDATE OF quote, source_section, details, source_url ON event
WHEN OLD.event_type IN ('zmiana_umowy','dokument BIP')
 AND (NEW.quote IS NOT OLD.quote OR NEW.source_section IS NOT OLD.source_section
      OR NEW.details IS NOT OLD.details OR NEW.source_url IS NOT OLD.source_url)
BEGIN
    DELETE FROM event WHERE id=(SELECT proposal_id FROM llm_run WHERE source_id=OLD.id)
    AND status='do_weryfikacji';
    DELETE FROM llm_run WHERE source_id=OLD.id AND proposal_id IS NULL;
END;
CREATE TRIGGER IF NOT EXISTS remove_pending_llm BEFORE DELETE ON event
WHEN OLD.event_type IN ('zmiana_umowy','dokument BIP')
BEGIN
    DELETE FROM event WHERE id=(SELECT proposal_id FROM llm_run WHERE source_id=OLD.id)
    AND status='do_weryfikacji';
END;

CREATE TABLE IF NOT EXISTS document (
    url           TEXT PRIMARY KEY,
    source        TEXT NOT NULL,           -- np. 'BIP Gminy Zagrodno'
    title         TEXT,
    section       TEXT,
    published_at  TEXT,
    ext           TEXT,
    status        TEXT,                    -- ok / skan / format / błąd
    pages_json    TEXT,                    -- treść strona po stronie
    fetched_at    TEXT
);
CREATE TABLE IF NOT EXISTS document_link (
    project_id  TEXT NOT NULL REFERENCES project(project_id) ON DELETE CASCADE,
    url         TEXT NOT NULL REFERENCES document(url) ON DELETE CASCADE,
    relation    TEXT NOT NULL,             -- przedsięwzięcie / powiązana inwestycja: ...
    page        INTEGER,
    quote       TEXT,
    reason      TEXT,
    location    TEXT,
    review_status TEXT NOT NULL DEFAULT 'do_weryfikacji',
    updated_at  TEXT,
    PRIMARY KEY (project_id, url)
);

CREATE TABLE IF NOT EXISTS document_review (
    id INTEGER PRIMARY KEY,
    project_id TEXT NOT NULL,
    url TEXT NOT NULL,
    status TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    FOREIGN KEY(project_id, url) REFERENCES document_link(project_id, url) ON DELETE CASCADE
);
-- Brakujące dane – widoczne w karcie projektu.
CREATE TABLE IF NOT EXISTS gap (
    project_id  TEXT NOT NULL REFERENCES project(project_id) ON DELETE CASCADE,
    key         TEXT NOT NULL,
    message     TEXT NOT NULL,
    updated_at  TEXT,
    PRIMARY KEY (project_id, key)
);

-- Historia decyzji eksperta (dowolny obiekt).
CREATE TABLE IF NOT EXISTS expert_decision (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    target      TEXT NOT NULL,                     -- 'fact' / 'event' / 'project_link'
    target_id   INTEGER NOT NULL,
    decision    TEXT NOT NULL,                     -- zaakceptowane / odrzucone / poprawione
    comment     TEXT,
    old_value   TEXT,
    new_value   TEXT,
    author      TEXT,
    created_at  TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path=None) -> sqlite3.Connection:
    path = path or config.DB_PATH
    if str(path) != ":memory:":
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    _migrate(con)
    return con


def _migrate(con):
    """Proste migracje dla istniejących baz (dodane kolumny)."""
    cols = {r["name"] for r in con.execute("PRAGMA table_info(event)")}
    for col in ("expert_title", "expert_comment"):
        if col not in cols:
            con.execute(f"ALTER TABLE event ADD COLUMN {col} TEXT")
    if "exemplar" not in cols:  # przykład wzorcowy oznaczony przez eksperta
        con.execute("ALTER TABLE event ADD COLUMN exemplar INTEGER NOT NULL DEFAULT 0")
    if "confidence" not in cols:  # pewność propozycji modelu: 'wysoka' (zgodna z regułami) / 'niska'
        con.execute("ALTER TABLE event ADD COLUMN confidence TEXT")
    # druga przyczyna z tego samego źródła („… · źródło N #2”) znika razem ze zmienionym/usuniętym źródłem
    con.execute("""CREATE TRIGGER IF NOT EXISTS invalidate_pending_llm_second AFTER UPDATE OF quote, source_section, details, source_url ON event
        WHEN OLD.event_type IN ('zmiana_umowy','dokument BIP')
         AND (NEW.quote IS NOT OLD.quote OR NEW.source_section IS NOT OLD.source_section
              OR NEW.details IS NOT OLD.details OR NEW.source_url IS NOT OLD.source_url)
        BEGIN
            DELETE FROM event WHERE event_type='ryzyko LLM' AND status='do_weryfikacji'
              AND project_id=OLD.project_id AND title LIKE '% · źródło ' || OLD.id || ' #2';
        END""")
    con.execute("""CREATE TRIGGER IF NOT EXISTS remove_pending_llm_second BEFORE DELETE ON event
        WHEN OLD.event_type IN ('zmiana_umowy','dokument BIP')
        BEGIN
            DELETE FROM event WHERE event_type='ryzyko LLM' AND status='do_weryfikacji'
              AND project_id=OLD.project_id AND title LIKE '% · źródło ' || OLD.id || ' #2';
        END""")
    # otwarty katalog ryzyk: R01–R15 + kategorie zaproponowane przez eksperta (do zatwierdzenia)
    con.execute("""CREATE TABLE IF NOT EXISTS risk_category (
        code TEXT PRIMARY KEY, name TEXT NOT NULL, effects TEXT,
        status TEXT NOT NULL DEFAULT 'zatwierdzona',   -- zatwierdzona / proponowana / odrzucona
        proposed_by TEXT, comment TEXT, created_at TEXT, decided_at TEXT)""")
    if not con.execute("SELECT count(*) FROM risk_category").fetchone()[0]:
        con.executemany("INSERT INTO risk_category(code, name, effects, status, proposed_by, created_at) "
                        "VALUES (?,?,?,'zatwierdzona','materiał ekspercki organizatora',?)",
                        [(c, n, e, now()) for c, n, e in risks.BASE_CATALOG])
    # ustawienia edytowalne bez zmian w kodzie (np. reguły interpretacyjne dla modelu)
    con.execute("CREATE TABLE IF NOT EXISTS setting (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")
    cols = {r["name"] for r in con.execute("PRAGMA table_info(link_candidate)")}
    for col, typ in (("confidence", "TEXT"), ("matched", "INTEGER"), ("checked", "INTEGER")):
        if col not in cols:
            con.execute(f"ALTER TABLE link_candidate ADD COLUMN {col} {typ}")
    cols = {r["name"] for r in con.execute("PRAGMA table_info(document_link)")}
    if not {"reason", "location", "review_status"}.issubset(cols):
        if not con.in_transaction:
            con.execute("BEGIN IMMEDIATE")
        cols = {r["name"] for r in con.execute("PRAGMA table_info(document_link)")}
        for name, typ in (("reason", "TEXT"), ("location", "TEXT"),
                          ("review_status", "TEXT NOT NULL DEFAULT 'do_weryfikacji'")):
            if name not in cols:
                con.execute(f"ALTER TABLE document_link ADD COLUMN {name} {typ}")
    for table in ("event", "fact"):
        con.execute(f"""CREATE VIEW IF NOT EXISTS visible_{table} AS SELECT item.* FROM {table} item
                        WHERE NOT EXISTS (SELECT 1 FROM document_link link
                        WHERE link.project_id=item.project_id AND link.url=item.source_url
                        AND link.review_status='odrzucone')""")
    con.commit()
    risks.load(con)


def get_setting(con, key, default=None):
    row = con.execute("SELECT value FROM setting WHERE key=?", (key,)).fetchone()
    return row[0] if row and row[0] is not None else default


def set_setting(con, key, value):
    con.execute("INSERT INTO setting(key, value, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at", (key, value, now()))
    con.commit()


@contextmanager
def tx(con: sqlite3.Connection):
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise


def upsert(con, table: str, row: dict, keys: list, preserve: tuple = ("status", "created_at")):
    """INSERT ... ON CONFLICT(keys) DO UPDATE – nie nadpisuje pól z `preserve`
    (np. statusu weryfikacji ustawionego przez eksperta). Zwraca id/None."""
    cols = list(row.keys())
    placeholders = ",".join("?" for _ in cols)
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c not in keys and c not in preserve)
    sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders}) ON CONFLICT({','.join(keys)}) "
    sql += f"DO UPDATE SET {updates}" if updates else "DO NOTHING"
    con.execute(sql, [row[c] for c in cols])
    where = " AND ".join(f"{k} IS ?" for k in keys)
    r = con.execute(f"SELECT rowid AS rid FROM {table} WHERE {where}", [row[k] for k in keys]).fetchone()
    return r["rid"] if r else None


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)
