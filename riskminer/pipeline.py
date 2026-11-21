"""Pobranie danych z BZP dla projektu i zbudowanie karty: postępowanie, umowy, zmiany,
fakty (z dowodem), obliczenia, zdarzenia na osi czasu, propozycje ryzyk i braki.

Rozdzielamy:
- fakt        – wartość odczytana ze znanego pola ogłoszenia (cytat + sekcja/pkt),
- obliczenie  – wynik działania na faktach (z formułą),
- propozycja  – interpretacja (np. kategoria ryzyka) do oceny eksperta.
Poziomy kwot: 'umowa' (pojedyncza umowa/część), 'postępowanie', 'projekt' (z arkusza/KPO).
"""
import re
from datetime import date

from . import db, matcher, risks, signals
from .bzp import parser as P
from .bzp.client import BZPClient, BZPError

NOTICE_LABELS = {
    "ContractNotice": "Ogłoszenie o zamówieniu",
    "NoticeUpdateNotice": "Ogłoszenie o zmianie ogłoszenia",
    "TenderResultNotice": "Ogłoszenie o wyniku postępowania",
    "AgreementIntentionNotice": "Ogłoszenie o zamiarze zawarcia umowy",
    "AgreementUpdateNotice": "Ogłoszenie o zmianie umowy",
    "ContractPerformingNotice": "Ogłoszenie o wykonaniu umowy",
}


def _digits(s):
    return re.sub(r"\D", "", s or "")


def _days(a, b):
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days
    except (TypeError, ValueError):
        return None


class Card:
    """Zbiera fakty/zdarzenia/braki jednego przebiegu i zapisuje je UPSERT-em."""

    def __init__(self, con, project):
        self.con, self.p = con, project
        self.pid = project["project_id"]
        self.ts = db.now()
        self.n_facts = self.n_events = 0

    def fact(self, kind, key, label, *, num=None, text=None, unit=None, level="umowa", part=0,
             ocid=None, notice=None, field=None, quote=None, formula=None):
        row = {
            "project_id": self.pid, "ocid": ocid, "part_no": part or 0, "kind": kind, "key": key,
            "label": label, "value_num": num, "value_text": text, "unit": unit, "level": level,
            "source_notice": notice["notice_number"] if notice else "arkusz",
            "source_url": notice["source_url"] if notice else None,
            "source_section": P.loc(field) if field else None,
            "quote": quote if quote is not None else (P.quote(field) if field else None),
            "formula": formula, "fetched_at": notice["fetched_at"] if notice else self.ts,
            "updated_at": self.ts,
        }
        db.upsert(self.con, "fact", row, ["project_id", "key", "part_no", "source_notice"], preserve=("status",))
        self.n_facts += 1

    def money_fact(self, key, label, field, notice, ocid, part=0, level="umowa"):
        if field and P.parse_money(field["value"]) is not None:
            self.fact("fakt", key, label, num=P.parse_money(field["value"]), unit="PLN", level=level,
                      part=part, ocid=ocid, notice=notice, field=field)

    def text_fact(self, key, label, field, notice, ocid, part=0, level="umowa", value=None):
        if field and (value or field["value"]):
            self.fact("fakt", key, label, text=value or field["value"], level=level, part=part,
                      ocid=ocid, notice=notice, field=field)

    def event(self, etype, title, *, when=None, details=None, kind="fakt", part=0, ocid=None,
              notice=None, field=None, quote=None, section=None):
        row = {
            "project_id": self.pid, "ocid": ocid, "part_no": part or 0, "event_date": when,
            "event_type": etype, "title": title, "details": details, "kind": kind,
            "source_notice": notice["notice_number"] if notice else "arkusz",
            "source_url": notice["source_url"] if notice else None,
            "source_section": section or (P.loc(field) if field else None),
            "quote": quote if quote is not None else (P.quote(field) if field else None),
            "updated_at": self.ts,
        }
        db.upsert(self.con, "event", row, ["project_id", "event_type", "part_no", "source_notice", "title"],
                  preserve=("status", "expert_title", "expert_comment"))
        self.n_events += 1

    def gap(self, key, message):
        self.con.execute(
            "INSERT INTO gap(project_id,key,message,updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(project_id,key) DO UPDATE SET message=excluded.message, updated_at=excluded.updated_at",
            (self.pid, key, message, self.ts),
        )


# --------------------------------------------------------------------------- notices
def store_notice(con, client: BZPClient, meta: dict) -> dict:
    """Pobiera treść (cache) i zapisuje ogłoszenie. Zwraca wiersz + wynik ekstrakcji."""
    full = dict(meta, **{k: v for k, v in client.fetch_full(meta).items() if v is not None})
    html = full.get("htmlBody") or ""
    ext = P.extract(full["noticeType"], html)
    row = {
        "notice_number": full["noticeNumber"], "bzp_number": full.get("bzpNumber"),
        "notice_type": full["noticeType"], "ocid": full.get("tenderId"), "object_id": full.get("objectId"),
        "publication_date": (full.get("publicationDate") or "")[:10], "order_object": full.get("orderObject"),
        "organization_name": full.get("organizationName"), "organization_id": full.get("organizationId"),
        "organization_nip": full.get("organizationNationalId"),
        "meta_json": db.dumps({k: v for k, v in full.items() if k != "htmlBody"}),
        "html": html, "text": P.html_to_text(html), "fields_json": db.dumps(ext["fields"]),
        "source_url": client.public_url(full), "fetched_at": db.now(),
    }
    old = con.execute("SELECT fetched_at, source_url FROM notice WHERE notice_number=?", (row["notice_number"],)).fetchone()
    if old:  # treść się nie zmienia – zachowujemy pierwotną datę pobrania
        row["fetched_at"] = old["fetched_at"]
        # kopia organizatora nie podaje moIdentifier – zostawiamy link z oficjalnej wyszukiwarki, jeśli był
        if not full.get("moIdentifier") and old["source_url"]:
            row["source_url"] = old["source_url"]
    db.upsert(con, "notice", row, ["notice_number"], preserve=())
    row["ext"] = ext
    return row


