import { Diagram as D, WorkspaceView } from "./api";

const SUPPLY: Record<string, string> = { owner: "业主提供", included: "随设备附带", missing: "未选出" };

/** 由 BOQ 生成的示意图。Level 1 用服务器生成的 SVG（文字已转义），Level 2 列出设备与连接，并对应 BOQ 行号。 */
export default function DiagramTab({ view, diagram }: { view: WorkspaceView; diagram: D }) {
  const rows = Object.fromEntries((view.boq?.lines ?? []).map((l, i) => [l.key, i + 1]).filter(([k]) => k));
  const rowText = (keys: string[]) => (keys.length ? `BOQ 第 ${keys.map((k) => rows[k] ?? "?").join("、")} 行` : "");
  const name = (id: string) => diagram.nodes[id]?.title ?? id;

  return (
    <>
      <section className="card">
        <h2>
          Level 1 · Concept diagram <span className="zh">概念图</span>
        </h2>
        <p className="muted">由 BOQ 生成：信号从左到右，电源来自下方的配电箱。虚线框是业主提供的设备，不进 BOQ。</p>
        {diagram.unmatched.length > 0 && <p className="error">图上有设备在 BOQ 里找不到：{diagram.unmatched.join("；")}</p>}
        <div className="svg-wrap" dangerouslySetInnerHTML={{ __html: diagram.svg }} />
      </section>

      <section className="card">
        <h2>
          Level 2 · Schematic <span className="zh">原理图</span>
        </h2>
        <p className="muted">型号和数量取自产品库和 BOQ，每条连接都标出线缆和对应的 BOQ 行。Level 3 施工图是下一版（B 模式）。</p>
        <div className="tiles">
          {Object.entries(diagram.nodes).map(([id, n]) => (
            <div key={id} className={`tile ${n.supply !== "boq" ? "dashed" : ""}`}>
              <div className="photo">产品库照片</div>
              <b>{n.title}</b>
              <div>
                {n.model} {typeof n.qty === "number" ? `× ${n.qty}` : n.qty}
              </div>
              <div className="muted small">{n.detail}</div>
              <div className="small">{n.supply === "boq" ? rowText(n.boq) : <span className="warn">{SUPPLY[n.supply]}</span>}</div>
            </div>
          ))}
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>From 起点</th>
                <th>To 终点</th>
                <th>Cable 线缆</th>
                <th>Qty 数量</th>
                <th>BOQ line BOQ 行</th>
              </tr>
            </thead>
            <tbody>
              {diagram.links.map((l, i) => (
                <tr key={i}>
                  <td>{name(l.from)}</td>
                  <td>{name(l.to)}</td>
                  <td>{l.cable}</td>
                  <td>{l.qty}</td>
                  <td>{l.boq ? rowText([l.boq]) : SUPPLY[l.supply]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
