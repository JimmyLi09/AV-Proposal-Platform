import { FormEvent, useEffect, useState } from "react";
import { Project, ProjectBrief, send, WorkspaceView } from "./api";
import { t } from "./i18n";
import { LINES, lineLabel } from "./labels";

type Form = { name: string; client: string; location: string; delivery: string; project_no: string; notes: string };
const FIELDS: (keyof Form)[] = ["name", "client", "location", "delivery", "project_no", "notes"];
const formOf = (p: ProjectBrief): Form =>
  ({ name: p.name, client: p.client, location: p.location, delivery: p.delivery, project_no: p.project_no ?? "", notes: p.notes });

function Fields({ form, set, lead }: { form: Form; set: (f: Form) => void; lead: boolean }) {
  return (
    <div className="form">
      {FIELDS.filter((k) => !(lead && k === "project_no")).map((k) => (
        <label key={k} className={k === "notes" ? "wide" : ""}>
          {t(`intake.${k}`)} {["name", "client"].includes(k) && "*"}
          {k === "notes" ? <textarea rows={2} value={form[k]} onChange={(e) => set({ ...form, [k]: e.target.value })} />
            : <input type={k === "delivery" ? "date" : "text"} value={form[k]} onChange={(e) => set({ ...form, [k]: e.target.value })} />}
        </label>
      ))}
    </div>
  );
}

// 01 立项询价 · 新建（CR-9）：填一次，后面每一步都带着走；项目编号可以先空着（售前接洽），之后再补。
// 「下一步」建好项目和第一个方案（选业务线），绑定当时最新的规则 / 产品库 / 模板版本。
export function NewIntake({ lead }: { lead: boolean }) {
  const [form, setForm] = useState<Form>({ name: "", client: "", location: "", delivery: "", project_no: "", notes: "" });
  const [line, setLine] = useState("LED");
  const [error, setError] = useState("");

  async function create(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const p = await send<Project>("POST", "/projects", { ...form, business_line: line });
      location.hash = `#/proposals/${p.proposals[0].id}/02-04`;
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <form onSubmit={create}>
      <div>
        <a href="#/">{t("flow.back")}</a>
        <h1>{t(lead ? "intake.leadTitle" : "intake.newTitle")}</h1>
      </div>
      <section className="card">
        <h2>01 · {t("flow.steps.01")}</h2>
        <p className="muted">{t("intake.intro")}</p>
        <Fields form={form} set={setForm} lead={lead} />
        <div className="row">
          <span>{t("intake.line")}</span>
          {LINES.map((l) => (
            <button type="button" key={l} className={`pill ${line === l ? "active" : ""}`} onClick={() => setLine(l)}>
              {lineLabel(l)}
            </button>
          ))}
          <span className="muted small">{t("intake.lineHint")}</span>
        </div>
        <p className="muted small">{t("intake.bindNew")}</p>
      </section>
      <div className="row step-nav">
        <a className="btn-outline" href="#/">{t("common.cancel")}</a>
        <span className="grow" />
        {error && <span className="error">{error}</span>}
        <button className="btn-primary" disabled={!form.name.trim() || !form.client.trim()}>
          {t("flow.next", { name: t("flow.steps.02-04") })}
        </button>
      </div>
    </form>
  );
}

/** 01 立项询价 · 已建的项目：改了约 1.2 秒后自动保存；业务线和建项时绑定的版本只显示，升级版本要手动点。 */
export default function IntakePage({ view, apply, onSaving }: {
  view: WorkspaceView;
  apply: (p: Promise<WorkspaceView>) => Promise<boolean>;
  onSaving: (p: Promise<unknown>) => Promise<boolean>;
}) {
  const p = view.project;
  const [form, setForm] = useState<Form>(() => formOf(p));
  const [line, setLine] = useState("LED");
  const dirty = JSON.stringify(form) !== JSON.stringify(formOf(p));
  const valid = form.name.trim() && form.client.trim();
  useEffect(() => {
    if (!dirty || !valid || view.readonly) return;
    const timer = setTimeout(() => onSaving(send("PATCH", `/projects/${p.id}`, form)), 1200);
    return () => clearTimeout(timer);
  }, [form]);
  const upgrades = Object.entries(view.flow.upgrades);

  async function addProposal() {
    const x = await send<{ id: number }>("POST", `/projects/${p.id}/proposals`, { business_line: line });
    location.hash = `#/proposals/${x.id}/02-04`;
  }

  return (
    <>
      <section className="card">
        <h2>01 · {t("flow.steps.01")}</h2>
        <p className="muted">{t("intake.intro")}</p>
        <Fields form={form} set={setForm} lead={false} />
        {!valid && <p className="error small">{t("intake.required")}</p>}
        <div className="row">
          <span>{t("intake.line")}</span>
          <span className="pill active">{view.flow.line_label}</span>
          <span className="muted small">{view.proposal.name}</span>
        </div>
        <p className="muted small">
          {t("intake.bound", { rules: view.rules_version, library: view.library_version, template: view.template_version })}
        </p>
        {upgrades.length > 0 && !view.readonly && (
          <p className="warn small">
            {t("intake.newer", { list: upgrades.map(([k, v]) => `${t(`intake.parts.${k}`)} ${v}`).join(" · ") })}{" "}
            <button className="btn-outline small" onClick={() => apply(send<WorkspaceView>("POST", `/proposals/${view.proposal.id}/upgrade`,
              { parts: upgrades.map(([k]) => k) }))}>{t("intake.upgrade")}</button>
          </p>
        )}
      </section>
      <section className="card">
        <h2>{t("intake.others")}</h2>
        <ul className="plain">
          {p.proposals.map((x) => (
            <li key={x.id}>
              {x.id === view.proposal.id ? <b>{x.name}</b> : <a href={`#/proposals/${x.id}`}>{x.name}</a>} · {x.line_label} · {x.version}
            </li>
          ))}
        </ul>
        <div className="row tight">
          <select aria-label={t("intake.line")} value={line} onChange={(e) => setLine(e.target.value)}>
            {LINES.map((l) => <option key={l} value={l}>{lineLabel(l)}</option>)}
          </select>
          <button className="btn-outline small" onClick={addProposal}>{t("intake.addProposal")}</button>
        </div>
      </section>
    </>
  );
}

