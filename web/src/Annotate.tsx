import { MouseEvent, useEffect, useRef, useState } from "react";
import { AnnotationDoc, api, Mark, Scale, send, WorkspaceView } from "./api";

type Tool = "point" | "area" | "device" | "text" | "scale";
const TOOLS: [Tool, string][] = [["point", "Point 点"], ["area", "Area 区域"], ["device", "Device 设备"], ["text", "Text 文字"], ["scale", "Set scale 设置比例"]];
const DEFAULT_LABEL: Record<string, string> = { point: "点", area: "区域", device: "设备", text: "文字" };

/** 在客户的 PDF 或照片上标出位置。保存时服务器另存一份标注副本，原文件不会被修改。 */
export default function AnnotateTab({ view, onSaved }: { view: WorkspaceView; onSaved: () => void }) {
  const files = view.files.filter((f) => ["pdf", "jpg", "jpeg", "png"].includes(f.file_type));
  const [fileId, setFileId] = useState<number | null>(files[0]?.id ?? null);
  const [pages, setPages] = useState(1);
  const [page, setPage] = useState(1);
  const [tool, setTool] = useState<Tool>("area");
  const [marks, setMarks] = useState<Mark[]>([]);
  const [scale, setScale] = useState<Scale | null>(null);
  const [scalePts, setScalePts] = useState<{ x: number; y: number }[]>([]);
  const [drag, setDrag] = useState<{ x: number; y: number; x2: number; y2: number } | null>(null);
  const [size, setSize] = useState({ w: 1, h: 1 });
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<AnnotationDoc | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const deviceLines = (view.result?.boq ?? []).filter((l) => l.key && !l.included);

  useEffect(() => {
    if (fileId === null) return;
    api<{ pages: number }>(`/files/${fileId}/pages`).then((r) => setPages(r.pages));
  }, [fileId]);

  useEffect(() => {  // 换文件 / 换页时载入已保存的标注
    const doc = fileId === null ? null : view.rev.annotations[`${fileId}:${page}`] ?? null;
    setMarks(doc?.marks ?? []);
    setScale(doc?.scale ?? null);
    setSaved(doc);
    setScalePts([]);
  }, [fileId, page]);

  if (fileId === null) return <section className="card"><p className="muted">项目里还没有 PDF 或照片可以标注。</p></section>;

  const at = (e: MouseEvent) => {
    const r = box.current!.getBoundingClientRect();
    return { x: Math.min(Math.max((e.clientX - r.left) / r.width, 0), 1), y: Math.min(Math.max((e.clientY - r.top) / r.height, 0), 1) };
  };
  const mmPerUnit = scale ? scale.mm / Math.hypot((scale.b.x - scale.a.x) * size.w, (scale.b.y - scale.a.y) * size.h) : null;
  const areaMm = (m: Mark) => (mmPerUnit && m.type === "area" ? `≈ ${Math.round(m.w * size.w * mmPerUnit)} × ${Math.round(m.h * size.h * mmPerUnit)} mm` : "");

  function down(e: MouseEvent) {
    e.preventDefault();
    const p = at(e);
    if (tool === "area") return setDrag({ ...p, x2: p.x, y2: p.y });
    if (tool === "scale") {
      const pts = [...scalePts, p];
      if (pts.length < 2) return setScalePts(pts);
      const mm = Number(window.prompt("这两点之间的实际距离（mm）", "4480"));
      setScalePts([]);
      if (mm > 0) setScale({ a: pts[0], b: pts[1], mm });
      return;
    }
    setMarks([...marks, { type: tool, x: p.x, y: p.y, w: 0, h: 0, label: DEFAULT_LABEL[tool], note: "", boq_key: null }]);
  }
  function move(e: MouseEvent) {
    if (drag) setDrag({ ...drag, ...((p) => ({ x2: p.x, y2: p.y }))(at(e)) });
  }
  function up() {
    if (!drag) return;
    const x = Math.min(drag.x, drag.x2), y = Math.min(drag.y, drag.y2), w = Math.abs(drag.x2 - drag.x), h = Math.abs(drag.y2 - drag.y);
    if (w > 0.01 && h > 0.01) setMarks([...marks, { type: "area", x, y, w, h, label: DEFAULT_LABEL.area, note: "", boq_key: null }]);
    setDrag(null);
  }
  const edit = (i: number, patch: Partial<Mark>) => setMarks(marks.map((m, j) => (j === i ? { ...m, ...patch } : m)));

  async function save(list = marks) {
    setError("");
    try {
      const r = await send<{ annotations: Record<string, AnnotationDoc> }>("PUT", `/proposals/${view.proposal.id}/annotations`,
        { file_id: fileId, page, scale, marks: list });
      setSaved(r.annotations[`${fileId}:${page}`] ?? null);
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const file = files.find((f) => f.id === fileId)!;
  const pct = (v: number) => `${v * 100}%`;
  return (
    <section className="card">
      <h2>
        Annotate <span className="zh">标注</span>
      </h2>
      <p className="muted">在客户的 PDF 或照片上标出位置。保存时另存一份标注副本，原文件不会被修改。区域：按住拖动；比例：在已知长度的两端各点一下。</p>
      <div className="row">
        <select aria-label="File 文件" value={fileId} onChange={(e) => { setFileId(Number(e.target.value)); setPage(1); }}>
          {files.map((f) => (
            <option key={f.id} value={f.id}>
              {f.filename}
            </option>
          ))}
        </select>
        {pages > 1 && (
          <select aria-label="Page 页" value={page} onChange={(e) => setPage(Number(e.target.value))}>
            {Array.from({ length: pages }, (_, i) => (
              <option key={i} value={i + 1}>
                p.{i + 1}
              </option>
            ))}
          </select>
        )}
        {TOOLS.map(([k, v]) => (
          <button key={k} className={`pill ${tool === k ? "active" : ""}`} onClick={() => setTool(k)}>
            {v}
          </button>
        ))}
        {scale && <span className="tag">Scale 比例: {scale.mm} mm</span>}
      </div>

      <div className="annotate">
        <div ref={box} className="canvas" onMouseDown={down} onMouseMove={move} onMouseUp={up}>
          <img src={`/api/files/${fileId}/page/${page}`} alt={file.filename} draggable={false}
            onLoad={(e) => setSize({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })} />
          {scale && (
            <svg className="overlay" viewBox="0 0 1 1" preserveAspectRatio="none">
              <line x1={scale.a.x} y1={scale.a.y} x2={scale.b.x} y2={scale.b.y} stroke="#15203A" strokeWidth="0.004" />
            </svg>
          )}
          {scalePts.map((p, i) => <span key={i} className="pin scale-pin" style={{ left: pct(p.x), top: pct(p.y) }} />)}
          {drag && <div className="area" style={{ left: pct(Math.min(drag.x, drag.x2)), top: pct(Math.min(drag.y, drag.y2)), width: pct(Math.abs(drag.x2 - drag.x)), height: pct(Math.abs(drag.y2 - drag.y)) }} />}
          {marks.map((m, i) => (
            <div key={i}>
              {m.type === "area" && <div className="area" style={{ left: pct(m.x), top: pct(m.y), width: pct(m.w), height: pct(m.h) }} />}
              {m.type === "device" && <span className="device" style={{ left: pct(m.x), top: pct(m.y) }} />}
              {m.type === "text" && <span className="text-mark" style={{ left: pct(m.x), top: pct(m.y) }}>{m.label}</span>}
              <span className="pin" style={{ left: pct(m.x), top: pct(m.y) }}>{i + 1}</span>
            </div>
          ))}
        </div>

        <div className="marks">
          <b>Marks 标记</b>
          {marks.length === 0 && <p className="muted small">选一个工具，在图上点一下（区域按住拖动）。</p>}
          {marks.map((m, i) => (
            <div key={i} className="mark">
              <span className="pin static">{i + 1}</span>
              <div className="grow">
                <input aria-label={`标记 ${i + 1} 名称`} value={m.label} onChange={(e) => edit(i, { label: e.target.value })} />
                <input aria-label={`标记 ${i + 1} 说明`} placeholder="Note 说明" value={m.note} onChange={(e) => edit(i, { note: e.target.value })} />
                {m.type === "device" && (
                  <select aria-label={`标记 ${i + 1} 对应明细行`} value={m.boq_key ?? ""}
                    onChange={(e) => {
                      const line = deviceLines.find((l) => l.key === e.target.value);
                      edit(i, { boq_key: e.target.value || null, label: line ? line.item : m.label });
                    }}>
                    <option value="">对应 BOQ 明细行（可选）</option>
                    {deviceLines.map((l) => (
                      <option key={l.key} value={l.key}>
                        {l.item} · {l.model}
                      </option>
                    ))}
                  </select>
                )}
                {areaMm(m) && <span className="small muted">{areaMm(m)}</span>}
              </div>
              <button className="btn-link" onClick={() => setMarks(marks.filter((_, j) => j !== i))}>
                Remove 删除
              </button>
            </div>
          ))}
          <div className="row">
            <button className="btn-primary" disabled={!marks.length} onClick={() => save()}>
              Save marked copy 保存标注副本
            </button>
            {saved && (
              <button className="btn-link" onClick={() => { setMarks([]); setScale(null); save([]); }}>
                Clear 清空
              </button>
            )}
          </div>
          {error && <p className="error">{error}</p>}
          {saved && (
            <p className="small">
              Saved as a copy 已另存副本：
              <a href={`/api/proposals/${view.proposal.id}/annotations/${fileId}/${page}/copy`}>{saved.copy_name}</a>
              <br />
              <span className="muted">{file.filename} 未改动 · {saved.updated_by}</span>
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
