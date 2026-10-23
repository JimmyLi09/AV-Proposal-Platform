import { useEffect, useState } from "react";
import { api, send, TemplateContent, TemplateRow, TemplateVersion, Version } from "./api";
import { nextVersion } from "./Calc";
import { fmtDate } from "./labels";

const LINE = "LED";
const isNumber = (s: string) => s.trim() !== "" && !Number.isNaN(Number(s));
function newKey(rows: TemplateRow[]) {
  let n = rows.length + 1;
  while (rows.some((r) => r.key === `line_${n}`)) n++;
  return `line_${n}`;
}

/** 模板：客户版 BOQ 的默认行。保存时整份另存新版本（第 6 步再加章节、信头和标准条款）。 */
export default function Templates() {
  const [saved, setSaved] = useState<TemplateVersion | null>(null);
  const [draft, setDraft] = useState<TemplateContent | null>(null);
  const [versions, setVersions] = useState<Version<unknown>[]>([]);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");

  async function load() {
    const t = await api<TemplateVersion>(`/templates/${LINE}`);
    setSaved(t);
    setDraft(structuredClone(t.content));
    setVersions(await api<Version<unknown>[]>(`/templates/${LINE}/versions`));
  }
  useEffect(() => {
    load();
  }, []);

  if (!saved || !draft) return null;
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved.content);
  const rows = draft.boq.rows;
  const setRows = (next: TemplateRow[]) => setDraft({ ...draft, boq: { ...draft.boq, rows: next } });
  const setRow = (i: number, patch: Partial<TemplateRow>) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  function move(i: number, d: number) {
    const next = rows.slice();
    [next[i], next[i + d]] = [next[i + d], next[i]];
    setRows(next);
  }

  async function save() {
    setError("");
    try {
      const clean = rows.map((r) => ({ ...r, specs: r.specs.map((x) => x.trim()).filter(Boolean) }));
      await send("POST", `/templates/${LINE}`, { base_id: saved!.id, reason, content: { ...draft!, boq: { ...draft!.boq, rows: clean } } });
      setReason("");
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <>
      <div className="page-head">
        <h1>
          Templates <span className="zh">模板</span>
        </h1>
        <span className="tag">LED · 模板 {saved.version}</span>
      </div>

      <section className="card">
        <h2>
          BOQ default lines <span className="zh">BOQ 默认行</span>
        </h2>
        <p className="muted">
          客户版 BOQ 每个方案都从这里的行开始。文字里写 {"{名字}"} 会换成规则结果或输入；数量填一个固定数（例如 1 lot），或选一个规则结果。模板不自己算数量。
        </p>
        <label className="row tight">
          Group title 组标题
          <input className="wide" aria-label="Group title 组标题" value={draft.boq.group}
            onChange={(e) => setDraft({ ...draft, boq: { ...draft.boq, group: e.target.value } })} />
        </label>
        <datalist id="value-names">
          {saved.names.map((n) => (
            <option key={n} value={n} />
          ))}
        </datalist>
        <div className="table-wrap">
          <table className="boq">
            <thead>
              <tr>
                <th>No.</th>
                <th>Description and spec lines 描述与规格</th>
                <th>Qty 数量</th>
                <th>Unit 单位</th>
                <th>Note / source 备注 / 来源</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td>
                    {i + 1}
                    <div className="mono small muted">{r.key}</div>
                  </td>
                  <td>
                    <input className="wide strong" aria-label={`第 ${i + 1} 行描述`} value={r.title} onChange={(e) => setRow(i, { title: e.target.value })} />
                    <textarea aria-label={`第 ${i + 1} 行规格`} rows={Math.max(1, r.specs.length)} placeholder="规格，每行一条"
                      value={r.specs.join("\n")} onChange={(e) => setRow(i, { specs: e.target.value.split("\n") })} />
                  </td>
                  <td>
                    <input list="value-names" className="num" aria-label={`第 ${i + 1} 行数量`} value={String(r.qty)}
                      onChange={(e) => setRow(i, { qty: isNumber(e.target.value) ? Number(e.target.value) : e.target.value })} />
                  </td>
                  <td>
                    <select aria-label={`第 ${i + 1} 行单位`} value={r.unit} onChange={(e) => setRow(i, { unit: e.target.value })}>
                      {saved.units.map((u) => (
                        <option key={u}>{u}</option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input aria-label={`第 ${i + 1} 行备注`} placeholder="Note 备注（斜体）" value={r.note ?? ""} onChange={(e) => setRow(i, { note: e.target.value })} />
                    <input aria-label={`第 ${i + 1} 行来源`} placeholder="Source 来源（内部）" value={r.source ?? ""} onChange={(e) => setRow(i, { source: e.target.value })} />
                  </td>
                  <td className="nowrap">
                    <button className="btn-link" disabled={i === 0} onClick={() => move(i, -1)} aria-label={`第 ${i + 1} 行上移`}>↑</button>
                    <button className="btn-link" disabled={i === rows.length - 1} onClick={() => move(i, 1)} aria-label={`第 ${i + 1} 行下移`}>↓</button>
                    <button className="btn-link" onClick={() => setRows(rows.filter((_, j) => j !== i))}>Remove 删除</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="row">
          <button className="btn-outline" onClick={() => setRows([...rows, { key: newKey(rows), title: "", specs: [], qty: 1, unit: "lot", note: "", source: "" }])}>
            + Add line 添加行
          </button>
        </div>
        <details>
          <summary className="small">可以用的名字（{saved.names.length} 个）</summary>
          <p className="mono small">{saved.names.map((n) => `{${n}}`).join("  ")}</p>
        </details>
      </section>

      <section className="card">
        <h2>
          Versions <span className="zh">版本</span>
        </h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Version 版本</th>
                <th>Date 日期</th>
                <th>By 修改人</th>
                <th>Reason 修改原因</th>
              </tr>
            </thead>
            <tbody>
              {versions.map((v) => (
                <tr key={v.id}>
                  <td className="strong">{v.version}</td>
                  <td>{fmtDate(v.created_at)}</td>
                  <td>{v.created_by ?? "—"}</td>
                  <td>{v.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className={`savebar ${dirty ? "on" : ""}`}>
        <b>{dirty ? "Unsaved changes 未保存修改" : "修改模板后才能保存"}</b>
        {dirty && (
          <>
            <input aria-label="Reason 修改原因" placeholder="Reason 修改原因（必填）" value={reason} onChange={(e) => setReason(e.target.value)} />
            <button className="btn-outline" onClick={() => setDraft(structuredClone(saved.content))}>
              Discard 放弃修改
            </button>
          </>
        )}
        <button className="btn-primary" disabled={!dirty || !reason.trim()} onClick={save}>
          Save as template {nextVersion(saved.version)} 另存为模板 {nextVersion(saved.version)}
        </button>
        {error && <span className="error">{error}</span>}
      </div>
    </>
  );
}
