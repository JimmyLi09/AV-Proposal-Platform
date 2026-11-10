import { useState } from "react";
import { ManualOverride, RuleResult, send, Suggestion, WorkspaceView } from "./api";
import { CheckChip, Outcome, ResultsTable, StatusChip } from "./Calc";
import { show as showValue } from "./Confirm";
import MultiView, { MultiCalc } from "./Multi";
import ProjectionDrawings from "./Projection";
import { LoadBudget, WiringDiagram } from "./Wiring";
import { t } from "./i18n";
import { fmtDate } from "./labels";
import { productStatus } from "./Products";

const TILES: Record<string, string[]> = {
  LED: ["F4", "F2", "F3", "F10", "F5", "F6", "F7", "F9", "F11", "F12"],
  PJ: ["P2", "P3", "P4", "P5", "P7", "P8", "P9", "P11", "P14", "P12", "P15", "P16"],
};

// 05 方案配置（CR-9）：来自 04 确认的输入；推荐结果卡片（手动改要写原因）、带载预算、接线图；计算依据收在下面。
// 04 的确认值改了，顶部提示「图纸校核有更新，是否重新带入？」，不静默覆盖。
export default function DesignPage({ view, apply, onCabinet, onUse }: {
  view: WorkspaceView;
  apply: (p: Promise<WorkspaceView>) => Promise<boolean>;
  onCabinet: (id: string) => void;
  onUse: (face: string, field: string, value: number) => void; // 多面屏 S7：选定一份资料的值（改的是 04 的输入）
}) {
  const result = view.result;
  const id = view.proposal.id;
  const { pull } = view.flow;
  // 05 正在用的输入：04 改过还没带进来的，用带进来时的值
  const used = { ...view.rev.inputs, ...Object.fromEntries(pull.changed.map((c) => [c.name, c.from])) };
  const post = (path: string, body: unknown = {}) => apply(send<WorkspaceView>("POST", `/proposals/${id}/${path}`, body));
  return (
    <>
      <section className="card from-04">
        <span className="tag ck-PASS">{t("flow.from04")}</span>{" "}
        {view.completeness && <span className={`tag ${view.completeness.grade === "A" ? "ck-PASS" : "st-sample"}`}>
          {t("completeness.grade", { grade: view.completeness.grade })}</span>}{" "}
        <span className="muted">{view.input_defs.filter((d) => ["pixel_pitch_mm", "width_mm", "height_mm", "wall_width_mm", "wall_height_mm", "viewing_distance_m", "nearest_viewing_m"]
          .includes(d.name) && used[d.name] !== undefined).map((d) => `${d.label} ${showValue(used[d.name])}`).join(" · ")}</span>
        {pull.changed.length > 0 && !view.readonly && (
          <div className="warn pull">
            {t("flow.pullAsk", { what: pull.changed.map((c) => `${c.label} ${showValue(c.to)}`).join(t("common.listSep")) })}
            {pull.ready ? (
              <span className="row tight">
                <button className="btn-primary small" onClick={() => post("pull")}>{t("flow.pull")}</button>
                <button className="btn-outline small" onClick={() => post("keep")}>{t("flow.keep")}</button>
              </span>
            ) : <span className="small"> {t("flow.pullLater")}</span>}
          </div>
        )}
      </section>
      {!result ? <section className="card"><p className="muted">{t("flow.noResult")}</p></section>
        : result.multi ? <MultiView view={view} onUse={onUse} />
        : (
          <>
            <Recommendation view={view} onCabinet={onCabinet} onLibrary={() => post("upgrade", { parts: ["library"] })}
              onView={(v) => apply(Promise.resolve(v))} />
            {view.proposal.business_line === "LED" && <LoadBudget view={view} onRules={() => post("upgrade", { parts: ["rules"] })} />}
            {view.drawing && <WiringDiagram view={view} drawing={view.drawing} />}
          </>
        )}
      {/* 投影：05 就能看平面机位图（P20 转角冲突阻断时还进不了 06）；和 06 的是同一张 */}
      {result && view.projection && <ProjectionDrawings view={view} kinds={["plan"]} title="pj.planTitle" intro="pj.planIntro" />}
      {result && (
        <details className="card">
          <summary><b>{t("ws.tabs.calc")}</b> <span className="muted small">{t("ws.calcIntro")}</span></summary>
          {result.multi ? <MultiCalc view={view} /> : <ResultsTable base={result} label={view.rules_version} />}
        </details>
      )}
    </>
  );
}

