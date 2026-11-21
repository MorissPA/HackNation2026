"""Drugie źródło: Biuletyn Informacji Publicznej gminy (system d-bip.pl).

Konfiguracja: bip_sources.json (NIP zamawiającego -> adres BIP). Dla projektu:
1. przegląd sekcji BIP (z cache) i lista załączników: tytuł, sekcja, data publikacji,
2. wybór dokumentów: tytuł wspomina miejscowość projektu albo dokument jest planem finansowym
   (WPF, plan postępowań) – takie czytamy w całości,
3. odczyt treści (PDF strona po stronie, DOCX, ODT); skany i stare .doc zostają z tytułem i datą jako dowodem,
4. powiązanie z projektem: miejscowość + zakres projektu („przedsięwzięcie”) albo miejscowość + obiekt,
   od którego projekt zależy według opisu KPO („powiązana inwestycja”, np. oczyszczalnia, do której
   wpięta będzie sieć). Każde powiązanie ma cytat i stronę.
"""
import html
import io
import json
import re
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from . import config, db
from .matcher import _fold, places, stem

SOURCES_FILE = config.BASE_DIR / "bip_sources.json"
SCHEMA = """
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
    updated_at  TEXT,
    PRIMARY KEY (project_id, url)
);
"""
# zakres projektu -> wzorzec w tekście dokumentu
SCOPE = {
    "kanalizacja": r"kanalizac|kanał\w* sanitarn|ście\w* sanitarn|przepompown",
    "oczyszczalnia": r"oczyszczal",
    "wodociąg": r"wodociąg|sieci wodn",
    "stacja uzdatniania wody": r"uzdatniani\w* wody|\bSUW\b",
    "kanalizacja deszczowa": r"deszczow|opadow",
}
FINANCE = r"Wieloletni\w* Prognoz|\bWPF\b|Plan postępowań"
MAX_FINANCE_DOCS = 4       # najnowsze uchwały WPF / plany postępowań czytane w całości
MAX_PAGES = 400


def sources():
    try:
        data = json.loads(Path(SOURCES_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _scopes(text):
    return {k for k, rx in SCOPE.items() if re.search(rx, text or "", re.I)}


class DBip:
    """Klient BIP w systemie d-bip.pl z cache stron w SQLite."""

    def __init__(self, con, base_url, name, log=lambda m: None):
        self.con, self.base, self.name, self.log = con, base_url.rstrip("/") + "/", name, log
        con.executescript(SCHEMA)
        self.session = requests.Session()
        self.session.headers["User-Agent"] = config.USER_AGENT
        self.n_network = 0

    def _get(self, path, binary=False, ttl_hours=24.0):
        url = path if path.startswith("http") else self.base + path
        if not binary:
            row = self.con.execute("SELECT fetched_at, body FROM http_cache WHERE url=?", (url,)).fetchone()
            if row and datetime.now(timezone.utc) - datetime.fromisoformat(row["fetched_at"]) < timedelta(hours=ttl_hours):
                return row["body"]
        time.sleep(0.2)
        self.n_network += 1
        r = self.session.get(url, timeout=60)
        r.raise_for_status()
        if binary:
            return r.content
        text = r.content.decode("utf-8", "replace")
        self.con.execute("INSERT OR REPLACE INTO http_cache(url, fetched_at, status, body) VALUES (?,?,?,?)",
                         (url, db.now(), 200, text))
        self.con.commit()
        return text

    def attachments(self):
        """Wszystkie załączniki BIP: {url, title, section, published_at, ext}."""
        seen, queue, files, labels = set(), ["index.php"], {}, {}
        while queue and len(seen) < MAX_PAGES:
            page = queue.pop(0)
            if page in seen:
                continue
            seen.add(page)
            try:
                s = self._get(page)
            except requests.RequestException as e:
                self.log(f"BIP: nie udało się pobrać {page}: {e}")
                continue
            body = re.sub(r"<script.*?</script>|<style.*?</style>", "", s, flags=re.S)
            h1 = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
            section = html.unescape(re.sub(r"<[^>]+>|\s+", " ", h1.group(1))).strip() if h1 else ""
            section = section or labels.get(page, "")  # podstrony stronicowane nie mają nagłówka
            for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', body, re.S):
                href, label = m.group(1), html.unescape(re.sub(r"<[^>]+>|\s+", " ", m.group(2))).strip()
                if href.startswith("pliki/"):
                    after = body[m.end(): m.end() + 300]
                    d = re.search(r"\((\d{4}-\d{2}-\d{2})[ \d:]*\)", after)
                    files.setdefault(self.base + href, {
                        "url": self.base + href, "title": re.sub(r"\s*\([\d.,]+ [KM]B, \.\w+\)\s*$", "", label),
                        "section": section, "section_url": self.base + page,
                        "published_at": d.group(1) if d else None, "ext": href.rsplit(".", 1)[-1].lower()})
                    continue
                n = re.match(r"(?:index\.php)?\?strona=(\d+)$", href)
                nxt = f"index.php?strona={n.group(1)}" if n else (href if re.match(r"^[^/:?#]+,m\d+,s\d+(,p\d+)?\.html$", href) else None)
                if nxt and nxt not in seen and nxt not in queue:
                    queue.append(nxt)
                    # podstrona stronicowania dziedziczy nazwę sekcji
                    labels.setdefault(nxt, section if re.search(r",p\d+\.html$", nxt) else label)
        self.log(f"{self.name}: {len(seen)} stron, {len(files)} załączników")
        return list(files.values())

    def document(self, att):
        """Treść dokumentu (cache bez TTL – opublikowany plik się nie zmienia)."""
        row = self.con.execute("SELECT * FROM document WHERE url=?", (att["url"],)).fetchone()
        if row:
            return dict(row)
        pages, status = [], "ok"
        try:
            content = self._get(att["url"], binary=True)
            if att["ext"] == "pdf":
                from pypdf import PdfReader
                pages = [p.extract_text() or "" for p in PdfReader(io.BytesIO(content)).pages]
                if sum(len(p.strip()) for p in pages) < 50:
                    status, pages = "skan", []
            elif att["ext"] in ("docx", "odt"):
                z = zipfile.ZipFile(io.BytesIO(content))
                xml = z.read("word/document.xml" if att["ext"] == "docx" else "content.xml").decode("utf-8", "replace")
                pages = [html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"</(w:p|text:p|text:h)>", "\n", xml)))]
            else:
                status = "format"
        except Exception as e:  # uszkodzony plik / sieć – dokument zostaje z tytułem
            status = "błąd"
            self.log(f"BIP: {att['url']}: {e}")
        doc = {"url": att["url"], "source": self.name, "title": att["title"], "section": att["section"],
               "published_at": att["published_at"], "ext": att["ext"], "status": status,
               "pages_json": json.dumps(pages, ensure_ascii=False), "fetched_at": db.now()}
        db.upsert(self.con, "document", doc, ["url"], preserve=())
        self.con.commit()
        return doc


