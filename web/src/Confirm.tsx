import { useState } from "react";
import { send, WorkspaceView } from "./api";
import { InputField, optionLabel } from "./Calc";
import { t } from "./i18n";

export const conf = (c: string) => t(`confirm.conf.${c}`);

export function show(v: unknown): string {
  if (Array.isArray(v)) return v.join(" – ");
  if (typeof v === "string") return v === "" ? "—" : optionLabel(v);
  return v === null || v === undefined ? "—" : String(v);
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
      <h2>{t("confirm.title")}</h2>
      <p className="muted">
        {reading > 0 ? t("confirm.reading", { n: reading }) : t("confirm.read", { files: files.length, found })}
        {t("confirm.intro")}
      </p>
      <div className="row">
        <button className="btn-outline" disabled={found === 0} onClick={() => post("fill-from-files")}>
          {t("confirm.fill")}
        </button>
        <span className="muted small">{t("confirm.fillHint")}</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t("confirm.field")}</th>
              <th>{t("confirm.value")}</th>
              <th>{t("confirm.source")}</th>
              <th>{t("confirm.confidence")}</th>
              <th>{t("common.status")}</th>
              <th>{t("confirm.others")}</th>
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
                    {d.name === "signal_sources" && (inputs[d.name] ?? null) === null && <div className="small muted">{t("confirm.oneSource")}</div>}
                  </td>
                  <td>
                    {meta?.source === "file" ? (
                      <button className="btn-link" onClick={() => setPreview(meta.extracted_id ?? null)}>
                        {meta.filename} · {meta.location}
                      </button>
                    ) : meta?.source === "manual" ? (
                      t("confirm.manual")
                    ) : (
                      <span className="muted">{cands.length ? "—" : t("confirm.notFound")}</span>
                    )}
                  </td>
                  <td>{meta && <span className={`tag conf-${meta.confidence}`}>{conf(meta.confidence)}</span>}</td>
                  <td>
                    {needs ? (
                      <button className="btn-primary small" onClick={() => post("confirm", { field: d.name })}>
                        {t("confirm.confirm")}
                      </button>
                    ) : meta?.confirmed_by ? (
                      <span className="small">
                        {t("confirm.confirmed")} · {meta.confirmed_by}
                      </span>
                    ) : meta ? (
                      <span className="small muted">{t("confirm.noNeed")}</span>
                    ) : null}
                  </td>
                  <td>
                    {meta?.source === "manual" && cands.some((c) => JSON.stringify(c.value) !== JSON.stringify(rev.inputs[d.name])) && (
                      <span className="tag st-review">{t("confirm.differs")}</span>
                    )}
                    {cands.length > 0 && (
                      <select aria-label={`${d.label} · ${t("confirm.others")}`} value={meta?.extracted_id ?? ""}
                        onChange={(e) => e.target.value && post("pick", { extracted_id: Number(e.target.value) })}>
                        <option value="">{t("project.candidates", { n: cands.length })}</option>
                        {cands.map((c) => (
                          <option key={c.id} value={c.id}>
                            {show(c.value)} · {c.filename} {c.location} · {conf(c.confidence)}
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
            {t("confirm.preview")} · {previewed.filename} · {previewed.location}
          </b>
          {previewed.crop && <img className="crop" src={`/api/extracted/${previewed.id}/crop`} alt={t("confirm.crop")} />}
          <span className="mono small">{previewed.snippet}</span>
          <span className="muted small">{t("confirm.previewHint")}</span>
        </div>
      )}
      <div className="row">
        <button className="btn-primary" onClick={() => onApply(send<WorkspaceView>("PUT", `/proposals/${id}/inputs`, { inputs, cabinet_id: rev.cabinet_id }))}>
          {t("confirm.save")}
        </button>
        {pending.length > 0 && <span className="warn">{t("confirm.pending", { n: pending.length })}</span>}
        {error && <span className="error">{error}</span>}
      </div>
    </section>
  );
}
