import { useEffect, useState } from "react";
import { ClientBoq, send, WorkspaceView } from "./api";
import { t } from "./i18n";
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
        <h2>{t("ws.tabs.boq")}</h2>
        <p className="muted">
          {t("boq.intro")} <a href="#/templates">{t("nav.templates")}</a>
          {t("boq.introVersion", { version: view.template_version })}
        </p>
        {boq.manual.length > 0 && <p className="warn">{t("boq.manualCount", { n: boq.manual.length })}</p>}
        <div className="row">
          <label className="row tight check">
            <input type="checkbox" checked={showSource} onChange={(e) => setShowSource(e.target.checked)} /> {t("boq.showSource")}
          </label>
        </div>
        <div className="table-wrap">
          <table className="boq">
            <thead>
              <tr>
                <th>No.</th>
                <th>{t("boq.description")}</th>
                <th>{t("diagram.qty")}</th>
                <th>{t("boq.unit")}</th>
                {showSource && <th>{t("confirm.source")}</th>}
              </tr>
            </thead>
            <tbody>
              <tr className="group-row">
                <td />
                <td colSpan={showSource ? 4 : 3}>
                  <input className="wide strong" aria-label={t("boq.group")} value={draft.group} onChange={(e) => setDraft({ ...draft, group: e.target.value })} />
                </td>
              </tr>
              {rules.map((r) => {
                const d = draft.rows[r.key];
                const qtyChanged = d.qty !== "" && Number(d.qty) !== r.rule_qty;
                return (
                  <tr key={r.key}>
                    <td>{r.no}</td>
                    <td>
                      <input className="wide strong" aria-label={t("boq.rowField", { no: r.no, field: t("boq.description") })} value={d.title} onChange={(e) => setRow(r.key, { title: e.target.value })} />
                      <textarea aria-label={t("boq.rowField", { no: r.no, field: t("boq.specs") })} rows={Math.max(1, lines(d.specs).length)} placeholder={t("boq.specsHint")}
                        value={d.specs} onChange={(e) => setRow(r.key, { specs: e.target.value })} />
                      {r.note && <div className="note">*{r.note}</div>}
                    </td>
                    <td>
                      <input type="number" step="any" min="0" className={`num ${qtyChanged ? "manual" : ""}`} aria-label={t("boq.rowField", { no: r.no, field: t("diagram.qty") })}
                        value={d.qty} onChange={(e) => setRow(r.key, { qty: e.target.value })} />
                      {r.rule_manual && !qtyChanged && (
                        <div className="small">
                          <span className="tag st-sample" title={t("manual.fromRec")}>{t("manual.tag")}</span>
                        </div>
                      )}
                      {qtyChanged && (
                        <div className="small">
                          <span className="tag st-sample">{t("boq.manual")}</span> {t("boq.ruleValue")} <s>{r.rule_qty ?? "—"}</s>{" "}
                          <button className="btn-link" onClick={() => setRow(r.key, { qty: qtyText(r.rule_qty), reason: "" })}>
                            {t("boq.restore")}
                          </button>
                          <input aria-label={t("boq.rowField", { no: r.no, field: t("boq.reason") })} placeholder={t("boq.reasonHint")} value={d.reason}
                            onChange={(e) => setRow(r.key, { reason: e.target.value })} />
                          {r.manual && r.by && <div className="muted">{r.by} · {fmtDate(r.at!)}</div>}
                        </div>
                      )}
                    </td>
                    <td>{r.unit}</td>
                    {showSource && <td className="muted small">{r.source || t("boq.templateDefault")}</td>}
                  </tr>
                );
              })}
              {draft.added.map((a, i) => (
                <tr key={a.key ?? `new${i}`}>
                  <td>{rules.length + i + 1}</td>
                  <td>
                    <input className="wide strong" aria-label={t("boq.addedField", { no: i + 1, field: t("boq.description") })} placeholder={t("boq.description")} value={a.title}
                      onChange={(e) => setAdded(i, { title: e.target.value })} />
                    <textarea aria-label={t("boq.addedField", { no: i + 1, field: t("boq.specs") })} rows={Math.max(1, lines(a.specs).length)} placeholder={t("boq.specsHint")}
                      value={a.specs} onChange={(e) => setAdded(i, { specs: e.target.value })} />
                  </td>
                  <td>
                    <input type="number" step="any" min="0" className="num manual" aria-label={t("boq.addedField", { no: i + 1, field: t("diagram.qty") })} value={a.qty}
                      onChange={(e) => setAdded(i, { qty: e.target.value })} />
                    <div className="small">
                      <span className="tag st-sample">{t("boq.added")}</span>{" "}
                      <button className="btn-link" onClick={() => setDraft({ ...draft, added: draft.added.filter((_, j) => j !== i) })}>
                        {t("common.remove")}
                      </button>
                    </div>
                  </td>
                  <td>
                    <select aria-label={t("boq.addedField", { no: i + 1, field: t("boq.unit") })} value={a.unit} onChange={(e) => setAdded(i, { unit: e.target.value })}>
                      {UNITS.map((u) => (
                        <option key={u}>{u}</option>
                      ))}
                    </select>
                  </td>
                  {showSource && <td className="muted small">{t("boq.added")}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted small">{t("boq.editHint")}</p>
        <div className="row">
          <button className="btn-outline" onClick={() => setDraft({ ...draft, added: [...draft.added, { key: null, title: "", specs: "", qty: "1", unit: "lot" }] })}>
            {t("boq.addLine")}
          </button>
          <button className="btn-primary" disabled={!dirty} onClick={save}>
            {t("common.save")}
          </button>
          {dirty ? (
            <span className="muted">{t("boq.saveFirst")}</span>
          ) : (
            <a className="btn-outline" href={`/api/proposals/${id}/boq.xlsx`}>
              {t("boq.export")}
            </a>
          )}
        </div>
      </section>

      <section className="card">
        <details>
          <summary>
            <b>{t("boq.internal")}</b>
          </summary>
          <p className="muted">{t("boq.internalIntro")}</p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>{t("boq.item")}</th>
                  <th>{t("ws.model")}</th>
                  <th>{t("diagram.qty")}</th>
                  <th>{t("boq.why")}</th>
                </tr>
              </thead>
              <tbody>
                {view.result!.boq.map((l, i) => (
                  <tr key={i}>
                    <td>{i + 1}</td>
                    <td>{l.item}</td>
                    <td>{l.model}</td>
                    <td>
                      {l.qty} {l.unit} {l.manual && <span className="tag st-sample">{t("manual.tag")}</span>}
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
