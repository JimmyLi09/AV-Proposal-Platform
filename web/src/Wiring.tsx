import { useEffect, useState } from "react";
import { api, Drawing, RuleResult, RuleVersion, send, WorkspaceView, revQuery } from "./api";
import { optionLabel } from "./Calc";
import { lang, t } from "./i18n";

// 带载预算左边的参数顺序：先电源（空开、电压、负载系数、线径、载流、串接），再网线，最后接线方式
const ORDER = ["mcb_a", "mains_v", "load_factor", "power_cable_mm2", "ampacity_1_5_mm2", "ampacity_2_5_mm2", "ampacity_4_mm2",
  "chain_max", "px_per_data_cable", "data_grouping", "spare_data_cables", "wiring_orientation", "power_route", "data_route"];

const rule = (view: WorkspaceView, id: string) => view.result?.rules.find((r) => r.id === id);
const shown = (v: unknown) => (typeof v === "string" ? optionLabel(v) : typeof v === "number" && v >= 10000 ? v.toLocaleString("en-US") : String(v ?? "—"));

// 带载预算（CR-10 / CR-11）：左边参数和来源（绿色已定，黄色待确认或示例值），右边逐行列出 F6 回路和 F9 网线怎么算出来的。
// CR-9：参数可以直接改，「应用」后另存一个新的规则版本，这个方案的草稿升级到它（onRules）；已锁定的版本不受影响。
export function LoadBudget({ view, onRules }: { view: WorkspaceView; onRules?: () => Promise<boolean> }) {
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const rules = ["F6", "W1", "F9"].map((id) => rule(view, id)).filter((r): r is RuleResult => !!r);
  if (!rules.length) return null;
  const params = new Map(rules.flatMap((r) => r.params).map((p) => [p.name, p]));
  const names = [...ORDER.filter((n) => params.has(n)), ...[...params.keys()].filter((n) => !ORDER.includes(n))];
  const editable = !!onRules && !view.readonly;
  const changed = Object.entries(edits).filter(([n, v]) => v !== String(params.get(n)?.value ?? ""));

  async function save() {
    setError("");
    try {
      const latest = await api<RuleVersion>(`/rules/${view.proposal.business_line}`);
      const content = structuredClone(latest.content);
      for (const p of content.params) {
        const v = edits[p.name];
        if (v !== undefined) p.value = typeof p.value === "string" || (p.options && typeof p.options[0] === "string") ? v : Number(v);
      }
      await send("POST", `/rules/${view.proposal.business_line}`, { base_id: latest.id, content,
        reason: t("wiring.editReason", { project: view.project.name, proposal: view.proposal.name }) });
      if (await onRules!()) setEdits({});
    } catch (err) {
      setError((err as Error).message);
    }
  }
  return (
    <section className="card">
      <h2>{t("wiring.budgetTitle")}</h2>
      <p className="muted">{t("wiring.budgetIntro")}</p>
      <div className="grid2 budget">
        <div>
          <h3>{t("wiring.params")}</h3>
          <ul className="plain">
            {names.map((n) => {
              const p = params.get(n)!;
              const opts = p.options;
              const value = edits[n] ?? String(p.value ?? "");
              const set = (v: string) => setEdits({ ...edits, [n]: v });
              return (
                <li key={n} className={p.status === "set" ? "param-set" : "param-open"}>
                  <span className="grow">{p.label}</span>{" "}
                  {!editable ? <b>{shown(p.value)}</b> : opts ? (
                    <select aria-label={p.label} value={value} onChange={(e) => set(e.target.value)}>
                      {opts.map((o) => <option key={String(o)} value={String(o)}>{shown(o)}</option>)}
                    </select>
                  ) : <input type="number" step="any" className="num" aria-label={p.label} value={value} onChange={(e) => set(e.target.value)} />}{" "}
                  <span className="muted">{p.unit}</span>
                  {p.source && <div className="small muted">{p.source}</div>}
                </li>
              );
            })}
          </ul>
          {editable && changed.length > 0 && (
            <div className="row tight">
              <button className="btn-primary small" onClick={save}>{t("wiring.applyParams", { n: changed.length })}</button>
              <button className="btn-link" onClick={() => setEdits({})}>{t("common.cancel")}</button>
            </div>
          )}
          {error && <p className="error small">{error}</p>}
          <p className="small muted">{t(editable ? "wiring.paramsNote" : "wiring.paramsReadonly")} <a href="#/rules/LED">{t("wiring.editParams")}</a></p>
        </div>
        <div>
          <h3>{t("wiring.calc")}</h3>
          {rules.filter((r) => r.id !== "W1").map((r) => (
            <div key={r.id} className="budget-rule">
              <div className="strong">{r.id} {r.title} · {r.display}</div>
              {r.missing.length > 0 && <div className="small error">{t("wiring.missing", { names: r.missing.join(", ") })}</div>}
              {r.lines.map((ln) => (
                <div key={ln.name} className={`mono small ${ln.manual ? "manual" : ""}`}>
                  {/^\w+$/.test(ln.expr ?? "") ? t(`wiring.from.${ln.expr}`) : ln.substituted ?? ln.name} = {ln.manual ? ln.rule_display : ln.display} {ln.unit}
                  {ln.manual ? ` → ${t("wiring.manual", { v: ln.display })}` : ""}
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/** 接线示意图（CR-11）：和图纸、DXF、BOQ 用同一份 W1 结果；可以只看电源或只看网线。 */
export function WiringDiagram({ view, drawing: d }: { view: WorkspaceView; drawing: Drawing }) {
  const [svg, setSvg] = useState("");
  const [show, setShow] = useState<"both" | "power" | "data">("both");
  useEffect(() => {
    fetch(`/api/proposals/${view.proposal.id}/wiring.svg?lang=${lang()}${revQuery(view, "&")}`).then((r) => r.text()).then(setSvg);
  }, [view.proposal.id, d]);
  const w1 = rule(view, "W1");
  const param = (n: string) => w1?.params.find((p) => p.name === n)?.value;
  const ports = rule(view, "F11")?.lines.find((ln) => ln.name === "ports")?.value;
  const blocks = d.checks.filter((c) => c.check === "BLOCK");
  return (
    <section className="card">
      <h2>{t("wiring.title")}</h2>
      <div className="row tight">
        {(["both", "power", "data"] as const).map((k) => (
          <button key={k} className={`pill ${show === k ? "active" : ""}`} onClick={() => setShow(k)}>
            {t(`wiring.show.${k}`)}
          </button>
        ))}
      </div>
      {blocks.length > 0 && (
        <div className="error-banner">
          {blocks.map((c, i) => <div key={i}>{c.text}</div>)}
        </div>
      )}
      <div className={`wiring-wrap ${show === "power" ? "hide-data" : show === "data" ? "hide-power" : ""}`}
        dangerouslySetInnerHTML={{ __html: svg }} />
      <ul className="plain small">
        <li>{t("wiring.powerSummary", { circuits: d.circuits.length, spare: d.spare_circuits, n: d.power_jumpers, m: d.power_jumper_m })}</li>
        <li>{t("wiring.dataSummary", { runs: d.cables.length, spare: d.spare_cables, n: d.data_jumpers, m: d.data_jumper_m,
          ports: ports === undefined ? "—" : String(ports) })}</li>
        <li>{t("wiring.routes", { orientation: shown(param("wiring_orientation")), power: shown(param("power_route")),
          data: shown(param("data_route")), grouping: shown(param("data_grouping")) })}</li>
        <li className="muted">{t("wiring.synced")}</li>
      </ul>
    </section>
  );
}
