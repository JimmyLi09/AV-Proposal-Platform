import { FaceResult, RuleResult, WorkspaceView } from "./api";
import { CheckChip, Outcome, ResultsTable } from "./Calc";
import { shapeLabel } from "./Faces";
import { t } from "./i18n";

const display = (rules: RuleResult[], id: string) => rules.find((r) => r.id === id)?.display || "—";
const faceLabel = (f: FaceResult) => (f.name && f.name !== f.id ? `${f.id} ${f.name}` : f.id);

/** 多面屏推荐（CR-7）：每面按 F1–F16 / P1–P10 单独算，再按 S1–S7 / P18–P22 合起来检查。 */
export default function MultiView({ view, onUse }: { view: WorkspaceView; onUse: (face: string, field: string, value: number) => void }) {
  const r = view.result!;
  const m = r.multi!;
  const led = view.proposal.business_line === "LED";
  const v = Object.fromEntries(r.rules.flatMap((x) => x.lines.map((l) => [l.name, l.value]))) as Record<string, number>;
  const tot = m.totals as Record<string, number> & { canvas_px?: number[] };
  const tiles: [string, string][] = !tot.canvas_px ? [] : led ? [
    [t("multi.canvas"), tot.canvas_px.join(" × ")],
    [t("multi.modules"), `${tot.modules} + ${tot.spare_modules} ${t("multi.spare")}`],
    [t("multi.area"), `${Number(tot.area_m2).toFixed(2)} ㎡`],
    [t("multi.power"), `${Number(tot.power_kw).toFixed(2)} kW`],
    [t("multi.circuits"), String(tot.circuits)],
    [t("multi.dbBoxes"), String(tot.db_boxes)],
    [t("multi.data"), String(tot.data_cables)],
    [t("multi.outputs"), String(tot.processor_outputs)],
  ] : [
    [t("multi.projectors"), String(tot.projectors)],
    [t("multi.canvas"), tot.canvas_px.join(" × ")],
    [t("multi.power"), v.power_with_margin_kw !== undefined ? `${Number(v.power_with_margin_kw).toFixed(2)} kW` : "—"],
    [t("multi.circuits"), String(v.circuits ?? "—")],
    [t("multi.cat6"), String(v.total_cat6 ?? "—")],
  ];
  const checks = r.rules.filter((x) => x.check || x.missing.length);

  return (
    <>
      {m.conflicts.length > 0 && (
        <section className="card">
          <h2>{t("multi.conflicts")}</h2>
          <p className="warn">{t("multi.conflictsIntro")}</p>
          {m.conflicts.map((c) => (
            <div key={`${c.face}${c.field}`} className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>{t("multi.faceField", { face: c.face, field: t(c.field === "width_mm" ? "faces.width" : "faces.height") })}</th>
                    <th>{t("faces.sourceKind")}</th>
                    <th>{t("faces.sourceValue")}</th>
                    <th>{t("multi.fits")}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {c.sources.map((s, i) => (
                    <tr key={i}>
                      <td>{s.src}</td>
                      <td>{t(`faces.kinds.${s.kind}`)}</td>
                      <td>{s.value}</td>
                      <td>{s.fits ? "✓" : t("multi.snap", { a: s.options[0], b: s.options[1] })}</td>
                      <td className="nowrap">
                        {(s.fits ? [s.value] : s.options).map((x) => (
                          <button key={x} className="btn-outline small" onClick={() => onUse(c.face, c.field, x)}>
                            {t("multi.use", { value: x })}
                          </button>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </section>
      )}

      <section className="card">
        <h2>
          {t("multi.title")} <span className="sub">{shapeLabel(m.shape)}</span>
        </h2>
        <p className="muted">{t(led ? "multi.introLed" : "multi.introPj")}</p>
        {tiles.length > 0 && (
          <div className="tiles">
            {tiles.map(([k, x]) => (
              <div key={k} className="tile">
                <div className="muted small">{k}</div>
                <div className="tile-value">{x}</div>
              </div>
            ))}
          </div>
        )}
        {r.faces && r.faces.length > 0 && <FaceTable faces={r.faces} led={led} />}
        {m.corners.length > 0 && (
          <ul className="plain">
            {m.corners.map((c) => (
              <li key={c.between.join("/")}>
                <CheckChip check={c.result} /> {t("multi.corner", { pair: c.between.join(" / "), m: c.distance_m.toFixed(2) })}
                {c.resolution && ` · ${c.resolution}`}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card">
        <h2>{t("multi.checks")}</h2>
        <ul className="checks">
          {checks.map((x) => (
            <li key={x.id}>
              <Outcome r={x} /> · {x.id} {x.title}
              {x.note && x.check && x.check !== "PASS" ? t("common.colon") + x.note : ""}
            </li>
          ))}
          {m.checks.map((c, i) => (
            <li key={`c${i}`}>
              <CheckChip check={c.check} /> {c.text}
            </li>
          ))}
        </ul>
        {[...checks.map((x) => x.check), ...m.checks.map((c) => c.check)].includes("BLOCK") && <p className="error">{t("ws.blocked")}</p>}
      </section>
    </>
  );
}

function FaceTable({ faces, led }: { faces: FaceResult[]; led: boolean }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          {led ? (
            <tr>
              <th>{t("faces.face")}</th>
              <th>{t("multi.size")}</th>
              <th>{t("multi.px")}</th>
              <th>{t("multi.modules")}</th>
              <th>㎡</th>
              <th>kW</th>
              <th>{t("multi.circuits")}</th>
              <th>{t("multi.dbBoxes")}</th>
              <th>{t("multi.data")}</th>
              <th>{t("ws.controller")}</th>
            </tr>
          ) : (
            <tr>
              <th>{t("faces.face")}</th>
              <th>{t("faces.width")}</th>
              <th>{t("multi.projectors")}</th>
              <th>{t("multi.lens")}</th>
              <th>{t("multi.blend")}</th>
              <th>{t("multi.px")}</th>
              <th>{t("multi.pixel")}</th>
            </tr>
          )}
        </thead>
        <tbody>
          {faces.map((f) => {
            const v = f.values;
            return led ? (
              <tr key={f.id}>
                <td className="strong">{faceLabel(f)}</td>
                <td>{f.width_mm} × {f.height_mm}</td>
                <td>{v.res_x} × {v.res_y}</td>
                <td>{v.modules}</td>
                <td>{v.area_m2 !== undefined ? Number(v.area_m2).toFixed(2) : "—"}</td>
                <td>{v.power_kw !== undefined ? Number(v.power_kw).toFixed(2) : "—"}</td>
                <td>{v.circuits}</td>
                <td>{v.db_boxes}</td>
                <td>{v.data_runs !== undefined ? `${v.data_runs} + ${v.data_cables - v.data_runs}` : "—"}</td>
                <td>{display(f.rules, "F11")}</td>
              </tr>
            ) : (
              <tr key={f.id}>
                <td className="strong">{faceLabel(f)}</td>
                <td>{f.width_mm}</td>
                <td>{v.projectors}</td>
                <td>{display(f.rules, "P3")}</td>
                <td>{display(f.rules, "P5")}</td>
                <td>{display(f.rules, "P7")}</td>
                <td>{display(f.rules, "P8")}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** 计算依据（多面屏）：合并检查和系统规则，再按面展开每面的规则结果。 */
export function MultiCalc({ view }: { view: WorkspaceView }) {
  const r = view.result!;
  return (
    <>
      <ResultsTable base={r} label={view.rules_version} />
      {(r.faces ?? []).map((f) => (
        <details key={f.id} className="face-calc">
          <summary>
            <b>{t("multi.faceRules", { face: faceLabel(f) })}</b>
          </summary>
          <ResultsTable base={{ ...r, rules: f.rules, choices: f.choices }} label={view.rules_version} />
        </details>
      ))}
    </>
  );
}
