"""Risk Miner – prototyp (Streamlit).

Uruchomienie:  streamlit run app.py
"""
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from riskminer import db, expert, importer, pipeline, risks
from riskminer.bzp.client import BZPClient

st.set_page_config(page_title="Risk Miner", page_icon="⛏️", layout="wide")
SAMPLE = Path(__file__).resolve().parent.parent / "Risk_Miner_dane_projekty.xlsx"


@st.cache_resource
def get_con():
    return db.connect()


con = get_con()


def q(sql, args=()):
    return [dict(r) for r in con.execute(sql, args).fetchall()]


def pln(v):
    return "—" if v is None else f"{v:,.2f} zł".replace(",", " ").replace(".", ",")


def mln(v):
    return "—" if v is None else f"{v / 1e6:.3f} mln zł".replace(".", ",")


STATUS_ICON = {"do_weryfikacji": "🟡", "zaakceptowane": "🟢", "odrzucone": "🔴", "poprawione": "🔵"}

# ============================================================================ sidebar
st.sidebar.title("⛏️ Risk Miner")
view = st.sidebar.radio("Widok", ["Baza inwestycji", "Weryfikacja eksperta", "Analiza nowego projektu"])
n_proj = con.execute("SELECT count(*) FROM project").fetchone()[0]
n_fetched = con.execute("SELECT count(*) FROM project WHERE last_fetch_status='ok'").fetchone()[0]
n_todo = con.execute("SELECT (SELECT count(*) FROM event WHERE kind='propozycja' AND status='do_weryfikacji')").fetchone()[0]
st.sidebar.caption(f"Projektów: {n_proj} · pobranych z BZP: {n_fetched} · propozycji do oceny: {n_todo}")


# ============================================================================ BAZA
def view_base():
    st.header("Baza inwestycji")
    with st.expander("1. Import arkusza projektów", expanded=n_proj == 0):
        up = st.file_uploader("Plik XLSX lub CSV", type=["xlsx", "csv"])
        c1, c2 = st.columns(2)
        run = None
        if up and c1.button("Importuj wgrany plik", type="primary"):
            run = (up.name, up.getvalue())
        if SAMPLE.exists() and c2.button(f"Importuj paczkę organizatora ({SAMPLE.name})"):
            run = (SAMPLE.name, SAMPLE.read_bytes())
        if run:
            rep = importer.import_file(con, *run)
            st.success(f"Import zakończony: {rep['counts']}")
            st.dataframe(pd.DataFrame(rep["rows"]), width="stretch", hide_index=True)

    projects = q("SELECT project_id, name, recipient_name, public_id_type, public_id, scope, last_fetch_status, "
                 "last_fetch_message FROM project ORDER BY project_id")
    if not projects:
        st.info("Zaimportuj arkusz, aby zobaczyć projekty.")
        return

    st.subheader("2. Projekty")
    df = pd.DataFrame(projects).rename(columns={
        "project_id": "ID", "name": "Przedsięwzięcie", "recipient_name": "Zamawiający", "public_id_type": "Rodzaj id",
        "public_id": "Identyfikator", "scope": "Zakres", "last_fetch_status": "BZP", "last_fetch_message": "Wynik pobrania"})
    st.dataframe(df, width="stretch", hide_index=True, height=300)

    ids = [p["project_id"] for p in projects]
    labels = {p["project_id"]: f"{p['project_id']} · {p['name'][:80]}" for p in projects}
    default = ids.index("RM-2026-003") if "RM-2026-003" in ids else 0
    pid = st.selectbox("Karta projektu", ids, index=default, format_func=lambda x: labels[x])

    c1, c2 = st.columns([1, 3])
    if c1.button("Pobierz / odśwież dane z BZP", type="primary"):
        _fetch([pid])
    if c2.button("Pobierz dane dla wszystkich rekordów (limit API: ~27 zapytań/min)"):
        _fetch(ids)
    project_card(pid)


