import { useState } from "react";
import { api, type Row } from "./api";
import { ConfidenceChip, ErrorBox, Evidence, LinkChip, OriginTag, STATUS_ICON, Spinner, mln, num, pln } from "./ui";

const EXAMPLES: { label: string; text: string }[] = [
  {
    label: "Nowa oczyszczalnia",
    text: "Gmina planuje budowę nowej biologicznej oczyszczalni ścieków dla 1200 RLM w formule zaprojektuj i wybuduj, " +
      "wraz z przebudową kolektora kanalizacji sanitarnej. Oczyszczone ścieki będą odprowadzane do rzeki. " +
      "Istniejąca oczyszczalnia musi pracować bez przerwy w trakcie budowy. Budżet 4,5 mln zł, termin realizacji 18 miesięcy.",
  },
  {
    label: "Sieć wodociągowa",
    text: "Rozbudowa sieci wodociągowej o długości 6,5 km w trzech miejscowościach wraz z 80 przyłączami. " +
      "Trasa w pasie drogi powiatowej i częściowo przez grunty prywatne, przejście pod linią kolejową. " +
      "Zasilanie z istniejącej SUW. Budżet 3 mln zł, termin 12 miesięcy.",
  },
  {
    label: "Kanalizacja sanitarna",
    text: "Budowa sieci kanalizacji sanitarnej grawitacyjno-tłocznej o długości 4,2 km z 3 przepompowniami ścieków i 120 przyłączami " +
      "w miejscowości wiejskiej. Roboty na podstawie projektu budowlanego zamawiającego, kolizje z istniejącym uzbrojeniem, " +
      "budżet 6 mln zł, termin 14 miesięcy.",
  },
];

const STRENGTH: Record<string, string> = { silna: "bad", "średnia": "warn", słaba: "neutral" };

function Feature({ label, f }: { label: string; f: Row | null | undefined }) {
  return (
    <tr>
      <td className="muted small">{label}</td>
      <td>{f ? <b>{typeof f.value === "number" ? num(f.value, 3) : f.value}</b> : <span className="chip warn">brak w opisie</span>}
        {f?.assumed ? <span className="small muted"> (przyjęte z kontekstu)</span> : null}</td>
      <td className="small muted">{f?.source ?? ""}{f?.note ? <><br />{f.note}</> : null}</td>
    </tr>
  );
}

function Stat({ label, st, unit, fmt = (v: number) => num(v) }: { label: string; st: Row; unit: string; fmt?: (v: number) => string }) {
  return (
    <div className="kpi">
      <span className="l">{label} · n = {st.n}</span>
      {st.n === 0 ? <span className="v">brak danych</span>
        : st.median != null ? <>
          <span className="v">{fmt(st.median)} {unit}</span>
          <span className="small muted">mediana; zakres {fmt(st.min)} … {fmt(st.max)} {unit}</span>
        </> : <span className="v" style={{ fontSize: 15 }}>{st.values.map((v: number) => `${fmt(v)} ${unit}`).join(" · ")}</span>}
      {st.n > 0 && st.median != null ? <span className="small muted">wartości: {st.values.map((v: number) => fmt(v)).join(" · ")}</span> : null}
    </div>
  );
}

