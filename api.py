"""REST API Risk Miner dla frontendu w Vite (web/).

Uruchomienie samodzielne:  .venv/bin/uvicorn api:app --port 8000
Razem z frontendem:        cd web && npm run dev
"""
import json
import threading
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from riskminer import analysis, db, expert, importer, matcher, pipeline, risks
from riskminer.bzp.client import BZPClient

SAMPLE = Path(__file__).resolve().parent.parent / "Risk_Miner_dane_projekty.xlsx"
app = FastAPI(title="Risk Miner API", version="0.1")


def get_con():
    con = db.connect()
    try:
        yield con
    finally:
        con.close()


def rows(con, sql, args=()):
    return [dict(r) for r in con.execute(sql, args).fetchall()]


# --------------------------------------------------------------------------- przegląd
@app.get("/api/stats")
def stats(con=Depends(get_con)):
    one = lambda sql: con.execute(sql).fetchone()[0]
    return {
        "projects": one("SELECT count(*) FROM project"),
        "fetched": one("SELECT count(*) FROM project WHERE last_fetch_status='ok'"),
        "links_confirmed": one("SELECT count(*) FROM project_link WHERE status='potwierdzone'"),
        "links_proposed": one("SELECT count(*) FROM project_link WHERE status='proponowane'"),
        "proposals_open": one("SELECT count(*) FROM visible_event WHERE kind='propozycja' AND status='do_weryfikacji'"),
        "sample_available": SAMPLE.exists(),
    }


@app.get("/api/risks")
def risk_catalog():
    return [{"code": c, "name": n, "effects": e} for c, n, e in risks.CATALOG]


# --------------------------------------------------------------------------- import
def _import(con, name, content):
    rep = importer.import_file(con, name, content)
    return rep


@app.post("/api/import")
async def import_upload(file: UploadFile = File(...), con=Depends(get_con)):
    return _import(con, file.filename, await file.read())


@app.post("/api/import/sample")
def import_sample(con=Depends(get_con)):
    if not SAMPLE.exists():
        raise HTTPException(404, f"Brak pliku {SAMPLE.name} obok katalogu aplikacji")
    return _import(con, SAMPLE.name, SAMPLE.read_bytes())


# --------------------------------------------------------------------------- projekty
@app.get("/api/projects")
def projects(con=Depends(get_con)):
    return rows(con, """
        SELECT p.project_id, p.name, p.recipient_name, p.city, p.public_id_type, p.public_id, p.scope,
               p.last_fetch_status, p.last_fetch_message, p.last_fetch_at,
               l.status AS link_status, l.method AS link_method,
               (SELECT count(*) FROM gap g WHERE g.project_id=p.project_id) AS n_gaps,
               (SELECT count(*) FROM visible_event e WHERE e.project_id=p.project_id AND e.kind='propozycja'
                  AND e.status='do_weryfikacji') AS n_open
        FROM project p
        LEFT JOIN project_link l ON l.project_id=p.project_id AND l.status<>'odrzucone'
        ORDER BY p.project_id""")


def _candidates(con, pid):
    out = rows(con, "SELECT project_id, ocid, rank, score, title, base_notice, features_json, notices_json, "
                    "confidence, matched, checked "
                    "FROM link_candidate WHERE project_id=? ORDER BY rank", (pid,))
    for c in out:
        c["features"] = json.loads(c.pop("features_json") or "[]")
        c["notices"] = [{"type": t, "label": pipeline.NOTICE_LABELS.get(t, t), "number": n, "date": d}
                        for t, n, d in json.loads(c.pop("notices_json") or "[]")]
    return out


