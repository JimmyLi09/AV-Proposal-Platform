import { useEffect, useState } from "react";
import { api, send } from "./api";
import { t } from "./i18n";

type Listing = { configured: boolean; root?: string; path?: string; folders?: string[]; files?: number; max?: number };

// 从服务器项目文件夹导入（例 D:\LED Projects）：逐层打开，选一个文件夹，把里面平台能读的文件复制进项目
export default function ServerImport({ project, onDone }: { project: number; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [list, setList] = useState<Listing | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  async function go(path: string) {
    setError("");
    try {
      setList(await api<Listing>(`/import-folder?path=${encodeURIComponent(path)}`));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  useEffect(() => { go(""); }, []);
  if (!list?.configured) return error ? <p className="error">{error}</p> : null;  // 没设置 project_import_dir：不显示

  async function importHere() {
    setBusy(true);
    setError("");
    setMsg("");
    try {
      const r = await send<{ files: unknown[]; skipped: number }>("POST", `/projects/${project}/import-folder`,
        { path: list!.path });
      setMsg(t("import.done", { n: r.files.length, skipped: r.skipped }));
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const parts = list.path ? list.path.split("/") : [];
  const tooMany = (list.files ?? 0) > (list.max ?? 0);
  return (
    <div className="card">
      <button className="btn-outline" onClick={() => setOpen(!open)}>{t("import.open")}</button>{" "}
      <span className="muted small">{list.root}</span>
      {open && (
        <>
          <p>
            <button className="btn-link" onClick={() => go("")}>{t("import.top")}</button>
            {parts.map((name, i) => (
              <span key={i}> / <button className="btn-link" onClick={() => go(parts.slice(0, i + 1).join("/"))}>{name}</button></span>
            ))}
          </p>
          <ul className="plain">
            {list.folders!.map((name) => (
              <li key={name}>
                <button className="btn-link" onClick={() => go([...parts, name].join("/"))}>📁 {name}</button>
              </li>
            ))}
            {list.folders!.length === 0 && <li className="muted">{t("import.noFolders")}</li>}
          </ul>
          <p className="muted small">{t("import.count", { n: list.files ?? 0 })}</p>
          {tooMany && <p className="warn">{t("import.tooMany", { max: list.max ?? 0 })}</p>}
          <button className="btn-primary" disabled={busy || !list.files || tooMany} onClick={importHere}>
            {busy ? t("import.busy") : t("import.here")}
          </button>
        </>
      )}
      {msg && <p className="ok">{msg}</p>}
      {error && <p className="error">{error}</p>}
    </div>
  );
}
