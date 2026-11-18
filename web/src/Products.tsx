import { useEffect, useState } from "react";
import { api, FieldDef, LibraryContent, LibraryVersion, Product, send, Version } from "./api";
import { nextVersion, optionLabel, SizesInput } from "./Calc";
import { t } from "./i18n";
import { fmtDate, LineTabs } from "./labels";
import SpecBatch from "./SpecBatch";

const STATUSES = ["preferred", "approved", "retired"];
const SCENES = ["indoor", "outdoor", "rental"];
const MAINT = ["front", "rear", "both"];

export const productStatus = (s: string) => t(`products.status.${s}`);

export function keySpecs(p: Product) {
  const n = (k: string) => p[k] as number | null;
  const v = { pitch: n("pixel_pitch_mm") ?? "?", mw: n("module_w_mm") ?? "?", mh: n("module_h_mm") ?? "?", nits: n("brightness_nits") ?? "?",
    mp: (n("capacity_px") ?? 0) / 1e6, ports: n("ports") ?? "?", inputs: n("inputs") ?? "?", max: (n("max_px") ?? 0) / 1e6 };
  if (p.category === "cabinet") return t("products.specs.cabinet", v) + (p.ip ? ` · ${p.ip}` : "");
  if (p.category === "controller") return t("products.specs.controller", v);
  if (p.category === "processor" && p.sending) return t("products.specs.sending", v);
  if (p.category === "processor") return t("products.specs.processor", v);
  const pj = { lm: n("lumens") ?? "?", w: n("native_px_w") ?? "?", h: n("native_px_h") ?? "?", watts: n("power_w") ?? "?",
    throw: n("throw_ratio") ?? "?", fits: ((p.fits as string[] | null) ?? []).join(", ") || "—", outputs: n("outputs") ?? "?" };
  if (p.category === "projector") return t("products.specs.projector", pj);
  if (p.category === "lens") return t("products.specs.lens", pj);
  if (p.category === "blender") return t(p.curved ? "products.specs.blenderCurved" : "products.specs.blender", pj);
  return "";
}

