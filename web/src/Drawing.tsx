import { MouseEvent, useEffect, useState } from "react";
import { api, Drawing, send, WorkspaceView } from "./api";
import { CheckChip } from "./Calc";
import { lang, t } from "./i18n";

const LAYERS = ["id", "size", "power", "data", "dim", "note"];
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
    fetch(`/api/proposals/${id}/drawing.svg?lang=${lang()}`).then((r) => r.text()).then(setSvg); // 页面上的图跟界面语言
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
        <h2>{t("drawing.title")}</h2>
        <p className="muted">{t("drawing.intro")}</p>
        <div className="row">
          <span className="muted small">
            {t("drawing.layers")}
            {t("common.colon")}
          </span>
          {LAYERS.map((k) => (
            <button key={k} className={`pill ${hidden.includes(k) ? "" : "active"}`}
              onClick={() => setHidden(hidden.includes(k) ? hidden.filter((x) => x !== k) : [...hidden, k])}>
              {t(`drawing.layer.${k}`)}
            </button>
          ))}
        </div>
        <div className="row">
          <button className={mode === "power" ? "btn-primary" : "btn-outline"} onClick={() => setMode(mode === "power" ? null : "power")}>
            {t("drawing.adjustPower")}
          </button>
          <button className={mode === "data" ? "btn-primary" : "btn-outline"} onClick={() => setMode(mode === "data" ? null : "data")}>
            {t("drawing.adjustData")}
          </button>
          <button className="btn-link" disabled={!d.manual.power && !d.manual.data} onClick={reset}>
            {t("drawing.reset")}
          </button>
          {mode && <span className="muted small">{t(mode === "power" ? "drawing.hintPower" : "drawing.hintData")}</span>}
        </div>
        <p className={over ? "error-banner" : "ok-banner"}>
          {over
            ? t("drawing.over", { n: over })
            : t("drawing.ok", { kw: d.circuit_cap_w / 1000, px: d.cable_cap_px.toLocaleString() })
              + (d.manual.power + d.manual.data ? t("drawing.manualCount", { n: d.manual.power + d.manual.data }) : "")}
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
            {t("drawing.circuits")} · ≤ {d.circuit_cap_w / 1000} kW
          </h3>
          <ul className="plain">
            {d.circuits.map((c) => (
              <li key={c.no} className={c.over ? "error" : ""}>
                {t("drawing.circuit", { no: c.no })} · {t("drawing.boxes", { n: c.cabinets })} · {c.watts} W · {c.amps} A
                {c.over ? ` · ${t("drawing.overload")}` : ""}
              </li>
            ))}
            <li className="muted">
              {t("drawing.circuit", { no: d.circuits.length + 1 })} · {t("drawing.reserved")}
            </li>
          </ul>
        </section>
        <section className="card">
          <h3>
            {t("drawing.cables")} · ≤ {d.cable_cap_px.toLocaleString()} px
          </h3>
          <ul className="plain">
            {d.cables.map((c) => (
              <li key={c.no} className={c.over ? "error" : ""}>
                {t("drawing.cable", { no: circled(c.no) })} · {t("drawing.boxes", { n: c.cabinets })} · {c.px.toLocaleString()} px
                {c.over ? ` · ${t("drawing.overload")}` : ""}
              </li>
            ))}
            <li className="muted">
              {t("drawing.cable", { no: circled(d.cables.length + 1) })} · FOR SPARE · {t("drawing.spare")}
            </li>
          </ul>
        </section>
      </div>

      <section className="card">
        <h3>{t("drawing.export")}</h3>
        <div className="row">
          <a className="btn-outline" href={file("drawing.svg")}>SVG</a>
          <a className="btn-outline" href={file("drawing.dxf")}>DXF</a>
          {dwg ? <a className="btn-outline" href={file("drawing.dwg")}>DWG</a>
            : <button className="btn-outline" disabled title={t("drawing.dwgHint")}>{t("drawing.dwgOff")}</button>}
          <a className="btn-outline" href={file("cabinets.xlsx")}>{t("drawing.excel")}</a>
          <a className="btn-outline" href={file("drawing.pdf?lang=zh")}>{t("drawing.pdfZh")}</a>
          <a className="btn-outline" href={file("drawing.pdf?lang=en")}>{t("drawing.pdfEn")}</a>
        </div>
        <p className="muted small">
          {t("drawing.exportNote")}
          {dwg ? "" : t("drawing.noOda")}
        </p>
      </section>

      <section className="card">
        <h3>{t("ws.tabs.calc")}</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("boq.item")}</th>
                <th>{t("drawing.formula")}</th>
                <th>{t("calc.result")}</th>
                <th>{t("calc.rule")}</th>
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