def _fetch(ids):
    log_box = st.empty()
    lines = []

    def log(msg):
        lines.append(msg)
        log_box.code("\n".join(lines[-12:]))

    client = BZPClient(con, log=log)
    bar = st.progress(0.0)
    for i, pid in enumerate(ids, 1):
        res = pipeline.fetch_project(con, pid, client, log=log)
        log(f"==> {pid}: {res['status']} – {res['message']}")
        bar.progress(i / len(ids))
    log(f"Zapytań sieciowych do BZP: {client.n_network_calls} (reszta z cache)")


def project_card(pid):
    p = q("SELECT * FROM project WHERE project_id=?", (pid,))[0]
    st.markdown(f"### {p['name']}")
    st.caption(f"{p['recipient_name']} · {p['city']} ({p['voivodeship']}) · {p['public_id_type']}: `{p['public_id']}` · "
               f"zakres rekordu: **{p['scope']}**")
    if p.get("annotation"):
        st.caption(f"Adnotacja: {p['annotation'][:400]}")

    links = q("SELECT * FROM project_link WHERE project_id=? AND status<>'odrzucone'", (pid,))
    gaps = q("SELECT * FROM gap WHERE project_id=?", (pid,))
    if not links:
        st.warning("Brak powiązania z postępowaniem w BZP. " + " ".join(g["message"] for g in gaps))
        candidates_table(pid)
        return
    for l in links:
        badge = {"potwierdzone": "🟢", "proponowane": "🟡"}.get(l["status"], "")
        st.markdown(f"**Postępowanie** `{l['ocid']}` · metoda: *{l['method']}* · status: {badge} **{l['status']}**")
        if l["status"] == "proponowane":
            st.warning("Powiązanie zaproponowane automatycznie – potwierdź je albo wybierz innego kandydata "
                       "w widoku **Weryfikacja eksperta → Powiązania z BZP**.")
        st.caption(l["evidence"])
    candidates_table(pid)

    contracts = q("SELECT c.* FROM contract c JOIN project_link l ON l.ocid=c.ocid AND (l.part_no=0 OR l.part_no=c.part_no) "
                  "WHERE l.project_id=? AND l.status<>'odrzucone' ORDER BY c.part_no", (pid,))
    facts = q("SELECT * FROM fact WHERE project_id=?", (pid,))
    fx = {(f["key"], f["part_no"]): f for f in facts}

    for c in contracts:
        part = c["part_no"]
        st.markdown(f"#### Umowa{f' – część {part}' if part else ''}: {c['contractor_name']}")
        k = st.columns(5)
        k[0].metric("Wartość umowy", mln(c["value"]), help="Poziom: pojedyncza umowa (nie cały projekt)")
        growth = fx.get(("wzrost_wyplaty_pct", part))
        k[1].metric("Wypłacono łącznie", mln(c["paid_total"]),
                    delta=f"{growth['value_num']:+.1f}%" if growth else None, delta_color="inverse")
        k[2].metric("Termin z umowy pierwotnej", c["planned_end"] or "—")
        delay = fx.get(("opoznienie_vs_pierwotny_dni", part))
        k[3].metric("Wykonano", c["actual_end"] or "brak danych",
                    delta=f"{int(delay['value_num']):+d} dni vs pierwotny" if delay else None, delta_color="inverse")
        k[4].metric("Zmian umowy", c["n_changes"] if c["n_changes"] is not None else "—")
        shift = [f for f in facts if f["key"].startswith("przesuniecie_terminu") and f["part_no"] == part]
        if shift:
            after = fx.get(("dotrzymanie_terminu_po_zmianach", part))
            st.info(f"Termin umowny przesunięto aneksem o **{int(shift[0]['value_num'])} dni**; faktyczne opóźnienie "
                    f"względem umowy pierwotnej: **{int(delay['value_num']) if delay else '?'} dni**"
                    + (f"; względem terminu po zmianie: **{after['value_text']}** ({int(after['value_num']):+d} dni)." if after else "."))

    if gaps:
        st.markdown("#### ⚠️ Braki i niepewności")
        for g in gaps:
            st.warning(g["message"])

    t1, t2, t3, t4 = st.tabs(["Oś czasu", "Fakty i obliczenia", "Zmiany umowy", "Źródła (ogłoszenia)"])
    with t1:
        ev = q("SELECT * FROM event WHERE project_id=? ORDER BY COALESCE(event_date,'9999-12-31'), id", (pid,))
        show_types = st.multiselect("Typy zdarzeń", sorted({e["event_type"] for e in ev}),
                                    default=sorted({e["event_type"] for e in ev} - {"ogłoszenie"}))
        for e in ev:
            if e["event_type"] not in show_types:
                continue
            icon = "🧭" if e["kind"] == "propozycja" else "📌"
            head = f"{icon} **{e['event_date'] or 'data nieznana'}** · {e.get('expert_title') or e['title']}"
            if e["kind"] == "propozycja":
                head += f" · _propozycja_ {STATUS_ICON.get(e['status'], '')} {e['status']}"
            with st.expander(head, expanded=False):
                if e["details"]:
                    st.write(e["details"])
                evidence(e)
    with t2:
        kind_lab = {"fakt": "Fakt (odczyt z dokumentu)", "obliczenie": "Obliczenie", "propozycja": "Propozycja"}
        rows = [{
            "Rodzaj": kind_lab[f["kind"]], "Część": f["part_no"] or "", "Poziom": f["level"], "Pole": f["label"],
            "Wartość": (pln(f["value_num"]) if f["unit"] == "PLN" else
                        f"{f['value_num']:g} {f['unit'] or ''}" if f["value_num"] is not None else f["value_text"]),
            "Formuła": f["formula"] or "", "Źródło": f["source_notice"], "Miejsce w dokumencie": f["source_section"] or "",
        } for f in sorted(facts, key=lambda f: (f["kind"] != "fakt", f["part_no"], f["key"]))]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        sel = st.selectbox("Pokaż dowód dla", facts, format_func=lambda f: f"{f['label']} ({f['source_notice']})")
        if sel:
            evidence(sel)
    with t3:
        ch = q("SELECT ch.*, c.part_no FROM contract_change ch JOIN contract c ON c.id=ch.contract_id "
               "JOIN project_link l ON l.ocid=c.ocid AND (l.part_no=0 OR l.part_no=c.part_no) WHERE l.project_id=? AND l.status<>'odrzucone' "
               "ORDER BY ch.source_notice, ch.change_no", (pid,))
        if ch:
            st.dataframe(pd.DataFrame(ch)[["part_no", "change_no", "change_date", "legal_basis", "value_change",
                                           "price_increase", "reason", "source_notice"]],
                         width="stretch", hide_index=True)
            st.caption("Ta sama zmiana może występować dwukrotnie: w ogłoszeniu o zmianie umowy (z datą) i w zbiorczym "
                       "wykazie w ogłoszeniu o wykonaniu (z numerem).")
        else:
            st.write("Brak zmian umowy w pobranych ogłoszeniach.")
    with t4:
        for l in links:
            for n in q("SELECT notice_number, notice_type, publication_date, source_url, fetched_at FROM notice "
                       "WHERE ocid=? ORDER BY publication_date", (l["ocid"],)):
                with st.expander(f"{n['publication_date']} · {pipeline.NOTICE_LABELS.get(n['notice_type'], n['notice_type'])} "
                                 f"· {n['notice_number']}"):
                    st.markdown(f"[Otwórz w BZP]({n['source_url']}) · pobrano: {n['fetched_at']}")
                    html = con.execute("SELECT html FROM notice WHERE notice_number=?", (n["notice_number"],)).fetchone()[0]
                    components.html(html, height=500, scrolling=True)


