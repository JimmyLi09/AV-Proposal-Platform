export type User = { id: number; name: string; role: string };

export type SourceFile = {
  id: number;
  filename: string;
  file_type: string;
  grade: string | null;
  size: number;
  sha256: string;
  uploaded_by: string;
  uploaded_at: string;
};

export type Proposal = {
  id: number;
  name: string;
  business_line: "LED" | "PJ";
  mode: string;
  rev_no: number;
  status: string;
  author: string;
  created_at: string;
};

export type Project = {
  id: number;
  name: string;
  client: string;
  project_no: string | null;
  location: string;
  notes: string;
  owner: User;
  created_at: string;
  files: SourceFile[];
  proposals: Proposal[];
};

export type ProjectRow = Omit<Project, "files"> & { file_count: number };

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = body?.detail;
    throw new Error(typeof detail === "string" ? detail : `请求失败（${res.status}）`);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export function send<T>(method: string, path: string, body: unknown): Promise<T> {
  return api<T>(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

// ---- 规则引擎 ----

export type Case = { when?: string | null; expr: string };
export type RuleOutput = { name: string; unit?: string; decimals?: number; cases: Case[] };
export type Rule = { id: string; title: string; note?: string; step?: string; check?: boolean; outputs?: RuleOutput[] };
export type Param = { name: string; group: string; label: string; unit: string; value: number | null; status: string };
export type InputDef = { name: string; label: string; unit?: string; type: "number" | "choice" | "range" | "sizes"; options?: string[] };
export type RuleContent = { business_line: string; inputs: InputDef[]; params: Param[]; rules: Rule[] };

export type RuleVersion = {
  id: number;
  version: string;
  reason: string;
  created_by: string | null;
  created_at: string;
  content: RuleContent;
};

export type ResultLine = { name: string; value: unknown; display: string; unit?: string; expr?: string; when?: string | null; substituted?: string };
export type RuleResult = {
  id: string;
  title: string;
  note: string;
  lines: ResultLine[];
  display: string;
  trace: string;
  check: string | null;
  status: string;
  params: { name: string; label: string; value: number | null; unit: string; status: string }[];
  missing: string[];
  error: string | null;
};
export type RunResult = { choices: Record<string, number[]>; rules: RuleResult[] };
