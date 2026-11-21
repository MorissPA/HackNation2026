"""Klient publicznego API Biuletynu Zamówień Publicznych (ezamowienia.gov.pl).

Wykorzystywane endpointy (odczyt nie wymaga procedury integracyjnej):
- GET /Board/Search   – wyszukiwarka; filtry: NoticeNumber, OrganizationId, NoticeType,
                        OrderObject (podciąg, bez rozróżniania wielkości liter),
                        PublicationDateFrom, PageNumber (strony po 10).
- GET /notice         – lista ogłoszeń z treścią (htmlBody); wymaga NoticeType,
                        PublicationDateFrom/To; filtr NoticeNumber.

Limit: 30 zapytań/min z IP -> pilnujemy odstępu między zapytaniami i cache'ujemy
odpowiedzi w SQLite (tabela http_cache).

Kopia organizatora (config.BZP_MIRROR_BASE, bzp.cytr.us) jest źródłem głównym: ten sam /notice bez limitu,
z filtrami NoticeNumber (także bez dat) i OrderObject. Nie ma Board/Search, stronicowania (max PageSize
wyników) ani ogłoszeń o zmianie ogłoszenia. Wyszukiwarkę emulujemy: /notice per typ ogłoszenia + filtry po
stronie klienta. Oficjalne API służy jako zapas, gdy kopia nie odpowiada albo nic nie znajduje.
"""
import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests

from .. import config, db

# typy ogłoszeń obecne w kopii organizatora
MIRROR_TYPES = ("ContractNotice", "TenderResultNotice", "AgreementUpdateNotice", "ContractPerformingNotice")
PUBLIC_NOTICE_URL = "https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/id/{object_id}"


class BZPError(RuntimeError):
    pass


