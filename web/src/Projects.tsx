import { FormEvent, useEffect, useState } from "react";
import { api, Project, ProjectRow, send } from "./api";
import { t } from "./i18n";
import { StatusTag } from "./labels";

export default function Projects() {
  const [rows, setRows] = useState<ProjectRow[]>([]);
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    api<ProjectRow[]>("/projects").then(setRows);
  }, []);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t("projects.title")}</h1>
          <p className="muted">{t("projects.intro")}</p>
        </div>
        {!adding && (
          <button className="btn-primary" onClick={() => setAdding(true)}>
            {t("projects.new")}
          </button>
        )}
      </div>

      {adding && <NewProject onCancel={() => setAdding(false)} />}

      <section className="card">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("projects.project")}</th>
                <th>{t("projects.client")}</th>
                <th>{t("projects.projectNo")}</th>
                <th>{t("projects.proposals")}</th>
                <th>{t("projects.files")}</th>
                <th>{t("projects.owner")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id}>
                  <td className="strong">
                    <a href={`#/projects/${p.id}`}>{p.name}</a>
                  </td>
                  <td>{p.client}</td>
                  <td>{p.project_no ?? <span className="tag">{t("projects.notLinked")}</span>}</td>
                  <td>
                    {p.proposals.map((x) => (
                      <div key={x.id}>
                        {x.name} <StatusTag status={x.status} rev={x.rev_no} />
                      </div>
                    ))}
                  </td>
                  <td>{p.file_count}</td>
                  <td>{p.owner.name}</td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={6} className="muted">
                    {t("projects.empty")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function NewProject({ onCancel }: { onCancel: () => void }) {
  const [form, setForm] = useState({ name: "", client: "", project_no: "", location: "", notes: "" });
  const [error, setError] = useState("");
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      const p = await send<Project>("POST", "/projects", form);
      location.hash = `#/projects/${p.id}`;
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <form className="card form" onSubmit={submit}>
      <h2>{t("projects.info")}</h2>
      <label>
        {t("projects.name")} *
        <input value={form.name} onChange={set("name")} required />
      </label>
      <label>
        {t("projects.client")} *
        <input value={form.client} onChange={set("client")} required />
      </label>
      <label>
        {t("projects.projectNo")} <span className="muted">{t("common.optional")}</span>
        <input value={form.project_no} onChange={set("project_no")} />
        <span className="hint">{t("projects.projectNoHint")}</span>
      </label>
      <label>
        {t("projects.location")}
        <input value={form.location} onChange={set("location")} />
      </label>
      <label className="wide">
        {t("projects.notes")}
        <textarea value={form.notes} onChange={set("notes")} rows={2} />
      </label>
      {error && <p className="error wide">{error}</p>}
      <div className="row wide">
        <button className="btn-primary">{t("common.create")}</button>
        <button type="button" className="btn-outline" onClick={onCancel}>
          {t("common.cancel")}
        </button>
      </div>
    </form>
  );
}
