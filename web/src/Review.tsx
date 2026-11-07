import { useState } from "react";
import { api, RevCompare, send, WorkspaceView } from "./api";
import { t, tOr } from "./i18n";
import { fmtDate, StatusTag } from "./labels";
import { ManualList } from "./Workspace";

/** 第 6 步「审核导出」：提交审核 → 批准（可自审）/ 退回；已批准的开新 Rev；Rev 列表与对比。 */
export default function ReviewTab({ view, onApply, onOpenRev }: {
  view: WorkspaceView;
  onApply: (p: Promise<WorkspaceView>) => Promise<void>;
  onOpenRev: (rev: number | null) => void;
}) {
  const id = view.proposal.id;
  const { rev } = view;
  const [note, setNote] = useState("");
  const post = (path: string, body: unknown = {}) => onApply(send<WorkspaceView>("POST", `/proposals/${id}/${path}`, body));
  const latest = view.viewing_latest;

  return (
    <>
      <section className="card">
        <h2>{t("review.title")}</h2>
        <p>
          <StatusTag status={rev.status} rev={rev.rev_no} />
          {view.reviewer && view.reviewed_at && (
            <span className="muted"> · {t("review.approvedBy", { name: view.reviewer, date: fmtDate(view.reviewed_at) })}</span>
          )}
        </p>
        {view.locked && (
          <p className="muted">
            {t("review.lockedVersions", {
              rules: view.locked.rules_version, library: view.locked.library_version, template: view.locked.template_version,
            })}
          </p>
        )}
        {!view.snapshot_ok && <p className="error">{t("review.snapshotChanged")}</p>}
        {view.overrides.length > 0 && <ManualList items={view.overrides} />}

        {latest && ["draft", "confirming", "calculated"].includes(rev.status) && (
          view.blockers.length > 0 ? (
            <div className="warn">
              <b>{t("review.blockers")}</b>
              <ul className="plain">{view.blockers.map((b) => <li key={b}>{b}</li>)}</ul>
            </div>
          ) : (
            <div className="row">
              <span className="muted">{t("review.ready")}</span>
              <button className="btn-primary" onClick={() => post("submit")}>{t("review.submit")}</button>
            </div>
          )
        )}

        {latest && rev.status === "review" && (
          <div>
            <label>
              {t("review.note")}
              <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} />
            </label>
            <div className="row">
              <button className="btn-primary" onClick={() => post("approve", { note }).then(() => setNote(""))}>{t("review.approve")}</button>
              <button className="btn-outline" disabled={!note.trim()} onClick={() => post("send-back", { note }).then(() => setNote(""))}>
                {t("review.sendBack")}
              </button>
              <span className="muted">{t("review.sendBackHint")}</span>
            </div>
          </div>
        )}

        {latest && rev.status === "approved" && (
          <div className="row">
            <span className="muted">{t("review.approvedHint")}</span>
            <button className="btn-outline" onClick={() => post("revisions").then(() => onOpenRev(null))}>{t("review.newRev")}</button>
          </div>
        )}

        {view.history.length > 0 && (
          <>
            <h3>{t("review.history")}</h3>
            <ul className="plain">
              {view.history.map((h, i) => (
                <li key={i}>
                  {tOr(`review.actions.${h.action}`, h.action)} · {h.by} · {fmtDate(h.at)}{h.note && ` · ${h.note}`}
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <Revisions view={view} onOpenRev={onOpenRev} />
    </>
  );
}

function Revisions({ view, onOpenRev }: { view: WorkspaceView; onOpenRev: (rev: number | null) => void }) {
  const revs = view.revisions;
  const [a, setA] = useState(revs.length > 1 ? revs[1].rev_no : revs[0].rev_no);
  const [b, setB] = useState(revs[0].rev_no);
  const [cmp, setCmp] = useState<RevCompare | null>(null);
  const [error, setError] = useState("");

  async function compare() {
    setError("");
    try {
      setCmp(await api<RevCompare>(`/proposals/${view.proposal.id}/compare?a=${a}&b=${b}`));
    } catch (err) {
      setError((err as Error).message);
    }
  }
  const pick = (value: number, set: (n: number) => void) => (
    <select value={value} onChange={(e) => set(Number(e.target.value))}>
      {revs.map((r) => <option key={r.rev_no} value={r.rev_no}>Rev {r.rev_no}</option>)}
    </select>
  );

  return (
    <section className="card">
      <h2>{t("review.revisions")}</h2>
      <table>
        <thead>
          <tr>
            <th>Rev</th><th>{t("common.status")}</th><th>{t("review.author")}</th><th>{t("review.reviewer")}</th>
            <th>{t("review.versions")}</th><th />
          </tr>
        </thead>
        <tbody>
          {revs.map((r) => (
            <tr key={r.rev_no}>
              <td>Rev {r.rev_no}</td>
              <td>{tOr(`status.${r.status}`, r.status)}</td>
              <td>{r.author} · {fmtDate(r.created_at)}</td>
              <td>{r.reviewer ? `${r.reviewer} · ${fmtDate(r.reviewed_at!)}` : "—"}</td>
              <td className="muted">{r.rules_version ? `${r.rules_version} · ${r.library_version} · ${r.template_version}` : t("review.notLocked")}</td>
              <td>
                {r.rev_no !== view.rev.rev_no && (
                  <button className="btn-link" onClick={() => onOpenRev(r.latest ? null : r.rev_no)}>{t("review.open")}</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {revs.length > 1 && (
        <div className="row">
          {t("review.compare")} {pick(a, setA)} ↔ {pick(b, setB)}
          <button className="btn-outline" disabled={a === b} onClick={compare}>{t("review.compareGo")}</button>
        </div>
      )}
      {error && <p className="error">{error}</p>}
      {cmp && <CompareTable cmp={cmp} />}
    </section>
  );
}

function CompareTable({ cmp }: { cmp: RevCompare }) {
  const parts: [string, { item: string; a: string; b: string; rule?: string }[]][] = [
    ["versions", cmp.versions], ["inputs", cmp.inputs], ["results", cmp.results], ["boq", cmp.boq],
  ];
  if (parts.every(([, rows]) => rows.length === 0)) return <p className="muted">{t("review.same")}</p>;
  return (
    <table>
      <thead>
        <tr><th>{t("review.item")}</th><th>Rev {cmp.a}</th><th>Rev {cmp.b}</th></tr>
      </thead>
      <tbody>
        {parts.filter(([, rows]) => rows.length > 0).flatMap(([key, rows]) => [
          <tr key={key} className="group-row"><td colSpan={3}><b>{t(`review.diff.${key}`)}</b></td></tr>,
          ...rows.map((r, i) => (
            <tr key={`${key}-${i}`}>
              <td>{r.rule ? `${r.rule} · ` : ""}{r.item}</td><td>{r.a}</td><td><b>{r.b}</b></td>
            </tr>
          )),
        ])}
      </tbody>
    </table>
  );
}