class BZPClient:
    _lock = threading.Lock()
    _last_call = {}  # host -> czas ostatniego zapytania (osobny limit tempa dla kopii i oficjalnego API)

    def __init__(self, con, offline: bool = False, log=None):
        self.con = con
        self.offline = offline  # tylko cache (testy, demo bez sieci)
        self.log = log or (lambda msg: None)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": config.USER_AGENT, "Accept": "application/json"})
        self.n_network_calls = 0
        self.mirror = config.BZP_MIRROR_BASE or None
        self._bodies = {}  # noticeNumber -> pełne ogłoszenie z treścią (kopia zwraca treść już w wyszukiwaniu)
        self.sources_used = set()

    # ------------------------------------------------------------------ HTTP
    def _get_json(self, path: str, params: dict, ttl_hours=None, base=None):
        base = base or config.BZP_API_BASE
        interval = config.BZP_MIRROR_INTERVAL_S if base == self.mirror else config.BZP_MIN_INTERVAL_S
        url = f"{base}/{path}?{urlencode(params)}"
        row = self.con.execute("SELECT fetched_at, status, body FROM http_cache WHERE url=?", (url,)).fetchone()
        if row and row["status"] == 200:
            fresh = ttl_hours is None or (
                datetime.now(timezone.utc) - datetime.fromisoformat(row["fetched_at"]) < timedelta(hours=ttl_hours)
            )
            if fresh or self.offline:
                return json.loads(row["body"])
        if self.offline:
            raise BZPError(f"Brak w cache (tryb offline): {url}")

        for attempt in range(4):
            with self._lock:
                wait = interval - (time.monotonic() - BZPClient._last_call.get(base, 0.0))
                if wait > 0:
                    time.sleep(wait)
                BZPClient._last_call[base] = time.monotonic()
            try:
                self.n_network_calls += 1
                resp = self.session.get(url, timeout=config.BZP_TIMEOUT_S)
            except requests.RequestException as e:
                self.log(f"Błąd sieci ({e}); ponawiam")
                time.sleep(3 * (attempt + 1))
                continue
            if (resp.status_code == 429 or resp.status_code >= 500) and base == self.mirror and attempt >= 1:
                raise BZPError(f"HTTP {resp.status_code} z kopii BZP")
            if resp.status_code == 429 or resp.status_code >= 500:
                self.log(f"HTTP {resp.status_code} z BZP; czekam i ponawiam")
                time.sleep(15 * (attempt + 1))
                continue
            if resp.status_code != 200:
                raise BZPError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            try:
                data = resp.json()
            except ValueError:
                # zdarza się pusta odpowiedź 200 przy przeciążeniu/limicie – ponawiamy
                self.log("Pusta/niepoprawna odpowiedź BZP; czekam i ponawiam")
                time.sleep(10 * (attempt + 1))
                continue
            self.sources_used.add("kopia organizatora" if base == self.mirror else "oficjalne API")
            self.con.execute(
                "INSERT OR REPLACE INTO http_cache(url, fetched_at, status, body) VALUES (?,?,?,?)",
                (url, db.now(), 200, resp.text),
            )
            self.con.commit()
            return data
        raise BZPError(f"Nie udało się pobrać: {url}")

    # ------------------------------------------------------------ kopia organizatora
    def _mirror_notice(self, ttl_hours, **params):
        res = self._get_json("notice", params, ttl_hours=ttl_hours, base=self.mirror)
        for n in res:
            if n.get("htmlBody"):
                self._bodies[n["noticeNumber"]] = n
        return res

    def _mirror_search(self, params):
        """Emulacja Board/Search na kopii. Zwraca listę albo None, gdy kopia nie umie obsłużyć zapytania."""
        if int(params.get("PageNumber", 1)) > 1:
            return []  # kopia nie stronicuje – wszystko przyszło na pierwszej „stronie”
        types = [params["NoticeType"]] if params.get("NoticeType") else list(MIRROR_TYPES)
        if params.get("NoticeType") and params["NoticeType"] not in MIRROR_TYPES:
            return None
        out = []
        if params.get("NoticeNumber"):
            for t in types:
                out += self._mirror_notice(None, NoticeType=t, NoticeNumber=params["NoticeNumber"])
                if out:
                    break
            return out
        if not params.get("OrderObject"):
            return None  # bez frazy kopia zwróciłaby losowe 500 ogłoszeń – to zadanie dla oficjalnej wyszukiwarki
        today = datetime.now(timezone.utc).date().isoformat()
        for t in types:
            res = self._mirror_notice(config.BZP_SEARCH_CACHE_TTL_H, NoticeType=t, OrderObject=params["OrderObject"],
                                      PublicationDateFrom=params.get("PublicationDateFrom") or "2018-01-01",
                                      PublicationDateTo=today, PageSize=config.BZP_MIRROR_PAGE_SIZE)
            if len(res) >= config.BZP_MIRROR_PAGE_SIZE:
                self.log(f"Kopia BZP: {t} „{params['OrderObject']}” – wynik ucięty do {len(res)} ogłoszeń")
            out += res
        org, nip = params.get("OrganizationId"), re.sub(r"\D", "", params.get("OrganizationNationalId") or "")
        if org:
            out = [n for n in out if str(n.get("organizationId")) == str(org)]
        if nip:
            out = [n for n in out if re.sub(r"\D", "", n.get("organizationNationalId") or "") == nip]
        return [{k: v for k, v in n.items() if k != "htmlBody"} for n in out]

    # ------------------------------------------------------------ wyszukiwanie
    def search(self, **params):
        params = {k: v for k, v in params.items() if v not in (None, "")}
        if self.mirror:
            try:
                res = self._mirror_search(params)
                if res is not None and (res or not params.get("NoticeNumber")):
                    return res
            except (BZPError, requests.RequestException) as e:
                self.log(f"Kopia BZP niedostępna ({e}); używam oficjalnego API")
        return self._get_json("Board/Search", params, ttl_hours=config.BZP_SEARCH_CACHE_TTL_H)

    def find_by_number(self, notice_number: str):
        """Ogłoszenie po numerze, np. '2024/BZP 00349631/01' (sufiks wersji opcjonalny)."""
        nn = notice_number.strip()
        res = self.search(NoticeNumber=nn)
        exact = [n for n in res if n["noticeNumber"] == nn or n["bzpNumber"] == nn]
        return exact[0] if exact else None

    def fetch_full(self, meta: dict) -> dict:
        """Metadane + treść (htmlBody). Treść ogłoszenia nie zmienia się -> cache bez TTL."""
        nn = meta["noticeNumber"]
        if nn in self._bodies:
            return self._bodies[nn]
        if self.mirror and meta["noticeType"] in MIRROR_TYPES:
            try:
                res = self._mirror_notice(None, NoticeType=meta["noticeType"], NoticeNumber=nn)
                hit = [n for n in res if n["noticeNumber"] == nn]
                if hit:
                    return hit[0]
            except (BZPError, requests.RequestException) as e:
                self.log(f"Kopia BZP niedostępna ({e}); używam oficjalnego API")
        # Okno ±1 dzień: API porównuje daty w innej strefie niż publicationDate (UTC),
        # przy wąskim oknie ogłoszenia z wczesnych godzin bywają pomijane.
        day = datetime.fromisoformat(meta["publicationDate"][:10])
        res = self._get_json(
            "notice",
            {
                "NoticeType": meta["noticeType"],
                "PublicationDateFrom": (day - timedelta(days=1)).date().isoformat(),
                "PublicationDateTo": (day + timedelta(days=2)).date().isoformat(),
                "NoticeNumber": meta["noticeNumber"],
                "PageSize": 10,
            },
            ttl_hours=None,
        )
        for n in res:
            if n["noticeNumber"] == meta["noticeNumber"]:
                return n
        raise BZPError(f"Nie znaleziono treści ogłoszenia {meta['noticeNumber']}")

    def find_via_references(self, notice_number: str, title: str, nip: str = None, org_name: str = None,
                            max_candidates: int = 8):
        """Zapasowa ścieżka, gdy ogłoszenia o podanym numerze nie zwraca żaden endpoint API
        (np. 2023/BZP 00110672/01 – Wolin). Szukamy ogłoszeń tego zamawiającego o podobnym tytule
        i sprawdzamy, które w treści cytują numer z arkusza; od nich bierzemy OCID.

        Zwraca (meta ogłoszenia odwołującego się, cytat z kontekstem) albo (None, opis prób).
        """
        core = re.sub(r"/\d{2}$", "", notice_number.strip())  # '2023/BZP 00110672'
        year = core[:4]
        nip_d = re.sub(r"\D", "", nip or "")
        words = re.findall(r"\w+", title or "")
        # kilka coraz krótszych fragmentów tytułu (od końca – zwykle zawiera nazwę gminy/miejscowości)
        phrases = []
        for n in (6, 4, 3):
            if len(words) >= n:
                phrases.append(" ".join(words[-n:]))
        tried, cands = [], {}
        for ph in phrases:
            tried.append(ph)
            for item in self.search(OrderObject=ph, PublicationDateFrom=f"{year}-01-01"):
                ok_org = (nip_d and re.sub(r"\D", "", item.get("organizationNationalId") or "") == nip_d) or (
                    not nip_d and org_name and org_name.lower() in (item.get("organizationName") or "").lower())
                if ok_org and item.get("tenderId"):
                    cands.setdefault(item["noticeNumber"], item)
            if cands:
                break
        # najpierw ogłoszenia najbliższe w czasie numerowi bazowemu
        for meta in sorted(cands.values(), key=lambda n: n["publicationDate"])[:max_candidates]:
            try:
                full = self.fetch_full(meta)
            except BZPError:
                continue
            text = re.sub(r"<[^>]+>", " ", full.get("htmlBody") or "")
            text = re.sub(r"\s+", " ", text)
            m = re.search(re.escape(core), text)
            if m:
                ctx = text[max(0, m.start() - 160): m.end() + 40].strip()
                return dict(meta, **{k: v for k, v in full.items() if k != "htmlBody" and v is not None}), ctx
        return None, f"przeszukano frazy: {tried}; kandydatów zamawiającego: {len(cands)}"

    def related_notices(self, base: dict, since: str = None):
        """Wszystkie ogłoszenia z tym samym identyfikatorem postępowania (OCID).

        1) wyszukiwanie po zamawiającym + początku tytułu (szybkie, zwykle wystarcza),
        2) gdy brakuje ogłoszeń po zawarciu umowy – przegląd wszystkich ogłoszeń
           zamawiającego od daty ogłoszenia bazowego (stronicowanie, limit stron).
        Zwraca (lista metadanych, opis użytej strategii).
        """
        ocid, org = base["tenderId"], base["organizationId"]
        since = since or base["publicationDate"][:10]
        found = {base["noticeNumber"]: base}

        def collect(items):
            n_new = 0
            for n in items:
                if n.get("tenderId") == ocid and n["noticeNumber"] not in found:
                    found[n["noticeNumber"]] = n
                    n_new += 1
            return n_new

        title = (base.get("orderObject") or "").strip()
        prefix = title[:45].rsplit(" ", 1)[0] if len(title) > 45 else title
        strategy = [f"tytuł zaczyna się od „{prefix}”"]
        for page in range(1, 6):
            items = self.search(OrganizationId=org, OrderObject=prefix, PublicationDateFrom=since, PageNumber=page)
            collect(items)
            if len(items) < 10:
                break

        if self.mirror and len(prefix) > 25:
            # kopia nie umie przejrzeć wszystkich ogłoszeń zamawiającego – próbujemy krótszego początku tytułu
            short = prefix[:25].rsplit(" ", 1)[0]
            if collect(self.search(OrganizationId=org, OrderObject=short, PublicationDateFrom=since)):
                strategy.append(f"krótszy tytuł „{short}”")
        types = {n["noticeType"] for n in found.values()}
        missing = "ContractPerformingNotice" not in types or "TenderResultNotice" not in types
        if missing and self.mirror and not config.BZP_OFFICIAL_ORG_SCAN:
            strategy.append("pominięto pełny przegląd w oficjalnym API (kopia organizatora jako źródło)")
        elif missing:
            strategy.append("pełny przegląd ogłoszeń zamawiającego")
            for page in range(1, config.BZP_MAX_ORG_PAGES + 1):
                items = self.search(OrganizationId=org, PublicationDateFrom=since, PageNumber=page)
                collect(items)
                if len(items) < 10:
                    break
        return sorted(found.values(), key=lambda n: n["publicationDate"]), "; ".join(strategy)

    @staticmethod
    def public_url(meta_or_object_id) -> str:
        # karta ogłoszenia w serwisie BZP adresowana jest identyfikatorem moIdentifier (z wyszukiwarki)
        m = meta_or_object_id
        oid = m if isinstance(m, str) else (m.get("moIdentifier") or m.get("objectId"))
        return PUBLIC_NOTICE_URL.format(object_id=oid)