@app.get("/api/projects/{pid}")
def project_card(pid: str, con=Depends(get_con)):
    p = con.execute("SELECT * FROM project WHERE project_id=?", (pid,)).fetchone()
    if not p:
        raise HTTPException(404, "Nie ma takiego projektu")
    p = dict(p)
    p.pop("raw_json", None)
    links = rows(con, "SELECT * FROM project_link WHERE project_id=? AND status<>'odrzucone'", (pid,))
    join = ("JOIN project_link l ON l.ocid=c.ocid AND (l.part_no=0 OR l.part_no=c.part_no) "
            "WHERE l.project_id=? AND l.status<>'odrzucone'")
    contracts = rows(con, f"SELECT c.* FROM contract c {join} ORDER BY c.part_no", (pid,))
    changes = rows(con, f"SELECT ch.*, c.part_no FROM contract_change ch JOIN contract c ON c.id=ch.contract_id {join} "
                        "ORDER BY c.part_no, ch.source_notice, ch.change_no", (pid,))
    facts = rows(con, "SELECT * FROM visible_fact WHERE project_id=? ORDER BY kind<>'fakt', part_no, key", (pid,))
    events = rows(con, "SELECT * FROM visible_event WHERE project_id=? ORDER BY COALESCE(event_date,'9999-12-31'), id", (pid,))
    notices = []
    for l in links:
        notices += rows(con, "SELECT notice_number, notice_type, publication_date, source_url, fetched_at FROM notice "
                             "WHERE ocid=? ORDER BY publication_date", (l["ocid"],))
    for n in notices:
        n["label"] = pipeline.NOTICE_LABELS.get(n["notice_type"], n["notice_type"])
    documents = rows(con, "SELECT d.url, d.source, d.title, d.section, d.published_at, d.ext, d.status, d.fetched_at, "
                          "l.reason, l.location, l.review_status, l.relation, l.page, l.quote FROM document_link l JOIN document d ON d.url=l.url "
                          "WHERE l.project_id=? ORDER BY d.published_at", (pid,))
    return {
        "project": p,
        "kpo_value": matcher.kpo_value(p.get("annotation")),
        "links": links,
        "candidates": _candidates(con, pid),
        "contracts": contracts,
        "changes": changes,
        "facts": facts,
        "events": events,
        "gaps": rows(con, "SELECT key, message FROM gap WHERE project_id=? ORDER BY key", (pid,)),
        "notices": notices,
        "documents": documents,
    }


@app.get("/api/notices/html", response_class=HTMLResponse)
def notice_html(number: str, con=Depends(get_con)):
    r = con.execute("SELECT html FROM notice WHERE notice_number=?", (number,)).fetchone()
    if not r:
        raise HTTPException(404, "Nie ma takiego ogłoszenia w bazie")
    return HTMLResponse(r["html"] or "")


# --------------------------------------------------------------------------- pobieranie z BZP
JOBS = {}
_job_lock = threading.Lock()


def _run_job(job_id, ids):
    job = JOBS[job_id]
    con = db.connect()

    def log(msg):
        with _job_lock:
            job["log"].append(msg)
            job["log"] = job["log"][-300:]

    try:
        client = BZPClient(con, log=log)
        for i, pid in enumerate(ids, 1):
            job["current"] = pid
            try:
                res = pipeline.fetch_project(con, pid, client, log=log)
                log(f"==> {pid}: {res['status']} – {res['message']}")
            except Exception as e:  # jeden rekord nie zatrzymuje reszty
                log(f"==> {pid}: błąd – {e}")
            job["done"] = i
        job["network_calls"] = client.n_network_calls
        job["sources"] = sorted(client.sources_used)
        job["status"] = "zakończone"
    except Exception as e:
        job["status"] = "błąd"
        log(f"Błąd: {e}")
    finally:
        con.close()


class FetchRequest(BaseModel):
    project_ids: list = []
    all: bool = False


@app.post("/api/fetch")
def start_fetch(req: FetchRequest, con=Depends(get_con)):
    ids = ([r["project_id"] for r in con.execute("SELECT project_id FROM project ORDER BY project_id")]
           if req.all else req.project_ids)
    if not ids:
        raise HTTPException(400, "Podaj rekordy do pobrania")
    job_id = uuid.uuid4().hex[:10]
    JOBS[job_id] = {"id": job_id, "status": "trwa", "total": len(ids), "done": 0, "current": None, "log": []}
    threading.Thread(target=_run_job, args=(job_id, ids), daemon=True).start()
    return JOBS[job_id]


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "Nie ma takiego zadania")
    return JOBS[job_id]


# --------------------------------------------------------------------------- ekspert
@app.get("/api/proposals")
def proposals(status: str = "do_weryfikacji", con=Depends(get_con)):
    out = rows(con, "SELECT e.*, p.name AS project_name FROM visible_event e JOIN project p USING(project_id) "
                    "WHERE e.kind='propozycja' AND e.status=? ORDER BY e.project_id, COALESCE(e.event_date,''), e.id",
               (status,))
    for e in out:
        e["history"] = rows(con, "SELECT decision, comment, old_value, new_value, created_at FROM expert_decision "
                                 "WHERE target='event' AND target_id=? ORDER BY id", (e["id"],))
    return out


