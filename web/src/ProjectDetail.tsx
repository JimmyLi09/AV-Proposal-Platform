import { FormEvent, useEffect, useState } from "react";
import { api, Project, send } from "./api";
import { fmtDate, fmtSize, LINE_LABEL, StatusTag } from "./labels";

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
        <a href="#/">← Projects 项目</a>
        <h1>{project.name}</h1>
        <p className="muted">
          {project.client}
          {project.location && ` · ${project.location}`} · Owner 负责人 {project.owner.name}
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
      <h2>
        Project Platform no. <span className="zh">项目平台编号</span>
      </h2>
      {editing ? (
        <form className="row" onSubmit={save}>
          {project.project_no === null && <span className="tag">Not linked 未关联</span>}
          <input aria-label="Project Platform no. 项目平台编号" value={value} onChange={(e) => setValue(e.target.value)} />
          <button className="btn-outline">Link 关联</button>
        </form>
      ) : (
        <div className="row">
          <b>{project.project_no}</b>
          <button className="btn-link" onClick={() => setEditing(true)}>
            Change 修改
          </button>
        </div>
      )}
      {error && <p className="error">{error}</p>}
    </section>
  );
}

const READ: Record<string, string> = {
  reading: "Reading 读取中…",
  read: "Read 已读取",
  attached: "Attached 已附加",
  failed: "Failed 读取失败",
};

function Files({ project, onUploaded }: { project: Project; onUploaded: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const reading = project.files.some((f) => f.read_status === "reading");
  useEffect(() => {  // 读取在后台进行，读完前每 1.5 秒刷新
    if (!reading) return;
    const t = setTimeout(onUploaded, 1500);
    return () => clearTimeout(t);
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
          <h2>
            Customer files <span className="zh">客户文件</span>
          </h2>
          <p className="muted">原件只读保存，不会被覆盖。同名文件再传会另存一份。上传后服务器自动读取文字和尺寸。</p>
          <p className="muted small">A：数值直接读取 · B：数值靠文字识别，必须逐项确认 · C：随项目保存，不用于计算数量。</p>
        </div>
        {project.files.length > 0 && (
          <button className="btn-outline" disabled={reading} onClick={reread}>
            Re-read 重新读取
          </button>
        )}
        <label className="btn-primary">
          {busy ? "Uploading 上传中…" : "Choose files 选择文件"}
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
              <th>File 文件</th>
              <th>Grade 等级</th>
              <th>How it is read 读取方式</th>
              <th>Status 状态</th>
              <th>Size 大小</th>
              <th>Fingerprint 指纹</th>
              <th>Added 添加</th>
            </tr>
          </thead>
          <tbody>
            {project.files.map((f) => (
              <tr key={f.id}>
                <td className="strong">
                  <a href={`/api/files/${f.id}`}>{f.filename}</a>
                  <div>
                    <span className="tag">Original 原件 · read-only 只读</span>
                  </div>
                </td>
                <td>{f.grade ?? "—"}</td>
                <td>
                  {f.read_method || "—"}
                  {f.read_note && <div className="muted small">{f.read_note}</div>}
                </td>
                <td>
                  {f.read_status ? READ[f.read_status] : "—"}
                  {f.read_status === "read" && <div className="muted small">{f.fields_found} 个候选值</div>}
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
                  还没有文件。PDF、Excel、JPG、PNG、DWG 都可以上传。
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
      <h2>
        Proposals <span className="zh">方案</span>
      </h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Proposal 方案</th>
              <th>Business line 业务线</th>
              <th>Mode 模式</th>
              <th>Status 状态</th>
              <th>Author 作者</th>
            </tr>
          </thead>
          <tbody>
            {project.proposals.map((x) => (
              <tr key={x.id}>
                <td className="strong">
                  <a href={`#/proposals/${x.id}`}>{x.name}</a>
                </td>
                <td>{LINE_LABEL[x.business_line]}</td>
                <td>A Light 轻量</td>
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
        <select aria-label="Business line 业务线" value={line} onChange={(e) => setLine(e.target.value)}>
          {Object.entries(LINE_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <input aria-label="Proposal name 方案名称" placeholder="Proposal name 方案名称，如 LED-1 Lobby" value={name}
          onChange={(e) => setName(e.target.value)} required />
        <button className="btn-outline">+ New proposal 新建方案</button>
      </form>
      {error && <p className="error">{error}</p>}
    </section>
  );
}