def evidence(item):
    if not item.get("source_notice") or item["source_notice"] == "arkusz":
        st.caption("Źródło: arkusz projektów")
        if item.get("quote"):
            st.markdown(f"> {item['quote']}")
        return
    st.caption(f"Źródło: [{item['source_notice']}]({item.get('source_url')}) · {item.get('source_section') or ''}")
    if item.get("formula"):
        st.code(item["formula"])
    if item.get("quote"):
        for part in str(item["quote"]).split(" | "):
            st.markdown(f"> {part}")


# ============================================================================ EKSPERT
def candidates_table(pid, expanded=False):
    import json
    cands = q("SELECT * FROM link_candidate WHERE project_id=? ORDER BY rank", (pid,))
    if not cands:
        return []
    with st.expander(f"Kandydaci dopasowania KPO → BZP ({len(cands)})", expanded=expanded):
        icon = {"pasuje": "✅", "częściowo": "🟨", "różni się": "❌", "brak danych": "❔"}
        for c in cands:
            st.markdown(f"**{c['rank']}. {c.get('matched')}/{c.get('checked')} kryteriów · pewność {c.get('confidence')}** · "
                        f"{c['title'][:110]}  \n`{c['ocid']}` · ogłoszenie bazowe {c['base_notice']}")
            feats = json.loads(c["features_json"])
            icon = {"pasuje": "✅", "częściowo": "🟨", "nie pasuje": "❌", "różni się": "❌", "brak danych": "❔"}
            st.dataframe(pd.DataFrame([{"": icon.get(f["status"], ""), "Kryterium": f["name"], "Ocena": f["status"],
                                        "Podstawa": f["detail"]} for f in feats]),
                         hide_index=True, width="stretch")
            st.caption("Ogłoszenia: " + ", ".join(f"{t[2]} {pipeline.NOTICE_LABELS.get(t[0], t[0])} {t[1]}"
                                                   for t in json.loads(c["notices_json"])))
    return cands


