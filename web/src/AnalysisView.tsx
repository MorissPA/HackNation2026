import { useState } from "react";
import { api, type Row } from "./api";
import { Chevron, ConfidenceChip, Evidence, OriginTag, Spinner, download, mln, num, pln, useToast } from "./ui";

const EXAMPLES: { label: string; text: string }[] = [
  {
    label: "Sieć wodociągowa 6,5 km",
    text: "Rozbudowa sieci wodociągowej o długości 6,5 km w trzech miejscowościach wraz z 80 przyłączami. " +
      "Trasa w pasie drogi powiatowej i częściowo przez grunty prywatne, przejście pod linią kolejową. " +
      "Zasilanie z istniejącej SUW. Budżet 3 mln zł, termin 12 miesięcy.",
  },
  {
    label: "Oczyszczalnia 1200 RLM",
    text: "Gmina planuje budowę nowej biologicznej oczyszczalni ścieków dla 1200 RLM w formule zaprojektuj i wybuduj, " +
      "wraz z przebudową kolektora kanalizacji sanitarnej. Oczyszczone ścieki będą odprowadzane do rzeki. " +
      "Istniejąca oczyszczalnia musi pracować bez przerwy w trakcie budowy. Budżet 4,5 mln zł, termin realizacji 18 miesięcy.",
  },
  {
    label: "Kanalizacja 4,2 km",
    text: "Budowa sieci kanalizacji sanitarnej grawitacyjno-tłocznej o długości 4,2 km z 3 przepompowniami ścieków i 120 przyłączami " +
      "w miejscowości wiejskiej. Roboty na podstawie projektu budowlanego zamawiającego, kolizje z istniejącym uzbrojeniem, " +
      "budżet 6 mln zł, termin 14 miesięcy.",
  },
];

type Sub = "risks" | "checklist" | "similar" | "features";
const SCALE_LABEL: Record<string, string> = {
  length_km: "Długość sieci [km]", rlm: "Wielkość [RLM]", flow_m3d: "Przepustowość [m³/d]",
  connections: "Przyłącza [szt.]", buildings: "Budynki / nieruchomości [szt.]", recipients: "Odbiorcy / mieszkańcy",
};
const CONFLICT_LABEL: Record<string, [string, (v: number) => string]> = {
  budget_pln: ["budżet inwestycji", (v) => pln(v)],
  length_km: ["długość całej sieci", (v) => num(v, 3) + " km"],
  flow_m3d: ["docelową przepustowość", (v) => num(v) + " m³/d"],
  rlm: ["docelową wielkość", (v) => num(v) + " RLM"],
  connections: ["liczbę przyłączy", (v) => num(v) + " szt."],
  recipients: ["liczbę odbiorców", (v) => num(v)],
  duration_months: ["czas realizacji", (v) => num(v) + " mies."],
};
const signed = (v: number, digits = 1) => `${v > 0 ? "+" : ""}${num(v, digits)}`;

function rangeText(st: Row | undefined, unit: string, digits = 1) {
  if (!st || !st.n) return "brak danych";
  if (st.median == null) return st.values.map((v: number) => `${signed(v, digits)} ${unit}`).join(" · ");
  return `${signed(st.min, digits)} … ${signed(st.max, digits)} ${unit}`;
}

function FeatureRow({ label, f }: { label: string; f: Row | null | undefined }) {
  return (
    <tr>
      <td className="t-sub" style={{ whiteSpace: "nowrap" }}>{label}</td>
      <td>{f ? <b>{typeof f.value === "number" ? num(f.value, 3) : f.value}</b> : <span className="st-miss">brak w opisie</span>}
        {f?.assumed ? <span className="small muted"> (przyjęte z kontekstu)</span> : null}
        {f?.origin === "model" ? <span className="chip warn" title="Odczytane przez model językowy; cytat sprawdzony w dokumencie"> model</span> : null}
        {f?.model_confirmed ? <span className="small muted"> (potwierdzone przez model)</span> : null}</td>
      <td className="small muted">{f?.source ?? ""}{f?.note ? <><br />{f.note}</> : null}</td>
    </tr>
  );
}

