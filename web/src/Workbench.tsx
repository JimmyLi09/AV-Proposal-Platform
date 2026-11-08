import { FormEvent, useEffect, useState } from "react";
import { api, send, Workbench as WB, WorkbenchRow } from "./api";
import { t } from "./i18n";
import { fmtDateTime } from "./labels";

export const STAGE_CODES = ["01", "02–04", "05", "06", "07"];

// AV 工作台（CR-9）：每个方案走同一条线 01 → 07。5 个阶段计数（点一下按阶段筛选，再点一次取消），
// 每行一条 5 段进度条（已完成绿、当前蓝、未到灰）；售前接洽可以没有项目编号，之后「转为正式项目」。
export default function Workbench() {
  const [data, setData] = useState<WB | null>(null);
  const [filter, setFilter] = useState(-1);
  const [msg, setMsg] = useState("");
  const load = () => api<WB>("/workbench").then(setData);
  useEffect(() => {
    load();
  }, []);
  if (!data) return null;
  const rows = data.rows.filter((r) => filter < 0 || r.stage === filter);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t("wb.title")}</h1>
          <p className="muted">{t("wb.intro")}</p>
        </div>
        <div className="row tight">
          <a className="btn-primary" href="#/new">{t("wb.new")}</a>
          <a className="btn-outline" href="#/new/lead">{t("wb.lead")}</a>
        </div>
      </div>

      <div className="stages">
        {STAGE_CODES.map((code, i) => (
          <button key={code} className={`stage-card ${filter === i ? "active" : ""}`} onClick={() => setFilter(filter === i ? -1 : i)}>
            <span className="muted small">{code} · {t(`wb.stages.${i}`)}</span>
            <b>{data.counts[i]}</b>
          </button>
        ))}
      </div>

      <section className="card">
        <div className="row tight">
          <span className="muted">
            {filter < 0 ? t("wb.all", { n: data.rows.length }) : t("wb.filtered", { stage: t(`wb.stages.${filter}`), n: rows.length })}
          </span>
          {filter >= 0 && <button className="btn-link" onClick={() => setFilter(-1)}>{t("wb.clear")}</button>}
        </div>
        {msg && <p className="ok">{msg}</p>}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("wb.project")}</th>
                <th>{t("wb.line")}</th>
                <th>{t("wb.progress")}</th>
                <th>{t("wb.now")}</th>
                <th>{t("wb.version")}</th>
                <th>{t("wb.updated")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <Row key={r.id} r={r} onConverted={(no) => { setMsg(t("wb.converted", { no })); load(); }} />
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="muted">{t("wb.empty")}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

export function ProgressBar({ stage }: { stage: number }) {
  return (
    <div className="bar" aria-label={stage > 4 ? t("wb.approved") : `${STAGE_CODES[stage]} · ${t(`wb.stages.${stage}`)}`}>
      {STAGE_CODES.map((code, i) => (
        <span key={code} title={code} className={i < stage ? "done" : i === stage ? "now" : ""} />
      ))}
    </div>
  );
}

function Row({ r, onConverted }: { r: WorkbenchRow; onConverted: (no: string) => void }) {
  const [converting, setConverting] = useState(false);
  const [no, setNo] = useState("");
  const [error, setError] = useState("");

  async function convert(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await send("PATCH", `/projects/${r.project_id}`, { project_no: no });
      onConverted(no.trim());
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <tr>
      <td>
        <a className="strong" href={`#/proposals/${r.id}`}>{r.name}</a> {r.lead && <span className="tag st-review">{t("wb.leadTag")}</span>}
        <div className="muted small">{r.project_no ?? "—"} · {r.client}</div>
      </td>
      <td>{r.line_label}</td>
      <td><ProgressBar stage={r.stage} /></td>
      <td>
        <span className={`tag ${r.stage > 4 ? "ck-PASS" : r.stage === 4 ? "st-review" : ""}`}>
          {r.stage > 4 ? t("wb.approved") : `${STAGE_CODES[r.stage]} ${t(`wb.short.${r.stage}`)}`}
        </span>
      </td>
      <td>{r.version}</td>
      <td className="small">{fmtDateTime(r.updated_at)}{r.updated_by && ` · ${r.updated_by}`}</td>
      <td className="nowrap">
        {r.lead && (converting ? (
          <form className="row tight" onSubmit={convert}>
            <input aria-label={t("projects.projectNo")} placeholder={t("projects.projectNo")} value={no} required
              onChange={(e) => setNo(e.target.value)} />
            <button className="btn-outline small">{t("common.save")}</button>
            <button type="button" className="btn-link" onClick={() => setConverting(false)}>{t("common.cancel")}</button>
            {error && <span className="error small">{error}</span>}
          </form>
        ) : (
          <button className="btn-link" onClick={() => setConverting(true)}>{t("wb.convert")}</button>
        ))}{" "}
        <a className="btn-outline small" href={`#/proposals/${r.id}`}>{t("wb.continue")}</a>
      </td>
    </tr>
  );
}