# --------------------------------------------------------------------------- main
def fetch_project(con, project_id: str, client: BZPClient, log=print) -> dict:
    p = con.execute("SELECT * FROM project WHERE project_id=?", (project_id,)).fetchone()
    if not p:
        raise ValueError(f"Nie ma projektu {project_id}")
    p = dict(p)
    card = Card(con, p)
    con.execute("DELETE FROM gap WHERE project_id=?", (project_id,))  # braki liczymy od nowa

    try:
        summary = _run(con, client, card, p, log)
        status, msg = "ok", summary.get("message", "")
    except BZPError as e:
        status, msg, summary = "błąd", f"BZP: {e}", {}
        card.gap("bzp_error", msg)
    bip_complete = _bip_evidence(con, card, p, log)
    # Nie kasuj wcześniejszych dowodów po niedostępności źródła.
    for table in ("fact", "event"):
        preserve_llm = " AND event_type<>'ryzyko LLM'" if table == "event" else ""
        con.execute(f"""DELETE FROM {table} WHERE project_id=? AND updated_at<? AND status='do_weryfikacji'{preserve_llm}
                    AND ((source_notice LIKE 'BIP: %' AND ?) OR (source_notice NOT LIKE 'BIP: %' AND ?))""",
                    (project_id, card.ts, bip_complete, status == "ok"))
    con.execute(
        "UPDATE project SET last_fetch_at=?, last_fetch_status=?, last_fetch_message=? WHERE project_id=?",
        (db.now(), status, msg, project_id),
    )
    con.commit()
    summary.update(status=status, message=msg, facts=card.n_facts, events=card.n_events)
    return summary


def _bzp_base(con, client, card, p, log):
    pid = (p.get("public_id") or "").strip()
    log(f"[{p['project_id']}] Szukam ogłoszenia {pid} w BZP…")
    base = client.find_by_number(pid)
    if base:
        return {"base": base, "since": None, "method": "numer_bzp", "status": "potwierdzone", "score": 1.0,
                "evidence": f"Ogłoszenie {base['noticeNumber']} z arkusza → identyfikator postępowania {base['tenderId']}."}
    log(f"[{p['project_id']}] API nie zwraca {pid}; szukam ogłoszeń zamawiającego, które cytują ten numer…")
    base, ctx = client.find_via_references(pid, p.get("name"), nip=p.get("recipient_id"),
                                           org_name=p.get("recipient_name"))
    if not base:
        card.gap("bzp_not_found", f"Nie znaleziono ogłoszenia {pid} w BZP ani ogłoszeń, które się do niego "
                                  f"odwołują ({ctx}).")
        return {"message": f"Nie znaleziono {pid}"}
    card.gap("brak_ogloszenia_bazowego",
             f"Treść ogłoszenia o zamówieniu {pid} jest niedostępna w API BZP – powiązanie ustalono przez "
             f"odwołanie w ogłoszeniu {base['noticeNumber']}. Brak danych z ogłoszenia bazowego "
             "(np. termin składania ofert, pierwotny opis przedmiotu).")
    return {"base": base, "since": f"{pid[:4]}-01-01", "method": "odwołanie_w_ogłoszeniu", "status": "potwierdzone",
            "score": 1.0,
            "evidence": (f"Ogłoszenia {pid} nie zwraca API BZP. {NOTICE_LABELS.get(base['noticeType'], base['noticeType'])} "
                         f"{base['noticeNumber']} tego samego zamawiającego cytuje ten numer: „…{ctx}…” → "
                         f"identyfikator postępowania {base['tenderId']}.")}


def _criteria_text(crit):
    return "; ".join(f"{c['name']}: {c['status']} ({c['detail']})" for c in crit)


def _kpo_base(con, client, card, p, log):
    """Rekord KPO: powiązanie potwierdzone przez eksperta albo ranking kandydatów z BZP."""
    pid = p["project_id"]
    confirmed = con.execute("SELECT l.*, c.base_meta_json FROM project_link l LEFT JOIN link_candidate c "
                            "ON c.project_id=l.project_id AND c.ocid=l.ocid "
                            "WHERE l.project_id=? AND l.status='potwierdzone'", (pid,)).fetchone()
    if confirmed and confirmed["base_meta_json"]:
        import json
        stale = con.execute("SELECT count(*) FROM link_candidate WHERE project_id=? AND confidence IS NULL", (pid,)).fetchone()[0]
        if stale:  # lista kandydatów z poprzedniej wersji ocen – odświeżamy ją, powiązanie zostaje bez zmian
            ranked, _ = matcher.rank(client, p, log=log)
            con.execute("DELETE FROM link_candidate WHERE project_id=? AND ocid<>?", (pid, confirmed["ocid"]))
            for i, c in enumerate(ranked[:6], 1):
                b = matcher.base_notice(c["notices"])
                con.execute(
                    "INSERT OR REPLACE INTO link_candidate(project_id, ocid, rank, score, title, base_notice, base_meta_json, "
                    "features_json, notices_json, created_at, confidence, matched, checked) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (pid, c["ocid"], i, c["score"], c["title"], b["noticeNumber"], db.dumps(b), db.dumps(c["criteria"]),
                     db.dumps(sorted((n["noticeType"], n["noticeNumber"], n["publicationDate"][:10]) for n in c["notices"])),
                     card.ts, c["confidence"], c["matched"], c["checked"]))
            con.commit()
        return {"base": json.loads(confirmed["base_meta_json"]), "since": None, "method": confirmed["method"],
                "status": "potwierdzone", "score": confirmed["score"],
                "evidence": confirmed["evidence"].split(" Powiązane ogłoszenia znalezione przez:")[0]}

    rejected = {r["ocid"] for r in con.execute(
        "SELECT ocid FROM project_link WHERE project_id=? AND status='odrzucone'", (pid,))}
    ranked, info = matcher.rank(client, p, log=log)
    ranked = [c for c in ranked if c["ocid"] not in rejected]
    con.execute("DELETE FROM link_candidate WHERE project_id=?", (pid,))
    for i, c in enumerate(ranked[:6], 1):
        b = matcher.base_notice(c["notices"])
        con.execute(
            "INSERT INTO link_candidate(project_id, ocid, rank, score, title, base_notice, base_meta_json, features_json, "
            "notices_json, created_at, confidence, matched, checked) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, c["ocid"], i, c["score"], c["title"], b["noticeNumber"], db.dumps(b), db.dumps(c["criteria"]),
             db.dumps(sorted((n["noticeType"], n["noticeNumber"], n["publicationDate"][:10]) for n in c["notices"])),
             card.ts, c["confidence"], c["matched"], c["checked"]))
    con.commit()
    search_desc = (f"Szukano w BZP po NIP {info['nip']} od {info['since']}, frazy: {', '.join(info['queries'])}; "
                   f"{len(ranked)} postępowań-kandydatów" + (f" (pominięto odrzucone przez eksperta: {len(rejected)})" if rejected else ""))
    if not ranked:
        card.gap("kpo_link", f"Nie znaleziono kandydatów w BZP. {search_desc}.")
        return {"message": "KPO – brak kandydatów w BZP"}
    # propozycja automatyczna tylko wtedy, gdy dokładnie jeden kandydat ma wysoką pewność
    top = ranked[0]
    high = [c for c in ranked if c["confidence"] == "wysoka"]
    label = lambda c: f"{c['matched']}/{c['checked']} kryteriów, pewność {c['confidence']}"
    tie_note = ""
    if len(high) > 1:
        # remis: wygrywa kandydat z największą liczbą słów z nazwy przedsięwzięcia w tytule – o ile jest jeden taki
        best = max(matcher.name_share(c) for c in high)
        leaders = [c for c in high if matcher.name_share(c) == best]
        if len(leaders) == 1:
            others = sorted((matcher.name_share(c) for c in high if c is not leaders[0]), reverse=True)
            tie_note = (f" Kryteria spełnia {len(high)} kandydatów; wybrano ten, którego tytuł zawiera najwięcej słów "
                        f"z nazwy przedsięwzięcia ({best:.0%} wobec {others[0]:.0%}).")
            high = leaders
    if len(high) != 1:
        why = "żaden kandydat nie ma wysokiej pewności" if not high else f"{len(high)} kandydatów spełnia wszystkie kryteria w równym stopniu"
        card.gap("kpo_link", f"Brak jednoznacznego kandydata ({why}; najlepszy: {label(top)}) – wybierz postępowanie "
                             f"w panelu eksperta. {search_desc}.")
        return {"message": f"KPO – {len(ranked)} kandydatów, wymaga wyboru eksperta"}
    top = high[0]
    second = next((c for c in ranked if c is not top), None)
    # porzucamy wcześniejsze automatyczne propozycje innych postępowań
    con.execute("DELETE FROM project_link WHERE project_id=? AND status='proponowane' AND ocid<>?", (pid, top["ocid"]))
    card.gap("kpo_link_do_potwierdzenia",
             f"Powiązanie zaproponowane automatycznie ({label(top)}"
             + (f"; następny kandydat: {label(second)}" if second else "") + ") – wymaga potwierdzenia eksperta." + tie_note)
    return {"base": matcher.base_notice(top["notices"]), "since": None, "method": "kryteria: nazwa, zamawiający, miejsce, CPV, wartość, daty",
            "status": "proponowane", "score": top["matched"] / top["checked"] if top["checked"] else 0,
            "evidence": f"Pewność {top['confidence']} ({top['matched']}/{top['checked']} kryteriów).{tie_note} "
                        f"{_criteria_text(top['criteria'])}. {search_desc}."}


