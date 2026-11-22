import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type QueueItem, type Risk } from "./api";
import { CandidateList } from "./ProjectCard";
import { ConfidenceChip, Spinner, num, pln, useToast } from "./ui";

type Filter = "all" | "ryzyko" | "powiazanie";

function impactText(i: { label: string; value_num: number; unit: string }) {
  const v = i.unit === "PLN" ? pln(i.value_num) : `${i.value_num > 0 ? "+" : ""}${num(i.value_num)} ${i.unit}`;
  return `${i.label}: ${v}`;
}

function RiskItem({ item, risks, onDone }: { item: QueueItem; risks: Risk[]; onDone: () => void }) {
  const toast = useToast();
  const [code, setCode] = useState(item.code ?? "");
  const [exemplar, setExemplar] = useState(false);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { setCode(item.code ?? ""); setExemplar(false); setComment(""); }, [item.id, item.code]);
  const act = async (action: "accept" | "reject") => {
    setBusy(true);
    try {
      const r = await api.decideEvent(item.event_id!, action, action === "accept" ? code : undefined, comment || undefined, exemplar);
      toast(action === "reject" ? "Odrzucono propozycję – nie trafi do statystyk." :
        `${r.status === "poprawione" ? "Zatwierdzono z poprawioną kategorią" : "Zatwierdzono"}${exemplar ? " jako przykład wzorcowy" : ""}.`);
      onDone();
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(false); }
  };
  const quotes = item.quote ? item.quote.split(" | ") : [];
  const approved = risks.filter((r) => (r.status ?? "zatwierdzona") === "zatwierdzona");
  return (
    <div className="vsplit">
      <div className="panel">
        <div>
          <div className="p-head">
            <div>
              <div className="kv-l">Projekt źródłowy · <a href={`#karta/${item.project_id}`}>{item.project_id}</a></div>
              <h2 className="panel-title">{item.project}</h2>
              <div className="panel-sub">{item.recipient}</div>
            </div>
            <span className="row" style={{ gap: 6, justifyContent: "flex-end" }}>
              <span className="conf" title="Skąd pochodzi propozycja">Źródło: <b>{item.origin}</b></span>
              {item.llm_confidence ? <span className={`chip ${item.llm_confidence === "niska" ? "warn" : "ok"}`}
                title="Wysoka: kategoria modelu zgadza się z regułami słownikowymi dla tego tekstu; niska: nie zgadza się – sprawdź uważnie">
                pewność {item.llm_confidence}</span> : null}
            </span>
          </div>
          <div>
            <label className="lbl" htmlFor="v-code">Kategoria ryzyka</label>
            <select id="v-code" className="field" value={code} onChange={(e) => setCode(e.target.value)}>
              {approved.map((r) => <option key={r.code} value={r.code}>{r.code} {r.name}</option>)}
            </select>
            {code !== item.code ? <div className="caption" style={{ marginTop: 4 }}>Zmieniasz kategorię zaproponowaną przez system ({item.code}) – decyzja zapisze się jako poprawka.</div> : null}
          </div>
          <div>
            <div className="kv-l">Wykryty sygnał w dokumencie</div>
            <p className="kv-v">{item.details || item.title}</p>
          </div>
          <div>
            <div className="kv-l">Wpływ zdarzenia według źródła</div>
            {item.event_effect_quote ? <blockquote className="kv-v">{item.event_effect_quote}</blockquote>
              : <p className="kv-v muted">W cytacie nie rozpoznano kwoty ani czasu przypisanego temu zdarzeniu.</p>}
          </div>
          <div>
            <div className="kv-l">Wynik całej umowy względem pierwotnych warunków</div>
            {item.contract_context?.length ? item.contract_context.map((i) => <p key={i.label} className="kv-v strong">{impactText(i)}</p>)
              : <p className="kv-v muted">Brak obliczeń dla tej umowy.</p>}
          </div>
          <div>
            <label className="lbl" htmlFor="v-comment">Uzasadnienie (opcjonalnie)</label>
            <input id="v-comment" type="text" className="field" value={comment} onChange={(e) => setComment(e.target.value)} />
          </div>
          <label className="check">
            <input type="checkbox" checked={exemplar} onChange={(e) => setExemplar(e.target.checked)} />
            <span>Zapisz jako przykład wzorcowy dla przyszłych analiz (większa waga w porównaniach)</span>
          </label>
        </div>
        <div className="actions">
          {busy ? <Spinner /> : null}
          <button className="btn" disabled={busy} onClick={() => act("reject")}>Odrzuć</button>
          <button className="btn btn-primary" disabled={busy || !code} onClick={() => act("accept")}>{code !== item.code ? "Zatwierdź z poprawką" : "Zatwierdź"}</button>
        </div>
      </div>
      <div className="panel">
        <div>
          <div className="p-head" style={{ display: "block" }}>
            <span className="eyebrow">Dowód w dokumencie źródłowym</span>
            <h3 className="panel-title" style={{ marginTop: 2 }}>{item.notice_label ?? "Dokument źródłowy"}</h3>
            <p className="panel-sub">
              {item.source_url ? <a href={item.source_url} target="_blank" rel="noreferrer">{item.source_notice}</a> : item.source_notice}
              {item.date ? ` · ${item.date}` : ""}{item.source_section ? ` · ${item.source_section}` : ""}
            </p>
          </div>
          <div className="doc">
            {item.before ? <p className="ctx">{item.before}</p> : null}
            {quotes.length ? quotes.map((q, i) => <span key={i} className="hl">{q}</span>) : <span className="hl">Brak cytatu w dokumencie.</span>}
            {item.after ? <p className="ctx">{item.after}</p> : null}
          </div>
          <p className="caption">Wyróżniony fragment to dosłowny cytat z ogłoszenia; szary tekst to sąsiednie punkty tego samego dokumentu.</p>
        </div>
      </div>
    </div>
  );
}

