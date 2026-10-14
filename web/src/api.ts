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

export type Version<T> = {
  id: number;
  version: string;
  reason: string;
  created_by: string | null;
  created_at: string;
  content: T;
};
export type RuleVersion = Version<RuleContent> & { product_fed: string[] };

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
export type RunResult = {
  choices: Record<string, number[]>;
  rules: RuleResult[];
  recommendation: Recommendation;
  boq: BoqLine[];
  library_version?: string;
};

// ---- 产品库、推荐、BOQ ----

export type Product = { id: string; category: string; brand: string; model: string; status: string; scenes: string[]; sample: boolean } & Record<string, unknown>;
export type LibraryContent = { business_line: string; products: Product[] };
export type FieldDef = { name: string; label: string; type: string };
export type LibraryVersion = Version<LibraryContent> & {
  fields: Record<string, FieldDef[]>;
  categories: Record<string, string>;
  statuses: string[];
  scenes: string[];
};
export type Recommendation = { cabinet: Product | null; candidates: Product[]; block: string | null; missing: string[] };

export type BoqLine = {
  key: string;
  item: string;
  model: string;
  qty: number | null;
  unit: string;
  why: string;
  rule?: string | null;
  included: boolean;
  manual: boolean;
  unit_cost?: number | null;
  cost_valid_until?: string | null;
  cost_sample?: boolean;
  cost_expired?: boolean;
  subtotal?: number | null;
};
export type Boq = { lines: BoqLine[]; subtotal: number; priced: number; count: number; missing: number; expired: number };
export type ManualLine = { item: string; model: string; qty: number | null; unit: string; unit_cost: number | null; why: string };

export type WorkspaceView = {
  proposal: Proposal;
  project: { id: number };
  rev: {
    rev_no: number;
    status: string;
    inputs: Record<string, unknown>;
    cabinet_id: string | null;
    manual_lines: ManualLine[];
    sell_price_cents: number | null;
    price_display: string;
  };
  rules_version: string;
  library_version: string;
  input_defs: InputDef[];
  product_fed: string[];
  gst_rate: number | null;
  gst_status: string | null;
  result: RunResult | null;
  boq: Boq | null;
};
