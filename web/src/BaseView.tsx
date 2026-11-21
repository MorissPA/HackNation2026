import { useEffect, useState } from "react";
import { api, type ImportReport, type Job, type Row, type Stats } from "./api";
import { ErrorBox, LinkChip, Spinner } from "./ui";
import { ProjectCard } from "./ProjectCard";

export function BaseView({ stats, selected, onSelect, job, startFetch, refreshKey, onChanged }: {
  stats: Stats | null; selected: string | null; onSelect: (id: string) => void;
  job: Job | null; startFetch: (ids: string[] | "all") => void; refreshKey: number; onChanged: () => void;
}) {
  const [projects, setProjects] = useState<Row[]>([]);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  useEffect(() => { api.projects().then(setProjects).catch((e) => setError(e.message)); }, [refreshKey]);
  useEffect(() => { if (!selected && projects.length) onSelect(projects.find((p) => p.project_id === "RM-2026-003")?.project_id ?? projects[0].project_id); },
    [projects, selected, onSelect]);

  const runImport = async (fn: () => Promise<ImportReport>) => {
    setBusy(true); setError(null);
    try { setReport(await fn()); onChanged(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const running = job?.status === "trwa";
  const q = filter.toLowerCase();
  const shown = projects.filter((p) => !q || `${p.project_id} ${p.name} ${p.recipient_name} ${p.public_id}`.toLowerCase().includes(q));

  return (
    <>
      <div className="row between">
        <h2>Baza inwestycji</h2>
        <div className="row">
          <button className="btn" disabled={busy || !stats?.sample_available} onClick={() => runImport(api.importSample)}
            title="Risk_Miner_dane_projekty.xlsx z paczki organizatora">Importuj paczkę organizatora</button>
          <label className="btn" style={{ cursor: busy ? "default" : "pointer" }}>
            Wgraj XLSX / CSV
            <input type="file" accept=".xlsx,.csv" hidden disabled={busy}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) runImport(() => api.importFile(f)); e.target.value = ""; }} />
          </label>
          <button className="btn primary" disabled={running || !projects.length} onClick={() => startFetch("all")}>
            Pobierz z BZP wszystkie rekordy</button>
        </div>
      </div>
      <ErrorBox error={error} />

      {report ? (
        <div className="panel">
          <div className="row between"><h3>Raport importu</h3><button className="btn" onClick={() => setReport(null)}>Zamknij</button></div>
          <div className="row">{Object.entries(report.counts).map(([k, v]) => <span key={k} className={`chip ${k === "błąd" && v ? "bad" : "neutral"}`}>{k}: {v}</span>)}</div>
          {report.rows.some((r) => r.status !== "bez_zmian" || r.message) ? (
            <div className="scroll"><table><thead><tr><th>Wiersz</th><th>Rekord</th><th>Status</th><th>Uwagi</th></tr></thead>
              <tbody>{report.rows.filter((r) => r.status !== "bez_zmian" || r.message).map((r, i) => (
                <tr key={i}><td>{r.row_no ?? "—"}</td><td className="mono">{r.project_id}</td><td>{r.status}</td><td className="small">{r.message}</td></tr>))}</tbody></table></div>
          ) : <p className="muted">Wszystkie rekordy bez zmian – ponowny import nie utworzył duplikatów.</p>}
        </div>
      ) : null}

      {job ? (
        <div className="panel">
          <div className="row between">
            <h3>{running ? <><Spinner /> Pobieranie z BZP</> : "Pobieranie z BZP – " + job.status}</h3>
            <span className="small muted">{job.done}/{job.total}{job.current && running ? ` · ${job.current}` : ""}
              {job.sources?.length ? ` · źródła: ${job.sources.join(", ")}` : ""}</span>
          </div>
          <div className="bar"><div style={{ width: `${(100 * job.done) / Math.max(1, job.total)}%` }} /></div>
          <div className="log">{job.log.slice(-40).join("\n") || "Start…"}</div>
        </div>
      ) : null}

      <div className="panel">
        <div className="row between">
          <h3>Projekty ({projects.length})</h3>
          <input type="text" id="project-filter" placeholder="Filtruj: nazwa, gmina, numer…" value={filter}
            onChange={(e) => setFilter(e.target.value)} style={{ width: 260 }} />
        </div>
        {projects.length ? (
          <div className="scroll" style={{ maxHeight: 340, overflowY: "auto" }}>
            <table>
              <thead><tr><th>ID</th><th>Przedsięwzięcie</th><th>Zamawiający</th><th>Identyfikator</th><th>Powiązanie z BZP</th><th className="num">Braki</th><th className="num">Do oceny</th></tr></thead>
              <tbody>
                {shown.map((p) => (
                  <tr key={p.project_id} className={`click ${selected === p.project_id ? "sel" : ""}`} onClick={() => onSelect(p.project_id)}>
                    <td className="mono small">{p.project_id}</td><td>{p.name}</td><td className="small">{p.recipient_name}</td>
                    <td className="small"><span className="muted">{p.public_id_type}</span><br /><span className="mono">{p.public_id}</span></td>
                    <td>{p.last_fetch_status ? <LinkChip status={p.link_status} /> : <span className="chip neutral">nie pobrano</span>}</td>
                    <td className="num">{p.n_gaps || ""}</td><td className="num">{p.n_open || ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <div className="empty">Zaimportuj arkusz, aby zobaczyć projekty.</div>}
      </div>

      {selected ? <ProjectCard pid={selected} refreshKey={refreshKey} fetching={running} onFetch={(id) => startFetch([id])} /> : null}
    </>
  );
}