function LinkItem({ item, onDone }: { item: QueueItem; onDone: () => void }) {
  const toast = useToast();
  const [choice, setChoice] = useState(item.ocid ?? "");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { setChoice(item.ocid ?? item.candidates?.[0]?.ocid ?? ""); setComment(""); }, [item.id, item.ocid, item.candidates]);
  const act = async (action: "confirm" | "reject") => {
    setBusy(true);
    try {
      await api.decideLink(item.project_id, action, action === "confirm" ? choice : undefined, comment || undefined);
      toast(action === "confirm" ? "Potwierdzono powiązanie – przypadek przeliczony z danych BZP." : "Odrzucono powiązanie.");
      onDone();
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(false); }
  };
  const sel = item.candidates?.find((c) => c.ocid === choice);
  return (
    <div className="vsplit">
      <div className="panel">
        <div>
          <div className="p-head">
            <div>
              <div className="kv-l">Rekord KPO bez numeru BZP · <a href={`#karta/${item.project_id}`}>{item.project_id}</a></div>
              <h2 className="panel-title">{item.project}</h2>
              <div className="panel-sub">{item.recipient}</div>
            </div>
            {sel ? <span className="conf">Kryteria: <b>{sel.matched}/{sel.checked}</b></span> : null}
          </div>
          <div>
            <label className="lbl" htmlFor="v-cand">Postępowanie w BZP</label>
            <select id="v-cand" className="field" value={choice} onChange={(e) => setChoice(e.target.value)}>
              {item.candidates?.map((c) => <option key={c.ocid} value={c.ocid}>{c.rank}. {c.matched}/{c.checked} kryteriów · {String(c.title).slice(0, 90)}</option>)}
            </select>
          </div>
          <div>
            <div className="kv-l">Dlaczego system to zaproponował</div>
            <p className="kv-v">{item.evidence}</p>
          </div>
          {sel ? <div className="row"><span className="kv-l" style={{ margin: 0 }}>Pewność dopasowania</span><ConfidenceChip level={sel.confidence} /></div> : null}
          <div>
            <label className="lbl" htmlFor="v-lcomment">Uzasadnienie (opcjonalnie)</label>
            <input id="v-lcomment" type="text" className="field" value={comment} onChange={(e) => setComment(e.target.value)} />
          </div>
        </div>
        <div className="actions">
          {busy ? <><Spinner /><span className="caption">przeliczam przypadek…</span></> : null}
          <button className="btn" disabled={busy} onClick={() => act("reject")}>Odrzuć</button>
          <button className="btn btn-primary" disabled={busy || !choice} onClick={() => act("confirm")}>Potwierdź powiązanie</button>
        </div>
      </div>
      <div className="panel">
        <div>
          <div className="p-head" style={{ display: "block" }}>
            <span className="eyebrow">Porównanie z rekordem KPO</span>
            <h3 className="panel-title" style={{ marginTop: 2 }}>{sel?.title ?? "Brak kandydata"}</h3>
            {sel ? <p className="panel-sub mono">ogłoszenie bazowe {sel.base_notice}</p> : null}
          </div>
          {sel ? <CandidateList candidates={[sel]} open /> : <div className="gap">Brak kandydatów – pobierz dane z BZP w zakładce „Dane i reguły”.</div>}
        </div>
      </div>
    </div>
  );
}

