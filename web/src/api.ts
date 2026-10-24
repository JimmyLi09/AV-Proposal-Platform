import { Lang, lang, t } from "./i18n";

export type User = { id: number; name: string; role: string; lang: Lang };

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
  const res = await fetch(`/api${path}`, { ...init, headers: { ...init?.headers, "X-Lang": lang() } });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = body?.detail;
    throw new Error(typeof detail === "string" ? detail : t("common.requestFailed", { status: res.status }));
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
export type RuleVersion = Version<RuleContent> & { product_fed: string[]; text: Record<string, string> };

export type ResultLine = {
  name: string;
  value: unknown;
  display: string;
  unit?: string;
  expr?: string;
  when?: string | null;
  substituted?: string;
  manual?: boolean; // CR-5：手动覆盖过；规则值在 rule_value / rule_display
  rule_value?: unknown;
  rule_display?: string;
};
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
  manual: string[];
};
export type RunResult = {
  choices: Record<string, number[]>;
  rules: RuleResult[];
  recommendation: Recommendation;
  boq: BoqLine[];
  diagram: Diagram | null;
  suggestions?: Suggestion[];
  library_version?: string;
  manual?: string[];
  faces?: FaceResult[]; // 多面屏（CR-7）：每面的规则结果
  multi?: MultiResult;
};

// 多面屏（CR-7）
export type FaceInput = {
  id: string;
  name?: string;
  orientation?: string;
  width_mm?: number | null;
  height_mm?: number | null;
  depth_mm?: number | null;
  mount_height_m?: number | null;
  signal_point?: string;
  power_point?: string;
  protection?: string;
  load?: string;
  width_sources?: SourceValue[];
  height_sources?: SourceValue[];
};
export type SourceValue = { src: string; kind: string; value: number };
export type CornerInput = { between: [string, string]; type: string; overlap?: string; resolution?: string };
export type FaceResult = FaceInput & { rules: RuleResult[]; values: Record<string, number>; choices: Record<string, number[]> };
export type MultiResult = {
  shape: string;
  totals: Record<string, number | number[]>;
  checks: { rule: string; check: string; text: string }[];
  conflicts: { face: string; field: string; sources: (SourceValue & { fits: boolean; options: number[] })[] }[];
  corners: { between: [string, string]; distance_m: number; result: string; resolution: string }[];
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

export type DiagramNode = { title: string; model: string; qty: number | string; detail: string; boq: string[]; supply: string; manual?: boolean };
export type DiagramLink = { from: string; to: string; cable: string; qty: string; boq: string | null; supply: string; manual?: boolean };
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

export type Product = { id: string; category: string; brand: string; model: string; status: string; scenes?: string[]; sample: boolean } & Record<string, unknown>;
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
  rule_manual: boolean; // 数量取自推荐页手动覆盖过的结果（CR-5）
  group?: string; // 多面屏按面分组（CR-7）
};
export type ClientBoq = {
  group: string;
  group_default: string;
  rows: ClientBoqRow[];
  manual: Pick<ClientBoqRow, "no" | "key" | "title" | "rule_qty" | "qty" | "unit" | "reason" | "by" | "at" | "added">[];
  readonly?: boolean; // 多面屏的 BOQ 目前只能看
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
  drawing: Drawing | null;
  overridable: Record<string, string[]>;
  overrides: ManualOverride[];
  shapes: string[];
  shape_guess: string;
  similar: Similar[];
};

// 推荐结果的手动覆盖（CR-5）：规则值 → 手动值 · 原因 · 修改人 · 时间
export type ManualOverride = {
  rule: string;
  title: string;
  name: string;
  unit: string;
  rule_value: unknown;
  rule_display: string;
  value: unknown;
  display: string;
  reason: string;
  by: string;
  at: string;
};

// 拼接与线路图（CR-3）
export type DrawingCabinet = { id: string; row: number; col: number; size: string; w: number; h: number; circuit: number; cable: number; manual: boolean; px: number; watts: number };
export type Drawing = {
  width: number;
  height: number;
  cols: number;
  rows: number[];
  sizes: Record<string, { w: number; h: number; count: number }>;
  cabinets: DrawingCabinet[];
  circuits: { no: number; cabinets: number; watts: number; amps: number; over: boolean }[];
  cables: { no: number; cabinets: number; px: number; over: boolean; path: string[] }[];
  circuit_cap_w: number;
  cable_cap_px: number;
  spare_circuits: number;
  spare_cables: number;
  manual: { power: number; data: number };
  edits: { power: Record<string, number>; data: Record<string, number> };
  checks: { check: string; text: string }[];
  blocked: boolean;
  basis: { item: string; formula: string; result: string; rule: string }[];
};

// 资料库（CR-8）
export type KbFile = { id: number; name: string; rel_path: string; doc_type: string; missing: boolean };
export type KbRecord = { line: "LED" | "PJ"; shape: string; inputs: Record<string, unknown>; actual: Record<string, number> };
export type KbOverview = {
  folder: string;
  exists: boolean;
  scan_at: string;
  types: { key: string; folder: string; enabled: boolean; files: number }[];
  counts: { files: number; read: number; failed: number; pending: number };
  last_scan: { at: string; by: number | null; new: number; changed: number; removed: number; failed: number; total: number } | null;
  progress: { done: number; total: number } | null;
  failed: (KbFile & { note: string })[];
};
export type KbItem = {
  id: number;
  kind: "product" | "template" | "project" | "rule";
  line: "LED" | "PJ";
  confidence: string;
  status: "pending" | "adopted" | "rejected";
  source: KbFile | null;
  location: string;
  snippet: string;
  decided_by: string | null;
  decided_at: string | null;
  result: { target: string; version?: string } | null;
  labels: Record<string, string>;
  // product
  model?: string;
  from_reference?: boolean;
  fields?: { name: string; label: string; value: number; current: number | null; changed: boolean }[];
  // template
  original?: string;
  row?: { title: string; specs: string[]; qty: number | string; unit: string; source: string };
  files?: number;
  // project / rule
  key?: string;
  record?: KbRecord;
  rule_id?: string;
  rule_title?: string;
  name?: string;
  rule_value?: number | null;
  actual?: number;
  rules_version?: string;
};
export type KbCompare = {
  rows: { name: string; rule_id: string | null; rule: number | null; actual: number; match: boolean }[];
  missing: string[];
  skipped: boolean;
  rules_version: string;
};
export type KbProject = {
  id: number;
  key: string;
  project_no: string | null;
  record: KbRecord | null;
  record_version: number;
  record_by: string | null;
  record_at: string | null;
  files: KbFile[];
  standard: { manual: boolean; list: boolean; by: string | null; at: string | null };
  labels: Record<string, string>;
  compare: KbCompare | null;
};
export type KbHit = { file: KbFile; project: string | null; location: string; snippet: string };
export type SimilarReason = { code: string; [k: string]: string | number };
export type Similar = {
  id: number;
  key: string;
  project_no: string | null;
  score: number;
  reasons: SimilarReason[];
  record: KbRecord;
  standard: boolean;
  files: { id: number; name: string }[];
};
export type KbReference = {
  id: number;
  rule_id: string;
  name: string;
  key: string;
  rule_value: number | null;
  actual: number;
  rules_version: string;
  label: string;
  decided_by: string | null;
  decided_at: string | null;
};
