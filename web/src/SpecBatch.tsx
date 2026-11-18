import { useState } from "react";
import { api, send, FieldDef, Product } from "./api";
import { optionLabel } from "./Calc";
import { t } from "./i18n";

type Found = { value: unknown; location: string; snippet: string };
type Item = {
  file: string; category: string; model: string; brand: string; id: string; match: string | null;
  values: Record<string, Record<string, Found>>; ocr: boolean; read: boolean; note: string; same_as: number | null;
};
type Row = Item & { use: boolean; off: Record<string, boolean> };
type Listing = { configured: boolean; root?: string; path?: string; folders?: string[]; entries?: { name: string; size: number }[] };

const TYPES = ["pdf", "jpg", "jpeg", "png", "xlsx", "xlsm", "xls", "docx"];
const kind = (name: string) => name.split(".").pop()!.toLowerCase();

function show(v: unknown): string {
  if (Array.isArray(v)) return v.map((x) => (Array.isArray(x) ? x.join("×") : optionLabel(String(x)))).join(", ");
  if (typeof v === "boolean") return optionLabel(v ? "yes" : "no");
  return typeof v === "number" ? v.toLocaleString() : optionLabel(String(v));
}

// 规格书批量导入（2026-11-18）：一次读多份 Word / PDF / 图片 / Excel，可直接选服务器文件夹里的文件。
// 读到的值逐行列出、带原文；勾选的行才加进草稿，扫描件的值默认不勾。
export default function SpecBatch({ line, fields, categories, products, blank, onMerge, onClose }: {
  line: string;
  fields: Record<string, FieldDef[]>;
  categories: Record<string, string>;
  products: Product[];
  blank: (category: string) => Product;
  onMerge: (products: Product[], added: number, updated: number) => void;
  onClose: () => void;
}) {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [skipped, setSkipped] = useState<string[]>([]);
  const [server, setServer] = useState<Listing | null>(null);
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function loaded(r: { items: Item[]; skipped: string[] }) {
    // 扫描件（文字识别）的值默认不勾；同一产品的第二份规格书默认不加
    setRows(r.items.map((it) => ({
      ...it, use: false,
      off: Object.fromEntries(Object.keys(it.values[it.category] ?? {}).map((f) => [f, it.ocr])),
    })));
    setSkipped(r.skipped);
  }

  async function run(job: () => Promise<{ items: Item[]; skipped: string[] }>) {
    setBusy(true);
    setError("");
    try {
      loaded(await job());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function upload(list: FileList | null) {
    if (!list?.length) return;
    const body = new FormData();
    for (const f of Array.from(list)) body.append("files", f);
    run(() => api(`/products/${line}/datasheets`, { method: "POST", body }));
  }

  async function browse(path: string) {
    setError("");
    try {
      setServer(await api<Listing>(`/import-folder?entries=1&path=${encodeURIComponent(path)}`));
      setPicked({});
    } catch (err) {
      setError((err as Error).message);
    }
  }

  function readServer() {
    const base = server!.path ? server!.path + "/" : "";
    const paths = Object.keys(picked).filter((n) => picked[n]).map((n) => base + n);
    run(() => send("POST", `/products/${line}/datasheets/server`, { paths }));
  }

  const set = (i: number, patch: Partial<Row>) => setRows(rows!.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const label = (cat: string, f: string) => fields[cat]?.find((x) => x.name === f)?.label ?? f;

  function merge() {
    const next = [...products];
    let added = 0;
    let updated = 0;
    for (const r of rows!.filter((r) => r.use)) {
      const vals = Object.fromEntries(Object.entries(r.values[r.category] ?? {}).filter(([f]) => !r.off[f]).map(([f, v]) => [f, v.value]));
      const at = r.match ? next.findIndex((p) => p.id === r.match) : -1;
      if (at >= 0) {
        next[at] = { ...next[at], ...vals, datasheet: r.file };
        updated++;
      } else {
        const p = blank(r.category);
        Object.assign(p, { id: r.id.trim(), brand: r.brand.trim(), model: r.model.trim(), datasheet: r.file }, vals);
        if (!fields[r.category].some((f) => f.name === "scenes")) delete (p as Record<string, unknown>).scenes;
        next.push(p);
        added++;
      }
    }
    onMerge(next, added, updated);
  }

  const chosen = rows?.filter((r) => r.use) ?? [];
  const ids = products.map((p) => p.id);
  const bad = chosen.filter((r) => !r.match && (!r.id.trim() || !r.model.trim() || ids.includes(r.id.trim())
    || chosen.filter((x) => !x.match && x.id.trim() === r.id.trim()).length > 1));
  const serverFiles = server?.entries?.filter((e) => TYPES.includes(kind(e.name))) ?? [];
  const parts = server?.path ? server.path.split("/") : [];

  return (
    <section className="card">
      <div className="page-head">
        <div>
          <h2>{t("products.batch.title")}</h2>
          <p className="muted small">{t("products.batch.intro")}</p>
        </div>
        <button className="btn-link" onClick={onClose}>{t("common.cancel")}</button>
      </div>

      {!rows && (
        <div className="row">
          <label className="btn-outline">
            {busy ? t("products.sheet.busy") : t("products.batch.upload")}
            <input type="file" multiple hidden disabled={busy} accept={TYPES.map((x) => "." + x).join(",")}
              onChange={(e) => { upload(e.target.files); e.target.value = ""; }} />
          </label>
          <button className="btn-outline" disabled={busy} onClick={() => browse("")}>{t("products.batch.server")}</button>
        </div>
      )}
      {error && <p className="error">{error}</p>}

      {!rows && server && !server.configured && <p className="warn">{t("products.batch.noServer")}</p>}
      {!rows && server?.configured && (
        <div>
          <p>
            <span className="muted small">{server.root}</span>{" "}
            <button className="btn-link" onClick={() => browse("")}>{t("import.top")}</button>
            {parts.map((name, i) => (
              <span key={i}> / <button className="btn-link" onClick={() => browse(parts.slice(0, i + 1).join("/"))}>{name}</button></span>
            ))}
          </p>
          <ul className="plain">
            {server.folders!.map((name) => (
              <li key={name}><button className="btn-link" onClick={() => browse([...parts, name].join("/"))}>📁 {name}</button></li>
            ))}
            {serverFiles.map((e) => (
              <li key={e.name}>
                <label>
                  <input type="checkbox" checked={!!picked[e.name]} onChange={(ev) => setPicked({ ...picked, [e.name]: ev.target.checked })} />{" "}
                  {e.name} <span className="muted small">{Math.max(1, Math.round(e.size / 1024))} KB</span>
                </label>
              </li>
            ))}
            {!server.folders!.length && !serverFiles.length && <li className="muted">{t("products.batch.empty")}</li>}
          </ul>
          <div className="row">
            {serverFiles.length > 0 && (
              <button className="btn-link" onClick={() => setPicked(Object.fromEntries(serverFiles.map((e) => [e.name, true])))}>
                {t("products.batch.all")}
              </button>
            )}
            <button className="btn-primary" disabled={busy || !Object.values(picked).some(Boolean)} onClick={readServer}>
              {busy ? t("products.sheet.busy") : t("products.batch.read", { n: Object.values(picked).filter(Boolean).length })}
            </button>
          </div>
        </div>
      )}

      {rows && (
        <>
          {skipped.length > 0 && <p className="warn small">{t("products.batch.skipped", { files: skipped.join(", ") })}</p>}
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("products.batch.use")}</th>
                  <th>{t("products.batch.file")}</th>
                  <th>{t("products.batch.category")}</th>
                  <th>{t("products.id")}</th>
                  <th>{t("products.batch.brandModel")}</th>
                  <th>{t("products.batch.values")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i} className={r.use ? "changed" : ""}>
                    <td><input type="checkbox" aria-label={r.file} checked={r.use} onChange={(e) => set(i, { use: e.target.checked })} /></td>
                    <td className="small">
                      {r.file}
                      {r.ocr && <div className="warn">{t("products.batch.ocr")}</div>}
                      {!r.read && <div className="warn">{r.note || t("products.sheet.unread")}</div>}
                      {r.same_as != null && <div className="muted">{t("products.batch.same", { n: r.same_as + 1 })}</div>}
                    </td>
                    <td>
                      <select value={r.category} disabled={!!r.match}
                        onChange={(e) => set(i, { category: e.target.value, off: Object.fromEntries(Object.keys(r.values[e.target.value] ?? {}).map((f) => [f, r.ocr])) })}>
                        {Object.keys(fields).map((c) => <option key={c} value={c}>{categories[c] ?? c}</option>)}
                      </select>
                    </td>
                    <td>
                      {r.match ? <span className="strong">{t("products.batch.update", { id: r.match })}</span>
                        : <input value={r.id} onChange={(e) => set(i, { id: e.target.value })} />}
                    </td>
                    <td>
                      {!r.match && (
                        <>
                          <input value={r.brand} placeholder={t("products.batch.brand")} onChange={(e) => set(i, { brand: e.target.value })} />
                          <input value={r.model} placeholder={t("products.batch.model")} onChange={(e) => set(i, { model: e.target.value })} />
                        </>
                      )}
                    </td>
                    <td className="small">
                      {Object.entries(r.values[r.category] ?? {}).map(([f, v]) => (
                        <label key={f} title={`${v.location} · ${v.snippet}`} className="row tight check value-chip">
                          <input type="checkbox" checked={!r.off[f]} onChange={(e) => set(i, { off: { ...r.off, [f]: !e.target.checked } })} />{" "}
                          {label(r.category, f)}: <b>{show(v.value)}</b>
                        </label>
                      ))}
                      {!Object.keys(r.values[r.category] ?? {}).length && <span className="muted">{t("products.sheet.none")}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {bad.length > 0 && <p className="warn">{t("products.batch.badIds")}</p>}
          <div className="row">
            <button className="btn-primary" disabled={!chosen.length || bad.length > 0} onClick={merge}>
              {t("products.batch.merge", { n: chosen.length })}
            </button>
            <button className="btn-link" onClick={() => { setRows(null); setServer(null); }}>{t("products.batch.again")}</button>
            <span className="muted small">{t("products.batch.check")}</span>
          </div>
        </>
      )}
    </section>
  );
}