def view_expert():
    st.header("Weryfikacja eksperta")
    t_risk, t_link = st.tabs(["Propozycje ryzyk", "Powiązania z BZP (rekordy KPO)"])
    with t_link:
        view_links()
    with t_risk:
        view_risks()


def view_links():
    st.caption("Rekordy KPO nie mają numeru ogłoszenia – system proponuje postępowanie z BZP na podstawie NIP "
               "zamawiającego, miejscowości, podsektora, nazwy, rodzaju zamówienia i skali. Ekspert potwierdza, "
               "wybiera innego kandydata albo odrzuca propozycję.")
    rows = q("SELECT p.project_id, p.name, p.public_id, l.id AS link_id, l.ocid, l.status, l.method, l.score "
             "FROM project p LEFT JOIN project_link l ON l.project_id=p.project_id AND l.status<>'odrzucone' "
             "WHERE p.public_id_type NOT LIKE '%BZP%' ORDER BY p.project_id")
    if not rows:
        st.info("Brak rekordów KPO.")
        return
    st.dataframe(pd.DataFrame([{"ID": r["project_id"], "Przedsięwzięcie": r["name"][:80], "KPO": r["public_id"],
                                "Status": r["status"] or "brak powiązania", "Metoda": r["method"] or "",
                                "Kryteria": f"{r['score'] * 100:.0f}%" if r["score"] else ""} for r in rows]),
                 hide_index=True, width="stretch")
    pid = st.selectbox("Rekord", [r["project_id"] for r in rows],
                       format_func=lambda x: next(f"{r['project_id']} · {r['name'][:80]} · {r['status'] or 'brak powiązania'}"
                                                  for r in rows if r["project_id"] == x))
    cur = next(r for r in rows if r["project_id"] == pid)
    cands = candidates_table(pid, expanded=True)
    if not cands:
        st.info("Brak kandydatów – uruchom pobranie danych z BZP dla tego rekordu w widoku Baza inwestycji.")
        return
    labels = {c["ocid"]: f"{c['rank']}. {c.get('matched')}/{c.get('checked')} kryteriów · pewność {c.get('confidence')} · {c['title'][:80]}" for c in cands}
    ocids = list(labels)
    choice = st.selectbox("Postępowanie do powiązania", ocids,
                          index=ocids.index(cur["ocid"]) if cur["ocid"] in labels else 0, format_func=labels.get)
    comment = st.text_input("Uzasadnienie powiązania", key=f"linkcom{pid}")
    c1, c2, _ = st.columns([1, 1, 2])
    if c1.button("✔ Potwierdź wybrane powiązanie", width="stretch"):
        with st.spinner("Przeliczam przypadek na podstawie BZP…"):
            expert.confirm_link(con, pid, choice, comment)
        st.rerun()
    if cur["link_id"] and c2.button("✖ Odrzuć obecne powiązanie", width="stretch"):
        with st.spinner("Przeliczam przypadek na podstawie BZP…"):
            expert.reject_link(con, pid, comment)
        st.rerun()
    hist = q("SELECT d.* FROM expert_decision d JOIN project_link l ON d.target='project_link' AND d.target_id=l.id "
             "WHERE l.project_id=? ORDER BY d.id", (pid,))
    if hist:
        st.caption("Historia: " + " · ".join(f"{h['created_at'][:16]} {h['decision']} {h['new_value'] or h['old_value'] or ''}"
                                             f"{(' – ' + h['comment']) if h['comment'] else ''}" for h in hist))


