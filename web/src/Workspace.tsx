import { useEffect, useState } from "react";
import { api, Boq, ManualLine, RuleResult, send, WorkspaceView } from "./api";
import { CheckChip, Choices, InputsForm, money, Outcome, ResultsTable, StatusChip } from "./Calc";
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
          <StatusTag status={rev.status} rev={rev.rev_no} /> · 按规则 {view.rules_version}、产品库 {view.library_version} 计算
        </p>
      </div>

      <section className="card">
        <h2>
          Confirmed inputs <span className="zh">已确认输入</span>
        </h2>
        <p className="muted">第 4 步会从客户文件里读取并逐项确认；现在先手工录入。模组和箱体尺寸由产品库里选定的箱体带出。</p>
        <InputsForm defs={view.input_defs} hidden={view.product_fed} inputs={inputs} setInputs={setInputs} />
        <div className="row">
          <button className="btn-primary" onClick={() => saveInputs()}>
            Save &amp; calculate 保存并计算
          </button>
          {error && <span className="error">{error}</span>}
        </div>
        {result && <Choices result={result} onPick={(k, v) => setInputs({ ...inputs, [k]: v })} />}
      </section>

      {result && (
        <>
          <div className="row">
            {[["rec", "Recommendation 推荐"], ["calc", "Calculations 计算依据"], ["cost", "Cost & BOQ 成本与 BOQ"]].map(([k, v]) => (
              <button key={k} className={`pill ${tab === k ? "active" : ""}`} onClick={() => setTab(k)}>
                {v}
              </button>
            ))}
          </div>
          {tab === "rec" && <Recommendation view={view} onCabinet={(cid) => saveInputs(cid)} />}
          {tab === "calc" && (
            <section className="card">
              <h2>
                Calculations <span className="zh">计算依据</span>
              </h2>
              <p className="muted">Proposal 里的每个数字：实际计算式、用到的参数，以及参数的状态。点一行展开。</p>
              <ResultsTable base={result} label={view.rules_version} />
            </section>
          )}
          {tab === "cost" && view.boq && <CostBoq view={view} boq={view.boq} onSaved={apply} />}
        </>
      )}
    </>
  );
}