def _run(con, client, card: Card, p: dict, log):
    pid_type = p.get("public_id_type") or ""
    _project_level_facts(card, p)

    if "BZP" in pid_type.upper():
        found = _bzp_base(con, client, card, p, log)
    else:
        found = _kpo_base(con, client, card, p, log)
    if found.get("message"):
        return {"message": found["message"]}
    base, since, method = found["base"], found["since"], found["method"]
    link_evidence, link_status, link_score = found["evidence"], found["status"], found["score"]

    ocid = base["tenderId"]
    log(f"[{p['project_id']}] OCID {ocid}; szukam powiązanych ogłoszeń…")
    metas, strategy = client.related_notices(base, since=since)
    log(f"[{p['project_id']}] Znaleziono {len(metas)} ogłoszeń ({strategy}); pobieram treść…")

    notices = []
    for m in metas:
        try:
            notices.append(store_notice(con, client, m))
        except BZPError as e:
            card.gap(f"notice_{m['noticeNumber']}", f"Nie udało się pobrać treści {m['noticeNumber']}: {e}")
    con.commit()

    by_type = {}
    for n in notices:
        by_type.setdefault(n["notice_type"], []).append(n)

    db.upsert(con, "project_link", {
        "project_id": p["project_id"], "ocid": ocid, "part_no": p.get("part_no") or 0, "method": method,
        "score": link_score,
        "evidence": f"{link_evidence.rstrip().rstrip('.')}. Powiązane ogłoszenia znalezione przez: {strategy}; filtr po OCID.",
        "status": link_status, "created_at": card.ts, "updated_at": card.ts,
    }, ["project_id", "ocid"], preserve=("status", "created_at"))

    base_n = next((n for n in notices if n["notice_number"] == base["noticeNumber"]), None)
    result = (by_type.get("TenderResultNotice") or [None])[-1]
    _procedure(con, card, p, ocid, base_n, result)
    contracts = _contracts(con, card, p, ocid, result, by_type)
    _timeline_and_risks(con, card, p, ocid, base_n, by_type, contracts)
    _repeated_procedures(con, client, card, p, ocid, base, log)
    _gaps(card, p, by_type, contracts)
    _project_vs_contracts(card, p, ocid, contracts)
    return {"message": f"{len(notices)} ogłoszeń, {len(contracts)} umów"
                       + (" (powiązanie do potwierdzenia)" if link_status == "proponowane" else ""), "ocid": ocid,
            "notices": [(n["notice_type"], n["notice_number"]) for n in notices]}


def _project_level_facts(card: Card, p: dict):
    ann = p.get("annotation") or ""
    m = re.search(r"Wartość przedsięwzięcia:\s*([\d\s\xa0]+,\d{2})", ann)
    if m:
        card.fact("fakt", "wartosc_przedsiewziecia", "Wartość przedsięwzięcia (KPO, z arkusza)",
                  num=P.parse_money(m.group(1)), unit="PLN", level="projekt",
                  quote=m.group(0), formula=None)
    m = re.search(r"dofinansowanie:\s*([\d\s\xa0]+,\d{2})", ann)
    if m:
        card.fact("fakt", "dofinansowanie", "Dofinansowanie (KPO, z arkusza)",
                  num=P.parse_money(m.group(1)), unit="PLN", level="projekt", quote=m.group(0))


def _procedure(con, card, p, ocid, base_n, result):
    est = result["ext"].get("estimated_value") if result else None
    ref = (result or base_n or {}).get("ext", {}).get("reference_no") if (result or base_n) else None
    db.upsert(con, "procedure", {
        "ocid": ocid, "title": (base_n or {}).get("order_object"),
        "organization_name": (base_n or {}).get("organization_name"),
        "organization_id": (base_n or {}).get("organization_id"),
        "base_notice": (base_n or {}).get("notice_number"),
        "reference_no": ref["value"] if ref else None,
        "estimated_value": P.parse_money(est["value"]) if est else None,
        "has_parts": int(bool(result and result["ext"]["parts"])),
        "updated_at": card.ts,
    }, ["ocid"], preserve=())
    if base_n:
        card.fact("fakt", "nazwa_zamowienia", "Nazwa zamówienia", text=base_n["order_object"], level="postępowanie",
                  ocid=ocid, notice=base_n, quote=base_n["order_object"])
    if est:
        card.money_fact("wartosc_szacunkowa", "Wartość zamówienia (szacunkowa, całe postępowanie)", est, result,
                        ocid, level="postępowanie")


