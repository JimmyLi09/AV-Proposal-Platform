import { useEffect, useRef, useState } from "react";
import { api, send, STEPS, StepKey, WorkspaceView } from "./api";
import AnnotateTab from "./Annotate";
import BoqTab from "./Boq";
import DiagramTab from "./Diagram";
import DrawingTab from "./Drawing";
import IntakePage from "./Intake";
import ProjectionDrawings from "./Projection";
import ReviewTab from "./Review";
import SourcesPage from "./Sources";
import DesignPage from "./Workspace";
import { t } from "./i18n";
import { fmtDateTime } from "./labels";
import { STAGE_CODES } from "./Workbench";

const go = (id: number, step: string) => {
  location.hash = `#/proposals/${id}/${step}`;
  window.scrollTo(0, 0);
};

// 方案流程 01 → 07（CR-9，和 PM Platform 的 AV 模块对齐）：顶栏（返回工作台、项目、自动保存状态、最近更新）、
// 5 段步骤条（完成 / 当前 / 草稿 / 🔒 原因 / 未开始，锁住的点不进去）、每步内容、底部「上一步 / 下一步」。
// 步骤写在 URL 里，浏览器后退键能用。编辑都自动存成草稿；在 05 / 06 点「下一步」时有改动，先弹窗保存为正式版本 vN。
export default function Flow({ id, step }: { id: number; step: string | null }) {
  const [view, setView] = useState<WorkspaceView | null>(null);
  const [inputs, setInputs] = useState<Record<string, unknown>>({});
  const [error, setError] = useState("");
  const [revNo, setRevNo] = useState<number | null>(null); // null = 最新；旧版本只读
  const [saving, setSaving] = useState<"" | "saving" | "saved">("");
  const [opened, setOpened] = useState<number | null>(null);
  const [modal, setModal] = useState(false);
  const sent = useRef(""); // 自动保存时发出去的输入；保存回来之前又改了，就不覆盖正在改的
  const typing = useRef(inputs);
  typing.current = inputs;
  const path = `/proposals/${id}${revNo === null ? "" : `?rev=${revNo}`}`;

  function show(v: WorkspaceView) {
    setView(v);
    if (!sent.current || JSON.stringify(typing.current) === sent.current) setInputs(v.rev.inputs);
    sent.current = "";
    setOpened((n) => v.flow.opened ?? (n === v.rev.rev_no ? n : null)); // 同一个草稿上接着改，提示保留
  }
  async function apply(p: Promise<WorkspaceView>): Promise<boolean> {
    setError("");
    setSaving("saving");
    try {
      show(await p);
      setSaving("saved");
      return true;
    } catch (err) {
      setError((err as Error).message);
      setSaving("");
      return false;
    }
  }
  /** 改项目资料（01）这类不直接返回方案的保存：存完重新读一遍。 */
  async function saved(p: Promise<unknown>): Promise<boolean> {
    return apply(p.then(() => api<WorkspaceView>(path)));
  }
  const reload = () => api<WorkspaceView>(path).then(show, (e) => setError(e.message));
  useEffect(() => {
    reload();
  }, [path]);
  const reading = view?.files.some((f) => f.read_status === "reading");
  useEffect(() => {  // 文件还在解析时每 1.5 秒刷新
    if (!reading) return;
    const timer = setTimeout(reload, 1500);
    return () => clearTimeout(timer);
  }, [reading, view]);
  const readonly = !!view?.readonly;
  const changed = !!view && JSON.stringify(inputs) !== JSON.stringify(view.rev.inputs);
  const saveInputs = (values = inputs, cabinet_id = view?.rev.cabinet_id ?? null) => {
    sent.current = JSON.stringify(values);
    return apply(send<WorkspaceView>("PUT", `/proposals/${id}/inputs`, { inputs: values, cabinet_id }));
  };
  useEffect(() => {  // 02–04 的输入：停止编辑约 1.2 秒后自动保存成草稿
    if (!changed || readonly) return;
    const timer = setTimeout(() => saveInputs(), 1200);
    return () => clearTimeout(timer);
  }, [inputs]);

  if (!view) return error ? <p className="error">{error}</p> : null;
  const { flow, project, proposal } = view;
  const current = (STEPS as readonly string[]).includes(step ?? "") ? (step as StepKey) : null;
  if (!current) {  // 没写步骤：进入当前所在的步骤（「继续 ›」）
    location.replace(`#/proposals/${id}/${STEPS[Math.min(flow.stage, 4)]}`);
    return null;
  }
  const i = STEPS.indexOf(current);
  const info = flow.steps[i];
  const prev = STEPS[i - 1];
  const next = STEPS[i + 1];
  const why = readonly ? "" : flow.gates[current];
  const useSource = (face: string, field: string, value: number) => {  // 多面屏 S7：选定一份资料的值
    const faces = (view.rev.inputs.faces as { id: string }[]).map((f) => (f.id === face ? { ...f, [field]: value } : f));
    saveInputs({ ...view.rev.inputs, faces });
  };

  async function onNext() {
    if (readonly || current === "01") return go(id, next);
    if (current === "02-04" && changed && !(await saveInputs())) return;
    if ((current === "05" || current === "06") && flow.dirty) return setModal(true);
    if (await apply(send<WorkspaceView>("POST", `/proposals/${id}/next`, { step: current }))) go(id, next);
  }
  async function saveVersion() {
    setModal(false);
    if (await apply(send<WorkspaceView>("POST", `/proposals/${id}/next`, { step: current, save: true }))) go(id, next);
  }
  // 自动保存的提示只对草稿：保存成正式版本、提交、批准之后不再显示
  const saveText = saving === "saving" ? t("flow.saving") : !flow.draft || readonly ? ""
    : opened ? t("flow.opened", { v: `v${opened}` }) : saving === "saved" ? t("flow.saved") : "";

  return (
    <>
      <div className="flow-top">
        <a href="#/">{t("flow.back")}</a>
        <h1>
          {project.name} <span className="sub">{project.project_no ?? t("wb.leadTag")} · {flow.line_label} · {proposal.name}</span>
        </h1>
        <div className="row tight">
          <span className={`tag ${flow.dirty ? "st-review" : ""}`}>{flow.version}</span>
          {saveText && <span className={saving === "saving" ? "muted small" : "ok small"}>{saveText}</span>}
          <span className="muted small">
            {t("flow.updated", { at: fmtDateTime(flow.updated.at), by: flow.updated.by ?? "—" })}
          </span>
        </div>
        {readonly && (
          <p className="warn">
            {t("flow.oldVersion", { v: `v${view.rev.rev_no}` })}{" "}
            <button className="btn-link" onClick={() => setRevNo(null)}>{t("ws.backLatest")}</button>
          </p>
        )}
      </div>

      <nav className="steps" aria-label={t("flow.stepsLabel")}>
        {flow.steps.map((s, k) => (
          <button key={s.key} className={`step st-${s.state} ${s.key === current ? "current" : ""}`} disabled={s.state === "lock"}
            title={s.why || s.note} aria-current={s.key === current ? "step" : undefined} onClick={() => go(id, s.key)}>
            <b>{STAGE_CODES[k]} · {t(`flow.steps.${s.key}`)}</b>
            <span className="small">{s.key === current ? t("flow.current") : s.state === "lock" ? `🔒 ${s.note}` : s.note}</span>
          </button>
        ))}
      </nav>

      {info.state === "lock" && !readonly ? (
        <section className="card"><p className="warn">🔒 {info.why || info.note}</p></section>
      ) : (
        <fieldset className="plain-fieldset" disabled={readonly && current !== "07"}>
          {current === "01" && <IntakePage key={project.id} view={view} apply={apply} onSaving={saved} />}
          {current === "02-04" && (
            <SourcesPage view={view} inputs={inputs} setInputs={setInputs} onApply={apply} onReload={reload} onUse={useSource} error={error} />
          )}
          {current === "05" && <DesignPage view={view} apply={apply} onCabinet={(cid) => saveInputs(view.rev.inputs, cid)} onUse={useSource} />}
          {current === "06" && <Sheets view={view} apply={apply} reload={reload} />}
          {current === "07" && <ReviewTab view={view} onApply={apply} onOpenRev={(n) => (n === revNo ? reload() : setRevNo(n))} />}
        </fieldset>
      )}
      {error && current !== "02-04" && <p className="error">{error}</p>}

      <div className="row step-nav">
        {prev && <button className="btn-outline" onClick={() => go(id, prev)}>{t("flow.prev", { name: t(`flow.steps.${prev}`) })}</button>}
        <span className="grow" />
        {next && why && <span className="warn small">🔒 {why}</span>}
        {next && (
          <button className="btn-primary" disabled={!!why} onClick={onNext}>{t("flow.next", { name: t(`flow.steps.${next}`) })}</button>
        )}
      </div>

      {modal && (
        <div className="modal-back" role="dialog" aria-modal="true" aria-labelledby="save-title">
          <div className="modal card">
            <h2 id="save-title">{t("flow.saveTitle", { v: flow.next_version })}</h2>
            <p>{t("flow.saveBody", { v: flow.next_version, name: t(`flow.steps.${next}`) })}</p>
            <div className="row">
              <span className="grow" />
              <button className="btn-outline" onClick={() => setModal(false)}>{t("common.cancel")}</button>
              <button className="btn-primary" onClick={saveVersion}>{t("flow.saveGo", { v: flow.next_version })}</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

/** 06 图纸与 BOQ：先图纸与标注（拼接与线路图、L2 示意图、标注），下面是客户版 BOQ，跟着同一份方案出（CR-12 / 13）。 */
function Sheets({ view, apply, reload }: { view: WorkspaceView; apply: (p: Promise<WorkspaceView>) => Promise<boolean>; reload: () => void }) {
  const result = view.result;
  if (!result) return <section className="card"><p className="muted">{t("flow.noResult")}</p></section>;
  return (
    <>
      {view.drawing && <DrawingTab view={view} drawing={view.drawing} onApply={apply} />}
      {view.projection && <ProjectionDrawings view={view} />}
      {result.diagram ? <DiagramTab view={view} diagram={result.diagram} />
        : <section className="card"><p className="muted">{t("ws.noDiagram")}</p></section>}
      <AnnotateTab view={view} onSaved={reload} />
      {view.boq && <BoqTab view={view} boq={view.boq} onApply={apply} />}
    </>
  );
}
