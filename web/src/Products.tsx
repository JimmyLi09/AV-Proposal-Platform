import { useEffect, useState } from "react";
import { api, FieldDef, LibraryContent, LibraryVersion, Product, send, Version } from "./api";
import { nextVersion, SizesInput } from "./Calc";
import { fmtDate } from "./labels";

const LINE = "LED";
export const PRODUCT_STATUS: Record<string, string> = {
  preferred: "Preferred 首选",
  approved: "Approved 已批准",
  retired: "Retired 已停用",
};
const SCENE: Record<string, string> = { indoor: "Indoor 室内", outdoor: "Outdoor 户外", rental: "Rental 租赁" };
const MAINT: Record<string, string> = { front: "Front 前维护", rear: "Rear 后维护", both: "Both 前后均可" };

export function keySpecs(p: Product) {
  const n = (k: string) => p[k] as number | null;
  if (p.category === "cabinet")
    return `P${n("pixel_pitch_mm") ?? "?"} · module 模组 ${n("module_w_mm") ?? "?"} × ${n("module_h_mm") ?? "?"} · ${n("brightness_nits") ?? "?"} nits${p.ip ? ` · ${p.ip}` : ""}`;
  if (p.category === "controller") return `${(n("capacity_px") ?? 0) / 1e6} MP · ${n("ports") ?? "?"} ports 网口`;
  if (p.category === "processor" && p.sending)
    return `With sending 含发送 · ${(n("capacity_px") ?? 0) / 1e6} MP · ${n("ports") ?? "?"} ports 网口 · ${n("inputs") ?? "?"} inputs 输入`;
  if (p.category === "processor") return `${n("inputs") ?? "?"} inputs 输入 · up to 最高 ${(n("max_px") ?? 0) / 1e6} MP`;
  return "";
}

