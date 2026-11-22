import { useEffect, useState } from "react";
import { api, type ImportReport, type Job, type Risk, type Stats } from "./api";
import { Spinner, useToast } from "./ui";

function ImportPanel({ stats, job, startFetch, startLlm, onChanged }: {
  stats: Stats | null; job: Job | null; startFetch: (ids: string[] | "all") => Promise<void>; startLlm: () => Promise<void>; onChanged: () => void;
}) {
  const toast = useToast();
  const [report, setReport] = useState<ImportReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const running = job?.status === "trwa";
  const isLlm = job?.kind === "llm";

  const runImport = async (fn: () => Promise<ImportReport>) => {
    setBusy(true);
    try {
      const r = await fn(); setReport(r); onChanged();
      toast(`Import zakończony: ${Object.entries(r.counts).map(([k, v]) => `${k} ${v}`).join(", ")}.`);
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(false); }
  };
  const onFile = (f: File | undefined) => {
    if (!f) return;
    if (!/\.(xlsx|csv)$/i.test(f.name)) { toast("Arkusz projektów musi być w formacie XLSX lub CSV. Dokumenty PDF/DOCX analizujesz w zakładce „Nowa inwestycja”.", true); return; }
    runImport(() => api.importFile(f));
  };
  const sync = async () => {
    try { await startFetch("all"); toast("Rozpoczęto synchronizację z BZP – postęp widać w dzienniku."); }
    catch (e) { toast((e as Error).message, true); }
  };
  const analyzeAll = async () => {
    try { await startLlm(); toast("Rozpoczęto analizę wszystkich fragmentów modelem – wyniki trafią do kolejki „Do weryfikacji”."); }
    catch (e) { toast((e as Error).message, true); }
  };
  const changedRows = report?.rows.filter((r) => r.status !== "bez_zmian" || r.message) ?? [];

  return (
    <div className="panel">
      <div>
        <h2 className="panel-title">Import i synchronizacja źródeł</h2>
        <p className="panel-sub">Wgraj arkusz projektów (XLSX / CSV w układzie arkusza organizatora). Ponowny import aktualizuje rekordy bez tworzenia duplikatów.</p>
      </div>
      <label className={`drop ${over ? "over" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); onFile(e.dataTransfer.files?.[0]); }}>
        <b>{busy ? "Importuję…" : "Kliknij lub upuść plik arkusza"}</b>
        <span>Obsługiwane formaty: .XLSX, .CSV</span>
        <input type="file" accept=".xlsx,.csv" disabled={busy} onChange={(e) => { onFile(e.target.files?.[0]); e.target.value = ""; }} />
      </label>
      <button className="btn" disabled={busy || !stats?.sample_available} onClick={() => runImport(api.importSample)}
        title="Risk_Miner_dane_projekty.xlsx z paczki organizatora">Importuj paczkę startową organizatora</button>
      <button className="btn btn-primary" style={{ width: "100%" }} disabled={running || !stats?.projects} onClick={sync}>
        {running && !isLlm ? <><Spinner /> Pobieranie danych z BZP… {job?.done}/{job?.total}</> : "Synchronizuj z rejestrem BZP"}</button>
      <button className="btn" style={{ width: "100%" }} disabled={running || !stats?.fetched} onClick={analyzeAll}
        title="Model przechodzi wszystkie fragmenty z przyczynami zmian umów i dokumenty BIP; wyniki zapamiętane nie są liczone ponownie">
        {running && isLlm ? <><Spinner /> Analiza modelem… projekt {job?.done}/{job?.total}</> : "Analizuj wszystkie źródła modelem językowym"}</button>
      {stats?.llm_model ? <span className="caption">Model: {stats.llm_model}. Propozycje trafiają do kolejki eksperta – nic nie wchodzi do statystyk bez zatwierdzenia.</span> : null}
      {running && job ? <div className="bar" aria-hidden="true"><div style={{ width: `${(100 * job.done) / Math.max(1, job.total)}%` }} /></div> : null}

      <div className="oplog">
        <h3>Dziennik ostatniej operacji</h3>
        <ul>
          {job ? <>
            <li><b>{isLlm ? `Analiza modelem (${job.model})` : "Synchronizacja BZP"} – {job.status}</b>: {job.done}/{job.total} {isLlm ? "projektów" : "rekordów"}{job.sources?.length ? ` · źródła: ${job.sources.join(", ")}` : ""}
              {job.network_calls != null ? ` · zapytań sieciowych: ${job.network_calls}` : ""}</li>
            {job.log.slice(-12).map((l, i) => <li key={`j${i}`} className="small">{l}</li>)}
          </> : null}
          {report ? <>
            <li><b>Import arkusza</b>: {Object.entries(report.counts).map(([k, v]) => `${k}: ${v}`).join(" · ")}</li>
            {changedRows.slice(0, 12).map((r, i) => (
              <li key={`r${i}`} className="small">Wiersz {r.row_no ?? "—"} <span className="mono">{r.project_id}</span> – {r.status}{r.message ? `: ${r.message}` : ""}</li>))}
            {!changedRows.length ? <li className="small">Wszystkie rekordy bez zmian – ponowny import nie utworzył duplikatów.</li> : null}
          </> : null}
          {!job && !report && stats ? <>
            <li>W bazie: {stats.projects} projektów z arkusza.</li>
            <li>Pobrano z BZP: {stats.fetched} rekordów.</li>
            <li>Powiązania potwierdzone: {stats.links_confirmed}, do potwierdzenia: {stats.links_proposed}.</li>
            <li>Propozycje ryzyk do oceny eksperta: {stats.proposals_open}.</li>
          </> : null}
        </ul>
      </div>
    </div>
  );
}

function CatalogPanel() {
  const toast = useToast();
  const [risks, setRisks] = useState<Risk[] | null>(null);
  const [name, setName] = useState("");
  const [effects, setEffects] = useState("");
  const [rules, setRules] = useState("");
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const load = () => api.risks().then(setRisks).catch((e) => toast(e.message, true));
  useEffect(() => {
    load();
    api.rules().then((r) => { setRules(r.text); setSavedAt(r.updated_at); }).catch(() => undefined);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const add = async () => {
    setBusy(true);
    try { const r = await api.proposeRisk(name, effects || undefined); toast(`Dodano propozycję ${r.code} – trafi do katalogu po zatwierdzeniu.`); setName(""); setEffects(""); await load(); }
    catch (e) { toast((e as Error).message, true); } finally { setBusy(false); }
  };
  const decide = async (code: string, action: "approve" | "reject") => {
    try { await api.decideRisk(code, action); toast(action === "approve" ? `Kategoria ${code} jest w katalogu – model i reguły już jej używają.` : `Odrzucono propozycję ${code}.`); await load(); }
    catch (e) { toast((e as Error).message, true); }
  };
  const save = async () => {
    try { const r = await api.saveRules(rules); setSavedAt(r.updated_at); toast("Zapisano reguły – obowiązują od następnej analizy modelem."); }
    catch (e) { toast((e as Error).message, true); }
  };
  const approved = risks?.filter((r) => r.status === "zatwierdzona") ?? [];
  const proposed = risks?.filter((r) => r.status === "proponowana") ?? [];
  const rejected = risks?.filter((r) => r.status === "odrzucona") ?? [];

  return (
    <div className="panel">
      <div>
        <h2 className="panel-title">Katalog ryzyk eksperckich ({approved.length} kategorii)</h2>
        <p className="panel-sub">Otwarty słownik używany przy klasyfikacji zdarzeń. Nowa kategoria trafia do katalogu dopiero po zatwierdzeniu przez eksperta; od tej chwili widzi ją też model językowy.</p>
      </div>
      <div style={{ display: "grid", gap: 8 }}>
        <div>
          <label className="lbl" htmlFor="new-risk-name">Nazwa nowej kategorii</label>
          <div className="add-row">
            <input id="new-risk-name" type="text" className="field" value={name} onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && name.trim()) add(); }} />
            <button className="btn" style={{ flexShrink: 0 }} disabled={busy || name.trim().length < 5} onClick={add}>Dodaj kategorię</button>
          </div>
        </div>
        <div>
          <label className="lbl" htmlFor="new-risk-effects">Typowe skutki (opcjonalnie)</label>
          <input id="new-risk-effects" type="text" className="field" value={effects} onChange={(e) => setEffects(e.target.value)} />
        </div>
      </div>
      <div className="catalog">
        {risks === null ? <div><Spinner /></div> : null}
        {proposed.map((r) => (
          <div key={r.code} className="prop">
            <span className="risk-code">{r.code}</span>
            <span style={{ flex: 1 }}><b>{r.name}</b> <span className="chip warn">propozycja</span>
              {r.effects ? <div className="t-sub">{r.effects}</div> : null}</span>
            <button className="btn btn-sm" onClick={() => decide(r.code, "reject")}>Odrzuć</button>
            <button className="btn btn-sm btn-primary" onClick={() => decide(r.code, "approve")}>Zatwierdź</button>
          </div>))}
        {approved.map((r) => (
          <div key={r.code}>
            <span className="risk-code">{r.code}</span>
            <span style={{ flex: 1 }}><b>{r.name}</b>{r.effects ? <div className="t-sub">{r.effects}</div> : null}</span>
          </div>))}
        {rejected.map((r) => (
          <div key={r.code} className="t-sub"><span className="mono">{r.code}</span><span style={{ flex: 1 }}><s>{r.name}</s> – odrzucona</span></div>))}
      </div>
      <div className="rules-sec">
        <div className="rules-head">
          <label htmlFor="llm-rules" className="panel-title">Reguły interpretacyjne dla modelu</label>
          <button className="link" onClick={save}>Zapisz reguły</button>
        </div>
        <p className="panel-sub">Dopisywane do instrukcji lokalnego modelu przy każdej analizie dokumentów. Zmiana reguł unieważnia zapamiętane wyniki modelu, więc kolejna analiza policzy je od nowa.</p>
        <textarea id="llm-rules" rows={7} className="field" value={rules} onChange={(e) => setRules(e.target.value)} style={{ fontSize: "0.875rem" }} />
        <span className="caption">{savedAt ? `Ostatni zapis: ${savedAt.slice(0, 16).replace("T", " ")}` : "Reguły nie zostały jeszcze zapisane."}</span>
      </div>
    </div>
  );
}

export function DataView({ stats, job, startFetch, startLlm, onChanged }: {
  stats: Stats | null; job: Job | null; startFetch: (ids: string[] | "all") => Promise<void>; startLlm: () => Promise<void>; onChanged: () => void;
}) {
  return (
    <section className="view">
      <div className="page-head">
        <div>
          <h1>Zasilanie danymi i reguły eksperckie</h1>
          <p>Import arkusza projektów, synchronizacja z rejestrem BZP oraz otwarty katalog ryzyk i wytyczne dla modelu – bez zmian w kodzie.</p>
        </div>
      </div>
      <div className="cols">
        <ImportPanel stats={stats} job={job} startFetch={startFetch} startLlm={startLlm} onChanged={onChanged} />
        <CatalogPanel />
      </div>
    </section>
  );
}