function RiskCard({ fl, nSimilar }: { fl: Row; nSimilar: number }) {
  const toast = useToast();
  const copy = async () => {
    try { await navigator.clipboard.writeText(fl.clause); toast("Skopiowano propozycję zapisu do PPU / SWZ."); }
    catch { toast("Nie udało się skopiować – zaznacz tekst ręcznie.", true); }
  };
  return (
    <article className={`risk s-${fl.strength}`}>
      <div className="risk-head">
        <div className="risk-title">
          <span className="risk-code">{fl.code}</span>
          <h3>{fl.name}</h3>
          <span className={`chip ${fl.strength === "silna" ? "bad" : fl.strength === "średnia" ? "warn" : "neutral"}`}>sygnał {fl.strength}</span>
          <OriginTag kind="wniosek" />
        </div>
        {fl.clause ? <button className="btn btn-sm" onClick={copy}>Kopiuj zapis do PPU</button> : null}
      </div>
      <dl className="dl">
        <dt>Dane źródłowe</dt>
        <dd>{fl.basis}
          {fl.from_description?.map((signal: { value: string; source: string }) => (
            <div className="small muted" key={signal.value}>Z Twojego opisu: <q>{signal.source}</q></div>
          ))}
          {fl.evidence?.length ? (
            <details style={{ marginTop: 6 }}>
              <summary className="link">Pokaż dowody z dokumentów ({fl.evidence.length})</summary>
              <div style={{ display: "grid", gap: 10, marginTop: 8 }}>
                {fl.evidence.map((e: Row) => (
                  <div key={e.event_id}>
                    <div className="small"><a href={`#baza/${e.project_id}`}>{e.project_id}</a> · {e.date ?? "data nieznana"} · status: {String(e.status).replace("_", " ")}</div>
                    <Evidence item={e} />
                  </div>))}
              </div>
            </details>) : null}
        </dd>
        <dt>Statystyka</dt>
        <dd>{fl.cases?.length ? `${fl.cases.length} z ${nSimilar} podobnych przypadków` : "z opisu inwestycji"}
          {" · "}potwierdzonych przez eksperta: {fl.confirmed_cases ?? 0}
          {fl.weight != null ? <span className="muted"> · waga sygnału {num(fl.weight, 2)}</span> : null}</dd>
        {fl.action ? <><dt>Rekomendacja</dt><dd className="strong">{fl.action}</dd></> : null}
      </dl>
      {fl.clause ? <div className="clause"><b>Zapis do PPU / umowy:</b> {fl.clause}</div> : null}
    </article>
  );
}

type ChkItem = { id: string; name: string; ok: boolean; detail: string };
function Checklist({ items }: { items: ChkItem[] }) {
  const [open, setOpen] = useState<Record<number, boolean>>(() => Object.fromEntries(items.map((x, i) => [i, !x.ok])));
  return (
    <div className="panel flush">
      {items.map((it, i) => (
        <div className="chk" key={i}>
          <button className="chk-btn" aria-expanded={!!open[i]} onClick={() => setOpen((o) => ({ ...o, [i]: !o[i] }))}>
            <span className="chk-l"><span className="chk-id">{it.id}</span><span className="chk-name">{it.name}</span></span>
            <span className="chk-r">{it.ok ? <span className="st-ok">Jest</span> : <span className="st-miss">Brak</span>}<Chevron open={!!open[i]} /></span>
          </button>
          {open[i] ? <div className="chk-detail">{it.detail}</div> : null}
        </div>
      ))}
    </div>
  );
}