function Recommendation({ view, onCabinet }: { view: WorkspaceView; onCabinet: (id: string) => void }) {
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

function CostBoq({ view, boq, onSaved }: { view: WorkspaceView; boq: Boq; onSaved: (p: Promise<WorkspaceView>) => void }) {
  const id = view.proposal.id;
  const [manual, setManual] = useState<ManualLine[]>(view.rev.manual_lines);
  const [sell, setSell] = useState<string>(view.rev.sell_price_cents === null ? "" : String(view.rev.sell_price_cents / 100));
  const [display, setDisplay] = useState(view.rev.price_display);
  const [prices, setPrices] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const ruleLines = boq.lines.filter((l) => !l.manual);
  const manualTotals = boq.lines.filter((l) => l.manual);
  const sellNum = sell === "" ? null : Number(sell);

  async function setPrice(key: string) {
    setError("");
    try {
      await send("POST", "/costs", { key, amount: Number(prices[key]) });
      setPrices({ ...prices, [key]: "" });
      onSaved(api<WorkspaceView>(`/proposals/${id}`));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  function saveCommercial() {
    onSaved(send<WorkspaceView>("PUT", `/proposals/${id}/commercial`, {
      manual_lines: manual.map((m) => ({ ...m, unit_cost: m.unit_cost === null ? null : m.unit_cost / 100 })),
      sell_price: sellNum,
      price_display: display,
    }));
  }

  const editManual = (i: number, patch: Partial<ManualLine>) => setManual(manual.map((m, j) => (j === i ? { ...m, ...patch } : m)));

  return (
    <section className="card">
      <h2>
        Cost &amp; BOQ <span className="zh">成本与 BOQ</span>
      </h2>
      <p className="muted">数量来自规则；单价人工填写，系统只做加总。单价是共用的价格表，改了会影响所有用到这个产品的方案。</p>
      {(boq.missing > 0 || boq.expired > 0) && (
        <p className="warn">
          {boq.missing} 行没有成本，{boq.expired} 个成本已过有效期。Proposal 仍可导出；这些行会列在审核页中。
        </p>
      )}
      {error && <p className="error">{error}</p>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Item 项目</th>
              <th>Model 型号</th>
              <th>Qty 数量</th>
              <th>Why this qty 数量依据</th>
              <th>Unit cost 单价 S$</th>
              <th>Subtotal 小计 S$</th>
            </tr>
          </thead>
          <tbody>
            {ruleLines.map((l, i) => (
              <tr key={`r${i}`}>
                <td>{i + 1}</td>
                <td>{l.item}</td>
                <td>{l.model}</td>
                <td>
                  {l.qty} {l.unit}
                </td>
                <td>{l.why}</td>
                <td>
                  {l.included ? (
                    <span className="tag">Included 已含</span>
                  ) : (
                    <div className="row tight">
                      {l.unit_cost !== null && l.unit_cost !== undefined ? (
                        <span className={l.cost_expired ? "error" : ""}>{money(l.unit_cost)}</span>
                      ) : (
                        <span className="tag st-empty">No cost 无成本</span>
                      )}
                      {l.cost_valid_until && (
                        <span className={`small ${l.cost_expired ? "error" : "muted"}`}>
                          {l.cost_expired ? "已过有效期" : "有效期至"} {l.cost_valid_until}
                        </span>
                      )}
                      {l.cost_sample && <span className="tag st-sample">示例价格</span>}
                      <input type="number" step="any" className="num" aria-label={`${l.item} 新单价`} placeholder="新单价" value={prices[l.key] ?? ""}
                        onChange={(e) => setPrices({ ...prices, [l.key]: e.target.value })} />
                      <button className="btn-outline small" disabled={!prices[l.key]} onClick={() => setPrice(l.key)}>
                        Set 填写
                      </button>
                    </div>
                  )}
                </td>
                <td>{l.included ? "—" : money(l.subtotal)}</td>
              </tr>
            ))}
            {manual.map((m, i) => (
              <tr key={`m${i}`}>
                <td>{ruleLines.length + i + 1}</td>
                <td>
                  <input aria-label={`手动行 ${i + 1} 项目`} value={m.item} onChange={(e) => editManual(i, { item: e.target.value })} />{" "}
                  <span className="tag">manual 手工</span>
                </td>
                <td>
                  <input className="num" aria-label={`手动行 ${i + 1} 型号`} value={m.model} onChange={(e) => editManual(i, { model: e.target.value })} />
                </td>
                <td>
                  <input type="number" step="any" className="num" aria-label={`手动行 ${i + 1} 数量`} value={m.qty ?? ""}
                    onChange={(e) => editManual(i, { qty: e.target.value === "" ? null : Number(e.target.value) })} />
                </td>
                <td>{m.why || "—"}</td>
                <td>
                  <input type="number" step="any" className="num" aria-label={`手动行 ${i + 1} 单价`}
                    value={m.unit_cost === null ? "" : m.unit_cost / 100}
                    onChange={(e) => editManual(i, { unit_cost: e.target.value === "" ? null : Math.round(Number(e.target.value) * 100) })} />{" "}
                  <button className="btn-link" onClick={() => setManual(manual.filter((_, j) => j !== i))}>
                    Remove 删除
                  </button>
                </td>
                <td>{money(manualTotals[i]?.subtotal)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row">
        <button className="btn-outline" onClick={() => setManual([...manual, { item: "", model: "", qty: 1, unit: "项", unit_cost: null, why: "" }])}>
          + Add manual line 添加手动行
        </button>
      </div>

      <div className="totals">
        <div>
          Cost subtotal 成本小计（{boq.count} 行中 {boq.priced} 行）<b>S$ {money(boq.subtotal)}</b>
        </div>
        <label className="row tight">
          Sell price 售价（人工填写，可选）S$
          <input type="number" step="any" className="num" aria-label="Sell price 售价" value={sell} onChange={(e) => setSell(e.target.value)} />
        </label>
        <div>
          GST 按售价 {view.gst_rate !== null ? `${view.gst_rate * 100}%` : "—"}
          {view.gst_status && <StatusChip status={view.gst_status} />}
          {sellNum !== null && view.gst_rate !== null && <b> S$ {money(Math.round(sellNum * view.gst_rate * 100))}</b>}
          <span className="muted"> · V1 不计算加价。</span>
        </div>
        <div className="row tight">
          Prices in the PDF PDF 中的价格：
          {[["none", "Not shown 不显示（仅数量）"], ["total", "Sell price total only 仅售价总额"], ["itemised", "Itemised sell prices 分项售价"]].map(([k, v]) => (
            <label key={k} className="row tight check">
              <input type="radio" name="price_display" checked={display === k} onChange={() => setDisplay(k)} /> {v}
            </label>
          ))}
        </div>
        <p className="muted">成本仅供内部，不会打印。V1 中平台上所有人都能看到成本。</p>
        <div>
          <button className="btn-primary" onClick={saveCommercial}>
            Save 保存
          </button>
        </div>
      </div>
    </section>
  );
}