def _find(pages, place_rx, scope_rx, window=250):
    """Pierwsze miejsce, gdzie miejscowość i zakres występują blisko siebie: (strona, cytat)."""
    for i, p in enumerate(pages, 1):
        t = re.sub(r"\s+", " ", p)
        for m in re.finditer(place_rx, t, re.I):
            a, b = max(0, m.start() - window), min(len(t), m.end() + window)
            if re.search(scope_rx, t[a:b], re.I):
                qa, qb = max(0, m.start() - 160), min(len(t), m.end() + 200)
                return i, ("…" if qa else "") + t[qa:qb].strip() + ("…" if qb < len(t) else "")
    return None


def evidence_for_project(con, project, log=lambda m: None):
    """Dokumenty BIP powiązane z projektem: lista {doc, relation, page, quote}. Pusta, gdy brak BIP dla NIP-u."""
    src = sources().get(re.sub(r"\D", "", project.get("recipient_id") or ""))
    if not src or src.get("cms") != "d-bip":
        return None
    client = DBip(con, src["url"], src["name"], log)
    pl = [p for p in places(project.get("name")) if _fold(p) not in _fold(project.get("recipient_name") or "")] \
        or places(project.get("name"))
    if not pl:
        return []
    place_rx = "|".join(re.escape(stem(p)) for p in pl)
    own = _scopes(project.get("name"))
    related = _scopes(project.get("annotation")) - own   # obiekty, od których projekt zależy (z opisu KPO)
    own_rx = "|".join(SCOPE[s] for s in own) or r"$^"
    rel_rx = "|".join(SCOPE[s] for s in related) or r"$^"

    atts = client.attachments()
    by_title = [a for a in atts if re.search(place_rx, a["title"], re.I) and re.search(f"{own_rx}|{rel_rx}", a["title"], re.I)]
    finance = sorted([a for a in atts if re.search(FINANCE, a["title"], re.I)],
                     key=lambda a: a["published_at"] or "", reverse=True)[:MAX_FINANCE_DOCS]
    log(f"{src['name']}: {len(by_title)} dokumentów z miejscowością w tytule, {len(finance)} najnowszych planów finansowych")
    out = []
    for att in by_title + [a for a in finance if a not in by_title]:
        doc = client.document(att)
        pages = json.loads(doc["pages_json"] or "[]")
        title_own = bool(re.search(own_rx, att["title"], re.I))
        hit = _find(pages, place_rx, own_rx) or (None if title_own else _find(pages, place_rx, rel_rx))
        if not hit and att not in by_title:
            continue  # plan finansowy bez wzmianki o projekcie
        if hit:
            page, quote = hit
            relation = "przedsięwzięcie" if re.search(own_rx, quote, re.I) else "powiązana inwestycja: " + ", ".join(sorted(related))
        else:
            page, quote = None, att["title"]
            relation = "przedsięwzięcie" if title_own else "powiązana inwestycja: " + ", ".join(sorted(related))
        out.append({"doc": doc, "relation": relation, "page": page, "quote": quote})
    log(f"{src['name']}: powiązanych dokumentów {len(out)} (zapytań sieciowych {client.n_network})")
    return out
