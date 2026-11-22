import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Card, type Row } from "./api";
import { ProjectsMap } from "./ProjectsMap";
import { LinkChip, Spinner, download, mln, num, pln, useToast } from "./ui";

function Drawer({ pid, project, onClose }: { pid: string | null; project: Row | undefined; onClose: () => void }) {
  const [card, setCard] = useState<Card | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!pid) return;
    let alive = true;
    setCard(null);
    api.card(pid).then((c) => alive && setCard(c)).catch(() => undefined);
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => { alive = false; window.removeEventListener("keydown", onKey); };
  }, [pid, onClose]);
  const open = !!pid;
  const link = card?.links.find((l) => l.status !== "odrzucone");
  const base = card?.notices.find((n) => n.notice_type === "ContractNotice") ?? card?.notices[0];
  const fact = (key: string, part = 0) => card?.facts.find((f) => f.key === key && f.part_no === part);
  const contractSum = card?.contracts.reduce((s, c) => s + (c.value ?? 0), 0) ?? 0;
  const paidSum = card?.contracts.reduce((s, c) => s + (c.paid_total ?? 0), 0) ?? 0;
  const risks = card?.events.filter((e) => e.kind === "propozycja" && e.status !== "odrzucone") ?? [];
  return (
    <>
      {open ? <div className="backdrop" onClick={onClose} /> : null}
      <aside className={`drawer ${open ? "open" : ""}`} role="dialog" aria-modal="true" aria-labelledby="drawer-title" aria-hidden={!open}>
        <div className="drawer-head">
          <div>
            <span className="eyebrow">{pid} · {project?.recipient_name}</span>
            <h2 id="drawer-title">{project?.name ?? card?.project.name}</h2>
          </div>
          <button ref={closeRef} className="x" aria-label="Zamknij" onClick={onClose}>✕</button>
        </div>
        <div className="drawer-body">
          {!card ? <Spinner /> : (
            <>
              <div>
                <div className="tree-h">Hierarchia powiązań w bazie</div>
                <div className="tree">
                  <div><div className="k">1. Projekt i podsektor</div>
                    <div className="v strong">{card.project.recipient_name} — {project?.subsector}</div>
                    <div className="v small muted">{card.project.public_id_type}: <span className="mono">{card.project.public_id}</span></div></div>
                  <div><div className="k">2. Postępowanie w BZP</div>
                    {link ? <>
                      <div className="v strong">{base?.source_url ? <a href={base.source_url} target="_blank" rel="noreferrer">{base.notice_number}</a> : base?.notice_number ?? link.ocid}</div>
                      <div className="v small"><LinkChip status={link.status} /> <span className="muted">metoda: {link.method}</span></div>
                    </> : <div className="v"><LinkChip status={null} /></div>}</div>
                  <div><div className="k">3. Części zamówienia i umowy</div>
                    {card.contracts.length ? card.contracts.map((c) => (
                      <div key={c.id} className="v"><b>{c.part_no ? `Część ${c.part_no}` : "Całe zamówienie"}</b>: {c.contractor_name ?? "wykonawca nieznany"}
                        <span className="muted"> · {mln(c.value)} · zawarta {c.signed_date ?? "—"}</span></div>))
                      : <div className="v muted">Brak informacji o udzieleniu zamówienia.</div>}</div>
                  <div><div className="k">4. Zmiany umowy (art. 455 Pzp)</div>
                    <div className="v">{card.changes.length ? `${card.changes.length} zmian w ogłoszeniach BZP` : "Brak ogłoszeń o zmianie umowy"}
                      {card.changes.slice(0, 3).map((ch) => <div key={ch.id} className="small muted">{ch.change_date ?? "data nieznana"} · {ch.legal_basis ?? "podstawa nieznana"}</div>)}
                      {card.changes.length > 3 ? <div className="small muted">… i {card.changes.length - 3} kolejne w pełnej karcie</div> : null}</div></div>
                  <div><div className="k">5. Wykonanie</div>
                    {card.contracts.map((c) => (
                      <div key={c.id} className="v">{c.part_no ? `Część ${c.part_no}: ` : ""}{c.actual_end ? `zakończono ${c.actual_end}` : "brak ogłoszenia o wykonaniu"}
                        {fact("opoznienie_vs_pierwotny_dni", c.part_no) ? <span className="muted"> · {num(fact("opoznienie_vs_pierwotny_dni", c.part_no)!.value_num, 0)} dni vs termin pierwotny</span> : null}</div>))}</div>
                  <div><div className="k">6. Ryzyka w przypadku</div>
                    <div className="v">{risks.length ? risks.map((e) => (e.expert_title ?? e.title).split(" ")[0]).filter((v, i, a) => a.indexOf(v) === i).join(", ") : "brak"}
                      <span className="muted small"> · do oceny: {project?.n_open ?? 0}</span></div></div>
                </div>
              </div>
              <div className="sum">
                <div className="r"><span>Szacunkowa wartość zamówienia (netto)</span><span>{pln(project?.estimated_value)}</span></div>
                <div className="r"><span>Wartość umów (brutto)</span><span>{pln(contractSum || null)}</span></div>
                <div className="r"><span>Wypłacono łącznie (brutto)</span><span>{pln(paidSum || null)}</span></div>
                {fact("wzrost_wyplaty_pct") ? <div className="r"><span>Wzrost wypłaty względem umowy</span><span>{num(fact("wzrost_wyplaty_pct")!.value_num)}%</span></div> : null}
                <p>Uwaga metodyczna: szacunek zamówienia (netto) i wartość umowy (brutto) raportujemy osobno, bo różni je podatek VAT – nie porównujemy ich wprost.</p>
              </div>
              {card.gaps.length ? <div className="gap"><b>Braki danych ({card.gaps.length}):</b> {card.gaps.slice(0, 3).map((g) => g.message).join(" · ")}{card.gaps.length > 3 ? " …" : ""}</div> : null}
              <a className="btn btn-primary" href={`#karta/${pid}`}>Otwórz pełną kartę przypadku</a>
            </>
          )}
        </div>
      </aside>
    </>
  );
}

