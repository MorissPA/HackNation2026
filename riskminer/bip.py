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
        data = json.loads(Path(config.BIP_SOURCES_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _scopes(text):
    return {k for k, rx in SCOPE.items() if re.search(rx, text or "", re.I)}


class DBip:
    """Klient BIP w systemie d-bip.pl z cache stron w SQLite."""

    def __init__(self, con, base_url, name, log=lambda m: None):
        self.con, self.base, self.name, self.log = con, base_url.rstrip("/") + "/", name, log
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
                raise RuntimeError(f"Niepełny odczyt BIP na stronie {page}: {e}") from e
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
        if queue:
            raise RuntimeError(f"Przegląd BIP przekroczył limit {MAX_PAGES} stron")
        self.log(f"{self.name}: {len(seen)} stron, {len(files)} załączników")
        return list(files.values())

    def document(self, att):
        """Treść dokumentu (cache bez TTL – opublikowany plik się nie zmienia)."""
        row = self.con.execute("SELECT * FROM document WHERE url=?", (att["url"],)).fetchone()
        if row and row["status"] != "błąd":
            return dict(row)
        pages, status = [], "ok"
        try:
            content = self._get(att["url"], binary=True)
            if att["ext"] == "pdf":
                from pypdf import PdfReader
                pages = [p.extract_text() or "" for p in PdfReader(io.BytesIO(content)).pages]
                if not any(p.strip() for p in pages):
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


def _find(pages, place_rx, scope_rx, financial=False, window=250):
    """Pierwsze miejsce, gdzie miejscowość i zakres występują blisko siebie: (strona, cytat)."""
    for i, p in enumerate(pages, 1):
        t = re.sub(r"\s+", " ", p)
        # Numery pozycji w tabelach WPF oddzielają kwoty sąsiednich inwestycji.
        rows = re.split(r"(?<!\S)(?=\d+\.\d+\.\d+\.\d+\.?\s)", t) if financial else [t]
        for row in rows:
            for m in re.finditer(place_rx, row, re.I):
                a, b = max(0, m.start() - window), min(len(row), m.end() + window)
                if re.search(scope_rx, row[a:b], re.I):
                    return i, ("…" if a else "") + row[a:b].strip() + ("…" if b < len(row) else "")
    return None


def evidence_for_project(con, project, log=lambda m: None):
    """Dokumenty BIP powiązane z projektem: lista {doc, relation, page, quote}. Pusta, gdy brak BIP dla NIP-u."""
    src = sources().get(re.sub(r"\D", "", project.get("recipient_id") or ""))
    if not src or src.get("cms") != "d-bip":
        return None
    client = DBip(con, src["url"], src["name"], log)
    pl = [p for p in places(project.get("name")) if _fold(p) not in _fold(project.get("recipient_name") or "")] \
        or places(project.get("name"))
    place_rx = "|".join(re.escape(stem(p)) for p in pl) or r"(?!)"
    own = _scopes(project.get("name"))
    related = _scopes(project.get("annotation")) - own   # obiekty, od których projekt zależy (z opisu KPO)
    own_rx = "|".join(SCOPE[s] for s in own) or r"(?!)"
    rel_rx = "|".join(SCOPE[s] for s in related) or r"(?!)"

    # Uwzględnij identyfikatory tylko dla aktywnych powiązań i właściwej części.
    terms = []
    public_id = project.get("public_id")
    if public_id and ("BZP" not in (project.get("public_id_type") or "").upper() or con.execute(
            "SELECT 1 FROM active_project_link l WHERE project_id=? AND status='potwierdzone' AND "
            "(instr(l.evidence, ?) > 0 OR EXISTS (SELECT 1 FROM notice n WHERE n.ocid=l.ocid AND n.notice_number=?))",
            (project["project_id"], public_id, public_id)).fetchone()):
        terms.append((public_id, "identyfikator z arkusza"))
    for row in con.execute("""SELECT l.ocid, n.notice_number, c.contractor_name FROM active_project_link l
            LEFT JOIN notice n ON l.ocid=n.ocid LEFT JOIN contract c ON c.ocid=l.ocid
            AND (l.part_no=0 OR c.part_no=l.part_no)
            WHERE l.project_id=?""", (project["project_id"],)):
        terms.extend(zip(row, ("OCID", "numer BZP", "wykonawca")))
    identifiers = {}
    for value, label in terms:
        if value:
            identifiers.setdefault(" ".join(value.split()).casefold(), label)

    def term_hit(text):
        normalized = " ".join(text.split()).casefold()
        for value, label in identifiers.items():
            match = re.search(r"(?<!\w)" + re.escape(value) + r"(?!\w)", normalized)
            if match:
                return label, match
        return None

    atts = client.attachments()
    by_title = [a for a in atts if term_hit(a["title"]) or (re.search(place_rx, a["title"], re.I)
                and re.search(f"{own_rx}|{rel_rx}", a["title"], re.I))]
    finance = sorted([a for a in atts if re.search(FINANCE, a["title"], re.I)],
                     key=lambda a: a["published_at"] or "", reverse=True)[:MAX_FINANCE_DOCS]
    log(f"{src['name']}: {len(by_title)} dokumentów z miejscowością w tytule, {len(finance)} najnowszych planów finansowych")
    out = []
    for att in by_title + [a for a in finance if a not in by_title]:
        doc = client.document(att)
        pages = json.loads(doc["pages_json"] or "[]")
        title_own = bool(re.search(own_rx, att["title"], re.I))
        title_related = bool(re.search(rel_rx, att["title"], re.I)) and not title_own
        relation = "powiązana inwestycja: " + ", ".join(sorted(related))
        reason = "miejscowość i zakres inwestycji zależnej"
        hit = None
        for i, text in enumerate(pages, 1):
            text = " ".join(text.split())
            found = term_hit(text)
            if found:
                label, match = found
                hit = i, text[max(0, match.start()-100):match.end()+120]
                reason = label
                relation = "kandydat według wykonawcy" if label == "wykonawca" else "przedsięwzięcie"
                break
        financial = bool(re.search(FINANCE, doc["title"], re.I))
        if not hit and not title_related:
            hit = _find(pages, place_rx, own_rx, financial)
            if hit:
                reason = "miejscowość i zakres projektu"
                relation = "przedsięwzięcie"
        if not hit:
            hit = _find(pages, place_rx, rel_rx, financial)
        if hit:
            page, quote = hit
        elif att in by_title:
            page, quote = None, att["title"]
            title_term = term_hit(quote)
            if title_term:
                reason = title_term[0]
                relation = "kandydat według wykonawcy" if title_term[0] == "wykonawca" else "przedsięwzięcie"
            elif title_own:
                reason = "miejscowość i zakres projektu"
                relation = "przedsięwzięcie"
        else:
            continue
        location = f"str. {page}" if page and doc["ext"] == "pdf" else "treść dokumentu" if hit else "tytuł dokumentu"
        out.append({"doc": doc, "relation": relation, "page": page if doc["ext"] == "pdf" else None,
                    "quote": quote, "reason": reason, "location": location})
    log(f"{src['name']}: powiązanych dokumentów {len(out)} (zapytań sieciowych {client.n_network})")
    return out
