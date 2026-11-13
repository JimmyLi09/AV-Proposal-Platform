import { useEffect, useState } from "react";
import { api, SourceFile, WorkspaceView } from "./api";
import { Choices } from "./Calc";
import ConfirmInputs from "./Confirm";
import ShapeFaces, { isMulti } from "./Faces";
import { Conflicts } from "./Multi";
import { t } from "./i18n";
import { fmtDate, fmtSize } from "./labels";

// 多面屏时尺寸在分面里填，确认输入表不再列整屏的尺寸（CR-7）
const FACE_FIELDS: Record<string, string[]> = { LED: ["width_mm", "height_mm"], PJ: ["wall_width_mm"] };

// 02–04 图纸 · 解析 · 校核（CR-9）：上传（原件存档，永不覆盖）→ 服务器解析 → 中 / 低置信度的字段逐个确认；
// 宽度不是模组整数倍时只能选吸附值；多面屏几份资料对不上的先选定。输入改了约 1.2 秒后自动保存。
export default function SourcesPage({ view, inputs, setInputs, onApply, onReload, onUse, error }: {
  view: WorkspaceView;
  inputs: Record<string, unknown>;
  setInputs: (v: Record<string, unknown>) => void;
  onApply: (p: Promise<WorkspaceView>) => void;
  onReload: () => void;
  onUse: (face: string, field: string, value: number) => void;
  error: string;
}) {
  const line = view.proposal.business_line;
  return (
    <>
      <Files project={view.project.id} files={view.files} onUploaded={onReload} />
      <ShapeFaces view={view} inputs={inputs} setInputs={setInputs} />
      {view.result && <Choices result={view.result} onPick={(k, v) => setInputs({ ...inputs, [k]: v })} />}
      <Conflicts view={view} onUse={onUse} />
      {view.result?.recommendation?.block && (
        <p className="error card">
          {view.result.recommendation.block} <a href="#/products">{t("nav.products")} →</a>
        </p>
      )}
      <ConfirmInputs view={view} inputs={inputs} setInputs={setInputs} onApply={onApply} error={error}
        hidden={isMulti(view, inputs) ? FACE_FIELDS[line] : []} />
      {line === "PJ" && <CompletenessNote view={view} />}
    </>
  );
}

function Files({ project, files, onUploaded }: { project: number; files: SourceFile[]; onUploaded: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const reading = files.some((f) => f.read_status === "reading");
  useEffect(() => {  // 读取在后台进行，读完前每 1.5 秒刷新
    if (!reading) return;
    const timer = setTimeout(onUploaded, 1500);
    return () => clearTimeout(timer);
  }, [reading, files]);

  async function reread() {
    await api(`/projects/${project}/read`, { method: "POST" });
    onUploaded();
  }

  async function upload(list: File[]) {
    if (!list.length) return;
    const body = new FormData();
    for (const f of list) body.append("files", f);
    setBusy(true);
    setError("");
    try {
      await api(`/projects/${project}/files`, { method: "POST", body });
      onUploaded();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <div className="page-head">
        <div>
          <h2>{t("project.files")}</h2>
          <p className="muted">{t("project.filesIntro")}</p>
          <p className="muted small">{t("project.grades")}</p>
        </div>
        {files.length > 0 && (
          <button className="btn-outline" disabled={reading} onClick={reread}>
            {t("project.reread")}
          </button>
        )}
        <label className="btn-primary">
          {busy ? t("project.uploading") : t("project.choose")}
          <input type="file" multiple hidden disabled={busy} onChange={(e) => {
              const list = Array.from(e.target.files ?? []);
              e.target.value = ""; // 允许再次选择同名文件
              upload(list);
            }} />
        </label>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t("project.file")}</th>
              <th>{t("project.grade")}</th>
              <th>{t("project.method")}</th>
              <th>{t("common.status")}</th>
              <th>{t("project.size")}</th>
              <th>{t("project.fingerprint")}</th>
              <th>{t("project.added")}</th>
            </tr>
          </thead>
          <tbody>
            {files.map((f) => (
              <tr key={f.id}>
                <td className="strong">
                  <a href={`/api/files/${f.id}`}>{f.filename}</a>
                  <div>
                    <span className="tag">{t("project.original")}</span>
                  </div>
                </td>
                <td>{f.grade ?? "—"}</td>
                <td>
                  {f.read_method || "—"}
                  {f.read_note && <div className="muted small">{f.read_note}</div>}
                </td>
                <td>
                  {f.read_status ? t(`project.read.${f.read_status}`) : "—"}
                  {f.read_status === "read" && <div className="muted small">{t("project.candidates", { n: f.fields_found })}</div>}
                </td>
                <td>{fmtSize(f.size)}</td>
                <td>
                  <code title={f.sha256}>{f.sha256.slice(0, 10)}</code>
                </td>
                <td>
                  {fmtDate(f.uploaded_at)} · {f.uploaded_by}
                </td>
              </tr>
            ))}
            {files.length === 0 && (
              <tr>
                <td colSpan={7} className="muted">
                  {t("project.noFiles")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}


// 资料齐全度（第 8 步 · 投影）：在确认输入里勾了拿到哪些图，这里写等级；不是 A 级时风险与假设会自动加一条条款，计算照常出
export function CompletenessNote({ view }: { view: WorkspaceView }) {
  const c = view.completeness;
  return (
    <section className="card">
      <h2>{t("completeness.title")}</h2>
      {!c ? <p className="muted">{t("completeness.unknown")}</p> : (
        <p className={c.grade === "A" ? "ok" : "warn"}>
          <span className={`tag ${c.grade === "A" ? "ck-PASS" : "st-sample"}`}>{t("completeness.grade", { grade: c.grade })}</span>{" "}
          {c.grade === "A" ? t("completeness.full") : t("completeness.missing", {
            missing: c.missing.join(t("common.listSep")), affected: c.affected.join(t("common.listSep")) })}
        </p>
      )}
    </section>
  );
}
