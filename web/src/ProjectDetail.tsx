import { FormEvent, useEffect, useState } from "react";
import { api, Project, send } from "./api";
import { t } from "./i18n";
import { fmtDate, fmtSize, LINES, lineLabel, StatusTag } from "./labels";

export default function ProjectDetail({ id }: { id: number }) {
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState("");

  const load = () => api<Project>(`/projects/${id}`).then(setProject, (e) => setError(e.message));
  useEffect(() => {
    load();
  }, [id]);

  if (error) return <p className="error">{error}</p>;
  if (!project) return null;

  return (
    <>
      <div>
        <a href="#/">← {t("projects.title")}</a>
        <h1>{project.name}</h1>
        <p className="muted">
          {project.client}
          {project.location && ` · ${project.location}`} · {t("projects.owner")} {project.owner.name}
        </p>
      </div>
      <ProjectNo project={project} onSaved={setProject} />
      <Files project={project} onUploaded={load} />
      <Proposals project={project} onCreated={load} />
    </>
  );
}

function ProjectNo({ project, onSaved }: { project: Project; onSaved: (p: Project) => void }) {
  const [value, setValue] = useState(project.project_no ?? "");
  const [editing, setEditing] = useState(project.project_no === null);
  const [error, setError] = useState("");

  async function save(e: FormEvent) {
    e.preventDefault();
    try {
      const p = await send<Project>("PATCH", `/projects/${project.id}`, { project_no: value });
      onSaved(p);
      setEditing(p.project_no === null);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <section className="card">
      <h2>{t("projects.projectNo")}</h2>
      {editing ? (
        <form className="row" onSubmit={save}>
          {project.project_no === null && <span className="tag">{t("projects.notLinked")}</span>}
          <input aria-label={t("projects.projectNo")} value={value} onChange={(e) => setValue(e.target.value)} />
          <button className="btn-outline">{t("project.link")}</button>
        </form>
      ) : (
        <div className="row">
          <b>{project.project_no}</b>
          <button className="btn-link" onClick={() => setEditing(true)}>
            {t("common.change")}
          </button>
        </div>
      )}
      {error && <p className="error">{error}</p>}
    </section>
  );
}

function Files({ project, onUploaded }: { project: Project; onUploaded: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const reading = project.files.some((f) => f.read_status === "reading");
  useEffect(() => {  // 读取在后台进行，读完前每 1.5 秒刷新
    if (!reading) return;
    const timer = setTimeout(onUploaded, 1500);
    return () => clearTimeout(timer);
  }, [reading, project]);

  async function reread() {
    await api(`/projects/${project.id}/read`, { method: "POST" });
    onUploaded();
  }

  async function upload(list: File[]) {
    if (!list.length) return;
    const body = new FormData();
    for (const f of list) body.append("files", f);
    setBusy(true);
    setError("");
    try {
      await api(`/projects/${project.id}/files`, { method: "POST", body });
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
        {project.files.length > 0 && (
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
            {project.files.map((f) => (
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
            {project.files.length === 0 && (
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

function Proposals({ project, onCreated }: { project: Project; onCreated: () => void }) {
  const [name, setName] = useState("");
  const [line, setLine] = useState("LED");
  const [error, setError] = useState("");

  async function create(e: FormEvent) {
    e.preventDefault();
    try {
      await send("POST", `/projects/${project.id}/proposals`, { name, business_line: line });
      setName("");
      onCreated();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <section className="card">
      <h2>{t("projects.proposals")}</h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t("project.proposal")}</th>
              <th>{t("project.line")}</th>
              <th>{t("project.mode")}</th>
              <th>{t("common.status")}</th>
              <th>{t("project.author")}</th>
            </tr>
          </thead>
          <tbody>
            {project.proposals.map((x) => (
              <tr key={x.id}>
                <td className="strong">
                  <a href={`#/proposals/${x.id}`}>{x.name}</a>
                </td>
                <td>{lineLabel(x.business_line)}</td>
                <td>{t("project.modeA")}</td>
                <td>
                  <StatusTag status={x.status} rev={x.rev_no} />
                </td>
                <td>{x.author}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <form className="row" onSubmit={create}>
        <select aria-label={t("project.line")} value={line} onChange={(e) => setLine(e.target.value)}>
          {LINES.map((k) => (
            <option key={k} value={k}>
              {lineLabel(k)}
            </option>
          ))}
        </select>
        <input aria-label={t("project.proposalName")} placeholder={t("project.proposalNameHint")} value={name}
          onChange={(e) => setName(e.target.value)} required />
        <button className="btn-outline">{t("project.newProposal")}</button>
      </form>
      {error && <p className="error">{error}</p>}
    </section>
  );
}