def _contracts(con, card, p, ocid, result, by_type):
    """Umowy z ogłoszenia o wyniku (per część) + dopasowanie ogł. o zmianie i o wykonaniu."""
    want_part = p.get("part_no") or 0
    contracts = []
    if result:
        for part, d in result["ext"]["by_part"].items():
            if want_part and part and part != want_part:
                continue
            if not d.get("signed") and not d.get("value"):
                continue  # część unieważniona / bez umowy
            c = {
                "ocid": ocid, "part_no": part or 0,
                "contractor_name": d["contractor"]["value"] if d.get("contractor") else None,
                "contractor_id": d["contractor_id"]["value"] if d.get("contractor_id") else None,
                "signed_date": P.parse_date(d["signed"]["value"]) if d.get("signed") else None,
                "value": P.parse_money(d["value"]["value"]) if d.get("value") else None,
                "currency": "PLN",
                "planned_end": P.end_date(d["period"]["value"], P.parse_date(d["signed"]["value"]) if d.get("signed") else None)[0] if d.get("period") else None,
                "source_notice": result["notice_number"], "updated_at": card.ts,
            }
            c["_src"], c["_d"] = result, d
            contracts.append(c)

    # dopasowanie ogłoszeń o wykonaniu i o zmianie do umów (część nie jest w nich podana)
    def match(ext):
        signed = P.parse_date(ext["signed"]["value"]) if ext.get("signed") else None
        val = P.parse_money(ext["value"]["value"]) if ext.get("value") else None
        cid = _digits(ext["contractor_id"]["value"]) if ext.get("contractor_id") else ""
        best, best_s = None, 0
        for c in contracts:
            s = (2 if val is not None and c["value"] is not None and abs(c["value"] - val) < 0.01 else 0)
            s += (1 if signed and signed == c["signed_date"] else 0)
            s += (1 if cid and cid == _digits(c["contractor_id"]) else 0)
            if s > best_s:
                best, best_s = c, s
        return best if best_s >= 2 else None

    perf_unmatched = []
    for n in by_type.get("ContractPerformingNotice", []):
        c = match(n["ext"])
        if c is None and not result:
            # brak ogł. o wyniku – umowę (per część) budujemy z ogłoszenia o wykonaniu
            e = n["ext"]
            hint = e.get("part_hint")
            if want_part and hint and hint != want_part:
                perf_unmatched.append(n)
                continue
            signed = P.parse_date(e["signed"]["value"]) if e.get("signed") else None
            c = {"ocid": ocid, "part_no": hint or want_part or (len(contracts) + 1 if contracts else 0),
                 "contractor_name": e["contractor"]["value"] if e.get("contractor") else None,
                 "contractor_id": e["contractor_id"]["value"] if e.get("contractor_id") else None,
                 "signed_date": P.parse_date(e["signed"]["value"]) if e.get("signed") else None,
                 "value": P.parse_money(e["value"]["value"]) if e.get("value") else None,
                 "currency": "PLN", "planned_end": P.end_date(e["period"]["value"], signed)[0] if e.get("period") else None,
                 "source_notice": n["notice_number"], "updated_at": card.ts, "_src": n, "_d": None}
            contracts.append(c)
        if c is None:
            perf_unmatched.append(n)
            continue
        if c.get("_perf"):
            # kilka ogłoszeń o wykonaniu tej samej umowy (korekta/ponowna publikacja): obowiązuje najnowsze
            old, new = sorted([c["_perf"], n], key=lambda x: (x["publication_date"], x["notice_number"]))
            c.setdefault("_perf_superseded", []).append(old)
            c["_perf"] = new
            continue
        c["_perf"] = n
    for n in by_type.get("AgreementUpdateNotice", []):
        c = match(n["ext"])
        if c is not None:
            c.setdefault("_upd", []).append(n)

    for c in contracts:
        perf = c.get("_perf")
        e = perf["ext"] if perf else {}
        row = {k: v for k, v in c.items() if not k.startswith("_")}
        row.update({
            "actual_end": P.parse_date(e["end_actual"]["value"]) if e.get("end_actual") else None,
            "on_time": e["on_time"]["value"] if e.get("on_time") else None,
            "paid_total": P.parse_money(e["paid_total"]["value"]) if e.get("paid_total") else None,
            "properly_executed": e["properly"]["value"] if e.get("properly") else None,
            "n_changes": int(P.parse_money(e["n_changes"]["value"])) if e.get("n_changes") and P.parse_money(e["n_changes"]["value"]) is not None else None,
            "performing_notice": perf["notice_number"] if perf else None,
        })
        c["id"] = db.upsert(con, "contract", row, ["ocid", "part_no"], preserve=())
        c.update(row)
        _contract_facts(con, card, p, c)
    # umowy z poprzednich przebiegów, których ten przebieg już nie zbudował – tylko w zakresie tego rekordu
    # (to samo postępowanie mogą współdzielić rekordy dla różnych części)
    if want_part:
        con.execute("DELETE FROM contract WHERE ocid=? AND part_no=? AND updated_at<?", (ocid, want_part, card.ts))
    else:
        con.execute("DELETE FROM contract WHERE ocid=? AND updated_at<?", (ocid, card.ts))
    for c in contracts:
        for old in c.get("_perf_superseded", []):
            card.gap(f"perf_duplikat_{c['part_no']}_{old['notice_number']}",
                     f"Ta sama umowa ma kilka ogłoszeń o wykonaniu – przyjęto najnowsze {c['_perf']['notice_number']}, "
                     f"wcześniejsze {old['notice_number']} różni się: {_perf_diff(old['ext'], c['_perf']['ext']) or 'brak różnic w kluczowych polach'}.")
    if perf_unmatched:
        card.gap("perf_unmatched", "Ogłoszenia o wykonaniu nieprzypisane do umowy z tego zakresu: "
                 + ", ".join(n["notice_number"] for n in perf_unmatched)
                 + (" (inne części postępowania)" if want_part else ""))
    return contracts


def _perf_diff(a, b):
    """Różnice w kluczowych polach dwóch ogłoszeń o wykonaniu tej samej umowy."""
    out = []
    for k, lab in (("period", "okres realizacji"), ("end_actual", "termin wykonania"), ("paid_total", "wypłacono"),
                   ("on_time", "w terminie"), ("n_changes", "liczba zmian")):
        va, vb = (a.get(k) or {}).get("value"), (b.get(k) or {}).get("value")
        if (va or "").strip() != (vb or "").strip():
            out.append(f"{lab}: „{va}” → „{vb}”")
    da = " | ".join((ch.get("description") or {}).get("value", "") for ch in a.get("changes", []))
    db_ = " | ".join((ch.get("description") or {}).get("value", "") for ch in b.get("changes", []))
    if da.strip() != db_.strip():
        out.append(f"opis zmian: „{da[:120]}” → „{db_[:120]}”")
    return "; ".join(out)


