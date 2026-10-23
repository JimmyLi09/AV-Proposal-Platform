import { Diagram as D, WorkspaceView } from "./api";
import { t } from "./i18n";

const supply = (s: string) => t(`diagram.supply.${s}`);

/** 由内部明细生成的示意图。Level 1 用服务器生成的 SVG（文字已转义），Level 2 列出设备与连接，并对应明细行号。 */
export default function DiagramTab({ view, diagram }: { view: WorkspaceView; diagram: D }) {
  const rows = Object.fromEntries((view.result?.boq ?? []).map((l, i) => [l.key, i + 1]).filter(([k]) => k));
  const rowText = (keys: string[]) => (keys.length ? t("diagram.rows", { rows: keys.map((k) => rows[k] ?? "?").join(t("common.listSep")) }) : "");
  const name = (id: string) => diagram.nodes[id]?.title ?? id;

  return (
    <>
      <section className="card">
        <h2>Level 1 · {t("diagram.l1")}</h2>
        <p className="muted">{t("diagram.l1Intro")}</p>
        {diagram.unmatched.length > 0 && (
          <p className="error">{t("diagram.unmatched", { items: diagram.unmatched.join(t("common.semicolon")) })}</p>
        )}
        <div className="svg-wrap" dangerouslySetInnerHTML={{ __html: diagram.svg }} />
      </section>

      <section className="card">
        <h2>Level 2 · {t("diagram.l2")}</h2>
        <p className="muted">{t("diagram.l2Intro")}</p>
        <div className="tiles">
          {Object.entries(diagram.nodes).map(([id, n]) => (
            <div key={id} className={`tile ${n.supply !== "boq" ? "dashed" : ""}`}>
              <div className="photo">{t("diagram.photo")}</div>
              <b>{n.title}</b>
              <div>
                {n.model} {typeof n.qty === "number" ? `× ${n.qty}` : n.qty}
              </div>
              <div className="muted small">{n.detail}</div>
              <div className="small">{n.supply === "boq" ? rowText(n.boq) : <span className="warn">{supply(n.supply)}</span>}</div>
            </div>
          ))}
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("diagram.from")}</th>
                <th>{t("diagram.to")}</th>
                <th>{t("diagram.cable")}</th>
                <th>{t("diagram.qty")}</th>
                <th>{t("diagram.line")}</th>
              </tr>
            </thead>
            <tbody>
              {diagram.links.map((l, i) => (
                <tr key={i}>
                  <td>{name(l.from)}</td>
                  <td>{name(l.to)}</td>
                  <td>{l.cable}</td>
                  <td>{l.qty}</td>
                  <td>{l.boq ? rowText([l.boq]) : supply(l.supply)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