def view_risks():
    st.caption("Propozycje (np. przypisanie zdarzenia do kategorii ryzyka) obok fragmentu dokumentu. "
               "Decyzje są zapisywane z historią i nie są nadpisywane przy ponownym pobraniu danych.")
    status = st.radio("Status", ["do_weryfikacji", "zaakceptowane", "poprawione", "odrzucone"], horizontal=True)
    props = q("SELECT e.*, p.name FROM event e JOIN project p USING(project_id) WHERE e.kind='propozycja' AND e.status=? "
              "ORDER BY e.project_id, e.event_date", (status,))
    if not props:
        st.info("Brak propozycji w tym statusie.")
    codes = [c for c, _, _ in risks.CATALOG]
    for e in props:
        with st.container(border=True):
            l, r = st.columns([1, 1])
            l.markdown(f"**{e['project_id']}** · {e['name'][:70]}")
            l.markdown(f"Propozycja: **{e['title']}**")
            if e.get("expert_title") and e["expert_title"] != e["title"]:
                l.markdown(f"Decyzja eksperta: **{e['expert_title']}**")
            l.caption(e["details"] or "")
            with r:
                evidence(e)
            cur = (e.get("expert_title") or e["title"]).split()[0]
            c3, c4 = st.columns(2)
            new_code = c3.selectbox("Kategoria ryzyka", codes, index=codes.index(cur) if cur in codes else 0,
                                    key=f"code{e['id']}", format_func=lambda c: f"{c} {risks.NAMES[c]}")
            comment = c4.text_input("Uzasadnienie decyzji", key=f"com{e['id']}", value=e.get("expert_comment") or "")
            c1, c2, _ = st.columns([1, 1, 3])
            if c1.button("✔ Akceptuj", key=f"ok{e['id']}", width="stretch"):
                expert.decide_event(con, e["id"], "accept", new_code, comment)
                st.rerun()
            if c2.button("✖ Odrzuć", key=f"no{e['id']}", width="stretch"):
                expert.decide_event(con, e["id"], "reject", comment=comment)
                st.rerun()
            hist = q("SELECT * FROM expert_decision WHERE target='event' AND target_id=? ORDER BY id", (e["id"],))
            if hist:
                st.caption("Historia: " + " · ".join(f"{h['created_at'][:16]} {h['decision']} {h['new_value'] or ''} "
                                                     f"{('– ' + h['comment']) if h['comment'] else ''}" for h in hist))
    with st.expander("Katalog ryzyk R01–R15"):
        st.dataframe(pd.DataFrame(risks.CATALOG, columns=["Kod", "Ryzyko", "Efekty"]), hide_index=True,
                     width="stretch")


# ============================================================================ NOWY PROJEKT
def view_new():
    st.header("Analiza nowego projektu")
    st.info("Kolejny etap: opis/PDF/DOCX → cechy (podsektor, typ robót, skala, formuła, budżet, termin) → ranking "
            "podobnych przypadków z bazy, przedziały kosztu i terminu, flagi i rekomendacje, eksport CSV/JSON.")


{"Baza inwestycji": view_base, "Weryfikacja eksperta": view_expert, "Analiza nowego projektu": view_new}[view]()