def _contract_facts(con, card: Card, p, c):
    ocid, part, src, d = c["ocid"], c["part_no"], c["_src"], c.get("_d")
    if d:
        card.money_fact("wartosc_umowy", "Wartość umowy (pierwotna)", d.get("value"), src, ocid, part)
        card.text_fact("data_umowy", "Data zawarcia umowy", d.get("signed"), src, ocid, part)
        card.text_fact("termin_umowny", "Termin realizacji z umowy pierwotnej", d.get("period"), src, ocid, part)
        card.text_fact("wykonawca", "Wykonawca", d.get("contractor"), src, ocid, part)
        if d.get("n_offers"):
            card.fact("fakt", "liczba_ofert", "Liczba otrzymanych ofert", num=P.parse_money(d["n_offers"]["value"]),
                      unit="szt.", part=part, ocid=ocid, notice=src, field=d["n_offers"], level="postępowanie" if not part else "umowa")
        card.money_fact("cena_min", "Najniższa cena oferty", d.get("price_min"), src, ocid, part)
        card.money_fact("cena_max", "Najwyższa cena oferty", d.get("price_max"), src, ocid, part)
        card.money_fact("wartosc_czesci", "Wartość szacunkowa części", d.get("part_value"), src, ocid, part)
        base = d.get("part_value") or (src["ext"].get("estimated_value") if not part else None)
        if base and c["value"] and P.parse_money(base["value"]):
            est = P.parse_money(base["value"])
            card.fact("obliczenie", "cena_vs_szacunek_pct", "Cena umowy względem wartości szacunkowej",
                      num=round((c["value"] / est - 1) * 100, 1), unit="%", part=part, ocid=ocid, notice=src,
                      formula=f"({c['value']:,.2f} / {est:,.2f} − 1) × 100".replace(",", " ")
                      + " · uwaga: wartość szacunkowa w BZP jest netto, wartość umowy zwykle brutto (VAT 23%)",
                      quote=f"{P.quote(d.get('value'))} | {P.quote(base)}")

    per = (d or {}).get("period") or ((c.get("_perf") or {}).get("ext") or {}).get("period")
    if per and c["signed_date"]:
        end, computed = P.end_date(per["value"], c["signed_date"])
        if computed:
            card.fact("obliczenie", "termin_umowny_wyliczony", "Termin z umowy pierwotnej (wyliczony z okresu realizacji)",
                      text=end, part=part, ocid=ocid, notice=d and src or c["_perf"],
                      formula=f"{c['signed_date']} + {per['value'].strip()}", quote=P.quote(per))

    perf = c.get("_perf")
    if not perf:
        return
    e = perf["ext"]
    if not d:
        card.money_fact("wartosc_umowy", "Wartość umowy (pierwotna)", e.get("value"), perf, ocid, part)
        card.text_fact("data_umowy", "Data zawarcia umowy", e.get("signed"), perf, ocid, part)
        card.text_fact("termin_umowny", "Termin realizacji z umowy pierwotnej", e.get("period"), perf, ocid, part)
        card.text_fact("wykonawca", "Wykonawca", e.get("contractor"), perf, ocid, part)
    card.text_fact("czy_wykonana", "Czy umowa została wykonana", e.get("executed"), perf, ocid, part)
    card.text_fact("termin_faktyczny", "Termin wykonania umowy (faktyczny)", e.get("end_actual"), perf, ocid, part)
    card.text_fact("w_terminie", "Wykonana w pierwotnie określonym terminie", e.get("on_time"), perf, ocid, part)
    card.text_fact("nalezycie", "Wykonana należycie", e.get("properly"), perf, ocid, part)
    card.money_fact("wyplacono", "Łączne wynagrodzenie wypłacone", e.get("paid_total"), perf, ocid, part)
    if e.get("n_changes"):
        card.fact("fakt", "liczba_zmian", "Liczba zmian umowy", num=P.parse_money(e["n_changes"]["value"]),
                  unit="szt.", part=part, ocid=ocid, notice=perf, field=e["n_changes"])
    for f in e.get("extra_info", []):
        card.fact("fakt", f"info_dodatkowe_{f['idx']}", "Informacje dodatkowe (ogłoszenie o wykonaniu)",
                  text=f["value"], part=part, ocid=ocid, notice=perf, field=f)

    # zmiany z ogłoszenia o wykonaniu
    for ch in e.get("changes", []):
        no = ch["no"]["value"].strip()
        val = P.parse_money(ch["value_change"]["value"]) if ch.get("value_change") else None
        db.upsert(con, "contract_change", {
            "contract_id": c["id"], "change_no": no, "change_date": None,
            "legal_basis": ch["legal_basis"]["value"] if ch.get("legal_basis") else None,
            "reason": ch["reason"]["value"] if ch.get("reason") else None,
            "description": ch["description"]["value"] if ch.get("description") else None,
            "value_change": val, "currency": ch["currency"]["value"] if ch.get("currency") else None,
            "price_increase": ch["price_increase"]["value"] if ch.get("price_increase") else None,
            "source_notice": perf["notice_number"], "source_section": P.loc(ch["no"]), "updated_at": card.ts,
        }, ["contract_id", "source_notice", "change_no"], preserve=())
        if val is not None:
            card.fact("fakt", f"zmiana_{no}_wartosc", f"Zmiana nr {no} – wartość zmiany", num=val, unit="PLN",
                      part=part, ocid=ocid, notice=perf, field=ch["value_change"])
            if c["value"] and val >= 0.9 * c["value"]:
                card.gap(f"zmiana_{part}_{no}_niejednoznaczna",
                         f"Zmiana nr {no} ({perf['notice_number']}): „Wartość zmiany” {val:,.2f} ≈ wartości umowy – "
                         "prawdopodobnie wpisano nową wartość umowy, a nie różnicę. Wymaga weryfikacji eksperta.")
    for n in c.get("_upd", []):
        x = n["ext"]
        val = P.parse_money(x["value_change"]["value"]) if x.get("value_change") else None
        db.upsert(con, "contract_change", {
            "contract_id": c["id"], "change_no": P.parse_date(x["change_date"]["value"]) if x.get("change_date") else n["notice_number"],
            "change_date": P.parse_date(x["change_date"]["value"]) if x.get("change_date") else None,
            "legal_basis": x["legal_basis"]["value"] if x.get("legal_basis") else None,
            "reason": x["reason"]["value"] if x.get("reason") else None,
            "description": x["description"]["value"] if x.get("description") else None,
            "value_change": val, "currency": x["currency"]["value"] if x.get("currency") else None,
            "price_increase": x["price_increase"]["value"] if x.get("price_increase") else None,
            "source_notice": n["notice_number"], "source_section": P.loc(x.get("change_date")), "updated_at": card.ts,
        }, ["contract_id", "source_notice", "change_no"], preserve=())

    # ---- obliczenia
    if c["value"] and c["paid_total"]:
        card.fact("obliczenie", "wzrost_wyplaty_pct", "Wzrost wypłaty względem wartości umowy",
                  num=round((c["paid_total"] / c["value"] - 1) * 100, 1), unit="%", part=part, ocid=ocid, notice=perf,
                  formula=f"({c['paid_total']:,.2f} / {c['value']:,.2f} − 1) × 100".replace(",", " "),
                  quote=f"{P.quote(e.get('paid_total'))} | {P.quote(e.get('value'))}")
        card.fact("obliczenie", "wzrost_wyplaty_pln", "Wzrost wypłaty względem wartości umowy (kwota)",
                  num=round(c["paid_total"] - c["value"], 2), unit="PLN", part=part, ocid=ocid, notice=perf,
                  formula=f"{c['paid_total']:,.2f} − {c['value']:,.2f}".replace(",", " "))
    if c["planned_end"] and c["actual_end"]:
        dd = _days(c["planned_end"], c["actual_end"])
        card.fact("obliczenie", "opoznienie_vs_pierwotny_dni",
                  "Faktyczne opóźnienie względem terminu z umowy pierwotnej", num=dd, unit="dni", part=part,
                  ocid=ocid, notice=perf, formula=f"{c['actual_end']} − {c['planned_end']}",
                  quote=f"{P.quote(e.get('period'))} | {P.quote(e.get('end_actual'))}")
    # przesunięcie terminu umownego aneksem (data w opisie zmiany późniejsza niż termin pierwotny)
    for ch in e.get("changes", []):
        txt = " ".join(ch[k]["value"] for k in ("description", "reason") if ch.get(k))
        dates = [P.parse_date(m) for m in re.findall(r"\d{1,2}\.\d{1,2}\.\d{4}|\d{4}-\d{2}-\d{2}", txt)]
        later = [x for x in dates if x and c["planned_end"] and x > c["planned_end"]]
        if later and re.search(r"termin|wydłuż|przedłuż", txt, re.I):
            new_end = max(later)
            no = ch["no"]["value"].strip()
            card.fact("obliczenie", f"przesuniecie_terminu_zm{no}",
                      f"Przesunięcie terminu umownego (zmiana nr {no})", num=_days(c["planned_end"], new_end),
                      unit="dni", part=part, ocid=ocid, notice=perf,
                      formula=f"{new_end} − {c['planned_end']} (nowy termin z opisu zmiany)",
                      quote=P.quote(ch.get("description") or ch.get("reason")))
            if c["actual_end"]:
                card.fact("obliczenie", "dotrzymanie_terminu_po_zmianach",
                          "Wykonanie względem terminu po zmianach", num=_days(new_end, c["actual_end"]), unit="dni",
                          part=part, ocid=ocid, notice=perf,
                          text="w terminie po zmianie" if c["actual_end"] <= new_end else "po terminie po zmianie",
                          formula=f"{c['actual_end']} − {new_end} (ujemne = przed terminem)")


