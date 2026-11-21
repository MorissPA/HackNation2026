import { useEffect, useState } from "react";
import { api, type Risk, type Row } from "./api";
import { CandidateList } from "./ProjectCard";
import { DecisionChip, ErrorBox, Evidence, LinkChip, Spinner, Tabs } from "./ui";

const STATUSES = ["do_weryfikacji", "zaakceptowane", "poprawione", "odrzucone"] as const;

function History({ items }: { items: Row[] }) {
  if (!items?.length) return null;
  return (
    <div className="small muted">Historia: {items.map((h, i) => (
      <span key={i}>{i ? " · " : ""}{String(h.created_at).slice(0, 16).replace("T", " ")} {h.decision}
        {h.new_value ? ` → ${h.new_value}` : ""}{h.comment ? ` – ${h.comment}` : ""}</span>))}</div>
  );
}

function ProposalCard({ e, risks, onDone }: { e: Row; risks: Risk[]; onDone: () => void }) {
  const current = String(e.expert_title ?? e.title).split(" ")[0];
  const [code, setCode] = useState(current);
  const [comment, setComment] = useState(e.expert_comment ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const act = async (action: "accept" | "reject") => {
    setBusy(true); setError(null);
    try { await api.decideEvent(e.id, action, action === "accept" ? code : undefined, comment || undefined); onDone(); }
    catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  return (
    <div className="panel">
      <div className="grid2" style={{ alignItems: "start" }}>
        <div style={{ display: "grid", gap: 6 }}>
          <div className="small muted"><span className="mono">{e.project_id}</span> · {e.project_name}</div>
          <div className="row"><b>{e.title}</b><DecisionChip status={e.status} /></div>
          {e.expert_title && e.expert_title !== e.title ? <div>Decyzja eksperta: <b>{e.expert_title}</b></div> : null}
          <div className="small muted">{e.event_date ?? "data nieznana"} · {e.details}</div>
        </div>
        <Evidence item={e} />
      </div>
      <div className="row">
        <label htmlFor={`code-${e.id}`} className="small muted">Kategoria</label>
        <select id={`code-${e.id}`} value={code} onChange={(x) => setCode(x.target.value)} style={{ maxWidth: 380 }}>
          {risks.map((r) => <option key={r.code} value={r.code}>{r.code} {r.name}</option>)}
        </select>
        <input type="text" id={`comment-${e.id}`} placeholder="Uzasadnienie decyzji" value={comment}
          onChange={(x) => setComment(x.target.value)} style={{ flex: 1, minWidth: 220 }} />
        <button className="btn ok" disabled={busy} onClick={() => act("accept")}>
          {code === String(e.title).split(" ")[0] ? "✔ Akceptuj" : "✔ Popraw kategorię"}</button>
        <button className="btn bad" disabled={busy} onClick={() => act("reject")}>✖ Odrzuć</button>
        {busy ? <Spinner /> : null}
      </div>
      <ErrorBox error={error} />
      <History items={e.history} />
    </div>
  );
}

function RiskProposals({ onChanged }: { onChanged: () => void }) {
  const [status, setStatus] = useState<string>("do_weryfikacji");
  const [items, setItems] = useState<Row[] | null>(null);
  const [risks, setRisks] = useState<Risk[]>([]);
  const [tick, setTick] = useState(0);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.risks().then(setRisks).catch(() => undefined); }, []);
  useEffect(() => { setItems(null); api.proposals(status).then(setItems).catch((e) => setError(e.message)); }, [status, tick]);
  return (
    <>
      <p className="muted">Propozycje przypisania zdarzenia do kategorii ryzyka R01–R15 obok fragmentu dokumentu. Decyzja trafia do historii i nie jest nadpisywana przy ponownym pobraniu danych.</p>
      <div className="row">{STATUSES.map((s) => (
        <button key={s} className={`btn ${status === s ? "primary" : ""}`} onClick={() => setStatus(s)}>{s.replace("_", " ")}</button>))}</div>
      <ErrorBox error={error} />
      {items === null ? <Spinner /> : items.length ? items.map((e) => (
        <ProposalCard key={e.id} e={e} risks={risks} onDone={() => { setTick((t) => t + 1); onChanged(); }} />
      )) : <div className="empty">Brak propozycji w tym statusie.</div>}
      <details className="panel">
        <summary><b>Katalog ryzyk R01–R15</b> <span className="small muted">(materiał ekspercki organizatora)</span></summary>
        <div className="scroll"><table><tbody>{risks.map((r) => (
          <tr key={r.code}><td className="mono">{r.code}</td><td><b>{r.name}</b></td><td className="small">{r.effects}</td></tr>))}</tbody></table></div>
      </details>
    </>
  );
}

