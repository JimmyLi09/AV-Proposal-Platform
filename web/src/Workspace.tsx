import { useEffect, useState } from "react";
import { api, RuleResult, send, Suggestion, WorkspaceView } from "./api";
import { CheckChip, Choices, Outcome, ResultsTable, StatusChip } from "./Calc";
import AnnotateTab from "./Annotate";
import BoqTab from "./Boq";
import ConfirmInputs from "./Confirm";
import DiagramTab from "./Diagram";
import DrawingTab from "./Drawing";
import { LINE_LABEL, StatusTag } from "./labels";
import { PRODUCT_STATUS } from "./Products";

const TILES = ["F4", "F2", "F3", "F10", "F5", "F6", "F7", "F9", "F11", "F12"];

export default function Workspace({ id }: { id: number }) {
  const [view, setView] = useState<WorkspaceView | null>(null);
  const [inputs, setInputs] = useState<Record<string, unknown>>({});
  const [tab, setTab] = useState("rec");
  const [error, setError] = useState("");

  async function apply(p: Promise<WorkspaceView>) {
    setError("");
    try {
      const v = await p;
      setView(v);
      setInputs(v.rev.inputs);
    } catch (err) {
      setError((err as Error).message);
    }
  }
  useEffect(() => {
    apply(api<WorkspaceView>(`/proposals/${id}`));
  }, [id]);
  const reading = view?.files.some((f) => f.read_status === "reading");
  useEffect(() => {  // 文件还在读取（提取中）时每 1.5 秒刷新一次
    if (!reading) return;
    const t = setTimeout(() => api<WorkspaceView>(`/proposals/${id}`).then(setView), 1500);
    return () => clearTimeout(t);
  }, [reading, view, id]);

  if (!view) return error ? <p className="error">{error}</p> : null;
  const { proposal, rev, result } = view;
  const saveInputs = (cabinet_id: string | null = rev.cabinet_id) =>
    apply(send<WorkspaceView>("PUT", `/proposals/${id}/inputs`, { inputs, cabinet_id }));

  return (
    <>
      <div>
        <a href={`#/projects/${view.project.id}`}>← Project 项目</a>
        <h1>
          {proposal.name} <span className="zh">{LINE_LABEL[proposal.business_line]}</span>
        </h1>
        <p className="muted">
          <StatusTag status={rev.status} rev={rev.rev_no} /> · 按规则 {view.rules_version}、产品库 {view.library_version}、模板 {view.template_version} 计算
        </p>
      </div>

      <ConfirmInputs view={view} inputs={inputs} setInputs={setInputs} onApply={apply} error={error} />
      {result && <Choices result={result} onPick={(k, v) => setInputs({ ...inputs, [k]: v })} />}

      {result && (
        <>
          <div className="row">
            {[["rec", "Recommendation 推荐"], ["calc", "Calculations 计算依据"], ["diagram", "Diagram 示意图"],
              ["boq", "BOQ 工程量清单"], ["annotate", "Annotate 标注"], ["drawing", "Drawing 图纸"]].map(([k, v]) => (
              <button key={k} className={`pill ${tab === k ? "active" : ""}`} onClick={() => setTab(k)}>
                {v}
              </button>
            ))}
          </div>
          {tab === "rec" && <Recommendation view={view} onCabinet={(cid) => saveInputs(cid)}
            onLibrary={() => apply(api<WorkspaceView>(`/proposals/${id}`))} />}
          {tab === "calc" && (
            <section className="card">
              <h2>
                Calculations <span className="zh">计算依据</span>
              </h2>
              <p className="muted">Proposal 里的每个数字：实际计算式、用到的参数，以及参数的状态。点一行展开。</p>
              <ResultsTable base={result} label={view.rules_version} />
            </section>
          )}
          {tab === "diagram" && (result.diagram ? <DiagramTab view={view} diagram={result.diagram} />
            : <section className="card"><p className="muted">先选定箱体并算出箱体数，才能生成示意图。</p></section>)}
          {tab === "boq" && view.boq && <BoqTab view={view} boq={view.boq} onApply={apply} />}
          {tab === "annotate" && <AnnotateTab view={view} onSaved={() => apply(api<WorkspaceView>(`/proposals/${id}`))} />}
          {tab === "drawing" && (view.drawing ? <DrawingTab view={view} drawing={view.drawing} onApply={apply} />
            : <section className="card"><p className="muted">先选定箱体并算出箱体数、回路和网线，才能出图。</p></section>)}
        </>
      )}
    </>
  );
}