const csvCell = (v: unknown) => { const s = v == null ? "" : String(v); return /[;"\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };

export function BaseView({ selected, onSelect, refreshKey }: { selected: string | null; onSelect: (id: string | null) => void; refreshKey: number }) {
  const toast = useToast();
  const [projects, setProjects] = useState<Row[] | null>(null);
  const [q, setQ] = useState("");
  const [sub, setSub] = useState("ALL");
  const [st, setSt] = useState("ALL");
  const [gmina, setGmina] = useState("ALL");
  const [viewMode, setViewMode] = useState<"split" | "table" | "map">("split");
  useEffect(() => { api.projects().then(setProjects).catch((e) => toast(e.message, true)); }, [refreshKey, toast]);
  const subsectors = useMemo(() => [...new Set((projects ?? []).map((p) => p.subsector))].sort(), [projects]);
  const gminas = useMemo(() => [...new Set((projects ?? []).map((p) => p.gmina || p.city).filter(Boolean))].sort(), [projects]);
  const shown = useMemo(() => (projects ?? []).filter((p) => {
    const t = q.toLowerCase();
    const gName = p.gmina || p.city;
    return (!t || `${p.project_id} ${p.name} ${p.recipient_name} ${p.public_id} ${p.city ?? ""}`.toLowerCase().includes(t))
      && (sub === "ALL" || p.subsector === sub)
      && (st === "ALL" || p.review_status === st)
      && (gmina === "ALL" || gName === gmina || p.city === gmina);
  }), [projects, q, sub, st, gmina]);
  const close = useMemo(() => () => onSelect(null), [onSelect]);

  const exportView = () => {
    const head = ["ID", "Zamawiający", "Nazwa", "Podsektor", "Identyfikator", "Powiązanie BZP", "Wartość umów brutto", "Szacunek netto", "Status"];
    const rows = shown.map((p) => [p.project_id, p.recipient_name, p.name, p.subsector, p.public_id, p.link_status ?? "brak",
      p.contract_value ?? "", p.estimated_value ?? "", p.review_status]);
    download(new Blob(["﻿" + [head, ...rows].map((r) => r.map(csvCell).join(";")).join("\n")], { type: "text/csv;charset=utf-8" }), "risk_miner_projekty.csv");
    toast(`Wyeksportowano ${shown.length} projektów do CSV.`);
  };

  return (
    <section className="view">
      <div className="page-head">
        <div>
          <h1>Baza doświadczeń projektowych</h1>
          <p>Projekty z arkusza powiązane z ogłoszeniami BZP. Kliknij wiersz, aby zobaczyć ścieżkę realizacji: postępowanie, części, umowy, zmiany i wykonanie.</p>
        </div>
        <div className="row">
          <button className="btn btn-sm" disabled={!shown.length} onClick={exportView}>Eksportuj widok (CSV)</button>
          <a className="btn btn-sm" href="/api/export?format=json" download title="Projekt po projekcie z relacjami, dowodami i decyzjami eksperta">Cała baza JSON</a>
          <a className="btn btn-sm" href="/api/export?format=csv" download title="Archiwum ZIP z tabelami CSV">Cała baza CSV (ZIP)</a>
        </div>
      </div>
      <div className="board">
        <aside className="panel flush">
          <div className="filter-head"><div className="panel-title">Kryteria wyszukiwania</div></div>
          <div className="filter-body">
            <div><label className="lbl" htmlFor="f-q">Szukaj</label>
              <input id="f-q" type="text" className="field" value={q} onChange={(e) => setQ(e.target.value)} /></div>
            <div><label className="lbl" htmlFor="f-gmina">Gmina ({gminas.length})</label>
              <select id="f-gmina" className="field" value={gmina} onChange={(e) => setGmina(e.target.value)}>
                <option value="ALL">Wszystkie gminy ({gminas.length})</option>
                {gminas.map((g) => <option key={g} value={g}>{g}</option>)}
              </select></div>
            {gmina !== "ALL" ? (
              <div style={{ marginTop: "4px" }}>
                <button
                  type="button"
                  className="btn btn-sm"
                  style={{ width: "100%", justifyContent: "space-between", borderColor: "var(--accent)" }}
                  onClick={() => setGmina("ALL")}
                >
                  <span>Filtrowanie: <b>{gmina}</b></span>
                  <span>✕</span>
                </button>
              </div>
            ) : null}
            <div><label className="lbl" htmlFor="f-sub">Podsektor</label>
              <select id="f-sub" className="field" value={sub} onChange={(e) => setSub(e.target.value)}>
                <option value="ALL">Wszystkie podsektory</option>
                {subsectors.map((s) => <option key={s} value={s}>{s}</option>)}
              </select></div>
            <div><label className="lbl" htmlFor="f-st">Status</label>
              <select id="f-st" className="field" value={st} onChange={(e) => setSt(e.target.value)}>
                <option value="ALL">Wszystkie statusy</option>
                <option value="Zatwierdzony">Zatwierdzony</option>
                <option value="Do weryfikacji">Do weryfikacji</option>
              </select></div>
            <p className="caption">„Zatwierdzony” – powiązanie z BZP potwierdzone i brak otwartych propozycji ryzyk. Pozostałe czekają w zakładce „Do weryfikacji”.</p>
          </div>
        </aside>
        <div className="panel flush">
          <div className="tbl-toolbar" style={{ flexWrap: "wrap", gap: "10px" }}>
            <span>Wyniki: <strong>{shown.length}</strong> z {projects?.length ?? 0} projektów</span>
            {gmina !== "ALL" ? (
              <span className="user-chip" style={{ cursor: "pointer" }} onClick={() => setGmina("ALL")}>
                Gmina: {gmina} ✕
              </span>
            ) : null}
            <div className="util-group" style={{ marginLeft: "auto" }}>
              <button
                type="button"
                className={`util-btn ${viewMode === "split" ? "on" : ""}`}
                onClick={() => setViewMode("split")}
                title="Pokaż mapę i tabelę"
              >
                🗺️ Podzielony
              </button>
              <button
                type="button"
                className={`util-btn ${viewMode === "map" ? "on" : ""}`}
                onClick={() => setViewMode("map")}
                title="Tylko mapa"
              >
                Tylko mapa
              </button>
              <button
                type="button"
                className={`util-btn ${viewMode === "table" ? "on" : ""}`}
                onClick={() => setViewMode("table")}
                title="Tylko tabela"
              >
                Tylko tabela
              </button>
            </div>
          </div>

          {viewMode !== "table" && (
            <div style={{ padding: "16px 16px 8px 16px" }}>
              <ProjectsMap
                projects={shown}
                selectedGmina={gmina}
                onSelectGmina={setGmina}
                onSelectProject={onSelect}
                selectedPid={selected}
              />
            </div>
          )}

          {viewMode !== "map" && (
            <div className="scroll-x">
              <table className="tbl">
                <thead><tr><th style={{ width: 130 }}>ID</th><th>Gmina / nazwa projektu</th><th>Podsektor</th><th className="num">Kwota umów (brutto)</th><th className="num">Status</th></tr></thead>
                <tbody className="click">
                  {projects === null ? <tr><td colSpan={5}><Spinner /></td></tr> : shown.length ? shown.map((p) => (
                    <tr key={p.project_id} className={selected === p.project_id ? "sel" : ""} tabIndex={0}
                      onClick={() => onSelect(p.project_id)} onKeyDown={(e) => { if (e.key === "Enter") onSelect(p.project_id); }}>
                      <td><span className="id-badge">{p.project_id}</span></td>
                      <td><div className="t-main">{p.recipient_name}</div><div className="t-sub">{p.name}</div></td>
                      <td>{p.subsector}</td>
                      <td className="num t-main">{p.contract_value != null ? pln(p.contract_value) : <span className="t-sub">brak umowy</span>}</td>
                      <td className="num"><span className={p.review_status === "Zatwierdzony" ? "status-appr" : "status-pend"}>{p.review_status}</span>
                        {p.n_open ? <div className="t-sub">{p.n_open} do oceny</div> : null}</td>
                    </tr>)) : <tr><td colSpan={5} style={{ textAlign: "center", padding: 32 }} className="t-sub">
                      {projects.length ? "Brak projektów pasujących do filtrów." : "Baza jest pusta – zaimportuj arkusz w zakładce „Dane i reguły”."}</td></tr>}
                </tbody>
              </table>
            </div>
          )}
          <div className="tbl-footer">
            <span>Źródło: Biuletyn Zamówień Publicznych (e-Zamówienia), arkusz projektów organizatora</span>
            <span>Wartości umów w PLN brutto</span>
          </div>
        </div>
      </div>
      <Drawer pid={selected} project={projects?.find((p) => p.project_id === selected)} onClose={close} />
    </section>
  );
}
