import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Job, type Stats } from "./api";
import { BaseView } from "./BaseView";
import { VerifyView } from "./ExpertView";
import { AnalysisView } from "./AnalysisView";
import { DataView } from "./DataView";
import { ProjectCard } from "./ProjectCard";
import { ToastProvider } from "./ui";

type View = "nowa" | "weryfikacja" | "baza" | "karta" | "dane";
const TABS: { id: View; label: string }[] = [
  { id: "nowa", label: "Nowa inwestycja" },
  { id: "weryfikacja", label: "Do weryfikacji" },
  { id: "baza", label: "Baza projektów" },
  { id: "dane", label: "Dane i reguły" },
];
const ALL: View[] = ["nowa", "weryfikacja", "baza", "karta", "dane"];

// Adres: #nowa, #weryfikacja, #baza/RM-2026-003 (szuflada), #karta/RM-2026-003 (pełna karta), #dane
function readHash(): { view: View; pid: string | null } {
  const [v, pid] = decodeURIComponent(location.hash.replace(/^#/, "")).split("/");
  const view = (ALL as string[]).includes(v) ? (v as View) : "nowa";
  return { view, pid: pid || null };
}

const store = {
  get: (k: string) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* tryb prywatny */ } },
};

function Header({ view, stats, onGo }: { view: View; stats: Stats | null; onGo: (v: View) => void }) {
  const [size, setSize] = useState(() => Number(store.get("rm.font")) || 16);
  const [hc, setHc] = useState(() => store.get("rm.hc") === "1");
  useEffect(() => { document.documentElement.style.fontSize = `${size}px`; store.set("rm.font", String(size)); }, [size]);
  useEffect(() => { document.body.classList.toggle("hc", hc); store.set("rm.hc", hc ? "1" : "0"); }, [hc]);
  const queue = stats ? stats.proposals_open + stats.links_proposed : null;
  const active = view === "karta" ? "baza" : view;
  return (
    <header className="site-head">
      <div className="top-stripe" />
      <div className="util">
        <div className="wrap util-in">
          <div className="util-badge">Prototyp HackNation 2026<span>wyzwanie MFiPR · inwestycje wod-kan · dane BZP</span></div>
          <div className="util-right">
            <div className="util-group" role="group" aria-label="Rozmiar tekstu">
              {[[16, "A", "Normalny rozmiar tekstu"], [18, "A+", "Większy tekst"], [20, "A++", "Największy tekst"]].map(([px, l, aria], i) => (
                <button key={px} className={`util-btn ${size === px ? "on" : ""}`} style={{ fontSize: `${0.8125 + i * 0.14}rem` }}
                  aria-label={String(aria)} aria-pressed={size === px} onClick={() => setSize(Number(px))}>{l}</button>))}
            </div>
            <span className="util-sep" />
            <button className={`util-btn ${hc ? "on" : ""}`} aria-pressed={hc} onClick={() => setHc(!hc)}>Kontrast</button>
            <span className="util-sep" />
            <span className="user-chip">Ekspert</span>
          </div>
        </div>
      </div>
      <div className="wrap brandrow">
        <div className="brand-left">
          <div className="brand-emblem" aria-hidden="true">RM</div>
          <div>
            <div className="brand-name">Risk Miner</div>
            <div className="brand-sub">Baza doświadczeń inwestycji wodno-kanalizacyjnych · BZP · KPO</div>
          </div>
        </div>
        {stats ? (
          <div className="brand-stats" aria-label="Stan bazy">
            <span><b>{stats.projects}</b> projektów</span>
            <span><b>{stats.fetched}</b> pobranych z BZP</span>
            <span><b>{stats.links_confirmed}</b> powiązań potwierdzonych</span>
          </div>
        ) : <div className="brand-stats"><span>Brak połączenia z API – uruchom <code>npm run dev</code>.</span></div>}
      </div>
      <div className="navrow">
        <nav className="wrap mainnav" aria-label="Nawigacja główna">
          {TABS.map((t) => (
            <button key={t.id} className={`tab ${active === t.id ? "active" : ""}`} aria-current={active === t.id ? "page" : undefined}
              onClick={() => onGo(t.id)}>
              <span>{t.label}</span>
              {t.id === "weryfikacja" && queue != null ? <span className="count" aria-label={`${queue} pozycji`}>{queue}</span> : null}
            </button>
          ))}
        </nav>
      </div>
    </header>
  );
}

function Breadcrumb({ view, pid }: { view: View; pid: string | null }) {
  const label = TABS.find((t) => t.id === (view === "karta" ? "baza" : view))?.label;
  return (
    <div className="breadcrumb-bar">
      <nav className="wrap breadcrumb-list" aria-label="Ścieżka">
        <a href="#nowa">Risk Miner</a><span className="sep">›</span>
        {view === "karta" ? <><a href="#baza">{label}</a><span className="sep">›</span><span className="current">Karta przypadku {pid}</span></>
          : <span className="current">{label}</span>}
      </nav>
    </div>
  );
}

export default function App() {
  const [{ view, pid }, setRoute] = useState(readHash);
  const [stats, setStats] = useState<Stats | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    const onHash = () => { setRoute(readHash()); };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => { window.scrollTo(0, 0); }, [view]);
  const go = useCallback((v: View, id?: string | null) => { location.hash = id ? `${v}/${id}` : v; }, []);
  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);
  const selectBase = useCallback((id: string | null) => go("baza", id), [go]);
  useEffect(() => { api.stats().then(setStats).catch(() => setStats(null)); }, [refreshKey]);

  const runJob = useCallback(async (start: () => Promise<Job>) => {
    const j = await start();
    setJob(j);
    if (timer.current) window.clearInterval(timer.current);
    timer.current = window.setInterval(async () => {
      const s = await api.job(j.id);
      setJob(s);
      if (s.status !== "trwa") { if (timer.current) window.clearInterval(timer.current); timer.current = null; refresh(); }
    }, 1000);
  }, [refresh]);
  const startFetch = useCallback((ids: string[] | "all") => runJob(() => api.startFetch(ids)), [runJob]);
  const startLlm = useCallback(() => runJob(api.llmAll), [runJob]);
  useEffect(() => () => { if (timer.current) window.clearInterval(timer.current); }, []);

  return (
    <ToastProvider>
      <Header view={view} stats={stats} onGo={(v) => go(v)} />
      <Breadcrumb view={view} pid={pid} />
      <main id="main">
        {view === "nowa" && <AnalysisView />}
        {view === "weryfikacja" && <VerifyView onChanged={refresh} />}
        {view === "baza" && <BaseView selected={pid} onSelect={selectBase} refreshKey={refreshKey} />}
        {view === "karta" && pid && (
          <div className="view card-page">
            <ProjectCard pid={pid} refreshKey={refreshKey} onChanged={refresh} fetching={job?.status === "trwa"} onFetch={(id) => startFetch([id])} />
          </div>
        )}
        {view === "dane" && <DataView stats={stats} job={job} startFetch={startFetch} startLlm={startLlm} onChanged={refresh} />}
      </main>
      <footer className="site-footer">
        <div className="wrap footer-in">
          <span><strong>Risk Miner</strong> · prototyp zespołu HackNation 2026 · dane: Biuletyn Zamówień Publicznych, arkusz projektów organizatora</span>
          <span>Licencja MIT · projektowane pod WCAG 2.1 AA</span>
        </div>
      </footer>
    </ToastProvider>
  );
}