function KpoLinks({ onChanged }: { onChanged: () => void }) {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [choice, setChoice] = useState<string>("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = () => api.kpoLinks().then((r) => { setRows(r); if (!sel && r.length) setSel(r[0].project_id); }).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const cur = rows?.find((r) => r.project_id === sel);
  useEffect(() => { if (cur) { setChoice(cur.ocid ?? cur.candidates[0]?.ocid ?? ""); setComment(""); } }, [sel, rows]); // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (action: "confirm" | "reject") => {
    if (!cur) return;
    setBusy(true); setError(null);
    try { await api.decideLink(cur.project_id, action, action === "confirm" ? choice : undefined, comment || undefined); await load(); onChanged(); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  if (!rows) return <Spinner />;
  return (
    <>
      <p className="muted">Rekordy KPO nie mają numeru ogłoszenia. System proponuje postępowanie z BZP na podstawie NIP zamawiającego, miejscowości, podsektora, nazwy, rodzaju zamówienia i skali. Ekspert potwierdza propozycję, wybiera innego kandydata albo ją odrzuca – przypadek przelicza się automatycznie.</p>
      <div className="panel scroll">
        <table>
          <thead><tr><th>ID</th><th>Przedsięwzięcie</th><th>Numer KPO</th><th>Status</th><th className="num">Wynik</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.project_id} className={`click ${sel === r.project_id ? "sel" : ""}`} onClick={() => setSel(r.project_id)}>
              <td className="mono small">{r.project_id}</td><td>{r.name}</td><td className="mono small">{r.public_id}</td>
              <td><LinkChip status={r.status} /></td><td className="num">{r.score != null ? Math.round(r.score * 100) : ""}</td></tr>))}</tbody>
        </table>
      </div>
      {cur ? (
        <div className="panel">
          <h3>{cur.name}</h3>
          {cur.candidates.length ? (
            <>
              <CandidateList candidates={cur.candidates} open />
              <div className="row">
                <label htmlFor="link-choice" className="small muted">Postępowanie</label>
                <select id="link-choice" value={choice} onChange={(e) => setChoice(e.target.value)} style={{ maxWidth: 520 }}>
                  {cur.candidates.map((c: Row) => <option key={c.ocid} value={c.ocid}>{c.rank}. {Math.round(c.score)}/100 · {String(c.title).slice(0, 90)}</option>)}
                </select>
              </div>
              <div className="row">
                <input type="text" id="link-comment" placeholder="Uzasadnienie powiązania" value={comment}
                  onChange={(e) => setComment(e.target.value)} style={{ flex: 1, minWidth: 220 }} />
                <button className="btn ok" disabled={busy || !choice} onClick={() => act("confirm")}>✔ Potwierdź wybrane powiązanie</button>
                {cur.ocid ? <button className="btn bad" disabled={busy} onClick={() => act("reject")}>✖ Odrzuć obecne</button> : null}
                {busy ? <><Spinner /> <span className="small muted">przeliczam przypadek…</span></> : null}
              </div>
            </>
          ) : <div className="gap">Brak kandydatów – pobierz dane z BZP dla tego rekordu w widoku Baza inwestycji.</div>}
          <ErrorBox error={error} />
          <History items={cur.history} />
        </div>
      ) : null}
    </>
  );
}

export function ExpertView({ onChanged }: { onChanged: () => void }) {
  const [tab, setTab] = useState<"risks" | "links">("risks");
  return (
    <>
      <h2>Weryfikacja eksperta</h2>
      <Tabs value={tab} onChange={setTab} items={[{ id: "risks", label: "Propozycje ryzyk" }, { id: "links", label: "Powiązania KPO → BZP" }]} />
      {tab === "risks" ? <RiskProposals onChanged={onChanged} /> : <KpoLinks onChanged={onChanged} />}
    </>
  );
}
