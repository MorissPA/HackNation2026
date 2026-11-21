import { useEffect, useMemo, useState } from "react";
import { api, type Card, type Candidate, type Row } from "./api";
import { ConfidenceChip, ErrorBox, Evidence, KindChip, LinkChip, DecisionChip, STATUS_ICON, Spinner, Tabs, factValue, mln, num, pln } from "./ui";

type Tab = "timeline" | "facts" | "changes" | "sources";

export function CandidateList({ candidates, open = false }: { candidates: Candidate[]; open?: boolean }) {
  if (!candidates.length) return null;
  return (
    <details open={open}>
      <summary className="small" style={{ color: "var(--accent)" }}>Kandydaci dopasowania KPO → BZP ({candidates.length})</summary>
      <div style={{ display: "grid", gap: 12, marginTop: 8 }}>
        {candidates.map((c) => (
          <div key={c.ocid} style={{ display: "grid", gap: 4 }}>
            <div className="row"><b>{c.rank}.</b> {c.matched != null ? <b>{c.matched}/{c.checked} kryteriów</b> : null}
              <ConfidenceChip level={c.confidence} /> <span>{c.title}</span></div>
            <div className="small muted mono">{c.ocid} · ogłoszenie bazowe {c.base_notice}</div>
            <div className="scroll">
              <table>
                <thead><tr><th></th><th>Kryterium</th><th>Ocena</th><th>Podstawa</th></tr></thead>
                <tbody>
                  {c.features.map((f) => (
                    <tr key={f.name}><td>{STATUS_ICON[f.status] ?? ""}</td><td>{f.name}</td><td>{f.status}</td>
                      <td className="small">{f.detail}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="small muted">{c.notices.map((n) => `${n.date} ${n.label} ${n.number}`).join(" · ")}</div>
          </div>
        ))}
      </div>
    </details>
  );
}

function ContractBlock({ c, facts }: { c: Row; facts: Row[] }) {
  const f = (key: string) => facts.find((x) => x.key === key && x.part_no === c.part_no);
  const growth = f("wzrost_wyplaty_pct");
  const delay = f("opoznienie_vs_pierwotny_dni");
  const shift = facts.find((x) => x.key.startsWith("przesuniecie_terminu") && x.part_no === c.part_no);
  const after = f("dotrzymanie_terminu_po_zmianach");
  return (
    <div className="panel">
      <div className="row between">
        <h3>Umowa{c.part_no ? ` – część ${c.part_no}` : ""}: {c.contractor_name ?? "wykonawca nieznany"}</h3>
        <span className="small muted">zawarta {c.signed_date ?? "—"}</span>
      </div>
      <div className="kpis">
        <div className="kpi"><span className="l">Wartość umowy</span><span className="v" title={pln(c.value)}>{mln(c.value)}</span>
          <span className="small muted">poziom: pojedyncza umowa</span></div>
        <div className="kpi"><span className="l">Wypłacono łącznie</span><span className="v" title={pln(c.paid_total)}>{mln(c.paid_total)}</span>
          {growth ? <span className={`d ${growth.value_num > 0 ? "up" : "down"}`}>{growth.value_num > 0 ? "+" : ""}{num(growth.value_num)}% względem umowy</span> : null}</div>
        <div className="kpi"><span className="l">Termin z umowy pierwotnej</span><span className="v">{c.planned_end ?? "—"}</span></div>
        <div className="kpi"><span className="l">Wykonano</span><span className="v">{c.actual_end ?? "brak danych"}</span>
          {delay ? <span className={`d ${delay.value_num > 0 ? "up" : "down"}`}>{delay.value_num > 0 ? "+" : ""}{num(delay.value_num, 0)} dni vs pierwotny</span> : null}</div>
        <div className="kpi"><span className="l">Zmian umowy</span><span className="v">{c.n_changes ?? "—"}</span></div>
      </div>
      {shift ? (
        <div className="note">
          Termin umowny przesunięto zmianą o <b>{num(shift.value_num, 0)} dni</b>; faktyczne opóźnienie względem umowy pierwotnej:{" "}
          <b>{delay ? num(delay.value_num, 0) : "?"} dni</b>
          {after ? <>; względem terminu po zmianie: <b>{after.value_text}</b> ({after.value_num > 0 ? "+" : ""}{num(after.value_num, 0)} dni).</> : "."}
        </div>
      ) : null}
    </div>
  );
}

function Timeline({ events }: { events: Row[] }) {
  const types = useMemo(() => Array.from(new Set(events.map((e) => e.event_type))).sort(), [events]);
  const [hidden, setHidden] = useState<Set<string>>(new Set(["ogłoszenie"]));
  const toggle = (t: string) => setHidden((h) => { const n = new Set(h); n.has(t) ? n.delete(t) : n.add(t); return n; });
  const shown = events.filter((e) => !hidden.has(e.event_type));
  return (
    <div style={{ display: "grid", gap: 10 }}>
      <div className="row small">
        <span className="muted">Pokaż:</span>
        {types.map((t) => (
          <label key={t} className="row" style={{ gap: 4 }}>
            <input type="checkbox" checked={!hidden.has(t)} onChange={() => toggle(t)} />{t}
          </label>
        ))}
      </div>
      <div className="timeline">
        {shown.map((e) => (
          <details key={e.id} className={`event ${e.kind === "propozycja" ? "prop" : ""}`}>
            <summary>
              <span className="date">{e.event_date ?? "data nieznana"}</span>
              <span style={{ flex: 1, minWidth: 0 }}>{e.expert_title ?? e.title}</span>
              {e.kind === "propozycja" ? <><KindChip kind="propozycja" /><DecisionChip status={e.status} /></> : null}
            </summary>
            <div className="body">
              {e.details ? <p>{e.details}</p> : null}
              {e.expert_comment ? <p className="small"><b>Ekspert:</b> {e.expert_comment}</p> : null}
              <Evidence item={e} />
            </div>
          </details>
        ))}
        {!shown.length ? <div className="empty">Brak zdarzeń w wybranych typach.</div> : null}
      </div>
    </div>
  );
}

function Facts({ facts }: { facts: Row[] }) {
  const [sel, setSel] = useState<Row | null>(null);
  return (
    <div className="split">
      <div className="scroll">
        <table>
          <thead><tr><th>Rodzaj</th><th>Cz.</th><th>Poziom</th><th>Pole</th><th className="num">Wartość</th><th>Źródło</th></tr></thead>
          <tbody>
            {facts.map((f) => (
              <tr key={f.id} className={`click ${sel?.id === f.id ? "sel" : ""}`} onClick={() => setSel(f)}>
                <td><KindChip kind={f.kind} /></td><td>{f.part_no || ""}</td><td className="small">{f.level}</td>
                <td>{f.label}</td>
                <td className={f.value_num != null ? "num" : "small"} style={f.value_num != null ? undefined : { maxWidth: 260 }}>
                  {f.value_num != null ? factValue(f) : String(f.value_text ?? "—").slice(0, 140) + (String(f.value_text ?? "").length > 140 ? "…" : "")}</td>
                <td className="small mono">{f.source_notice}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="panel" style={{ position: "sticky", top: 12 }}>
        {sel ? <><h4>{sel.label}</h4><div><b>{factValue(sel)}</b></div><Evidence item={sel} /></>
          : <span className="muted">Kliknij wiersz, aby zobaczyć dowód: dokument, miejsce w nim, formułę i cytat.</span>}
      </div>
    </div>
  );
}

const DOC_STATUS: Record<string, string> = {
  ok: "", skan: "skan – bez warstwy tekstowej", format: "format nieodczytywany", "błąd": "błąd odczytu",
};

function Documents({ documents }: { documents: Row[] }) {
  if (!documents.length) return null;
  return (
    <div style={{ display: "grid", gap: 8 }}>
      <h4>Dokumenty z BIP ({documents.length})</h4>
      <p className="small muted">Drugie źródło: dokumenty z Biuletynu Informacji Publicznej zamawiającego, w których występuje miejscowość
        projektu razem z jego zakresem („przedsięwzięcie”) albo z obiektem, od którego projekt zależy według opisu KPO („powiązana inwestycja”).</p>
      {documents.map((d) => (
        <div key={d.url} className="event" style={{ padding: "8px 12px", display: "grid", gap: 4 }}>
          <div className="row between">
            <span><span className="date">{d.published_at ?? "—"}</span> {d.title}</span>
            <a className="small" href={d.url} target="_blank" rel="noreferrer">Otwórz plik (.{d.ext})</a>
          </div>
          <div className="row small">
            <span className={`chip ${d.relation === "przedsięwzięcie" ? "info" : "neutral"}`}>{d.relation}</span>
            <span className="muted">{d.source} › {d.section}{d.page ? ` › str. ${d.page}` : ""}</span>
            {DOC_STATUS[d.status] ? <span className="chip warn">{DOC_STATUS[d.status]}</span> : null}
          </div>
          {d.page ? <div className="quote">{d.quote}</div> : null}
        </div>
      ))}
    </div>
  );
}

function Sources({ notices, documents }: { notices: Row[]; documents: Row[] }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div style={{ display: "grid", gap: 8 }}>
      <h4>Ogłoszenia BZP ({notices.length})</h4>
      {notices.map((n) => (
        <div key={n.notice_number} className="event">
          <div className="row between" style={{ padding: "8px 12px" }}>
            <span><span className="date">{n.publication_date}</span> {n.label} <span className="mono">{n.notice_number}</span></span>
            <span className="row">
              {n.source_url ? <a className="small" href={n.source_url} target="_blank" rel="noreferrer">Otwórz w BZP</a> : null}
              <button className="btn" onClick={() => setOpen(open === n.notice_number ? null : n.notice_number)}>
                {open === n.notice_number ? "Zwiń treść" : "Pokaż treść"}</button>
            </span>
          </div>
          {open === n.notice_number ? <div style={{ padding: "0 12px 12px" }}>
            <iframe className="notice" title={n.notice_number} src={api.noticeHtmlUrl(n.notice_number)} sandbox="" />
            <div className="small muted">Pobrano: {n.fetched_at}</div>
          </div> : null}
        </div>
      ))}
      {!notices.length ? <div className="empty">Brak ogłoszeń.</div> : null}
      <Documents documents={documents} />
    </div>
  );
}

export function ProjectCard({ pid, refreshKey, onFetch, fetching }:
  { pid: string; refreshKey: number; onFetch: (id: string) => void; fetching: boolean }) {
  const [card, setCard] = useState<Card | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("timeline");
  useEffect(() => {
    let alive = true;
    setError(null);
    api.card(pid).then((c) => alive && setCard(c)).catch((e) => alive && setError(String(e.message ?? e)));
    return () => { alive = false; };
  }, [pid, refreshKey]);

  if (error) return <ErrorBox error={error} />;
  if (!card || card.project.project_id !== pid) return <div className="panel"><Spinner /></div>;
  const p = card.project;
  const link = card.links[0];
  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="panel">
        <div className="row between" style={{ alignItems: "start" }}>
          <div style={{ display: "grid", gap: 4, minWidth: 0, flex: 1 }}>
            <span className="small muted mono">{p.project_id}</span>
            <h2>{p.name}</h2>
            <span className="small muted">{p.recipient_name} · {p.city} ({p.voivodeship}) · {p.public_id_type}: <code>{p.public_id}</code> · zakres rekordu: <b>{p.scope}</b></span>
          </div>
          <button className="btn primary" disabled={fetching} onClick={() => onFetch(pid)}>
            {fetching ? <Spinner /> : null} Pobierz / odśwież z BZP</button>
        </div>
        {p.annotation ? <p className="small muted">{p.annotation}</p> : null}
        {card.kpo_value ? <p className="small">Wartość przedsięwzięcia (KPO, poziom projektu): <b>{pln(card.kpo_value)}</b></p> : null}
        {link ? (
          <div style={{ display: "grid", gap: 4 }}>
            <div className="row"><b>Postępowanie</b> <code>{link.ocid}</code> <LinkChip status={link.status} />
              <span className="small muted">metoda: {link.method}</span></div>
            {link.status === "proponowane" ? <div className="gap">Powiązanie zaproponowane automatycznie – potwierdź je albo wybierz innego kandydata w widoku <b>Weryfikacja eksperta → Powiązania KPO</b>.</div> : null}
            <p className="small muted">{link.evidence}</p>
          </div>
        ) : <div className="gap">Brak powiązania z postępowaniem w BZP.</div>}
        <CandidateList candidates={card.candidates} />
      </div>

      {card.contracts.map((c) => <ContractBlock key={c.id} c={c} facts={card.facts} />)}

      {card.gaps.length ? (
        <div className="panel">
          <h3>Braki i niepewności</h3>
          {card.gaps.map((g) => <div key={g.key} className="gap">{g.message}</div>)}
        </div>
      ) : null}

      <div className="panel">
        <Tabs value={tab} onChange={setTab} items={[
          { id: "timeline", label: `Oś czasu (${card.events.length})` },
          { id: "facts", label: `Fakty i obliczenia (${card.facts.length})` },
          { id: "changes", label: `Zmiany umowy (${card.changes.length})` },
          { id: "sources", label: `Źródła (${card.notices.length + (card.documents?.length ?? 0)})` },
        ]} />
        {tab === "timeline" && <Timeline events={card.events} />}
        {tab === "facts" && <Facts facts={card.facts} />}
        {tab === "changes" && (card.changes.length ? (
          <div style={{ display: "grid", gap: 8 }}>
            <div className="scroll"><table>
              <thead><tr><th>Cz.</th><th>Nr / data</th><th>Podstawa</th><th className="num">Wartość zmiany</th><th>Wzrost ceny</th><th>Przyczyna</th><th>Źródło</th></tr></thead>
              <tbody>{card.changes.map((ch) => (
                <tr key={ch.id}><td>{ch.part_no || ""}</td><td className="mono small">{ch.change_date ?? ch.change_no}</td>
                  <td className="small">{ch.legal_basis}</td><td className="num">{pln(ch.value_change)}</td><td>{ch.price_increase}</td>
                  <td className="small">{ch.reason}</td><td className="small mono">{ch.source_notice}</td></tr>))}
              </tbody></table></div>
            <p className="small muted">Ta sama zmiana może występować dwa razy: w ogłoszeniu o zmianie umowy (z datą) i w zbiorczym wykazie w ogłoszeniu o wykonaniu (z numerem).</p>
          </div>) : <div className="empty">Brak zmian umowy w pobranych ogłoszeniach.</div>)}
        {tab === "sources" && <Sources notices={card.notices} documents={card.documents ?? []} />}
      </div>
    </div>
  );
}
