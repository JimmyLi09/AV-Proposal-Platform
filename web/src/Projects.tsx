import { FormEvent, useEffect, useState } from "react";
import { api, Project, ProjectRow, send } from "./api";
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
          <h1>
            Projects <span className="zh">项目</span>
          </h1>
          <p className="muted">项目可以先建，之后再关联 Project Platform 编号。两个系统只共用这个编号，不共用数据库。</p>
        </div>
        {!adding && (
          <button className="btn-primary" onClick={() => setAdding(true)}>
            + New project 新建项目
          </button>
        )}
      </div>

      {adding && <NewProject onCancel={() => setAdding(false)} />}

      <section className="card">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Project 项目</th>
                <th>Client 客户</th>
                <th>Project Platform no. 项目平台编号</th>
                <th>Proposals 方案</th>
                <th>Files 文件</th>
                <th>Owner 负责人</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id}>
                  <td className="strong">
                    <a href={`#/projects/${p.id}`}>{p.name}</a>
                  </td>
                  <td>{p.client}</td>
                  <td>{p.project_no ?? <span className="tag">Not linked 未关联</span>}</td>
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
                    还没有项目。
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
      <h2>
        Project information <span className="zh">项目信息</span>
      </h2>
      <label>
        Project name 项目名称 *
        <input value={form.name} onChange={set("name")} required />
      </label>
      <label>
        Client 客户 *
        <input value={form.client} onChange={set("client")} required />
      </label>
      <label>
        Project Platform no. 项目平台编号 <span className="muted">(optional 选填)</span>
        <input value={form.project_no} onChange={set("project_no")} />
        <span className="hint">项目还没建档可以先留空，之后在项目页关联。</span>
      </label>
      <label>
        Site location 项目地点
        <input value={form.location} onChange={set("location")} />
      </label>
      <label className="wide">
        Notes 备注
        <textarea value={form.notes} onChange={set("notes")} rows={2} />
      </label>
      {error && <p className="error wide">{error}</p>}
      <div className="row wide">
        <button className="btn-primary">Create 创建</button>
        <button type="button" className="btn-outline" onClick={onCancel}>
          Cancel 取消
        </button>
      </div>
    </form>
  );
}