class EventDecision(BaseModel):
    action: str            # accept | reject
    code: str = None       # kategoria R01–R15 przy akceptacji (inna = poprawka)
    comment: str = None


@app.post("/api/events/{event_id}/decision")
def event_decision(event_id: int, d: EventDecision, con=Depends(get_con)):
    try:
        return {"status": expert.decide_event(con, event_id, d.action, d.code, d.comment)}
    except ValueError as e:
        raise HTTPException(400, str(e))


class DocumentDecision(BaseModel):
    url: str
    action: str


@app.post("/api/projects/{pid}/documents/decision")
def document_decision(pid: str, decision: DocumentDecision, con=Depends(get_con)):
    statuses = {"accept": "zaakceptowane", "reject": "odrzucone"}
    if decision.action not in statuses:
        raise HTTPException(400, "Nieznana decyzja")
    status = statuses[decision.action]
    with con:
        updated = con.execute("UPDATE document_link SET review_status=? WHERE project_id=? AND url=?",
                              (status, pid, decision.url))
        if not updated.rowcount:
            raise HTTPException(404, "Nie znaleziono powiązania dokumentu z projektem")
        con.execute("INSERT INTO document_review(project_id,url,status,reviewed_at) VALUES(?,?,?,?)",
                    (pid, decision.url, status, db.now()))
    return {"status": status}


@app.get("/api/kpo-links")
def kpo_links(con=Depends(get_con)):
    out = rows(con, """
        SELECT p.project_id, p.name, p.public_id, l.ocid, l.status, l.method, l.score
        FROM project p LEFT JOIN project_link l ON l.project_id=p.project_id AND l.status<>'odrzucone'
        WHERE p.public_id_type NOT LIKE '%BZP%' ORDER BY p.project_id""")
    for r in out:
        r["candidates"] = _candidates(con, r["project_id"])
        r["history"] = rows(con, "SELECT d.decision, d.comment, d.old_value, d.new_value, d.created_at "
                                 "FROM expert_decision d JOIN project_link l ON d.target='project_link' "
                                 "AND d.target_id=l.id WHERE l.project_id=? ORDER BY d.id", (r["project_id"],))
    return out


class LinkDecision(BaseModel):
    action: str            # confirm | reject
    ocid: str = None
    comment: str = None


@app.post("/api/projects/{pid}/link")
def link_decision(pid: str, d: LinkDecision, con=Depends(get_con)):
    try:
        if d.action == "confirm":
            res = expert.confirm_link(con, pid, d.ocid, d.comment)
        elif d.action == "reject":
            res = expert.reject_link(con, pid, d.comment)
        else:
            raise ValueError("Nieznana akcja")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"result": res}


# --------------------------------------------------------------------------- analiza nowego projektu
class AnalysisRequest(BaseModel):
    text: str
    top_k: int = 5


def _analyze(con, text, top_k=5):
    if len((text or "").strip()) < 30:
        raise HTTPException(400, "Opis jest za krótki – podaj co najmniej zakres, podsektor i skalę inwestycji.")
    return analysis.analyze(con, text, top_k=top_k)


@app.post("/api/analysis")
def run_analysis(req: AnalysisRequest, con=Depends(get_con)):
    return _analyze(con, req.text, req.top_k)


@app.post("/api/analysis/file")
async def run_analysis_file(file: UploadFile = File(...), con=Depends(get_con)):
    try:
        text = analysis.text_from_file(file.filename, await file.read())
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # uszkodzony plik
        raise HTTPException(400, f"Nie udało się odczytać pliku: {e}")
    return _analyze(con, text)


@app.post("/api/analysis/export")
def export_analysis(req: AnalysisRequest, format: str = "csv", con=Depends(get_con)):
    result = _analyze(con, req.text, req.top_k)
    if format == "json":
        body = json.dumps(result, ensure_ascii=False, indent=2)
        return Response(body, media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="risk_miner_analiza.json"'})
    body = "\ufeff" + analysis.to_csv(result)  # BOM: polskie znaki poprawnie w Excelu
    return Response(body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="risk_miner_analiza.csv"'})


# --------------------------------------------------------------------------- zbudowany frontend
# Po `npm run build` w web/ backend serwuje też interfejs – całość działa wtedy na jednym porcie (:8000).
_DIST = Path(__file__).resolve().parent / "web" / "dist"
if _DIST.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="web")