function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function AnalysisView() {
  const [text, setText] = useState(EXAMPLES[0].text);
  const [result, setResult] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (fn: () => Promise<Row>) => {
    setBusy(true); setError(null);
    try { const r = await fn(); setResult(r); setText(r.input_text); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const exp = async (format: "csv" | "json") => {
    try { download(await api.exportAnalysis(result?.input_text ?? text, format), `risk_miner_analiza.${format}`); }
    catch (e) { setError((e as Error).message); }
  };
  const f = result?.features;
  const cmp = result?.comparison;

  return (
    <>
      <h2>Analiza nowego projektu</h2>
      <div className="panel">
        <p className="muted">Opisz inwestycję (podsektor, zakres i skalę, formułę realizacji, budżet, termin, znane ograniczenia) albo wgraj PDF z warstwą tekstową lub DOCX. System dobierze podobne przypadki z bazy i pokaże, na czym opiera każdy wniosek.</p>
        <div className="row small"><span className="muted">Przykłady:</span>
          {EXAMPLES.map((e) => <button key={e.label} className="btn" onClick={() => { setText(e.text); setResult(null); }}>{e.label}</button>)}</div>
        <textarea id="analysis-text" rows={6} value={text} onChange={(e) => setText(e.target.value)} style={{ width: "100%", resize: "vertical" }} />
        <div className="row">
          <button className="btn primary" disabled={busy} onClick={() => run(() => api.analyze(text))}>Analizuj opis</button>
          <label className="btn" style={{ cursor: busy ? "default" : "pointer" }}>Wgraj PDF / DOCX
            <input type="file" accept=".pdf,.docx,.txt" hidden disabled={busy}
              onChange={(e) => { const file = e.target.files?.[0]; if (file) run(() => api.analyzeFile(file)); e.target.value = ""; }} />
          </label>
          {busy ? <Spinner /> : null}
          {result ? <span className="row" style={{ marginLeft: "auto" }}>
            <button className="btn" onClick={() => exp("csv")}>Eksport CSV</button>
            <button className="btn" onClick={() => exp("json")}>Eksport JSON</button></span> : null}
        </div>
        <ErrorBox error={error} />
      </div>

      {result && f ? (
        <>
          <div className="panel">
            <div className="row"><h3>Cechy nowej inwestycji</h3><OriginTag kind="dane" />
              <span className="small muted">odczytane z Twojego opisu, z fragmentem, z którego pochodzą</span></div>
            <div className="scroll"><table><tbody>
              <Feature label="Podsektor główny" f={f.subsector_main} />
              <tr><td className="muted small">Podsektory dodatkowe</td><td colSpan={2}>{f.subsector_extra.length ? f.subsector_extra.map((x: Row) => x.value).join(", ") : <span className="muted">—</span>}</td></tr>
              <Feature label="Rodzaj prac" f={f.work_type} />
              <Feature label="Formuła realizacji" f={f.formula} />
              {Object.entries(f.scale as Record<string, Row>).map(([k, v]) => (
                <Feature key={k} label={{ length_km: "Długość sieci [km]", rlm: "Wielkość [RLM]", flow_m3d: "Przepustowość [m³/d]",
                  connections: "Przyłącza [szt.]", buildings: "Budynki / nieruchomości [szt.]" }[k] ?? k} f={v} />))}
              {!Object.keys(f.scale).length ? <Feature label="Skala" f={null} /> : null}
              <Feature label="Budżet" f={f.budget_pln ? { ...f.budget_pln, value: pln(f.budget_pln.value) } : null} />
              <Feature label="Termin [miesiące]" f={f.duration_months} />
              <tr><td className="muted small">Znane ograniczenia</td><td colSpan={2}>{f.constraints.length
                ? f.constraints.map((c: Row) => <div key={c.value}><b>{c.value}</b> <span className="small muted">– {c.source}</span></div>)
                : <span className="muted">nie wskazano</span>}</td></tr>
            </tbody></table></div>
            {result.missing_inputs.length ? <div className="gap">Opis nie podaje: <b>{result.missing_inputs.join(", ")}</b>. Uzupełnienie poprawi dobór przypadków i porównanie kosztów.</div> : null}
          </div>

          <div className="panel">
            <div className="row between"><div className="row"><h3>Podobne przypadki ({result.similar.length} z {result.n_candidates})</h3>
              <OriginTag kind="wniosek" /><span className="small muted">dobór; kwoty i terminy przypadków to dane źródłowe z BZP</span></div>
              <span className="small muted">Każda cecha waży tyle samo; „częściowo” liczy się jako pół. Cechy bez danych nie są liczone. Najpierw przypadki z tym samym podsektorem głównym.</span></div>
            {result.similar.map((s: Row) => (
              <details key={s.project_id} className="event">
                <summary>
                  <span className="date" style={{ minWidth: 150 }} title={`${s.score}% porównywalnych cech`}>
                    pasuje <b>{s.matched} z {s.checked}</b>{s.partial ? ` (+${s.partial} częściowo)` : ""}</span>
                  <span style={{ flex: 1, minWidth: 0 }}><a href={`#baza/${s.project_id}`} onClick={(e) => e.stopPropagation()}>{s.project_id}</a> · {s.name}</span>
                  <span className="small muted">wzrost {s.growth_pct != null ? `${num(s.growth_pct)}%` : "—"} · opóźn. {s.delay_days != null ? `${s.delay_days} dni` : "—"}</span>
                  <LinkChip status={s.link_status} />
                </summary>
                <div className="body">
                  <div className="scroll"><table>
                    <thead><tr><th></th><th>Cecha</th><th>Ocena</th><th>Szczegóły</th></tr></thead>
                    <tbody>{s.features.map((x: Row) => (
                      <tr key={x.name}><td>{STATUS_ICON[x.status] ?? ""}</td><td>{x.name}</td><td>{x.status}</td><td className="small">{x.detail}</td></tr>))}</tbody>
                  </table></div>
                  <div className="kpis">
                    <div className="kpi"><span className="l">Wartość umów</span><span className="v">{mln(s.contract_value)}</span></div>
                    <div className="kpi"><span className="l">Wypłacono</span><span className="v">{mln(s.paid_total)}</span></div>
                    <div className="kpi"><span className="l">Termin z umowy</span><span className="v">{s.planned_months != null ? `${num(s.planned_months)} mies.` : "—"}</span></div>
                    <div className="kpi"><span className="l">Liczba ofert</span><span className="v">{s.n_offers ?? "—"}</span></div>
                  </div>
                  <div className="small muted">Opis przypadku pochodzi z: {s.description_source}. Ryzyka w przypadku: {s.risks.join(", ") || "brak"}.</div>
                </div>
              </details>
            ))}
          </div>

          {cmp ? (
            <div className="panel">
              <div className="row between"><div className="row"><h3>Koszty i terminy w podobnych przypadkach</h3><OriginTag kind="obliczenie" /></div>
                {cmp.confidence ? <span className="row"><span className="small muted">pewność prognozy:</span><ConfidenceChip level={cmp.confidence.level} /></span> : null}</div>
              {cmp.confidence ? <p className="small muted">{cmp.confidence.basis}</p> : null}
              <div className="kpis">
                <Stat label="Wzrost wypłaty vs wartość umowy" st={cmp.growth_pct} unit="%" />
                <Stat label="Opóźnienie vs termin pierwotny" st={cmp.delay_days} unit="dni" fmt={(v) => num(v, 0)} />
                <Stat label="Okres realizacji z umowy" st={cmp.planned_months} unit="mies." />
                {cmp.budget_after_growth ? <div className="kpi"><span className="l">Budżet po typowym wzroście</span>
                  <span className="v">{mln(cmp.budget_after_growth.value)}</span><span className="small muted">{cmp.budget_after_growth.basis}</span></div> : null}
              </div>
              {cmp.notes.map((n: string, i: number) => <div key={i} className="gap">{n}</div>)}
              <p className="small muted">Wartości dotyczą umów na roboty (kwoty brutto), nie całych projektów. Ujemny wzrost oznacza wypłatę niższą niż wartość umowy.</p>
            </div>
          ) : null}

          <div className="panel">
            <div className="row"><h3>Flagi ryzyka i rekomendacje</h3><OriginTag kind="wniosek" />
              <span className="small muted">każda flaga wskazuje przypadki i dowody, na których się opiera</span></div>
            {result.flags.length ? result.flags.map((fl: Row) => (
              <div key={fl.code} className="event" style={{ padding: 12, display: "grid", gap: 6 }}>
                <div className="row"><b>{fl.code} {fl.name}</b><span className={`chip ${STRENGTH[fl.strength]}`}>sygnał {fl.strength}</span></div>
                <div className="small muted">Podstawa: {fl.basis}</div>
                {fl.action ? <div>➜ <b>Działanie:</b> {fl.action}</div> : null}
                {fl.clause ? <div>➜ <b>Zapis do sprawdzenia:</b> {fl.clause}</div> : null}
                {fl.evidence.length ? (
                  <details><summary className="small" style={{ color: "var(--accent)" }}>Dowody z podobnych przypadków ({fl.evidence.length})</summary>
                    <div style={{ display: "grid", gap: 8, marginTop: 6 }}>
                      {fl.evidence.map((e: Row) => (
                        <div key={e.event_id}>
                          <div className="small"><a href={`#baza/${e.project_id}`}>{e.project_id}</a> · {e.date ?? "data nieznana"} · status: {e.status}</div>
                          <Evidence item={e} />
                        </div>))}
                    </div></details>) : null}
              </div>
            )) : <div className="empty">Brak flag – podobne przypadki nie mają zdarzeń ryzyka, a opis nie wskazuje znanych ograniczeń.</div>}
          </div>

          {result.water_checklist ? (
            <div className="panel">
              <div className="row"><h3>Checklista przygotowania sieci wodociągowej</h3><OriginTag kind="dane" /></div>
              <p className="small muted">Według poradnika eksperckiego organizatora. „Brak w opisie” to pytanie do uzupełnienia przed ogłoszeniem zamówienia, a nie stwierdzenie, że czegoś nie zrobiono.</p>
              <div className="scroll"><table><tbody>{result.water_checklist.map((c: Row) => (
                <tr key={c.item}><td>{c.status === "jest w opisie" ? "✅" : "❔"}</td><td>{c.item} <span className="small muted">({c.ref})</span></td>
                  <td className="small muted">{c.source ?? <span className="chip warn">brak w opisie</span>}</td></tr>))}</tbody></table></div>
            </div>
          ) : null}
        </>
      ) : null}
    </>
  );
}
