// Wspólne drobne komponenty i formatowanie
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import type { Row } from "./api";

export const pln = (v: number | null | undefined) =>
  v == null ? "—" : `${v.toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} zł`;
export const mln = (v: number | null | undefined) =>
  v == null ? "—" : `${(v / 1e6).toLocaleString("pl-PL", { minimumFractionDigits: 3, maximumFractionDigits: 3 })} mln zł`;
export const num = (v: number | null | undefined, digits = 1) =>
  v == null ? "—" : v.toLocaleString("pl-PL", { maximumFractionDigits: digits });

export function factValue(f: Row): string {
  if (f.value_num == null) return f.value_text ?? "—";
  if (f.unit === "PLN") return pln(f.value_num);
  return `${num(f.value_num)} ${f.unit ?? ""}`.trim();
}

const LINK_CHIP: Record<string, [string, string]> = {
  potwierdzone: ["ok", "potwierdzone"], proponowane: ["warn", "do potwierdzenia"], odrzucone: ["bad", "odrzucone"],
};
export function LinkChip({ status }: { status?: string | null }) {
  const [cls, label] = status ? LINK_CHIP[status] ?? ["neutral", status] : ["bad", "brak powiązania"];
  return <span className={`chip ${cls}`}>{label}</span>;
}
const DECISION_CHIP: Record<string, string> = {
  do_weryfikacji: "warn", zaakceptowane: "ok", poprawione: "info", odrzucone: "bad",
};
export function DecisionChip({ status }: { status: string }) {
  return <span className={`chip ${DECISION_CHIP[status] ?? "neutral"}`}>{status.replace("_", " ")}</span>;
}
const KIND_CHIP: Record<string, [string, string]> = {
  fakt: ["neutral", "fakt"], obliczenie: ["info", "obliczenie"], propozycja: ["warn", "propozycja"],
};
export function KindChip({ kind }: { kind: string }) {
  const [cls, label] = KIND_CHIP[kind] ?? ["neutral", kind];
  return <span className={`chip ${cls}`}>{label}</span>;
}

/** Dowód: źródło + miejsce w dokumencie + formuła + cytat. */
export function Evidence({ item }: { item: Row }) {
  const quotes: string[] = item.quote ? String(item.quote).split(" | ") : [];
  const fromSheet = !item.source_notice || item.source_notice === "arkusz";
  return (
    <div style={{ display: "grid", gap: 6 }}>
      <div className="small muted">
        Źródło:{" "}
        {fromSheet ? "arkusz projektów" : item.source_url
          ? <a href={item.source_url} target="_blank" rel="noreferrer">{item.source_notice}</a>
          : <span className="mono">{item.source_notice}</span>}
        {item.source_section ? <> · {item.source_section}</> : null}
      </div>
      {item.formula ? <div className="formula">{item.formula}</div> : null}
      {quotes.map((q, i) => <div className="quote" key={i}>{q}</div>)}
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, items }:
  { value: T; onChange: (v: T) => void; items: { id: T; label: ReactNode }[] }) {
  return (
    <div className="tabs" role="tablist">
      {items.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} className={value === t.id ? "on" : ""}
          onClick={() => onChange(t.id)}>{t.label}</button>
      ))}
    </div>
  );
}

export function ErrorBox({ error }: { error: string | null }) {
  return error ? <div className="err">{error}</div> : null;
}

export const Spinner = () => <span className="spin" aria-label="Trwa…" />;

export const STATUS_ICON: Record<string, string> = {
  "pasuje": "✅", "częściowo": "🟨", "nie pasuje": "❌", "różni się": "❌", "brak danych": "❔",
};
const CONF: Record<string, string> = { wysoka: "ok", "średnia": "warn", niska: "bad" };

/** Rodzaj informacji (treść zadania: „wyraźnie odróżniać dane źródłowe, obliczenia i wnioski”). */
const ORIGIN: Record<string, [string, string]> = {
  dane: ["neutral", "dane źródłowe"], obliczenie: ["info", "obliczenie"], wniosek: ["warn", "wniosek – do oceny eksperta"],
};
export function OriginTag({ kind }: { kind: "dane" | "obliczenie" | "wniosek" }) {
  const [cls, label] = ORIGIN[kind];
  return <span className={`chip ${cls}`} title="Rodzaj informacji">{label}</span>;
}
export function ConfidenceChip({ level }: { level?: string | null }) {
  return level ? <span className={`chip ${CONF[level] ?? "neutral"}`}>pewność {level}</span> : null;
}

/* ---------- powiadomienia (toast) ---------- */
type Toast = { id: number; text: string; error?: boolean };
const ToastCtx = createContext<(text: string, error?: boolean) => void>(() => undefined);
export const useToast = () => useContext(ToastCtx);
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const show = useCallback((text: string, error = false) => {
    const id = Date.now() + Math.random();
    setItems((t) => [...t, { id, text, error }]);
    window.setTimeout(() => setItems((t) => t.filter((x) => x.id !== id)), error ? 6000 : 3200);
  }, []);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => <div key={t.id} className={`toast ${t.error ? "err" : ""}`}>{t.text}</div>)}
      </div>
    </ToastCtx.Provider>
  );
}

export function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const Chevron = ({ open }: { open: boolean }) => (
  <svg className={`chev ${open ? "open" : ""}`} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    <path d="M5 8l5 5 5-5" strokeLinecap="round" strokeLinejoin="round" /></svg>
);