export function AnalysisView({ minChars }: { minChars?: number }) {
  const toast = useToast();
  const [text, setText] = useState(EXAMPLES[0].text);
  const [result, setResult] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false);
  const [file, setFile] = useState<string | null>(null);
  const [sub, setSub] = useState<Sub>("risks");
  const [llmBusy, setLlmBusy] = useState(false);

  const run = async (fn: () => Promise<Row>) => {
    setBusy(true);
    try {
      const r = await fn();
      // ponowne przeliczenie (wybór eksperta, model) idzie z tekstu – zachowujemy informację o OCR
      setResult((prev) => (r.ocr_pages == null && prev?.input_text === r.input_text ? { ...r, ocr_pages: prev?.ocr_pages } : r));
      setText(r.input_text); setSub("risks");
    }
    catch (e) { toast((e as Error).message, true); } finally { setBusy(false); }
  };
  const exp = async (format: "csv" | "json") => {
    try { download(await api.exportAnalysis(result?.input_text ?? text, format, result?.choices, !!result?.llm), `risk_miner_analiza.${format}`); toast(`Wyeksportowano analizę do pliku ${format.toUpperCase()}.`); }
    catch (e) { toast((e as Error).message, true); }
  };
  const f = result?.features;
  const usedLlm = !!result?.llm && !result.llm.error;
  const findings = f?.model_findings;
  const cmp = result?.comparison;
  const similar: Row[] = result?.similar ?? [];
  const checklist: ChkItem[] = result ? (result.water_checklist
    ? result.water_checklist.map((c: Row) => ({ id: c.ref, name: c.item, ok: c.status === "jest w opisie",
        detail: c.status === "jest w opisie" ? `Fragment opisu: ${c.source}` : "Pytanie kontrolne przed przetargiem: opis tego nie podaje – uzupełnij przed ogłoszeniem zamówienia. To pytanie, a nie stwierdzenie, że czegoś nie zrobiono." }))
    : (result.missing_inputs as string[]).map((m, i) => ({ id: `B${i + 1}`, name: m, ok: false,
        detail: "Opis nie podaje tej informacji. Uzupełnienie poprawi dobór podobnych przypadków i porównanie kosztów." }))) : [];
  const missingCount = checklist.filter((c) => !c.ok).length;
  const growthUp = cmp?.growth_pct?.values?.filter((v: number) => v > 0).length ?? 0;
  const delayUp = cmp?.delay_days?.values?.filter((v: number) => v > 0).length ?? 0;

  return (
    <section className="view">
      <div className="page-head">
        <div>
          <h1>Ocena ryzyk nowej inwestycji</h1>
          <p>Opisz planowane zadanie lub załącz koncepcję (PDF – także skan, DOCX, zdjęcie dokumentu). System porówna je z historycznymi umowami wod-kan z BZP i pokaże, na czym opiera każdy wniosek.</p>
        </div>
      </div>
      <div className="panel">
        <div className="examples"><span>Wstaw przykład:</span>
          {EXAMPLES.map((e) => <button key={e.label} className="link" onClick={() => { setText(e.text); setResult(null); setFile(null); }}>{e.label}</button>)}</div>
        <div>
          <label htmlFor="analysis-text" className="lbl">Opis zakresu, lokalizacji, szacowanego budżetu oraz terminu</label>
          {minChars && <span className="caption">Opis musi mieć co najmniej {minChars} znaków.</span>}
          <textarea id="analysis-text" rows={5} className="field" value={text} onChange={(e) => { setText(e.target.value); setResult(null); }} />
        </div>
        <div className="input-foot">
          <label className="attach">
            <span>{file ? `Załączono: ${file}` : "Załącz plik PDF / DOCX / skan (np. PFU, koncepcja)"}</span>
            <input type="file" accept=".pdf,.docx,.txt,.png,.jpg,.jpeg,.tif,.tiff" disabled={busy}
              onChange={(e) => { const fl = e.target.files?.[0]; if (fl) { setFile(fl.name); run(() => api.analyzeFile(fl)); } e.target.value = ""; }} />
          </label>
          <span className="row">
            {busy ? <><Spinner /><span className="caption">{llmBusy ? "Model czyta dokument (zwykle 1–2 min)…" : "Analizuję…"}</span></> : null}
            {result && !usedLlm ? <button className="btn" disabled={busy}
              title="Lokalny model językowy czyta cały dokument: kontekst kwot, długości, terminów, sprzeczności i braki. Każda wartość ma cytat sprawdzony w dokumencie."
              onClick={() => { setLlmBusy(true); run(() => api.analyze(result.input_text, result.choices, true)).finally(() => setLlmBusy(false)); }}>
              Doczytaj szczegóły modelem</button> : null}
            <button className="btn btn-primary" disabled={busy || !minChars || Array.from(text.trim()).length < minChars} onClick={() => run(() => api.analyze(text))}>Analizuj inwestycję</button>
          </span>
        </div>
      </div>

      {result && f ? (
        <div style={{ display: "grid", gap: 22 }}>
          <div>
            <div className="summary-head">
              <span className="caption">Podsumowanie na podstawie podobnych przypadków z bazy · kwoty umów brutto z ogłoszeń BZP</span>
              <span className="row">
                <button className="btn btn-sm" onClick={() => exp("json")}>Eksportuj JSON</button>
                <button className="btn btn-sm" onClick={() => exp("csv")}>Eksportuj CSV</button>
              </span>
            </div>
            {result.ocr_pages ? <p className="caption">Tekst odczytany przez OCR ze skanu (stron: {result.ocr_pages}).
              Sprawdź liczby (kwoty, daty) z dokumentem – rozpoznanie może mylić cyfry.</p> : null}
            {result.llm?.error ? <div className="gap"><p>Model językowy niedostępny: {result.llm.error} Wynik oparty tylko na regułach.</p></div> : null}
            {usedLlm ? <p className="caption">Szczegóły doczytał model {result.llm.model}{result.llm.cached ? " (wynik zapamiętany)" : ` w ${result.llm.seconds} s`}.
              Wartości oznaczone „model” mają cytat sprawdzony w dokumencie{result.llm.rejected ? `; odrzucono ${result.llm.rejected} odpowiedzi bez pokrycia w tekście` : ""}.
              {result.llm.truncated ? " Dokument był dłuższy niż kontekst modelu – model przeczytał jego początek." : ""}</p> : null}
            {Object.entries(f.conflicts as Record<string, Row[]>).map(([key, options]) => {
              const [what, fmt] = CONFLICT_LABEL[key] ?? [key, (v: number) => num(v)];
              const groups = new Map<number, Row[]>();
              options.forEach((o) => groups.set(o.value, [...(groups.get(o.value) ?? []), o]));
              return (
                <div className="gap" key={key}>
                  <p>Dokument podaje różne wartości. Wybierz {what}, aby obliczyć prognozę.</p>
                  {[...groups.entries()].map(([value, opts]) => (
                    <p key={value}><button className="btn btn-sm" disabled={busy}
                      onClick={() => run(() => api.analyze(result.input_text, { ...result.choices, [key]: value }, usedLlm))}>
                      {fmt(value)}{opts.some((o) => o.net) ? " netto" : ""}
                    </button>{opts.some((o) => o.model_pick) ? <span className="chip warn"> wskazanie modelu</span> : null}
                      {" "}{opts.map((o) => `„${o.source}”`).join(" · ")}</p>
                  ))}
                </div>);
            })}
            {findings && (findings.inconsistencies.length || findings.gaps.length) ? (
              <div className="gap">
                {findings.inconsistencies.length ? <><p><b>Sprzeczności w dokumencie</b> (model)</p>
                  <ul>{findings.inconsistencies.map((x: Row, i: number) => <li key={i}>{x.opis} <span className="small muted">– „{x.cytat}”</span></li>)}</ul></> : null}
                {findings.gaps.length ? <><p><b>Braki do uzupełnienia przed przetargiem</b> (ocena modelu – sprawdź)</p>
                  <ul>{findings.gaps.map((g: string, i: number) => <li key={i}>{g}</li>)}</ul></> : null}
              </div>) : null}
            <div className="kpis">
              <div className="kpi">
                <div className="kpi-l">Próba porównawcza</div>
                <div className="kpi-v">N = {similar.length} {similar.length === 1 ? "projekt" : "projektów"}</div>
                <div className="kpi-n">Podsektor: {f.subsector_main?.value ?? "nie rozpoznano"} · z {result.n_candidates} w bazie</div>
                {cmp?.confidence ? <div><ConfidenceChip level={cmp.confidence.level} /></div> : null}
              </div>
              <div className="kpi">
                <div className="kpi-l">Odchylenie terminu</div>
                <div className="kpi-v">{rangeText(cmp?.delay_days, "dni", 0)}</div>
                <div className="kpi-n">{cmp?.delay_days?.median != null ? `Mediana ${signed(cmp.delay_days.median, 0)} dni względem umowy pierwotnej · ` : ""}
                  opóźnienie w {delayUp} z {cmp?.delay_days?.n ?? 0}</div>
              </div>
              <div className="kpi">
                <div className="kpi-l">Odchylenie kosztu brutto</div>
                <div className="kpi-v">{rangeText(cmp?.growth_pct, "%")}</div>
                <div className="kpi-n">{cmp?.growth_pct?.median != null ? `Mediana ${signed(cmp.growth_pct.median)}% · ` : ""}wzrost w {growthUp} z {cmp?.growth_pct?.n ?? 0} umów</div>
              </div>
              {cmp?.budget_after_growth ? (
                <div className="kpi">
                  <div className="kpi-l">Budżet po typowym wzroście</div>
                  <div className="kpi-v">{mln(cmp.budget_after_growth.value)}</div>
                  <div className="kpi-n">{cmp.budget_after_growth.basis}</div>
                </div>) : null}
            </div>
            {cmp?.confidence ? <p className="caption" style={{ marginTop: 8 }}>Pewność prognozy: {cmp.confidence.basis}</p> : null}
            {cmp?.notes?.map((n: string, i: number) => <div key={i} className="gap" style={{ marginTop: 8 }}>{n}</div>)}
          </div>

          <div>
            <div className="subtabs" role="tablist">
              {([["risks", `Kluczowe ryzyka i rekomendacje (${result.flags.length})`],
                 ["checklist", `Braki w opisie (${missingCount} z ${checklist.length})`],
                 ["similar", `Podobne inwestycje (N = ${similar.length})`],
                 ["features", "Cechy inwestycji"]] as [Sub, string][]).map(([id, label]) => (
                <button key={id} role="tab" aria-selected={sub === id} className={`pill ${sub === id ? "active" : ""}`} onClick={() => setSub(id)}>{label}</button>))}
            </div>
            <div style={{ marginTop: 18 }}>
              {sub === "risks" && (result.flags.length
                ? <div style={{ display: "grid", gap: 14 }}>{result.flags.map((fl: Row) => <RiskCard key={fl.code} fl={fl} nSimilar={similar.length} />)}</div>
                : <div className="panel empty-state"><div className="panel-title">Brak flag ryzyka</div>
                    <p className="panel-sub">{similar.length ? "W porównanych projektach i w opisie nie znaleziono sygnału ryzyka." : "Brak porównywalnych projektów do oceny ryzyka."}</p></div>)}

              {sub === "checklist" && (
                <div style={{ display: "grid", gap: 10 }}>
                  <p className="caption">{result.water_checklist
                    ? "Checklista przygotowania sieci wodociągowej wg poradnika eksperckiego organizatora."
                    : "Informacje, których brakuje w opisie, a które poprawiają dobór przypadków."} „Brak” to pytanie do uzupełnienia przed ogłoszeniem zamówienia.</p>
                  {checklist.length ? <Checklist key={result.input_text} items={checklist} />
                    : <div className="panel empty-state"><div className="panel-title">Opis zawiera wszystkie kluczowe dane</div></div>}
                  {result.water_checklist && result.missing_inputs.length
                    ? <div className="gap">Opis nie podaje także: <b>{result.missing_inputs.join(", ")}</b>.</div> : null}
                </div>)}

              {sub === "similar" && (
                <div className="panel flush">
                  <div className="tbl-toolbar">
                    <span>Podobne postępowania: <strong>{similar.length}</strong> z {result.n_candidates}</span>
                    <span>Sortowanie: <strong>liczba pasujących cech (malejąco)</strong></span>
                  </div>
                  <div className="scroll-x">
                    <table className="tbl">
                      <thead><tr><th>Inwestycja</th><th>Podobieństwo</th><th className="num">Wartość umów</th><th className="num">Zmiana kosztu / terminu</th></tr></thead>
                      <tbody className="click">{similar.map((s) => (
                        <tr key={s.project_id} onClick={() => { location.hash = `baza/${s.project_id}`; }}>
                          <td><div className="t-main">{s.name}</div>
                            <div className="t-sub"><span className="mono">{s.project_id}</span> · {s.recipient} · pasuje: {(s.matches ?? []).map((m: Row) => m.name).join(", ") || "—"}</div></td>
                          <td><span className="sim" title={`${s.score}% porównywalnych cech`}>{s.matched} z {s.checked}{s.partial ? ` (+${s.partial} częściowo)` : ""}</span></td>
                          <td className="num">{mln(s.contract_value)}</td>
                          <td className="num">{s.growth_pct != null ? `${signed(s.growth_pct)}%` : "—"} / {s.delay_days != null ? `${signed(s.delay_days, 0)} dni` : "—"}
                            {s.risks?.length ? <div className="t-sub">ryzyka: {s.risks.join(", ")}</div> : null}</td>
                        </tr>))}</tbody>
                    </table>
                  </div>
                  <div className="tbl-footer"><span>Każda cecha waży tyle samo; „częściowo” liczy się jako pół. Cechy bez danych nie są liczone.</span><span>Kliknij wiersz, aby otworzyć kartę projektu</span></div>
                </div>)}

              {sub === "features" && (
                <div className="panel">
                  <div className="row"><span className="panel-title">Cechy odczytane z opisu</span><OriginTag kind="dane" /></div>
                  <div className="scroll-x"><table><tbody>
                    <FeatureRow label="Podsektor główny" f={f.subsector_main} />
                    <tr><td className="t-sub">Podsektory dodatkowe</td><td colSpan={2}>{f.subsector_extra.length ? f.subsector_extra.map((x: Row) => x.value).join(", ") : <span className="muted">—</span>}</td></tr>
                    <FeatureRow label="Rodzaj prac" f={f.work_type} />
                    <FeatureRow label="Formuła realizacji" f={f.formula} />
                    {Object.entries(f.scale as Record<string, Row>).map(([k, v]) => <FeatureRow key={k} label={SCALE_LABEL[k] ?? k} f={v} />)}
                    {!Object.keys(f.scale).length ? <FeatureRow label="Skala" f={null} /> : null}
                    <FeatureRow label="Budżet" f={f.budget_pln ? { ...f.budget_pln, value: pln(f.budget_pln.value) } : null} />
                    <FeatureRow label="Termin [miesiące]" f={f.duration_months} />
                    {(f.extra_costs ?? []).map((o: Row, i: number) => (
                      <FeatureRow key={`x${i}`} label="Koszt zmiany umowy" f={{ ...o, value: pln(o.value) + (o.tax ? ` ${o.tax}` : "") }} />))}
                    {f.deadline_change ? <FeatureRow label="Zmiana terminu" f={f.deadline_change} /> : null}
                    {f.remuneration ? <FeatureRow label="Wynagrodzenie" f={f.remuneration} /> : null}
                    <tr><td className="t-sub">Znane ograniczenia</td><td colSpan={2}>{f.constraints.length
                      ? f.constraints.map((c: Row) => <div key={c.value}><b>{c.value}</b>{c.origin === "model" ? <span className="chip warn"> model</span> : null} <span className="small muted">– {c.source}</span></div>)
                      : <span className="muted">nie wskazano</span>}</td></tr>
                  </tbody></table></div>
                </div>)}
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
