import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Job, type Stats } from "./api";
import { BaseView } from "./BaseView";
import { ExpertView } from "./ExpertView";

type View = "baza" | "weryfikacja" | "analiza";
const VIEWS: { id: View; label: string }[] = [
  { id: "baza", label: "Baza inwestycji" },
  { id: "weryfikacja", label: "Weryfikacja eksperta" },
  { id: "analiza", label: "Analiza nowego projektu" },
];

// Adres: #baza/RM-2026-003, #weryfikacja, #analiza
function readHash(): { view: View; pid: string | null } {
  const [v, pid] = decodeURIComponent(location.hash.replace(/^#/, "")).split("/");
  return { view: (VIEWS.some((x) => x.id === v) ? v : "baza") as View, pid: pid || null };
}

export default function App() {
  const [{ view, pid }, setRoute] = useState(readHash);
  const [stats, setStats] = useState<Stats | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    const onHash = () => setRoute(readHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const go = useCallback((v: View, id?: string | null) => { location.hash = id ? `${v}/${id}` : v; }, []);
  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);
  useEffect(() => { api.stats().then(setStats).catch(() => setStats(null)); }, [refreshKey]);

  const startFetch = useCallback(async (ids: string[] | "all") => {
    const j = await api.startFetch(ids);
    setJob(j);
    if (timer.current) window.clearInterval(timer.current);
    timer.current = window.setInterval(async () => {
      const s = await api.job(j.id);
      setJob(s);
      if (s.status !== "trwa") { if (timer.current) window.clearInterval(timer.current); timer.current = null; refresh(); }
    }, 1000);
  }, [refresh]);
  useEffect(() => () => { if (timer.current) window.clearInterval(timer.current); }, []);

  return (
    <div className="shell">
      <aside className="side">
        <div className="brand"><b>Risk Miner</b><span>inwestycje wod-kan · BZP · KPO</span></div>
        <nav className="nav">
          {VIEWS.map((v) => (
            <button key={v.id} className={view === v.id ? "on" : ""} onClick={() => go(v.id, v.id === "baza" ? pid : null)}>
              {v.label}
              {v.id === "weryfikacja" && stats ? <span className="chip warn">{stats.proposals_open + stats.links_proposed}</span> : null}
            </button>
          ))}
        </nav>
        {stats ? (
          <div className="stats">
            <span>Projektów: {stats.projects}</span>
            <span>Pobranych z BZP: {stats.fetched}</span>
            <span>Powiązań potwierdzonych: {stats.links_confirmed}</span>
            <span>Powiązań do potwierdzenia: {stats.links_proposed}</span>
            <span>Propozycji ryzyk do oceny: {stats.proposals_open}</span>
          </div>
        ) : <div className="stats"><span>Brak połączenia z API – uruchom <code>npm run dev</code>.</span></div>}
      </aside>
      <main className="main">
        {view === "baza" && (
          <BaseView stats={stats} selected={pid} onSelect={(id) => go("baza", id)} job={job}
            startFetch={startFetch} refreshKey={refreshKey} onChanged={refresh} />
        )}
        {view === "weryfikacja" && <ExpertView onChanged={refresh} />}
        {view === "analiza" && (
          <>
            <h2>Analiza nowego projektu</h2>
            <div className="panel">
              <p>Ten widok jest w przygotowaniu. Plan: opis inwestycji albo PDF/DOCX → cechy (podsektor, typ robót, skala,
                formuła realizacji, budżet, termin) → ranking podobnych przypadków z bazy z wyjaśnieniem, porównanie kosztów
                i terminów z liczebnością próby, flagi i rekomendacje oraz eksport do CSV lub JSON.</p>
              <p className="muted">Dla sieci wodociągowych pytania formularza oprze się na checkliście z materiału eksperckiego organizatora.</p>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