def _signal(card, title, code, details, *, when, part, ocid, notice, field=None, quote=None):
    """Sygnał z materiału eksperckiego: zdarzenie z dowodem + propozycja kategorii do oceny eksperta."""
    card.event("sygnał", title, when=when, part=part, ocid=ocid, notice=notice, field=field, quote=quote, details=details)
    card.event("ryzyko", f"{code} {risks.NAMES[code]}", when=when, kind="propozycja", part=part, ocid=ocid,
               notice=notice, field=field, quote=quote,
               details=f"Propozycja regułowa dla sygnału „{title}”. Kategoria do potwierdzenia przez eksperta.")


def _change_signals(card, ch, title, when, part, ocid, notice):
    """Zmiana wykonawcy (art. 455 ust. 1 pkt 2) i odstąpienie/rozwiązanie umowy w opisie zmiany."""
    basis = (ch.get("legal_basis") or {}).get("value")
    if signals.contractor_change(basis):
        _signal(card, "Zmiana wykonawcy", "R12",
                f"{title}: zmiana na podstawie {basis} – wykonawcę zastąpiono innym podmiotem.",
                when=when, part=part, ocid=ocid, notice=notice, field=ch.get("legal_basis"))
    for key in ("reason", "description"):
        frag = signals.termination((ch.get(key) or {}).get("value"))
        if frag:
            _signal(card, "Odstąpienie lub rozwiązanie umowy", "R12",
                    f"{title}: w opisie zmiany pojawia się „{frag}”.",
                    when=when, part=part, ocid=ocid, notice=notice, field=ch.get(key))
            break