export default function Products({ line }: { line: string }) {
  const [saved, setSaved] = useState<LibraryVersion | null>(null);
  const [draft, setDraft] = useState<LibraryContent | null>(null);
  const [versions, setVersions] = useState<Version<unknown>[]>([]);
  const [filter, setFilter] = useState("all");
  const [preferredOnly, setPreferredOnly] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [imported, setImported] = useState<ExcelResult | null>(null);
  const [batch, setBatch] = useState(false);
  const [merged, setMerged] = useState("");

  async function load() {
    const v = await api<LibraryVersion>(`/products/${line}`);
    setSaved(v);
    setDraft(structuredClone(v.content));
    setEditing(null);
    setVersions(await api<Version<unknown>[]>(`/products/${line}/versions`));
  }
  useEffect(() => {
    load();
  }, []);

  if (!saved || !draft) return null;
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved.content);

  function setProduct(i: number, p: Product) {
    const copy = structuredClone(draft!);
    copy.products[i] = p;
    setDraft(copy);
  }

  function blank(category: string): Product {
    const p: Product = { id: "", category, brand: "", model: "", status: "approved", scenes: [], sample: false };
    if (saved!.fields[category].some((f) => f.name === "scenes")) p.scenes = ["indoor"];
    else delete (p as Record<string, unknown>).scenes; // 投影产品不按室内外选型
    for (const f of saved!.fields[category]) if (!(f.name in p)) p[f.name] = f.type === "text" ? "" : f.type === "maintenance" ? "front" : null;
    return p;
  }

  function add(category: string) {
    const copy = structuredClone(draft!);
    copy.products.push(blank(category));
    setDraft(copy);
    setEditing(copy.products.length - 1);
  }

  async function importExcel(file: File | undefined) {
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    body.append("content", JSON.stringify(draft));
    setError("");
    try {
      const r = await api<ExcelResult>(`/products/${line}/excel`, { method: "POST", body });
      setDraft({ ...draft!, products: r.products });
      setImported({ ...r, name: file.name });
      setEditing(null);
      if (!reason && (r.added.length || r.updated.length)) setReason(t("products.excel.reason", { name: file.name }));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function save() {
    setError("");
    try {
      await send("POST", `/products/${line}`, { base_id: saved!.id, reason, content: draft });
      setReason("");
      setImported(null);
      setMerged("");
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const rows = draft.products
    .map((p, i) => [p, i] as const)
    .filter(([p]) => (filter === "all" || p.category === filter) && (!preferredOnly || p.status === "preferred"));

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t("nav.products")}</h1>
          <p className="muted">{t("products.intro")}</p>
        </div>
        <span className="tag">{t("products.tag", { version: saved.version, n: saved.content.products.length })}</span>
      </div>

      {draft.products.some((p) => p.sample) && (
        <p className="warn">{t("products.sampleWarn")}</p>
      )}

      <div className="row">
        <LineTabs page="products" line={line} />
        {["all", ...Object.keys(saved.fields)].map((k) => (
          <button key={k} className={`pill ${filter === k ? "active" : ""}`} onClick={() => setFilter(k)}>
            {t(`products.filter.${k}`)}
          </button>
        ))}
        <label className="row tight">
          <input type="checkbox" checked={preferredOnly} onChange={(e) => setPreferredOnly(e.target.checked)} /> {t("products.preferredOnly")}
        </label>
        <div className="grow" />
        <a className="btn-outline" href={`/api/products/${line}/excel`}>{t("products.excel.export")}</a>
        <button className="btn-outline" onClick={() => setBatch(true)}>{t("products.batch.open")}</button>
        <label className="btn-outline">
          {t("products.excel.import")}
          <input type="file" accept=".xlsx,.xlsm" hidden onChange={(e) => { importExcel(e.target.files?.[0]); e.target.value = ""; }} />
        </label>
        <select aria-label={t("products.add")} value="" onChange={(e) => e.target.value && add(e.target.value)}>
          <option value="">+ {t("products.add")}</option>
          {Object.entries(saved.categories).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </div>

      {batch && (
        <SpecBatch line={line} fields={saved.fields} categories={saved.categories} products={draft.products} blank={blank}
          onClose={() => setBatch(false)}
          onMerge={(products, added, updated) => {
            setDraft({ ...draft, products });
            setBatch(false);
            setEditing(null);
            setMerged(t("products.batch.done", { added, updated }));
            if (!reason) setReason(t("products.batch.reason", { n: added + updated }));
          }} />
      )}
      {merged && <p className="ok">{merged}</p>}

      {imported && (
        <section className="card">
          <p className={imported.added.length || imported.updated.length ? "ok" : "muted"}>
            {t("products.excel.done", { name: imported.name ?? "", added: imported.added.length, updated: imported.updated.length })}
          </p>
          {imported.errors.length > 0 && (
            <>
              <p className="warn">{t("products.excel.errors", { n: imported.errors.length })}</p>
              <ul className="small">{imported.errors.map((e) => <li key={e}>{e}</li>)}</ul>
            </>
          )}
          <p className="muted small">{t("products.excel.hint")}</p>
        </section>
      )}

      <section className="card">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("ws.model")}</th>
                <th>{t("products.category")}</th>
                <th>{t("products.keySpecs")}</th>
                <th>{t("products.use")}</th>
                <th>{t("common.status")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([p, i]) => (
                <tr key={i} className={`clickable ${JSON.stringify(p) !== JSON.stringify(saved.content.products[i]) ? "changed" : ""}`}
                  onClick={() => setEditing(editing === i ? null : i)}>
                  <td className="strong">
                    {p.model || t("products.unnamed")} {p.sample && <span className="tag st-sample">{t("products.sample")}</span>}
                  </td>
                  <td>{saved.categories[p.category]}</td>
                  <td>{keySpecs(p)}</td>
                  <td>{p.scenes ? p.scenes.map(optionLabel).join(t("common.listSep")) : "—"}</td>
                  <td>
                    <span className={`tag ps-${p.status}`}>{productStatus(p.status)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {editing !== null && draft.products[editing] && (
        <ProductForm line={line} product={draft.products[editing]} fields={saved.fields[draft.products[editing].category]}
          isNew={editing >= saved.content.products.length}
          onChange={(p) => setProduct(editing, p)}
          onRemove={() => {
            const copy = structuredClone(draft);
            copy.products.splice(editing, 1);
            setDraft(copy);
            setEditing(null);
          }}
          onDone={() => setEditing(null)} />
      )}

      <section className="card">
        <h2>{t("versions.title")}</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("versions.version")}</th>
                <th>{t("versions.date")}</th>
                <th>{t("versions.by")}</th>
                <th>{t("versions.reason")}</th>
              </tr>
            </thead>
            <tbody>
              {versions.map((v) => (
                <tr key={v.id}>
                  <td className="strong">{v.version}</td>
                  <td>{fmtDate(v.created_at)}</td>
                  <td>{v.created_by ?? "—"}</td>
                  <td>{v.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className={`savebar ${dirty ? "on" : ""}`}>
        <b>{dirty ? t("versions.unsaved") : t("products.nothingToSave")}</b>
        {dirty && (
          <>
            <input aria-label={t("versions.reason")} placeholder={t("versions.reasonHint")} value={reason} onChange={(e) => setReason(e.target.value)} />
            <button className="btn-outline" onClick={() => setDraft(structuredClone(saved.content))}>
              {t("versions.discard")}
            </button>
          </>
        )}
        <button className="btn-primary" disabled={!dirty || !reason.trim()} onClick={save}>
          {t("products.saveAs", { version: nextVersion(saved.version) })}
        </button>
        {error && <span className="error">{error}</span>}
      </div>
    </>
  );
}

type ExcelResult = { products: Product[]; added: string[]; updated: string[]; errors: string[]; name?: string };
type Found = { value: number; location: string; snippet: string };
type SheetResult = { datasheet: string; values: Record<string, Found>; ocr: boolean; note: string; read: boolean };

// 读规格书：认出的参数逐项列出原文，人勾选后才填进产品
function Datasheet({ line, product, fields, onApply }: { line: string; product: Product; fields: FieldDef[]; onApply: (p: Product) => void }) {
  const [result, setResult] = useState<SheetResult | null>(null);
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function read(file: File | undefined) {
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    body.append("category", product.category);
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const r = await api<SheetResult>(`/products/${line}/datasheet`, { method: "POST", body });
      setResult(r);
      setPicked({}); // 默认都不勾：逐项核对后再勾
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function apply() {
    const next: Product = { ...product, datasheet: result!.datasheet };
    for (const [f, v] of Object.entries(result!.values)) if (picked[f]) next[f] = v.value;
    onApply(next);
    setResult(null);
  }

  const label = (name: string) => fields.find((f) => f.name === name)?.label ?? name;
  const entries = result ? Object.entries(result.values) : [];
  return (
    <div className="wide">
      <div className="row">
        <label className="btn-outline">
          {busy ? t("products.sheet.busy") : t("products.sheet.read")}
          <input type="file" accept=".pdf,.jpg,.jpeg,.png,.xlsx,.xlsm,.docx" hidden disabled={busy}
            onChange={(e) => { read(e.target.files?.[0]); e.target.value = ""; }} />
        </label>
        <span className="muted small">{t("products.sheet.hint")}</span>
      </div>
      {error && <p className="error">{error}</p>}
      {result && (
        <div className="card">
          <p className="strong">{result.datasheet}</p>
          {result.ocr && <p className="warn">{t("products.sheet.ocr")}</p>}
          {!result.read && <p className="warn">{result.note || t("products.sheet.unread")}</p>}
          {result.read && entries.length === 0 && <p className="warn">{t("products.sheet.none")}</p>}
          {entries.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th />
                  <th>{t("products.sheet.field")}</th>
                  <th>{t("products.sheet.value")}</th>
                  <th>{t("products.sheet.now")}</th>
                  <th>{t("products.sheet.source")}</th>
                </tr>
              </thead>
              <tbody>
                {entries.map(([f, v]) => (
                  <tr key={f}>
                    <td><input type="checkbox" aria-label={label(f)} checked={!!picked[f]} onChange={(e) => setPicked({ ...picked, [f]: e.target.checked })} /></td>
                    <td>{label(f)}</td>
                    <td className="strong">{v.value.toLocaleString()}</td>
                    <td>{product[f] == null || product[f] === "" ? "—" : String(product[f])}</td>
                    <td className="muted small">{v.location} · {v.snippet}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="row">
            <button className="btn-primary" disabled={!Object.values(picked).some(Boolean)} onClick={apply}>{t("products.sheet.apply")}</button>
            <button className="btn-link" onClick={() => setResult(null)}>{t("common.cancel")}</button>
          </div>
        </div>
      )}
    </div>
  );
}

function ProductForm({ line, product, fields, isNew, onChange, onRemove, onDone }: {
  line: string;
  product: Product;
  fields: FieldDef[];
  isNew: boolean;
  onChange: (p: Product) => void;
  onRemove: () => void;
  onDone: () => void;
}) {
  const set = (name: string, v: unknown) => onChange({ ...product, [name]: v });
  return (
    <section className="card form">
      <h2>
        {product.model || t("products.newProduct")} <span className="sub">{t("products.info")}</span>
      </h2>
      <Datasheet line={line} product={product} fields={fields} onApply={onChange} />
      {isNew && (
        <label>
          {t("products.id")}
          <input value={product.id} placeholder={t("products.idHint")} onChange={(e) => set("id", e.target.value.trim())} />
        </label>
      )}
      {fields.map((f) => (
        <label key={f.name} className={f.type === "ratings" ? "wide" : ""}>
          {f.label}
          {f.type === "ratings" ? (
            <RatingsInput sizes={(product.cabinet_sizes_mm as number[][] | null) ?? []} value={product[f.name] as Ratings | null}
              onChange={(v) => set(f.name, v)} />
          ) : (
            <Field def={f} value={product[f.name]} onChange={(v) => set(f.name, v)} />
          )}
        </label>
      ))}
      <div className="row wide">
        <button className="btn-outline" onClick={onDone}>
          {t("products.done")}
        </button>
        {isNew && (
          <button className="btn-link" onClick={onRemove}>
            {t("common.remove")}
          </button>
        )}
        <span className="muted">{t("products.retireHint")}</span>
      </div>
    </section>
  );
}

function Field({ def, value, onChange }: { def: FieldDef; value: unknown; onChange: (v: unknown) => void }) {
  switch (def.type) {
    case "status":
      return (
        <select aria-label={def.label} value={String(value)} onChange={(e) => onChange(e.target.value)}>
          {STATUSES.map((k) => (
            <option key={k} value={k}>
              {productStatus(k)}
            </option>
          ))}
        </select>
      );
    case "maintenance":
      return (
        <select aria-label={def.label} value={String(value)} onChange={(e) => onChange(e.target.value)}>
          {MAINT.map((k) => (
            <option key={k} value={k}>
              {optionLabel(k)}
            </option>
          ))}
        </select>
      );
    case "scenes": {
      const list = (value as string[]) ?? [];
      return (
        <span className="row tight">
          {SCENES.map((k) => (
            <label key={k} className="row tight check">
              <input type="checkbox" checked={list.includes(k)}
                onChange={(e) => onChange(e.target.checked ? [...list, k] : list.filter((s) => s !== k))} />
              {optionLabel(k)}
            </label>
          ))}
        </span>
      );
    }
    case "bool":
    case "flag":
      return <input type="checkbox" aria-label={def.label} checked={!!value} onChange={(e) => onChange(e.target.checked)} />;
    case "number":
      return <input type="number" step="any" aria-label={def.label} value={(value as number | null) ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} />;
    case "ids":
      return <input aria-label={def.label} value={((value as string[] | null) ?? []).join(", ")}
        onChange={(e) => onChange(e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} />;
    case "sizes":
      return <SizesInput label={def.label} text={((value as number[][] | null) ?? []).map((s) => s.join("x")).join(", ")} onChange={onChange} />;
    default:
      return <input aria-label={def.label} value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} />;
  }
}

type Ratings = Record<string, { a: number | null; w: number | null; sample: boolean }>;

/** 箱体每种尺寸的最大电流 / 功率（CR-10，规格书）：F5 按 Σ 箱数 × 最大功率，F6 按最大单箱电流算每回路带几箱。 */
function RatingsInput({ sizes, value, onChange }: { sizes: number[][]; value: Ratings | null; onChange: (v: Ratings) => void }) {
  const all = value ?? {};
  const set = (key: string, patch: Partial<Ratings[string]>) =>
    onChange({ ...all, [key]: { ...(all[key] ?? { a: null, w: null, sample: true }), ...patch } });
  const num = (s: string) => (s === "" ? null : Number(s));
  if (!sizes.length) return <span className="muted small">{t("products.ratings.noSizes")}</span>;
  return (
    <span className="ratings">
      {sizes.map(([w, h]) => {
        const key = `${w}x${h}`;
        const r = all[key] ?? { a: null, w: null, sample: true };
        return (
          <span key={key} className={`row tight ${r.sample ? "st-sample" : ""}`}>
            <b>{w} × {h}</b>
            <input type="number" step="any" className="num" aria-label={t("products.ratings.amps", { size: key })} value={r.a ?? ""}
              onChange={(e) => set(key, { a: num(e.target.value) })} /> A
            <input type="number" step="any" className="num" aria-label={t("products.ratings.watts", { size: key })} value={r.w ?? ""}
              onChange={(e) => set(key, { w: num(e.target.value) })} /> W
            <label className="row tight check">
              <input type="checkbox" checked={r.sample} onChange={(e) => set(key, { sample: e.target.checked })} />
              {t("products.ratings.sample")}
            </label>
          </span>
        );
      })}
    </span>
  );
}
