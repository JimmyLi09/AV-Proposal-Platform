import { useEffect, useState } from "react";
import { api, DeckSettings, RevCompare, send, WorkspaceView } from "./api";
import { lang as currentLang, t, tOr } from "./i18n";
import { fmtDate } from "./labels";
import { ManualList } from "./Workspace";

// 07 审批与导出（CR-9）：只有正式版本能提交（草稿先在 05 / 06 保存）；批准（可以自审，记录批准人和时间）/ 退回（必须写意见）；
// 再次提交会替换还在等待的那条。显示和上一版相比的差异。导出：语言只选一次，一排按钮；没批准只出 DRAFT 草稿。
export default function ReviewTab({ view, onApply, onOpenRev }: {
  view: WorkspaceView;
  onApply: (p: Promise<WorkspaceView>) => Promise<boolean>;
  onOpenRev: (rev: number | null) => void;
}) {
  const id = view.proposal.id;
  const [note, setNote] = useState("");
  const post = (path: string, body: unknown = {}) => onApply(send<WorkspaceView>("POST", `/proposals/${id}/${path}`, body));
  const latest = view.viewing_latest;
  const { flow } = view;
  const formal = view.revisions.find((r) => !r.draft);
  const waiting = view.revisions.find((r) => r.status === "review");
  const lastNote = [...view.history].reverse().find((h) => h.action === "send_back")?.note ?? "";
  const hint = !latest ? "" : waiting ? t("review.hintPending")
    : formal?.status === "approved" && !flow.dirty ? t("review.hintApproved", { v: `v${formal.rev_no + 1}` })
    : flow.dirty || !formal ? t("review.hintDraft")
    : formal.returned ? t("review.hintReturned", { note: lastNote })
    : t("review.hintReady");
  const canSubmit = latest && !flow.dirty && !!formal && !["review", "approved"].includes(formal.status) && view.blockers.length === 0;

  return (
    <>
      <section className="card">
        <h2>07 · {t("flow.steps.07")}</h2>
        <p>
          <span className={`tag ${formal?.status === "approved" ? "ck-PASS" : waiting ? "st-review" : ""}`}>{flow.version}</span>
          {view.reviewer && view.reviewed_at && (
            <span className="muted"> · {t("review.approvedBy", { name: view.reviewer, date: fmtDate(view.reviewed_at) })}</span>
          )}
        </p>
        {hint && <p className="muted">{hint}</p>}
        {view.locked && (
          <p className="muted small">
            {t("review.lockedVersions", {
              rules: view.locked.rules_version, library: view.locked.library_version, template: view.locked.template_version,
            })}
          </p>
        )}
        {!view.snapshot_ok && <p className="error">{t("review.snapshotChanged")}</p>}

        {latest && <Diff view={view} />}

        {latest && !waiting && formal?.status !== "approved" && (
          view.blockers.length > 0 && !flow.dirty ? (
            <div className="warn">
              <b>{t("review.blockers")}</b>
              <ul className="plain">{view.blockers.map((b) => <li key={b}>{b}</li>)}</ul>
            </div>
          ) : (
            <div className="row">
              <button className="btn-primary" disabled={!canSubmit} onClick={() => post("submit")}>
                {t("review.submitV", { v: formal && !flow.dirty ? `v${formal.rev_no}` : flow.next_version })}
              </button>
            </div>
          )
        )}

        {latest && waiting && (
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
              <span className="muted small">{t("review.sendBackHint")}</span>
            </div>
          </div>
        )}

        {view.history.length > 0 && (
          <details>
            <summary>{t("review.history")}</summary>
            <ul className="plain">
              {view.history.map((h, i) => (
                <li key={i}>
                  {tOr(`review.actions.${h.action}`, h.action)} · {h.by} · {fmtDate(h.at)}{h.note && ` · ${h.note}`}
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>

      <Exports view={view} />
      <details className="card">
        <summary><b>{t("review.deck")}</b> <span className="muted small">{t("review.deckIntro")}</span></summary>
        <Deck view={view} onApply={onApply} />
      </details>
      <details className="card">
        <summary><b>{t("review.revisions")}</b></summary>
        <Revisions view={view} onOpenRev={onOpenRev} />
      </details>
    </>
  );
}

/** 和上一版相比：有上一个正式版本就逐项对比（输入、回路、BOQ）；第一版列出和规则值不一样的手动改动。 */
function Diff({ view }: { view: WorkspaceView }) {
  const formals = view.revisions.filter((r) => !r.draft);
  const current = view.flow.dirty ? view.rev.rev_no : formals[0]?.rev_no;
  const prev = formals.find((r) => r.rev_no < (current ?? 0));
  const [cmp, setCmp] = useState<RevCompare | null>(null);
  useEffect(() => {
    if (prev && current) api<RevCompare>(`/proposals/${view.proposal.id}/compare?a=${prev.rev_no}&b=${current}`).then(setCmp);
  }, [prev?.rev_no, current, view]);
  const manualBoq = view.boq?.manual.length ?? 0;
  return (
    <>
      <h3>{prev ? t("review.diffWith", { v: `v${prev.rev_no}` }) : t("review.diffFirst")}</h3>
      {prev ? (cmp && <CompareTable cmp={cmp} />) : (
        <>
          {view.overrides.length > 0 ? <ManualList items={view.overrides} /> : <p className="muted small">{t("review.noManual")}</p>}
          {manualBoq > 0 && <p className="muted small">{t("review.boqManual", { n: manualBoq })}</p>}
        </>
      )}
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
      {revs.map((r) => <option key={r.rev_no} value={r.rev_no}>{r.label}</option>)}
    </select>
  );

  return (
    <>
      <table>
        <thead>
          <tr>
            <th>{t("review.version")}</th><th>{t("common.status")}</th><th>{t("review.author")}</th><th>{t("review.reviewer")}</th>
            <th>{t("review.versions")}</th><th />
          </tr>
        </thead>
        <tbody>
          {revs.map((r) => (
            <tr key={r.rev_no}>
              <td>{r.label}</td>
              <td>{r.draft ? t("review.draft") : tOr(`status.${r.status}`, r.status)}{r.saved_by && ` · ${t("review.savedBy", { name: r.saved_by })}`}</td>
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
    </>
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
        <tr><th>{t("review.item")}</th><th>v{cmp.a}</th><th>v{cmp.b}</th></tr>
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

type LockedFile = { kind: string; lang: string; name: string; by: string | null; at: string };

// 导出（CR-9 · 07）：语言只选一次（中文 / English / 中英对照），然后一排按钮。
// 草稿和最近的正式版本一样时导出那个正式版本；没批准的是带 DRAFT 的草稿；批准后第一次导出的文件存档，之后给同一份。
function Exports({ view }: { view: WorkspaceView }) {
  const [lang, setLang] = useState<"zh" | "en" | "bi">(currentLang());
  const formal = view.revisions.find((r) => !r.draft);
  const rev = !view.viewing_latest || view.flow.dirty || !formal ? view.rev.rev_no : formal.rev_no;
  const approved = view.revisions.find((r) => r.rev_no === rev)?.status === "approved";
  const base = `/api/proposals/${view.proposal.id}`;
  const one = lang === "bi" ? "en" : lang;
  const items: [string, string, boolean][] = [
    ["pdf", `${base}/proposal.pdf?lang=${one}&rev=${rev}`, lang !== "bi"],
    ["docx", `${base}/proposal.docx?lang=${one}&rev=${rev}`, lang !== "bi"],
    ["pptx", `${base}/proposal.pptx?lang=${lang}&rev=${rev}`, true],
    ["boards", `${base}/proposal.boards?lang=${one}&rev=${rev}`, lang !== "bi"],
    ["boq", `${base}/boq.xlsx?rev=${rev}`, true],
    ["dxf", `${base}/drawing.dxf?lang=${one}&rev=${rev}`, lang !== "bi" && !!view.drawing],
  ];
  const files = (rev === view.rev.rev_no ? view.locked?.files ?? [] : []) as LockedFile[];
  return (
    <section className="card">
      <h2>{t("review.exports")} <span className="sub">v{rev}</span></h2>
      <div className="row tight">
        <span>{t("review.lang")}</span>
        {(["zh", "en", "bi"] as const).map((l) => (
          <button key={l} className={`pill small ${lang === l ? "active" : ""}`} onClick={() => setLang(l)}>
            {t(`review.lang${l === "zh" ? "Zh" : l === "en" ? "En" : "Bi"}`)}
          </button>
        ))}
      </div>
      <div className="row">
        {items.map(([fmt, href, ok]) => ok ? <a key={fmt} className="btn-outline" href={href}>{t(`review.formats.${fmt}`)}</a>
          : <button key={fmt} className="btn-outline" disabled title={t(fmt === "dxf" && !view.drawing ? "review.noDxf" : "review.biOnly")}>
            {t(`review.formats.${fmt}`)}
          </button>)}
      </div>
      {lang === "bi" && <p className="muted small">{t("review.biOnly")}</p>}
      <p className={`small ${approved ? "ok" : "warn"}`}>{t(approved ? "review.official" : "review.draftOnly")}</p>
      {files.length > 0 && (
        <>
          <h3>{t("review.lockedFiles")}</h3>
          <ul className="plain">
            {files.map((f) => (
              <li key={f.name}>{f.name} · {f.by ?? "—"} · {fmtDate(f.at)}</li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

const COVER = ["title", "project", "project_no", "client", "location", "date"];

/** 演示稿设置：封面字段（空 = 用默认值）和要出的页；随 Rev 保存，锁定后只读。 */
function Deck({ view, onApply }: { view: WorkspaceView; onApply: (p: Promise<WorkspaceView>) => Promise<boolean> }) {
  const d: DeckSettings = view.deck;
  const [cover, setCover] = useState<Record<string, string>>(() =>
    Object.fromEntries(COVER.map((k) => [k, d.cover[k] !== d.cover_defaults[k] ? d.cover[k] : ""])));
  const [off, setOff] = useState<string[]>(d.slides.filter((s) => !s.included).map((s) => s.key));
  const save = () => onApply(send<WorkspaceView>("PUT", `/proposals/${view.proposal.id}/deck`, { cover, off }));
  return (
    <>
      <div className="form">
        {COVER.map((k) => (
          <label key={k}>
            {t(`review.cover.${k}`)}
            <input value={cover[k]} placeholder={d.cover_defaults[k]} disabled={view.readonly}
              onChange={(e) => setCover({ ...cover, [k]: e.target.value })} />
          </label>
        ))}
      </div>
      <div className="row">
        {d.slides.map((s, i) => (
          <label key={s.key} className="row tight">
            <input type="checkbox" checked={!off.includes(s.key)} disabled={s.fixed || view.readonly}
              onChange={(e) => setOff(e.target.checked ? off.filter((x) => x !== s.key) : [...off, s.key])} />
            {i + 1}. {s.title}
          </label>
        ))}
      </div>
      {!view.readonly && <button className="btn-primary" onClick={save}>{t("common.save")}</button>}
    </>
  );
}