def _timeline_and_risks(con, card: Card, p, ocid, base_n, by_type, contracts):
    linked_perf = {c["_perf"]["notice_number"] for c in contracts if c.get("_perf")}
    want_part = p.get("part_no") or 0
    for res in by_type.get("TenderResultNotice", []):
        for part, d in res["ext"].get("by_part", {}).items():
            if want_part and part and part != want_part:
                continue
            cancel = signals.cancellation((d.get("result") or {}).get("value"),
                                          (d.get("cancel_basis") or {}).get("value"),
                                          (d.get("cancel_reason") or {}).get("value"))
            if cancel:
                _signal(card, "Postępowanie unieważnione" + (f" (część {part})" if part else ""), cancel["code"],
                        f"Przesłanka: {cancel['label']}" + (f" ({cancel['basis']})" if cancel["basis"] else "") + "."
                        + (f" Przyczyna: {cancel['reason'][:300]}" if cancel["reason"] else ""),
                        when=res["publication_date"], part=part, ocid=ocid, notice=res,
                        field=d.get("cancel_reason") or d.get("cancel_basis") or d.get("result"))
    for n in sum(by_type.values(), []):
        if n["notice_type"] == "ContractPerformingNotice" and n["notice_number"] not in linked_perf:
            continue  # ogłoszenie o wykonaniu innej części postępowania
        card.event("ogłoszenie", f"{NOTICE_LABELS.get(n['notice_type'], n['notice_type'])} {n['notice_number']}",
                   when=n["publication_date"], ocid=ocid, notice=n, quote=n["order_object"])
    for c in contracts:
        part, src, d = c["part_no"], c["_src"], c.get("_d") or {}
        if c["signed_date"]:
            card.event("umowa", f"Zawarcie umowy z {c['contractor_name'] or 'wykonawcą'}"
                       + (f" (część {part})" if part else ""), when=c["signed_date"], part=part, ocid=ocid,
                       notice=src, field=d.get("signed") or (src["ext"].get("signed")),
                       details=f"Wartość {c['value']:,.2f} PLN; termin do {c['planned_end']}".replace(",", " ")
                       if c["value"] else None)
        if c["planned_end"]:
            card.event("termin_umowny", "Pierwotny termin realizacji umowy", when=c["planned_end"], part=part,
                       ocid=ocid, notice=src, field=d.get("period") or src["ext"].get("period"))
        perf = c.get("_perf")
        upd_vals = {}
        for n in c.get("_upd", []):
            x = n["ext"]
            val = P.parse_money(x["value_change"]["value"]) if x.get("value_change") else None
            upd_vals[val] = n
            title = f"Zmiana umowy ({x['legal_basis']['value'] if x.get('legal_basis') else 'zmiana'})"
            card.event("zmiana_umowy", title, when=P.parse_date(x["change_date"]["value"]) if x.get("change_date") else n["publication_date"],
                       part=part, ocid=ocid, notice=n, field=x.get("reason"),
                       details=(f"Wartość zmiany: {val:,.2f} PLN".replace(",", " ") if val is not None else None))
            _risk_proposals(card, ocid, part, n, [x.get("reason"), x.get("description")], title,
                            when=P.parse_date(x["change_date"]["value"]) if x.get("change_date") else n["publication_date"])
            _change_signals(card, x, title, P.parse_date(x["change_date"]["value"]) if x.get("change_date") else n["publication_date"],
                            part, ocid, n)
        if perf:
            e = perf["ext"]
            for ch in e.get("changes", []):
                val = P.parse_money(ch["value_change"]["value"]) if ch.get("value_change") else None
                if val is not None and val in upd_vals:
                    continue  # ta sama zmiana jest już opisana ogłoszeniem o zmianie umowy (z datą)
                no = ch["no"]["value"].strip()
                title = f"Zmiana umowy nr {no} ({ch['legal_basis']['value'] if ch.get('legal_basis') else ''})".strip()
                card.event("zmiana_umowy", title, when=None, part=part, ocid=ocid, notice=perf, field=ch.get("reason"),
                           details=("Data zmiany nieznana – zmiana wykazana tylko w ogłoszeniu o wykonaniu. "
                                    + (f"Wartość zmiany: {val:,.2f} PLN".replace(",", " ") if val is not None else "Bez zmiany wynagrodzenia.")))
                _risk_proposals(card, ocid, part, perf, [ch.get("reason"), ch.get("description")], title)
                _change_signals(card, ch, title, None, part, ocid, perf)
            if c["actual_end"]:
                card.event("wykonanie", "Wykonanie umowy" + (" (po terminie pierwotnym)" if (c["on_time"] or "").lower().startswith("nie") else ""),
                           when=c["actual_end"], part=part, ocid=ocid, notice=perf, field=e.get("end_actual"),
                           details=(f"Wypłacono łącznie {c['paid_total']:,.2f} PLN".replace(",", " ") if c["paid_total"] else None))
            # sygnały z ogłoszenia o wykonaniu (materiał eksperta: „nienależyte wykonanie albo kara umowna”)
            when = c["actual_end"] or perf["publication_date"]
            if (c["properly_executed"] or "").lower().startswith("nie"):
                card.event("sygnał", "Umowa wykonana nienależycie", when=when, part=part, ocid=ocid, notice=perf,
                           field=e.get("properly"),
                           details="Ogłoszenie o wykonaniu umowy podaje, że umowa nie została wykonana należycie. "
                                   "Przyczyna (kary, odstąpienie, wady) nie wynika z ogłoszenia – wymaga sprawdzenia "
                                   "w dokumentach zamawiającego (BIP, protokoły).")
                card.event("ryzyko", f"R12 {risks.NAMES['R12']}", when=when, kind="propozycja", part=part, ocid=ocid,
                           notice=perf, field=e.get("properly"),
                           details="Propozycja regułowa: nienależyte wykonanie umowy wskazuje na problem po stronie "
                                   "wykonawcy lub realizacji. Kategoria do potwierdzenia przez eksperta.")
            if signals.not_executed((e.get("executed") or {}).get("value")):
                _signal(card, "Umowa niewykonana", "R12",
                        "Ogłoszenie o wykonaniu umowy podaje, że umowa nie została wykonana. Przyczynę (odstąpienie, "
                        "rozwiązanie, upadłość wykonawcy) trzeba ustalić w dokumentach zamawiającego.",
                        when=when, part=part, ocid=ocid, notice=perf, field=e.get("executed"))
            for f in e.get("extra_info", []):
                frag = signals.termination(f["value"])
                if frag:
                    _signal(card, "Odstąpienie lub rozwiązanie umowy", "R12",
                            f"Informacje dodatkowe w ogłoszeniu o wykonaniu wspominają: „{frag}”.",
                            when=when, part=part, ocid=ocid, notice=perf, field=f)
                    break
            if c["paid_total"] and c["value"] and c["paid_total"] < 0.9 * c["value"]:
                card.event("sygnał", "Wypłata niższa niż wartość umowy", when=when, part=part, ocid=ocid, notice=perf,
                           field=e.get("paid_total"),
                           details=(f"Wypłacono {c['paid_total'] / c['value']:.0%} wartości umowy. Możliwe przyczyny: "
                                    "ograniczenie zakresu, kary umowne, odstąpienie od umowy – ogłoszenie ich nie rozstrzyga."))
            for f in e.get("extra_info", []):
                for m in re.finditer(r"(Pozwolenie na użytkowanie[^\n]*?z dnia (\d{1,2}\.\d{1,2}\.\d{4}))|"
                                     r"(Protokół[^\n]*?odbior[^\n]*?z dnia (\d{1,2}\.\d{1,2}\.\d{4}))", f["value"]):
                    txt, dt = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
                    card.event("odbiór", txt[:120], when=P.parse_date(dt), part=part, ocid=ocid, notice=perf,
                               field=f, quote=txt)


def _repeated_procedures(con, client, card, p, ocid, base, log):
    """Wcześniejsze, unieważnione postępowanie tego samego zamawiającego o podobnym przedmiocie
    (materiał eksperta: „unieważnione postępowanie i jego powtórzenie są sygnałem ryzyka”)."""
    title = (base.get("orderObject") or "").strip().strip("„”\"")
    prefix = title[:30].rsplit(" ", 1)[0] if len(title) > 30 else title
    base_date = (base.get("publicationDate") or "")[:10]
    if not prefix or not base_date:
        return
    since = f"{int(base_date[:4]) - 2}{base_date[4:]}"
    try:
        items = client.search(OrganizationId=base.get("organizationId"), OrderObject=prefix,
                              PublicationDateFrom=since, NoticeType="TenderResultNotice")
    except BZPError as e:
        log(f"[{p['project_id']}] Wyszukiwanie wcześniejszych postępowań nie powiodło się: {e}")
        return
    for it in items:
        if (it.get("tenderId") == ocid or "uniew" not in (it.get("procedureResult") or "").lower()
                or (it.get("publicationDate") or "")[:10] > base_date
                or not signals.similar_title(title, it.get("orderObject"))):
            continue
        try:
            n = store_notice(con, client, it)
        except BZPError:
            continue
        for part, d in n["ext"].get("by_part", {}).items():
            cancel = signals.cancellation((d.get("result") or {}).get("value"),
                                          (d.get("cancel_basis") or {}).get("value"),
                                          (d.get("cancel_reason") or {}).get("value"))
            if not cancel:
                continue
            _signal(card, f"Wcześniejsze postępowanie unieważnione: {n['notice_number']}", cancel["code"],
                    f"Postępowanie {n['notice_number']} ({n['publication_date']}) o podobnym przedmiocie "
                    f"(„{(n['order_object'] or '')[:120]}”) unieważniono – obecne postępowanie jest jego powtórzeniem. "
                    f"Przesłanka: {cancel['label']}." + (f" Przyczyna: {cancel['reason'][:250]}" if cancel["reason"] else ""),
                    when=n["publication_date"], part=0, ocid=ocid, notice=n,
                    field=d.get("cancel_reason") or d.get("cancel_basis") or d.get("result"))
            lost = _days(n["publication_date"], base_date)
            if lost is not None:
                card.fact("obliczenie", f"czas_powtorzenia_{n['notice_number']}",
                          "Czas stracony na powtórzenie postępowania", num=lost, unit="dni", level="postępowanie",
                          ocid=ocid, notice=n,
                          formula=f"{base_date} (ogłoszenie obecnego postępowania) − {n['publication_date']} "
                                  f"(wynik unieważnionego {n['notice_number']})",
                          quote=P.quote(d.get("cancel_reason") or d.get("result")))
            break


