// Klient REST API (backend: ../api.py, przez proxy Vite /api -> :8000)

/* eslint-disable @typescript-eslint/no-explicit-any */
export type Row = Record<string, any>;

export interface Stats {
  projects: number; fetched: number; links_confirmed: number; links_proposed: number;
  proposals_open: number; sample_available: boolean;
}
export interface Feature { name: string; status: string; detail: string }
export interface Candidate {
  ocid: string; rank: number; score: number; title: string; base_notice: string;
  confidence: string | null; matched: number | null; checked: number | null;
  features: Feature[]; notices: { type: string; label: string; number: string; date: string }[];
}
export interface Card {
  project: Row; kpo_value: number | null; links: Row[]; candidates: Candidate[]; contracts: Row[];
  changes: Row[]; facts: Row[]; events: Row[]; gaps: { key: string; message: string }[]; notices: Row[];
}
export interface Job { id: string; status: string; total: number; done: number; current: string | null; log: string[];
  network_calls?: number; sources?: string[] }
export interface ImportReport { run_id: number; counts: Record<string, number>;
  rows: { row_no: number | null; project_id: string | null; status: string; message: string | null }[] }
export interface Risk { code: string; name: string; effects: string }

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try { const j = await res.json(); if (j.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* brak JSON */ }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}
const post = <T>(path: string, body?: unknown) =>
  call<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  stats: () => call<Stats>("/api/stats"),
  risks: () => call<Risk[]>("/api/risks"),
  projects: () => call<Row[]>("/api/projects"),
  card: (id: string) => call<Card>(`/api/projects/${encodeURIComponent(id)}`),
  noticeHtmlUrl: (number: string) => `/api/notices/html?number=${encodeURIComponent(number)}`,
  importSample: () => post<ImportReport>("/api/import/sample"),
  importFile: (file: File) => {
    const fd = new FormData(); fd.append("file", file);
    return call<ImportReport>("/api/import", { method: "POST", body: fd });
  },
  startFetch: (ids: string[] | "all") => post<Job>("/api/fetch", ids === "all" ? { all: true } : { project_ids: ids }),
  job: (id: string) => call<Job>(`/api/jobs/${id}`),
  proposals: (status: string) => call<Row[]>(`/api/proposals?status=${encodeURIComponent(status)}`),
  decideEvent: (id: number, action: "accept" | "reject", code?: string, comment?: string) =>
    post<{ status: string }>(`/api/events/${id}/decision`, { action, code, comment }),
  analyze: (text: string) => post<Row>("/api/analysis", { text }),
  analyzeFile: (file: File) => {
    const fd = new FormData(); fd.append("file", file);
    return call<Row>("/api/analysis/file", { method: "POST", body: fd });
  },
  exportAnalysis: async (text: string, format: "csv" | "json") => {
    const res = await fetch(`/api/analysis/export?format=${format}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.blob();
  },
  kpoLinks: () => call<Row[]>("/api/kpo-links"),
  decideLink: (pid: string, action: "confirm" | "reject", ocid?: string, comment?: string) =>
    post<Row>(`/api/projects/${encodeURIComponent(pid)}/link`, { action, ocid, comment }),
};
