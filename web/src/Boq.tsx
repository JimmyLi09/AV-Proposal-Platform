import { useEffect, useState } from "react";
import { ClientBoq, send, WorkspaceView } from "./api";
import { fmtDate } from "./labels";

const UNITS = ["sqm", "set", "lot", "pcs"];
type RowDraft = { title: string; specs: string; qty: string; reason: string };
type AddedDraft = { key: string | null; title: string; specs: string; qty: string; unit: string };

const lines = (text: string) => text.split("\n").map((s) => s.trim()).filter(Boolean);
const qtyText = (q: number | null) => (q === null ? "" : String(q));

function draftOf(boq: ClientBoq) {
  return {
    group: boq.group,
    rows: Object.fromEntries(boq.rows.filter((r) => !r.added).map((r) => [r.key,
      { title: r.title, specs: r.specs.join("\n"), qty: qtyText(r.qty), reason: r.reason ?? "" } as RowDraft])),
    added: boq.rows.filter((r) => r.added).map((r) => ({ key: r.key, title: r.title, specs: r.specs.join("\n"), qty: qtyText(r.qty), unit: r.unit } as AddedDraft)),
  };
}

/** 客户版 BOQ：按区域分组，每行标题 + 规格子行，数量来自规则。不含价格。 */
export default function BoqTab({ view, boq, onApply }: { view: WorkspaceView; boq: ClientBoq; onApply: (p: Promise<WorkspaceView>) => void }) {
  const [draft, setDraft] = useState(() => draftOf(boq));
  const [showSource, setShowSource] = useState(false);
  useEffect(() => setDraft(draftOf(boq)), [boq]);
  const id = view.proposal.id;
  const dirty = JSON.stringify(draft) !== JSON.stringify(draftOf(boq));
  const setRow = (key: string, patch: Partial<RowDraft>) => setDraft({ ...draft, rows: { ...draft.rows, [key]: { ...draft.rows[key], ...patch } } });
  const setAdded = (i: number, patch: Partial<AddedDraft>) => setDraft({ ...draft, added: draft.added.map((a, j) => (j === i ? { ...a, ...patch } : a)) });

  function save() {
    onApply(send<WorkspaceView>("PUT", `/proposals/${id}/boq`, {
      group: draft.group,
      rows: Object.fromEntries(Object.entries(draft.rows).map(([k, r]) => [k,
        { title: r.title, specs: lines(r.specs), qty: r.qty === "" ? null : Number(r.qty), reason: r.reason }])),
      added: draft.added.map((a) => ({ key: a.key, title: a.title, specs: lines(a.specs), qty: Number(a.qty || 0), unit: a.unit })),
    }));
  }

  const rules = boq.rows.filter((r) => !r.added);
  return (
    <>
      <section className="card">
        <h2>
          BOQ <span className="zh">工程量清单</span>
        </h2>
        <p className="muted">按区域分组；每行写清楚规格，数量来自规则。不含价格。行的默认写法在 <a href="#/templates">Templates 模板</a> 里设定（模板 {view.template_version}）。</p>
        {boq.manual.length > 0 && <p className="warn">已有 {boq.manual.length} 项手动修改，审核时会逐项列出。</p>}
        <div className="row">
          <label className="row tight check">
            <input type="checkbox" checked={showSource} onChange={(e) => setShowSource(e.target.checked)} /> Show rule source 显示规则来源（内部，不导出）
          </label>
        </div>
        <div className="table-wrap">
          <table className="boq">
            <thead>
              <tr>
                <th>No.</th>
                <th>Description 描述</th>
                <th>Qty 数量</th>
                <th>Unit 单位</th>
                {showSource && <th>Source 来源</th>}
              </tr>
            </thead>
            <tbody>
              <tr className="group-row">
                <td />
                <td colSpan={showSource ? 4 : 3}>
                  <input className="wide strong" aria-label="Group title 组标题" value={draft.group} onChange={(e) => setDraft({ ...draft, group: e.target.value })} />
                </td>
              </tr>
              {rules.map((r) => {
                const d = draft.rows[r.key];
                const qtyChanged = d.qty !== "" && Number(d.qty) !== r.rule_qty;
                return (
                  <tr key={r.key}>
                    <td>{r.no}</td>
                    <td>
                      <input className="wide strong" aria-label={`第 ${r.no} 行描述`} value={d.title} onChange={(e) => setRow(r.key, { title: e.target.value })} />
                      <textarea aria-label={`第 ${r.no} 行规格`} rows={Math.max(1, lines(d.specs).length)} placeholder="规格，每行一条"
                        value={d.specs} onChange={(e) => setRow(r.key, { specs: e.target.value })} />
                      {r.note && <div className="note">*{r.note}</div>}
                    </td>
                    <td>
                      <input type="number" step="any" min="0" className={`num ${qtyChanged ? "manual" : ""}`} aria-label={`第 ${r.no} 行数量`}
                        value={d.qty} onChange={(e) => setRow(r.key, { qty: e.target.value })} />
                      {qtyChanged && (
                        <div className="small">
                          <span className="tag st-sample">Manual 手动</span> 规则 <s>{r.rule_qty ?? "—"}</s>{" "}
                          <button className="btn-link" onClick={() => setRow(r.key, { qty: qtyText(r.rule_qty), reason: "" })}>
                            Restore 恢复
                          </button>
                          <input aria-label={`第 ${r.no} 行修改原因`} placeholder="Reason 原因（必填）" value={d.reason}
                            onChange={(e) => setRow(r.key, { reason: e.target.value })} />
                          {r.manual && r.by && <div className="muted">{r.by} · {fmtDate(r.at!)}</div>}
                        </div>
                      )}
                    </td>
                    <td>{r.unit}</td>
                    {showSource && <td className="muted small">{r.source || "Template default 模板默认行"}</td>}
                  </tr>
                );
              })}
              {draft.added.map((a, i) => (
                <tr key={a.key ?? `new${i}`}>
                  <td>{rules.length + i + 1}</td>
                  <td>
                    <input className="wide strong" aria-label={`手动行 ${i + 1} 描述`} placeholder="Description 描述" value={a.title}
                      onChange={(e) => setAdded(i, { title: e.target.value })} />
                    <textarea aria-label={`手动行 ${i + 1} 规格`} rows={Math.max(1, lines(a.specs).length)} placeholder="规格，每行一条"
                      value={a.specs} onChange={(e) => setAdded(i, { specs: e.target.value })} />
                  </td>
                  <td>
                    <input type="number" step="any" min="0" className="num manual" aria-label={`手动行 ${i + 1} 数量`} value={a.qty}
                      onChange={(e) => setAdded(i, { qty: e.target.value })} />
                    <div className="small">
                      <span className="tag st-sample">Added manually 手动添加</span>{" "}
                      <button className="btn-link" onClick={() => setDraft({ ...draft, added: draft.added.filter((_, j) => j !== i) })}>
                        Remove 删除
                      </button>
                    </div>
                  </td>
                  <td>
                    <select aria-label={`手动行 ${i + 1} 单位`} value={a.unit} onChange={(e) => setAdded(i, { unit: e.target.value })}>
                      {UNITS.map((u) => (
                        <option key={u}>{u}</option>
                      ))}
                    </select>
                  </td>
                  {showSource && <td className="muted small">Added manually 手动添加</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted small">描述、规格和数量都可以直接改；改过的数量标「手动」，要写原因，审核页会列出。</p>
        <div className="row">
          <button className="btn-outline" onClick={() => setDraft({ ...draft, added: [...draft.added, { key: null, title: "", specs: "", qty: "1", unit: "lot" }] })}>
            + Add line 添加行
          </button>
          <button className="btn-primary" disabled={!dirty} onClick={save}>
            Save 保存
          </button>
          {dirty ? (
            <span className="muted">导出的是已保存的内容，先保存再导出。</span>
          ) : (
            <a className="btn-outline" href={`/api/proposals/${id}/boq.xlsx`}>
              Export BOQ Excel 导出 BOQ
            </a>
          )}
        </div>
      </section>

      <section className="card">
        <details>
          <summary>
            <b>Internal breakdown 内部明细（不导出）</b>
          </summary>
          <p className="muted">示意图、图纸和计算依据用这份明细；客户版 BOQ 只显示上面的汇总行。</p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Item 项目</th>
                  <th>Model 型号</th>
                  <th>Qty 数量</th>
                  <th>Why this qty 数量依据</th>
                </tr>
              </thead>
              <tbody>
                {view.result!.boq.map((l, i) => (
                  <tr key={i}>
                    <td>{i + 1}</td>
                    <td>{l.item}</td>
                    <td>{l.model}</td>
                    <td>
                      {l.qty} {l.unit}
                    </td>
                    <td>{l.why}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </section>
    </>
  );
}
