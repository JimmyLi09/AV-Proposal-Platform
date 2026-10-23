import { MouseEvent, useEffect, useState } from "react";
import { api, Drawing, send, WorkspaceView } from "./api";
import { CheckChip } from "./Calc";

const LAYERS: [string, string][] = [["id", "IDs 箱体编号"], ["size", "Sizes 箱体尺寸"], ["power", "Power 电源"], ["data", "Data 网线"], ["dim", "Dims 尺寸线"], ["note", "Notes 说明栏"]];
const circled = (n: number) => (n >= 1 && n <= 20 ? String.fromCharCode(0x2460 + n - 1) : String(n));

/** 拼接与线路图（CR-3）：由 F3 箱体排布、F6 回路、F9 网线自动生成；可手动调整分组（随 Rev 保存），可导出 SVG / DXF / DWG / Excel / PDF。 */
export default function DrawingTab({ view, drawing: d, onApply }: { view: WorkspaceView; drawing: Drawing; onApply: (p: Promise<WorkspaceView>) => void }) {
  const id = view.proposal.id;
  const [svg, setSvg] = useState("");
  const [hidden, setHidden] = useState<string[]>([]);
  const [mode, setMode] = useState<"power" | "data" | null>(null);
  const [dwg, setDwg] = useState(false);
  useEffect(() => {
    api<{ dwg: boolean }>("/capabilities").then((c) => setDwg(c.dwg));
  }, []);
  useEffect(() => {
    fetch(`/api/proposals/${id}/drawing.svg`).then((r) => r.text()).then(setSvg);
  }, [id, d]);

  function click(e: MouseEvent) {
    const cab = (e.target as Element).closest("[data-cab]")?.getAttribute("data-cab");
    const c = cab && d.cabinets.find((x) => x.id === cab);
    if (!mode || !c) return;
    const edits = { power: { ...d.edits.power }, data: { ...d.edits.data } };
    if (mode === "power") edits.power[c.id] = (c.circuit % d.circuits.length) + 1;
    else edits.data[c.id] = (c.cable % d.cables.length) + 1;
    onApply(send<WorkspaceView>("PUT", `/proposals/${id}/drawing`, edits));
  }
  const reset = () => {
    setMode(null);
    onApply(send<WorkspaceView>("PUT", `/proposals/${id}/drawing`, {}));
  };
  const over = d.circuits.filter((c) => c.over).length + d.cables.filter((c) => c.over).length;
  const file = (path: string) => `/api/proposals/${id}/${path}`;

  return (
    <>
      <section className="card">
        <h2>
          Drawing <span className="zh">拼接与线路图</span>
        </h2>
        <p className="muted">由 F3 箱体排布、F6 / F7 电源回路、F9 网线自动生成，可导出 DXF / DWG。编号从左下角 R1C1 开始，网线起点在左侧。</p>
        <div className="row">
          <span className="muted small">Layers 图层：</span>
          {LAYERS.map(([k, v]) => (
            <button key={k} className={`pill ${hidden.includes(k) ? "" : "active"}`}
              onClick={() => setHidden(hidden.includes(k) ? hidden.filter((x) => x !== k) : [...hidden, k])}>
              {v}
            </button>
          ))}
        </div>
        <div className="row">
          <button className={mode === "power" ? "btn-primary" : "btn-outline"} onClick={() => setMode(mode === "power" ? null : "power")}>
            Adjust power 调整电源回路
          </button>
          <button className={mode === "data" ? "btn-primary" : "btn-outline"} onClick={() => setMode(mode === "data" ? null : "data")}>
            Adjust data 调整网线
          </button>
          <button className="btn-link" disabled={!d.manual.power && !d.manual.data} onClick={reset}>
            Reset to auto 恢复自动
          </button>
          {mode && <span className="muted small">{mode === "power" ? "点箱体，把它换到下一个回路；改完立即重新校验每个回路的功率。" : "点箱体，把它换到下一根网线；改完立即重新校验每根网线的带载。"}</span>}
        </div>
        <p className={over ? "error-banner" : "ok-banner"}>
          {over
            ? `有 ${over} 处超载，已标红。这个 Rev 不能批准，改回或点「恢复自动」。`
            : `校验通过：每个回路 ≤ ${d.circuit_cap_w / 1000} kW，每根网线 ≤ ${d.cable_cap_px.toLocaleString()} px。${d.manual.power + d.manual.data ? `已手动调整 ${d.manual.power + d.manual.data} 个箱体，随 Rev 保存。` : ""}`}
        </p>
        {d.checks.filter((c) => c.check === "NOTE").map((c, i) => (
          <p key={i} className="small">
            <CheckChip check="NOTE" /> {c.text}
          </p>
        ))}
        <div className={`drawing-wrap ${mode ? "adjusting" : ""} ${hidden.map((h) => `hide-${h}`).join(" ")}`} onClick={click}
          dangerouslySetInnerHTML={{ __html: svg }} />
      </section>

      <div className="grid2">
        <section className="card">
          <h3>
            Power circuits <span className="zh">电源回路 · ≤ {d.circuit_cap_w / 1000} kW</span>
          </h3>
          <ul className="plain">
            {d.circuits.map((c) => (
              <li key={c.no} className={c.over ? "error" : ""}>
                回路 {c.no} · {c.cabinets} 箱 · {c.watts} W · {c.amps} A{c.over ? " · 超载" : ""}
              </li>
            ))}
            <li className="muted">回路 {d.circuits.length + 1} · 预留 Reserved</li>
          </ul>
        </section>
        <section className="card">
          <h3>
            Data cables <span className="zh">网线 · ≤ {d.cable_cap_px.toLocaleString()} px</span>
          </h3>
          <ul className="plain">
            {d.cables.map((c) => (
              <li key={c.no} className={c.over ? "error" : ""}>
                网线 {circled(c.no)} · {c.cabinets} 箱 · {c.px.toLocaleString()} px{c.over ? " · 超载" : ""}
              </li>
            ))}
            <li className="muted">网线 {circled(d.cables.length + 1)} · FOR SPARE 备用</li>
          </ul>
        </section>
      </div>

      <section className="card">
        <h3>
          Export <span className="zh">导出</span>
        </h3>
        <div className="row">
          <a className="btn-outline" href={file("drawing.svg")}>SVG</a>
          <a className="btn-outline" href={file("drawing.dxf")}>DXF</a>
          {dwg ? <a className="btn-outline" href={file("drawing.dwg")}>DWG</a>
            : <button className="btn-outline" disabled title="装 ODA 后可导出 DWG">DWG（需 ODA）</button>}
          <a className="btn-outline" href={file("cabinets.xlsx")}>Excel 箱体清单</a>
          <a className="btn-outline" href={file("drawing.pdf?lang=zh")}>PDF 中文</a>
          <a className="btn-outline" href={file("drawing.pdf?lang=en")}>PDF English</a>
        </div>
        <p className="muted small">
          未批准的 Rev 导出带 DRAFT 水印；文件属性写入 Rev、规则版本和产品库版本。DXF：单位 mm、1:1，图层 AVP-CABINET / AVP-CABINET-ID / AVP-POWER / AVP-DATA / AVP-DIM / AVP-NOTE，尺寸为 DIMENSION 实体。{dwg ? "" : "服务器没有装 ODA File Converter，装好后可导出 DWG。"}
        </p>
      </section>

      <section className="card">
        <h3>
          Calculation basis <span className="zh">计算依据</span>
        </h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Item 项目</th>
                <th>Formula 公式（代入数值）</th>
                <th>Result 结果</th>
                <th>Rule 规则</th>
              </tr>
            </thead>
            <tbody>
              {d.basis.map((b) => (
                <tr key={b.rule}>
                  <td>{b.item}</td>
                  <td className="mono small">{b.formula}</td>
                  <td>{b.result}</td>
                  <td>{b.rule}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
