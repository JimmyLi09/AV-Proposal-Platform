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
  read_status: string | null;
  read_method: string;
  read_note: string;
  fields_found: number;
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
  diagram: Diagram | null;
  suggestions?: Suggestion[];
  library_version?: string;
};

// CR-2：产品库里没有够用的型号时，从参考型号表给出的建议型号（未入库，待核对规格书）
export type Suggestion = {
  id: string;
  model: string;
  capacity_px: number;
  ports: number;
  ports_used: number;
  load_pct: number;
  status: "recommended" | "headroom" | "no";
  label: string;
  reason: string;
  note: string;
  remark: string;
};

export type DiagramNode = { title: string; model: string; qty: number | string; detail: string; boq: string[]; supply: string };
export type DiagramLink = { from: string; to: string; cable: string; qty: string; boq: string | null; supply: string };
export type Diagram = {
  chain: string[];
  power: string | null;
  nodes: Record<string, DiagramNode>;
  links: DiagramLink[];
  unmatched: string[];
  svg: string;
};

export type Mark = { type: "point" | "area" | "device" | "text"; x: number; y: number; w: number; h: number; label: string; note: string; boq_key: string | null; size_mm?: number[] | null };
export type Scale = { a: { x: number; y: number }; b: { x: number; y: number }; mm: number };
export type AnnotationDoc = {
  file_id: number;
  filename: string;
  page: number;
  width: number;
  height: number;
  scale: Scale | null;
  marks: Mark[];
  copy_name: string;
  updated_by: string;
  updated_at: string;
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
};

// 客户版 BOQ（CR-6，不含价格）
export type ClientBoqRow = {
  no: number;
  key: string;
  title: string;
  title_default: string | null;
  specs: string[];
  specs_default: string[] | null;
  qty: number | null;
  rule_qty: number | null;
  unit: string;
  note: string;
  source: string;
  manual: boolean;
  reason: string | null;
  by: string | null;
  at: string | null;
  added: boolean;
};
export type ClientBoq = {
  group: string;
  group_default: string;
  rows: ClientBoqRow[];
  manual: Pick<ClientBoqRow, "no" | "key" | "title" | "rule_qty" | "qty" | "unit" | "reason" | "by" | "at" | "added">[];
};
export type TemplateRow = { key: string; title: string; specs: string[]; qty: number | string; unit: string; note?: string; source?: string };
export type TemplateContent = { business_line: string; boq: { group: string; rows: TemplateRow[] } };
export type TemplateVersion = Version<TemplateContent> & { units: string[]; names: string[] };

export type InputMeta = {
  source: "manual" | "file";
  confidence: string;
  filename?: string;
  location?: string;
  snippet?: string;
  extracted_id?: number;
  confirmed_by: string | null;
  confirmed_at?: string;
};
export type Candidate = {
  id: number;
  value: unknown;
  confidence: string;
  file_id: number;
  filename: string;
  location: string;
  snippet: string;
  crop: boolean;
};

export type WorkspaceView = {
  proposal: Proposal;
  project: { id: number };
  rev: {
    rev_no: number;
    status: string;
    inputs: Record<string, unknown>;
    cabinet_id: string | null;
    input_meta: Record<string, InputMeta>;
    annotations: Record<string, AnnotationDoc>;
  };
  pending: string[];
  files: SourceFile[];
  candidates: Record<string, Candidate[]>;
  rules_version: string;
  library_version: string;
  template_version: string;
  input_defs: InputDef[];
  product_fed: string[];
  result: RunResult | null;
  boq: ClientBoq | null;
};