function Recommendation({ view, onCabinet, onLibrary }: { view: WorkspaceView; onCabinet: (id: string) => void; onLibrary: () => void }) {
  const result = view.result!;
  const rec = result.recommendation;
  const byId = Object.fromEntries(result.rules.map((r) => [r.id, r])) as Record<string, RuleResult>;
  const value = (rid: string, name: string) => byId[rid]?.lines.find((l) => l.name === name)?.value as string | undefined;
  const sample = [rec.cabinet?.sample, ...result.rules.filter((r) => ["F11", "F13"].includes(r.id)).map((r) => r.status === "sample")].some(Boolean);
  const checks = result.rules.filter((r) => r.check);
  const blocked = !!rec.block || checks.some((r) => r.check === "BLOCK");

  return (
    <>
      <section className="card">
        <h2>
          Recommendation <span className="zh">推荐</span>
        </h2>
        {rec.missing.length > 0 && <p className="warn">缺少输入：{rec.missing.join(", ")}，补齐后才能从产品库选箱体。</p>}
        {rec.block && (
          <p className="error">
            {rec.block} <a href="#/products">Product Library 产品库 →</a>
          </p>
        )}
        {rec.cabinet && (
          <div className="row">
            <label className="row tight">
              Cabinet 箱体
              <select aria-label="Cabinet 箱体" value={rec.cabinet.id} onChange={(e) => onCabinet(e.target.value)}>
                {rec.candidates.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.brand} {c.model}（{PRODUCT_STATUS[c.status]}）
                  </option>
                ))}
              </select>
            </label>
            <span>
              · Controller 控制器：{value("F11", "controller") ?? "—"} · Processor 处理器：{value("F13", "processor") ?? "—"}
            </span>
            {sample && <span className="tag st-sample">示例值 sample</span>}
          </div>
        )}
        <p className="muted">推荐只从产品库 {view.library_version} 里选：点间距、使用环境、维护方式都要对得上，首选排在前面。</p>
        <div className="tiles">
          {TILES.filter((t) => byId[t]).map((t) => (
            <div key={t} className="tile">
              <div className="muted small">{byId[t].title}</div>
              <div className="tile-value">
                <Outcome r={byId[t]} />
              </div>
              <div className="mono small muted">{byId[t].trace}</div>
              <div className="small">
                {t} · {view.rules_version} <StatusChip status={byId[t].status} />
              </div>
            </div>
          ))}
        </div>
      </section>

      {(result.suggestions ?? []).length > 0 && <Suggestions items={result.suggestions!} onAdded={onLibrary} />}

      <section className="card">
        <h2>
          Checks <span className="zh">校验</span>
        </h2>
        <ul className="checks">
          {rec.block && (
            <li>
              <CheckChip check="BLOCK" /> {rec.block}
            </li>
          )}
          {checks.map((r) => (
            <li key={r.id}>
              <CheckChip check={r.check} /> {r.id} {r.title}
              {r.note && r.check !== "PASS" ? `：${r.note}` : ""}
            </li>
          ))}
          {byId.F11?.check === "PASS" && byId.F11.note && (
            <li>
              <CheckChip check="NOTE" /> {byId.F11.note}
            </li>
          )}
        </ul>
        {blocked && <p className="error">有阻断项，修正之前不能导出。</p>}
      </section>
    </>
  );
}

function Suggestions({ items, onAdded }: { items: Suggestion[]; onAdded: () => void }) {
  const [error, setError] = useState("");
  async function add(id: string) {
    setError("");
    try {
      await send("POST", "/products/LED/reference", { id });
      onAdded();
    } catch (err) {
      setError((err as Error).message);
    }
  }
  return (
    <section className="card">
      <h2>
        Suggested models <span className="zh">建议型号 · 未入库</span>
      </h2>
      <p className="muted">产品库里没有带载、网口都够的处理器 / 控制器。下面是参考型号表里的处理器（含发送），数值待核对规格书；选一款加进产品库后自动重算。</p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Model 型号</th>
              <th>Load 带载</th>
              <th>Ports 网口</th>
              <th>Status 结论</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((s) => (
              <tr key={s.id}>
                <td className="strong">
                  {s.model} <span className="tag st-sample">待核对规格书</span> {s.remark && <span className="muted small">{s.remark}</span>}
                </td>
                <td>
                  {s.capacity_px / 1e6} MP · 负载 {s.load_pct} %
                </td>
                <td>
                  {s.ports_used} / {s.ports}
                </td>
                <td>
                  {s.status === "no" ? <span className="error">不推荐：{s.reason}</span>
                    : <span className={`tag ${s.status === "recommended" ? "ck-PASS" : ""}`}>{s.label}</span>}
                  {s.note && <span className="tag ck-NOTE">{s.note}</span>}
                </td>
                <td>
                  {s.status !== "no" && (
                    <button className="btn-outline small" onClick={() => add(s.id)}>
                      Add to library 加入产品库
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
