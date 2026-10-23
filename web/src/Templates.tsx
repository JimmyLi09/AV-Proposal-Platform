import { useEffect, useState } from "react";
import { api, send, TemplateContent, TemplateRow, TemplateVersion, Version } from "./api";
import { nextVersion } from "./Calc";
import { t } from "./i18n";
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
    const v = await api<TemplateVersion>(`/templates/${LINE}`);
    setSaved(v);
    setDraft(structuredClone(v.content));
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
        <h1>{t("nav.templates")}</h1>
        <span className="tag">LED · {t("templates.tag", { version: saved.version })}</span>
      </div>

      <section className="card">
        <h2>{t("templates.boq")}</h2>
        <p className="muted">{t("templates.intro")}</p>
        <label className="row tight">
          {t("boq.group")}
          <input className="wide" aria-label={t("boq.group")} value={draft.boq.group}
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
                <th>{t("templates.description")}</th>
                <th>{t("diagram.qty")}</th>
                <th>{t("boq.unit")}</th>
                <th>{t("templates.noteSource")}</th>
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
                    <input className="wide strong" aria-label={t("boq.rowField", { no: i + 1, field: t("boq.description") })} value={r.title} onChange={(e) => setRow(i, { title: e.target.value })} />
                    <textarea aria-label={t("boq.rowField", { no: i + 1, field: t("boq.specs") })} rows={Math.max(1, r.specs.length)} placeholder={t("boq.specsHint")}
                      value={r.specs.join("\n")} onChange={(e) => setRow(i, { specs: e.target.value.split("\n") })} />
                  </td>
                  <td>
                    <input list="value-names" className="num" aria-label={t("boq.rowField", { no: i + 1, field: t("diagram.qty") })} value={String(r.qty)}
                      onChange={(e) => setRow(i, { qty: isNumber(e.target.value) ? Number(e.target.value) : e.target.value })} />
                  </td>
                  <td>
                    <select aria-label={t("boq.rowField", { no: i + 1, field: t("boq.unit") })} value={r.unit} onChange={(e) => setRow(i, { unit: e.target.value })}>
                      {saved.units.map((u) => (
                        <option key={u}>{u}</option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input aria-label={t("boq.rowField", { no: i + 1, field: t("templates.note") })} placeholder={t("templates.noteHint")} value={r.note ?? ""} onChange={(e) => setRow(i, { note: e.target.value })} />
                    <input aria-label={t("boq.rowField", { no: i + 1, field: t("confirm.source") })} placeholder={t("templates.sourceHint")} value={r.source ?? ""} onChange={(e) => setRow(i, { source: e.target.value })} />
                  </td>
                  <td className="nowrap">
                    <button className="btn-link" disabled={i === 0} onClick={() => move(i, -1)} aria-label={t("templates.up", { no: i + 1 })}>↑</button>
                    <button className="btn-link" disabled={i === rows.length - 1} onClick={() => move(i, 1)} aria-label={t("templates.down", { no: i + 1 })}>↓</button>
                    <button className="btn-link" onClick={() => setRows(rows.filter((_, j) => j !== i))}>{t("common.remove")}</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="row">
          <button className="btn-outline" onClick={() => setRows([...rows, { key: newKey(rows), title: "", specs: [], qty: 1, unit: "lot", note: "", source: "" }])}>
            {t("boq.addLine")}
          </button>
        </div>
        <details>
          <summary className="small">{t("templates.names", { n: saved.names.length })}</summary>
          <p className="mono small">{saved.names.map((n) => `{${n}}`).join("  ")}</p>
        </details>
      </section>

      <section className="card">
        <h2>{t("versions.title")}</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("versions.version")}</th>
                <th>{t("versions.date")}</th>
                <th>{t("versions.by")}</th>
                <th>{t("versions.reason")}</th>
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
        <b>{dirty ? t("versions.unsaved") : t("templates.nothingToSave")}</b>
        {dirty && (
          <>
            <input aria-label={t("versions.reason")} placeholder={t("versions.reasonHint")} value={reason} onChange={(e) => setReason(e.target.value)} />
            <button className="btn-outline" onClick={() => setDraft(structuredClone(saved.content))}>
              {t("versions.discard")}
            </button>
          </>
        )}
        <button className="btn-primary" disabled={!dirty || !reason.trim()} onClick={save}>
          {t("templates.saveAs", { version: nextVersion(saved.version) })}
        </button>
        {error && <span className="error">{error}</span>}
      </div>
    </>
  );
}
