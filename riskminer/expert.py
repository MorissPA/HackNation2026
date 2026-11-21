"""Decyzje eksperta – wspólne dla UI w Streamlit i REST API.

Każda decyzja trafia do historii (expert_decision). Decyzja nie zmienia klucza wpisu (event.title),
tylko pola expert_title/expert_comment i status – dzięki temu ponowne pobranie danych jej nie nadpisze.
"""
from . import db, pipeline, risks
from .bzp.client import BZPClient

EVENT_DECISIONS = ("zaakceptowane", "poprawione", "odrzucone")


def _log(con, target, target_id, decision, comment, old, new, author="ekspert"):
    con.execute(
        "INSERT INTO expert_decision(target,target_id,decision,comment,old_value,new_value,author,created_at) "
        "VALUES (?,?,?,?,?,?,?,?)", (target, target_id, decision, comment, old, new, author, db.now()))


def decide_event(con, event_id: int, action: str, code: str = None, comment: str = None, author="ekspert"):
    """action: 'accept' (z opcjonalnie inną kategorią `code`) albo 'reject'."""
    e = con.execute("SELECT * FROM event WHERE id=?", (event_id,)).fetchone()
    if not e:
        raise ValueError(f"Nie ma zdarzenia {event_id}")
    if e["kind"] != "propozycja":
        raise ValueError("Decyzję podejmuje się tylko dla propozycji")
    orig = e["title"].split()[0]
    old = e["expert_title"] or e["title"]
    if action == "reject":
        decision, new_title = "odrzucone", None
    elif action == "accept":
        code = code or orig
        if code not in risks.NAMES:
            raise ValueError(f"Nieznana kategoria {code}")
        decision = "zaakceptowane" if code == orig else "poprawione"
        new_title = f"{code} {risks.NAMES[code]}"
    else:
        raise ValueError(f"Nieznana akcja {action}")
    _log(con, "event", event_id, decision, comment, old, new_title, author)
    con.execute("UPDATE event SET status=?, expert_title=?, expert_comment=? WHERE id=?",
                (decision, new_title, comment, event_id))
    con.commit()
    return decision


def _current_link(con, pid):
    return con.execute("SELECT * FROM project_link WHERE project_id=? AND status<>'odrzucone'", (pid,)).fetchone()


def confirm_link(con, pid: str, ocid: str, comment: str = None, refetch=True, author="ekspert"):
    """Potwierdza powiązanie z kandydatem `ocid` (ten sam co propozycja albo inny z rankingu)."""
    cand = con.execute("SELECT * FROM link_candidate WHERE project_id=? AND ocid=?", (pid, ocid)).fetchone()
    if not cand:
        raise ValueError("Wybrane postępowanie nie jest na liście kandydatów tego rekordu")
    cur = _current_link(con, pid)
    ts = db.now()
    same = bool(cur) and cur["ocid"] == ocid
    if cur and not same:
        con.execute("UPDATE project_link SET status='odrzucone', updated_at=? WHERE id=?", (ts, cur["id"]))
        _log(con, "project_link", cur["id"], "odrzucone", comment, cur["ocid"], None, author)
    link_id = db.upsert(con, "project_link", {
        "project_id": pid, "ocid": ocid, "part_no": 0, "method": cur["method"] if same else "ekspert",
        "score": cand["score"] / 100, "status": "potwierdzone",
        "evidence": (f"Potwierdzone przez eksperta. Kandydat nr {cand['rank']} ({cand['score']:.0f}/100): "
                     f"{cand['title'][:120]}." + (f" Uzasadnienie: {comment}" if comment else "")),
        "created_at": ts, "updated_at": ts}, ["project_id", "ocid"], preserve=("created_at",))
    _log(con, "project_link", link_id, "zaakceptowane" if same else "poprawione", comment,
         cur["ocid"] if cur else None, ocid, author)
    con.commit()
    if refetch:
        return pipeline.fetch_project(con, pid, BZPClient(con), log=lambda m: None)


def reject_link(con, pid: str, comment: str = None, refetch=True, author="ekspert"):
    cur = _current_link(con, pid)
    if not cur:
        raise ValueError("Rekord nie ma aktywnego powiązania")
    con.execute("UPDATE project_link SET status='odrzucone', updated_at=? WHERE id=?", (db.now(), cur["id"]))
    _log(con, "project_link", cur["id"], "odrzucone", comment, cur["ocid"], None, author)
    con.commit()
    if refetch:
        return pipeline.fetch_project(con, pid, BZPClient(con), log=lambda m: None)