export function VerifyView({ onChanged }: { onChanged: () => void }) {
  const [queue, setQueue] = useState<QueueItem[] | null>(null);
  const [risks, setRisks] = useState<Risk[]>([]);
  const [idx, setIdx] = useState(0);
  const [filter, setFilter] = useState<Filter>("all");
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api.verifyQueue().then(setQueue).catch((e) => setError(e.message)), []);
  useEffect(() => { load(); api.risks().then(setRisks).catch(() => undefined); }, [load]);

  const shown = useMemo(() => (queue ?? []).filter((q) => filter === "all" || q.type === filter), [queue, filter]);
  const pos = shown.length ? Math.min(idx, shown.length - 1) : 0;
  const item = shown[pos];
  const step = (d: number) => setIdx((i) => (Math.min(i, shown.length - 1) + d + shown.length) % shown.length);
  const done = async () => { await load(); onChanged(); };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest("input, textarea, select")) return;
      if (e.key === "ArrowRight") step(1); else if (e.key === "ArrowLeft") step(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
  const n = (t: Filter) => (queue ?? []).filter((q) => t === "all" || q.type === t).length;

  return (
    <section className="view">
      <div className="page-head">
        <div>
          <h1>Weryfikacja ekspercka</h1>
          <p>Zatwierdź, popraw albo odrzuć wnioski wykryte w dokumentach, zanim trafią do statystyk. Każda decyzja trafia do historii i nie jest nadpisywana przy ponownym pobraniu danych.</p>
        </div>
        <div className="row">
          <span className="caption" style={{ fontWeight: 700, marginRight: 6 }} aria-live="polite">
            {shown.length ? `Pozycja ${pos + 1} z ${shown.length}` : "Kolejka pusta"}</span>
          <button className="btn btn-sm" disabled={shown.length < 2} onClick={() => step(-1)}>Poprzedni</button>
          <button className="btn btn-sm" disabled={shown.length < 2} onClick={() => step(1)}>Następny</button>
        </div>
      </div>
      <div className="subtabs" role="tablist">
        {([["all", "Wszystkie"], ["ryzyko", "Propozycje ryzyk"], ["powiazanie", "Powiązania KPO → BZP"]] as [Filter, string][]).map(([id, label]) => (
          <button key={id} role="tab" aria-selected={filter === id} className={`pill ${filter === id ? "active" : ""}`}
            onClick={() => { setFilter(id); setIdx(0); }}>{label} ({n(id)})</button>))}
      </div>
      {error ? <div className="err">{error}</div> : null}
      {queue === null ? <Spinner /> : !item ? (
        <div className="panel empty-state">
          <div className="panel-title">Wszystkie pozycje zostały zweryfikowane</div>
          <p className="panel-sub">Zatwierdzone wnioski zasilają bazę doświadczeń i porównania dla nowych inwestycji.</p>
        </div>
      ) : item.type === "ryzyko"
        ? <RiskItem item={item} risks={risks} onDone={done} />
        : <LinkItem item={item} onDone={done} />}
      {shown.length > 1 ? (
        <details className="panel flush">
          <summary className="tbl-toolbar" style={{ borderBottom: 0 }}><span><strong>Cała kolejka</strong> – kliknij, aby rozwinąć listę</span><span>strzałki ← → przełączają pozycje</span></summary>
          <div className="scroll-x qlist">
            <table className="tbl"><tbody className="click">{shown.map((q, i) => (
              <tr key={q.id} className={i === pos ? "sel" : ""} onClick={() => setIdx(i)}>
                <td><span className="id-badge">{q.project_id}</span></td>
                <td><div className="t-main">{q.type === "ryzyko" ? q.title : "Powiązanie KPO → BZP"}</div><div className="t-sub">{q.project}</div></td>
                <td className="num t-sub">{q.type === "ryzyko" ? `${q.origin}${q.llm_confidence ? ` · pewność ${q.llm_confidence}` : ""}` : `pewność ${q.confidence ?? "—"}`}</td>
              </tr>))}</tbody></table>
          </div>
        </details>) : null}
    </section>
  );
}