export default function Products() {
  const [saved, setSaved] = useState<LibraryVersion | null>(null);
  const [draft, setDraft] = useState<LibraryContent | null>(null);
  const [versions, setVersions] = useState<Version<unknown>[]>([]);
  const [filter, setFilter] = useState("all");
  const [preferredOnly, setPreferredOnly] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");

  async function load() {
    const v = await api<LibraryVersion>(`/products/${LINE}`);
    setSaved(v);
    setDraft(structuredClone(v.content));
    setEditing(null);
    setVersions(await api<Version<unknown>[]>(`/products/${LINE}/versions`));
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

  function add(category: string) {
    const blank: Product = { id: "", category, brand: "", model: "", status: "approved", scenes: ["indoor"], sample: false };
    for (const f of saved!.fields[category]) if (!(f.name in blank)) blank[f.name] = f.type === "text" ? "" : f.type === "maintenance" ? "front" : null;
    const copy = structuredClone(draft!);
    copy.products.push(blank);
    setDraft(copy);
    setEditing(copy.products.length - 1);
  }

  async function save() {
    setError("");
    try {
      await send("POST", `/products/${LINE}`, { base_id: saved!.id, reason, content: draft });
      setReason("");
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
          <h1>
            Product Library <span className="zh">产品库</span>
          </h1>
          <p className="muted">推荐只使用这里列出的产品。编辑会生成新的产品库版本；已发出的 Rev 保留当时使用的版本。</p>
        </div>
        <span className="tag">
          Library 产品库 {saved.version} · {saved.content.products.length} products 个产品
        </span>
      </div>

      {draft.products.some((p) => p.sample) && (
        <p className="warn">标「示例数据」的产品用于测试流程；清单 D 组填好后替换。</p>
      )}

      <div className="row">
        <span className="pill active">LED</span>
        {[["all", "All 全部"], ["cabinet", "Cabinets 箱体"], ["controller", "Controllers 控制器"], ["processor", "Processors 视频处理器"]].map(([k, v]) => (
          <button key={k} className={`pill ${filter === k ? "active" : ""}`} onClick={() => setFilter(k)}>
            {v}
          </button>
        ))}
        <label className="row tight">
          <input type="checkbox" checked={preferredOnly} onChange={(e) => setPreferredOnly(e.target.checked)} /> Preferred only 仅首选
        </label>
        <div className="grow" />
        <select aria-label="Add product 添加产品" value="" onChange={(e) => e.target.value && add(e.target.value)}>
          <option value="">+ Add product 添加产品</option>
          {Object.entries(saved.categories).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </div>

      <section className="card">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Model 型号</th>
                <th>Category 类别</th>
                <th>Key specs 关键参数</th>
                <th>Use 用途</th>
                <th>Status 状态</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([p, i]) => (
                <tr key={i} className={`clickable ${JSON.stringify(p) !== JSON.stringify(saved.content.products[i]) ? "changed" : ""}`}
                  onClick={() => setEditing(editing === i ? null : i)}>
                  <td className="strong">
                    {p.model || "（新产品）"} {p.sample && <span className="tag st-sample">示例数据</span>}
                  </td>
                  <td>{saved.categories[p.category]}</td>
                  <td>{keySpecs(p)}</td>
                  <td>{p.scenes.map((s) => SCENE[s]).join("、")}</td>
                  <td>
                    <span className={`tag ps-${p.status}`}>{PRODUCT_STATUS[p.status]}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {editing !== null && draft.products[editing] && (
        <ProductForm product={draft.products[editing]} fields={saved.fields[draft.products[editing].category]}
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
        <h2>
          Versions <span className="zh">版本</span>
        </h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Version 版本</th>
                <th>Date 日期</th>
                <th>By 修改人</th>
                <th>Reason 修改原因</th>
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
        <b>{dirty ? "Unsaved changes 未保存修改" : "修改产品后才能保存"}</b>
        {dirty && (
          <>
            <input aria-label="Reason 修改原因" placeholder="Reason 修改原因（必填）" value={reason} onChange={(e) => setReason(e.target.value)} />
            <button className="btn-outline" onClick={() => setDraft(structuredClone(saved.content))}>
              Discard 放弃修改
            </button>
          </>
        )}
        <button className="btn-primary" disabled={!dirty || !reason.trim()} onClick={save}>
          Save as library {nextVersion(saved.version)} 另存为产品库 {nextVersion(saved.version)}
        </button>
        {error && <span className="error">{error}</span>}
      </div>
    </>
  );
}

function ProductForm({ product, fields, isNew, onChange, onRemove, onDone }: {
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
        {product.model || "New product 新产品"} <span className="zh">产品信息</span>
      </h2>
      {isNew && (
        <label>
          ID 编号（保存后不能改）
          <input value={product.id} placeholder="例如 IC-25" onChange={(e) => set("id", e.target.value.trim())} />
        </label>
      )}
      {fields.map((f) => (
        <label key={f.name}>
          {f.label}
          <Field def={f} value={product[f.name]} onChange={(v) => set(f.name, v)} />
        </label>
      ))}
      <div className="row wide">
        <button className="btn-outline" onClick={onDone}>
          Done 完成
        </button>
        {isNew && (
          <button className="btn-link" onClick={onRemove}>
            Remove 删除
          </button>
        )}
        <span className="muted">不用的产品请改为「Retired 已停用」，旧版本仍保留。</span>
      </div>
    </section>
  );
}

function Field({ def, value, onChange }: { def: FieldDef; value: unknown; onChange: (v: unknown) => void }) {
  switch (def.type) {
    case "status":
      return (
        <select aria-label={def.label} value={String(value)} onChange={(e) => onChange(e.target.value)}>
          {Object.entries(PRODUCT_STATUS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      );
    case "maintenance":
      return (
        <select aria-label={def.label} value={String(value)} onChange={(e) => onChange(e.target.value)}>
          {Object.entries(MAINT).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      );
    case "scenes": {
      const list = (value as string[]) ?? [];
      return (
        <span className="row tight">
          {Object.entries(SCENE).map(([k, v]) => (
            <label key={k} className="row tight check">
              <input type="checkbox" checked={list.includes(k)}
                onChange={(e) => onChange(e.target.checked ? [...list, k] : list.filter((s) => s !== k))} />
              {v}
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
    case "sizes":
      return <SizesInput label={def.label} text={((value as number[][] | null) ?? []).map((s) => s.join("x")).join(", ")} onChange={onChange} />;
    default:
      return <input aria-label={def.label} value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} />;
  }
}