function Recommendation({ view, onCabinet, onLibrary, onView }: {
  view: WorkspaceView;
  onCabinet: (id: string) => void;
  onLibrary: () => void;
  onView: (v: WorkspaceView) => void;
}) {
  const result = view.result!;
  const rec = result.recommendation;
  const byId = Object.fromEntries(result.rules.map((r) => [r.id, r])) as Record<string, RuleResult>;
  const value = (rid: string, name: string) => byId[rid]?.lines.find((l) => l.name === name)?.value as string | undefined;
  const pj = view.proposal.business_line === "PJ";
  const sample = [rec.cabinet?.sample, ...result.rules.filter((r) => ["F11", "F13", "P3", "P11"].includes(r.id)).map((r) => r.status === "sample")].some(Boolean);
  const checks = result.rules.filter((r) => r.check);
  const blocked = !!rec.block || checks.some((r) => r.check === "BLOCK");

  return (
    <>
      <section className="card">
        <h2>{t("ws.tabs.rec")}</h2>
        {view.overrides.length > 0 && <ManualList items={view.overrides} />}
        {rec.missing.length > 0 && <p className="warn">{t("ws.missing", { names: rec.missing.join(", ") })}</p>}
        {rec.block && (
          <p className="error">
            {rec.block} <a href="#/products">{t("nav.products")} →</a>
          </p>
        )}
        {rec.cabinet && (
          <div className="row">
            <label className="row tight">
              {t(pj ? "ws.projector" : "ws.cabinet")}
              <select aria-label={t(pj ? "ws.projector" : "ws.cabinet")} value={rec.cabinet.id} onChange={(e) => onCabinet(e.target.value)}>
                {rec.candidates.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.brand} {c.model}
                    {t("common.paren", { x: productStatus(c.status) })}
                  </option>
                ))}
              </select>
            </label>
            {pj ? (
              <span>
                · {t("ws.lens")}
                {t("common.colon")}
                {value("P3", "lens") ?? "—"} · {t("ws.blender")}
                {t("common.colon")}
                {value("P11", "blender") ?? "—"}
              </span>
            ) : (
              <span>
                · {t("ws.controller")}
                {t("common.colon")}
                {value("F11", "controller") ?? "—"} · {t("ws.processor")}
                {t("common.colon")}
                {value("F13", "processor") ?? "—"}
              </span>
            )}
            {sample && <span className="tag st-sample">{t("common.sample")}</span>}
          </div>
        )}
        <p className="muted">{t("ws.fromLibrary", { version: view.library_version })}</p>
        <div className="tiles">
          {TILES[view.proposal.business_line].filter((rid) => byId[rid]).map((rid) => (
            <Tile key={rid} view={view} r={byId[rid]} names={view.overridable[rid] ?? []} onView={onView} />
          ))}
        </div>
      </section>

      {(result.suggestions ?? []).length > 0 && <Suggestions items={result.suggestions!} onAdded={onLibrary} />}

      <section className="card">
        <h2>{t("ws.checks")}</h2>
        <ul className="checks">
          {rec.block && (
            <li>
              <CheckChip check="BLOCK" /> {rec.block}
            </li>
          )}
          {checks.map((r) => (
            <li key={r.id}>
              <CheckChip check={r.check} /> {r.id} {r.title}
              {r.note && r.check !== "PASS" ? t("common.colon") + r.note : ""}
            </li>
          ))}
          {byId.F11?.check === "PASS" && byId.F11.note && (
            <li>
              <CheckChip check="NOTE" /> {byId.F11.note}
            </li>
          )}
        </ul>
        {blocked && <p className="error">{t("ws.blocked")}</p>}
      </section>
    </>
  );
}

/** 推荐页顶部：已有几项手动修改，逐项列出规则值 → 手动值 · 原因 · 修改人 · 时间（审核时同样列出）。 */
export function ManualList({ items }: { items: ManualOverride[] }) {
  return (
    <details className="warn manual-list">
      <summary>{t("manual.count", { n: items.length })}</summary>
      <ul className="plain">
        {items.map((m) => (
          <li key={m.name}>
            {m.rule} {m.title} · <s>{m.rule_display}</s> → <b>{m.display}</b> {m.unit} · {m.reason} · {m.by} · {fmtDate(m.at)}
          </li>
        ))}
      </ul>
    </details>
  );
}

