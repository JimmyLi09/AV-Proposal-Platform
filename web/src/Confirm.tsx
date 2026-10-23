import { useState } from "react";
import { send, WorkspaceView } from "./api";
import { InputField } from "./Calc";

export const CONF: Record<string, string> = { high: "High 高", medium: "Medium 中", low: "Low 低" };

export function show(v: unknown): string {
  if (Array.isArray(v)) return v.join(" – ");
  return v === null || v === undefined || v === "" ? "—" : String(v);
}

/** 确认输入：每个字段的值、来源、置信度与确认状态。medium / low 的值逐项确认之前不计算。 */
export default function ConfirmInputs({ view, inputs, setInputs, onApply, error }: {
  view: WorkspaceView;
  inputs: Record<string, unknown>;
  setInputs: (v: Record<string, unknown>) => void;
  onApply: (p: Promise<WorkspaceView>) => void;
  error: string;
}) {
  const [preview, setPreview] = useState<number | null>(null);
  const id = view.proposal.id;
  const { rev, candidates, pending, files } = view;
  const reading = files.filter((f) => f.read_status === "reading").length;
  const found = Object.values(candidates).reduce((n, c) => n + c.length, 0);
  const defs = view.input_defs.filter((d) => !view.product_fed.includes(d.name));
  const post = (path: string, body: unknown = {}) => onApply(send<WorkspaceView>("POST", `/proposals/${id}/${path}`, body));
  const previewed = Object.values(candidates).flat().find((c) => c.id === preview);

  return (
    <section className="card">
      <h2>
        Confirm Inputs <span className="zh">确认输入</span>
      </h2>
      <p className="muted">
        {reading > 0 ? `正在读取 ${reading} 个文件…` : `已读取 ${files.length} 个文件，找到 ${found} 个候选值。`}
        标为 Medium / Low 的字段必须逐项确认，才会运行规则计算。手填的值视为录入人已确认。模组和箱体尺寸由产品库里选定的箱体带出。
      </p>
      <div className="row">
        <button className="btn-outline" disabled={found === 0} onClick={() => post("fill-from-files")}>
          Fill from files 用文件中的值填入
        </button>
        <span className="muted small">只填还空着的字段，不覆盖已填的值。</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Field 字段</th>
              <th>Value 值</th>
              <th>Source 来源</th>
              <th>Confidence 置信度</th>
              <th>Status 状态</th>
              <th>Other values 其它读到的值</th>
            </tr>
          </thead>
          <tbody>
            {defs.map((d) => {
              const meta = rev.input_meta[d.name];
              const cands = candidates[d.name] ?? [];
              const changed = JSON.stringify(inputs[d.name] ?? null) !== JSON.stringify(rev.inputs[d.name] ?? null);
              const needs = pending.includes(d.name);
              return (
                <tr key={d.name} className={changed ? "changed" : needs ? "needs" : ""}>
                  <td className="strong">
                    {d.label} {d.unit && <span className="muted">({d.unit})</span>}
                  </td>
                  <td>
                    <InputField def={d} value={inputs[d.name]} onChange={(v) => setInputs({ ...inputs, [d.name]: v })} />
                  </td>
                  <td>
                    {meta?.source === "file" ? (
                      <button className="btn-link" onClick={() => setPreview(meta.extracted_id ?? null)}>
                        {meta.filename} · {meta.location}
                      </button>
                    ) : meta?.source === "manual" ? (
                      "Manual 手填"
                    ) : (
                      <span className="muted">{cands.length ? "—" : "文件中未找到"}</span>
                    )}
                  </td>
                  <td>{meta && <span className={`tag conf-${meta.confidence}`}>{CONF[meta.confidence]}</span>}</td>
                  <td>
                    {needs ? (
                      <button className="btn-primary small" onClick={() => post("confirm", { field: d.name })}>
                        Confirm 确认
                      </button>
                    ) : meta?.confirmed_by ? (
                      <span className="small">Confirmed 已确认 · {meta.confirmed_by}</span>
                    ) : meta ? (
                      <span className="small muted">High 无需逐项确认</span>
                    ) : null}
                  </td>
                  <td>
                    {meta?.source === "manual" && cands.some((c) => JSON.stringify(c.value) !== JSON.stringify(rev.inputs[d.name])) && (
                      <span className="tag st-review">Differs from file 与文件读到的不同</span>
                    )}
                    {cands.length > 0 && (
                      <select aria-label={`${d.label} 其它读到的值`} value={meta?.extracted_id ?? ""}
                        onChange={(e) => e.target.value && post("pick", { extracted_id: Number(e.target.value) })}>
                        <option value="">{cands.length} 个候选值</option>
                        {cands.map((c) => (
                          <option key={c.id} value={c.id}>
                            {show(c.value)} · {c.filename} {c.location} · {CONF[c.confidence]}
                          </option>
                        ))}
                      </select>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {previewed && (
        <div className="detail">
          <b>
            Source preview 来源预览 · {previewed.filename} · {previewed.location}
          </b>
          {previewed.crop && <img className="crop" src={`/api/extracted/${previewed.id}/crop`} alt="原文截图" />}
          <span className="mono small">{previewed.snippet}</span>
          <span className="muted small">原文件只读，这里是供核对的截取片段。</span>
        </div>
      )}
      <div className="row">
        <button className="btn-primary" onClick={() => onApply(send<WorkspaceView>("PUT", `/proposals/${id}/inputs`, { inputs, cabinet_id: rev.cabinet_id }))}>
          Save &amp; calculate 保存并计算
        </button>
        {pending.length > 0 && <span className="warn">还有 {pending.length} 个字段需要确认，确认之前不计算。</span>}
        {error && <span className="error">{error}</span>}
      </div>
    </section>
  );
}