def _risk_proposals(card, ocid, part, notice, fields, change_title, when=None):
    fields = [f for f in fields if f]
    text = " ".join(f["value"] for f in fields)
    for code, frag in risks.propose(text):
        src = next((f for f in fields if re.search(re.escape(frag), f["value"], re.I)), fields[0])
        card.event("ryzyko", f"{code} {risks.NAMES[code]}", when=when, kind="propozycja", part=part, ocid=ocid, notice=notice,
                   field=src, details=f"Propozycja regułowa dla: {change_title}. Sygnał w tekście: „{frag}”.")


def _bip_evidence(con, card, p, log):
    """Drugie źródło: dokumenty z BIP gminy (jeśli BIP zamawiającego jest w bip_sources.json)."""
    from . import bip
    try:
        found = bip.evidence_for_project(con, p, log=log)
    except Exception as e:  # BIP niedostępny – karta z BZP i tak powstaje
        card.gap("bip_error", f"Nie udało się przeszukać BIP zamawiającego: {e}")
        return False
    if found is None:
        return False  # BIP tej gminy nie jest skonfigurowany
    unreadable = []
    for f in found:
        d = f["doc"]
        status_note = {"skan": "skan bez warstwy tekstowej – dowodem jest tytuł i data publikacji",
                       "format": f"format .{d['ext']} nie jest odczytywany – dowodem jest tytuł i data publikacji",
                       "błąd": "nie udało się odczytać pliku – dowodem jest tytuł i data publikacji"}.get(d["status"])
        if status_note:
            unreadable.append(d["title"][:80])
        src = {"notice_number": f"BIP: {d['url'].rsplit('/', 1)[-1]}", "source_url": d["url"],
               "fetched_at": d["fetched_at"]}
        section = f"{d['source']} › {d['section']} › {f['location']}"
        db.upsert(con, "document_link", {"project_id": p["project_id"], "url": d["url"], "relation": f["relation"],
                                         "page": f["page"], "quote": f["quote"], "reason": f["reason"],
                                         "location": f["location"], "updated_at": card.ts},
                  ["project_id", "url"], preserve=())
        card.event("dokument BIP", d["title"][:160], when=d["published_at"], ocid=None, notice=src, quote=f["quote"], section=section,
                   details=f"{f['relation'].capitalize()}." + (f" {status_note.capitalize()}." if status_note else ""))
        for code, frag in risks.propose(f"{d['title']} {f['quote']}"):
            card.event("ryzyko", f"{code} {risks.NAMES[code]}", when=d["published_at"], kind="propozycja", ocid=None,
                       notice=src, quote=f["quote"], section=section,
                       details=f"Propozycja regułowa z dokumentu BIP ({f['relation']}). Sygnał w tekście: „{frag}”.")
        # łączne nakłady z WPF: „<nazwa> … <rok od> <rok do> <kwota>”
        m = re.search(r"(\d{4}) (\d{4}) (\d{1,3}(?: \d{3})+,\d{2})", f["quote"])
        if m and re.match(r"^\d+\.\d+\.\d+\.\d+\.?\s", f["quote"]) and re.search(r"Wieloletni|WPF", d["title"], re.I):
            card.fact("fakt", "bip_wpf_naklady", f"Łączne nakłady w WPF ({f['relation']}), okres {m.group(1)}–{m.group(2)}",
                      num=P.parse_money(m.group(3)), unit="PLN", level=f["relation"], ocid=None, notice=src, quote=f["quote"])
        con.execute("UPDATE fact SET source_section=? WHERE project_id=? AND source_notice=?",
                    (section, p["project_id"], src["notice_number"]))
    con.execute("DELETE FROM document_link WHERE project_id=? AND updated_at<? AND review_status='do_weryfikacji'", (p["project_id"], card.ts))
    if unreadable:
        card.gap("bip_nieczytelne", f"{len(unreadable)} dokumentów z BIP to skany lub pliki .doc – OCR nie jest obsługiwany, "
                                    f"więc dowodem jest tytuł i data publikacji (np. „{unreadable[0]}”).")
    if not found:
        card.gap("bip_brak", "W BIP zamawiającego nie znaleziono dokumentów wspominających miejscowość i zakres projektu.")
    return True


def _project_vs_contracts(card, p, ocid, contracts):
    """Kwota projektu (KPO) a suma umów – osobne poziomy, porównanie jako obliczenie."""
    kv = matcher.kpo_value(p.get("annotation"))
    vals = [c["value"] for c in contracts if c.get("value")]
    if kv and vals:
        card.fact("obliczenie", "udzial_umow_w_projekcie", "Suma umów względem wartości przedsięwzięcia (KPO)",
                  num=round(sum(vals) / kv * 100, 1), unit="%", level="projekt", ocid=ocid,
                  formula=f"{sum(vals):,.2f} / {kv:,.2f} × 100".replace(",", " ")
                  + " · wartość przedsięwzięcia może obejmować koszty poza umową na roboty")


def _gaps(card, p, by_type, contracts):
    if "TenderResultNotice" not in by_type:
        card.gap("brak_wyniku", "Nie znaleziono ogłoszenia o wyniku postępowania – brak cen ofert i wartości szacunkowej.")
    if not contracts:
        card.gap("brak_umowy", "Nie ustalono umowy dla tego zakresu.")
    for c in contracts:
        lab = f" (część {c['part_no']})" if c["part_no"] else ""
        if not c.get("_perf"):
            card.gap(f"brak_wykonania_{c['part_no']}",
                     f"Brak ogłoszenia o wykonaniu umowy{lab} – nie znamy faktycznego terminu ani kwoty wypłaconej. "
                     "Po publikacji przypadek zostanie przeliczony.")
        if c.get("n_changes") and c["n_changes"] > len(c.get("_upd", [])) and c.get("_perf"):
            pass  # zmiany bez osobnych ogłoszeń są wykazane w ogł. o wykonaniu – to nie brak