/** 推荐卡片：显示规则结果；可以手动改（新值 + 原因，原因必填），改过的标「手动」、规则值划掉，可恢复。 */
function Tile({ view, r, names, onView }: { view: WorkspaceView; r: RuleResult; names: string[]; onView: (v: WorkspaceView) => void }) {
  const lines = names.map((n) => r.lines.find((l) => l.name === n)).filter((l) => l !== undefined);
  const [draft, setDraft] = useState<Record<string, string> | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const manual = lines.filter((l) => l.manual);
  const why = (name: string) => view.overrides.find((m) => m.name === name)?.reason;

  async function save(values: Record<string, number | null>, text = "") {
    setError("");
    try {
      onView(await send<WorkspaceView>("PUT", `/proposals/${view.proposal.id}/overrides`, { values, reason: text }));
      setDraft(null);
      setReason("");
    } catch (err) {
      setError((err as Error).message);
    }
  }
  const edit = () => setDraft(Object.fromEntries(lines.map((l) => [l.name, String(l.value ?? "")])));
  const values = () => Object.fromEntries(Object.entries(draft!).map(([k, v]) => [k, v === "" ? null : Number(v)]));

  return (
    <div className={`tile ${manual.length ? "manual" : ""}`}>
      <div className="muted small">{r.title}</div>
      <div className="tile-value">
        <Outcome r={r} />
      </div>
      {manual.map((l) => (
        <div key={l.name} className="small">
          {t("manual.rule")} <s>{l.rule_display}</s> · {why(l.name)}
        </div>
      ))}
      <div className="mono small muted">{r.trace}</div>
      <div className="small">
        {r.id} · {view.rules_version} <StatusChip status={r.status} />
      </div>
      {draft ? (
        <div className="tile-edit">
          {lines.map((l) => (
            <label key={l.name} className="row tight">
              <span className="mono small">{l.name}</span>
              <input type="number" step="any" min="0" className="num" aria-label={`${r.id} ${l.name}`} value={draft[l.name]}
                onChange={(e) => setDraft({ ...draft, [l.name]: e.target.value })} />
            </label>
          ))}
          <input aria-label={t("manual.reason")} placeholder={t("manual.reasonHint")} value={reason} onChange={(e) => setReason(e.target.value)} />
          <div className="row tight">
            <button className="btn-primary small" disabled={!reason.trim()} onClick={() => save(values(), reason)}>
              {t("common.save")}
            </button>
            <button className="btn-link" onClick={() => setDraft(null)}>
              {t("common.cancel")}
            </button>
          </div>
        </div>
      ) : (
        names.length > 0 && lines.length > 0 && (
          <div className="row tight">
            <button className="btn-link" onClick={edit}>
              {t("manual.edit")}
            </button>
            {manual.length > 0 && (
              <button className="btn-link" onClick={() => save(Object.fromEntries(manual.map((l) => [l.name, null])))}>
                {t("boq.restore")}
              </button>
            )}
          </div>
        )
      )}
      {error && <p className="error small">{error}</p>}
    </div>
  );
}

function Suggestions({ items, onAdded }: { items: Suggestion[]; onAdded: () => void }) {
  const [error, setError] = useState("");
  async function add(id: string) {
    setError("");
    try {
      await send("POST", "/products/LED/reference", { id });
      onAdded(); // 再把这个方案的产品库升级到刚生成的版本（建项时绑定的版本不会自己变，CR-9）
    } catch (err) {
      setError((err as Error).message);
    }
  }
  return (
    <section className="card">
      <h2>{t("ws.suggested")}</h2>
      <p className="muted">{t("ws.suggestedIntro")}</p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t("ws.model")}</th>
              <th>{t("ws.load")}</th>
              <th>{t("ws.ports")}</th>
              <th>{t("ws.verdict")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((s) => (
              <tr key={s.id}>
                <td className="strong">
                  {s.model} <span className="tag st-sample">{t("ws.checkDatasheet")}</span> {s.remark && <span className="muted small">{s.remark}</span>}
                </td>
                <td>
                  {s.capacity_px / 1e6} MP · {t("ws.loadPct", { pct: s.load_pct })}
                </td>
                <td>
                  {s.ports_used} / {s.ports}
                </td>
                <td>
                  {s.status === "no" ? <span className="error">{s.label + t("common.colon") + s.reason}</span>
                    : <span className={`tag ${s.status === "recommended" ? "ck-PASS" : ""}`}>{s.label}</span>}
                  {s.note && <span className="tag ck-NOTE">{s.note}</span>}
                </td>
                <td>
                  {s.status !== "no" && (
                    <button className="btn-outline small" onClick={() => add(s.id)}>
                      {t("ws.addToLibrary")}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {error && <p className="error">{error}</p>}
    </section>
  );
}
