import { useEffect, useState } from "react";
import { api, InputDef, Param, RuleContent, RuleVersion, RunResult, send } from "./api";
import { Choices, InputsForm, nextVersion, ResultsTable, STATUS, StatusChip } from "./Calc";
import { fmtDate } from "./labels";

const LINE = "LED";

export default function Rules() {
  const [saved, setSaved] = useState<RuleVersion | null>(null);
  const [draft, setDraft] = useState<RuleContent | null>(null);
  const [versions, setVersions] = useState<RuleVersion[]>([]);
  const [inputs, setInputs] = useState<Record<string, unknown> | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");

  async function load() {
    const v = await api<RuleVersion>(`/rules/${LINE}`);
    setSaved(v);
    setDraft(structuredClone(v.content));
    setVersions(await api<RuleVersion[]>(`/rules/${LINE}/versions`));
  }

  useEffect(() => {
    load();
    api<{ input: Record<string, unknown> }>(`/rules/${LINE}/sample`).then((s) => setInputs(s.input));
  }, []);

  if (!saved || !draft || !inputs) return null;
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved.content);

  function update(fn: (c: RuleContent) => void) {
    const copy = structuredClone(draft!);
    fn(copy);
    setDraft(copy);
  }

  async function save() {
    setError("");
    try {
      await send("POST", `/rules/${LINE}`, { base_id: saved!.id, reason, content: draft });
      setReason("");
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const groups = [...new Set(draft.params.map((p) => p.group))];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>
            Rules Engine <span className="zh">规则引擎</span>
          </h1>
          <p className="muted">所有系数和算式都在这里改。保存会生成新的规则版本；已发出的 Rev 保留计算时使用的版本。</p>
        </div>
        <span className="tag">
          Rules 规则 {saved.version} · {fmtDate(saved.created_at)}
          {saved.created_by && ` · ${saved.created_by}`}
        </span>
      </div>

      <div className="row">
        <span className="pill active">LED</span>
        {Object.keys(STATUS).map((s) => (
          <StatusChip key={s} status={s} />
        ))}
      </div>

      <section className="card">
        <h2>
          Parameters <span className="zh">参数</span>
        </h2>
        {groups.map((g) => (
          <div key={g} className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{g}</th>
                  <th>Value 数值</th>
                  <th>Status 状态</th>
                </tr>
              </thead>
              <tbody>
                {draft.params.map((p, i) =>
                  p.group !== g ? null : (
                    <ParamRow key={p.name} p={p} changed={JSON.stringify(p) !== JSON.stringify(saved.content.params[i])}
                      onChange={(next) => update((c) => (c.params[i] = next))} />
                  ),
                )}
              </tbody>
            </table>
          </div>
        ))}
      </section>

      <section className="card">
        <h2>
          Formulas <span className="zh">算式</span>
        </h2>
        <p className="muted">
          公式类规则可以改算式，也可以加分档（满足「条件」时用这一行，从上往下取第一条）。步骤类规则的步骤写在代码里，只改参数。可用函数：ceil、floor、round、min、max、abs。
        </p>
        {draft.rules.map((rule, ri) => (
          <div key={rule.id} className="rule">
            <div className="rule-head">
              <b>
                {rule.id} {rule.title}
              </b>
              <span className="muted">{rule.note}</span>
            </div>
            {rule.step ? (
              <p className="muted">步骤类规则（{rule.step}），步骤写在代码里。</p>
            ) : (
              rule.outputs!.map((out, oi) => (
                <div key={out.name} className="output">
                  <code className="out-name">{out.name}</code>
                  {out.cases.map((c, ci) => {
                    const at = (fn: (cs: typeof out.cases) => void) =>
                      update((d) => fn(d.rules[ri].outputs![oi].cases));
                    const tiered = out.cases.length > 1 || !!c.when;
                    return (
                      <div key={ci} className="case">
                        {tiered && (
                          <input className="mono when" aria-label={`${rule.id} ${out.name} 条件 ${ci + 1}`} placeholder="条件 when，例如 pixel_pitch_mm < 2"
                            value={c.when ?? ""} onChange={(e) => at((cs) => (cs[ci].when = e.target.value || null))} />
                        )}
                        <input className="mono expr" aria-label={`${rule.id} ${out.name} 算式 ${ci + 1}`} value={c.expr}
                          onChange={(e) => at((cs) => (cs[ci].expr = e.target.value))} />
                        {out.cases.length > 1 && (
                          <button className="btn-link" onClick={() => at((cs) => cs.splice(ci, 1))}>
                            Remove 删除
                          </button>
                        )}
                      </div>
                    );
                  })}
                  <button className="btn-link"
                    onClick={() => update((d) => d.rules[ri].outputs![oi].cases.unshift({ when: "", expr: out.cases[0].expr }))}>
                    + Add tier 加分档
                  </button>
                </div>
              ))
            )}
          </div>
        ))}
      </section>

      <TryCalc inputs={inputs} setInputs={setInputs} defs={draft.inputs} hidden={saved.product_fed} saved={saved} draft={dirty ? draft : null} />

      <section className="card">
        <h2>
          Versions <span className="zh">版本</span>
        </h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Version 版本</th>
                <th>Date 日期</th>
                <th>By 修改人</th>
                <th>Reason 修改原因</th>
              </tr>
            </thead>
            <tbody>
              {versions.map((v) => (
                <tr key={v.id}>
                  <td className="strong">{v.version}</td>
                  <td>{fmtDate(v.created_at)}</td>
                  <td>{v.created_by ?? "—"}</td>
                  <td>{v.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className={`savebar ${dirty ? "on" : ""}`}>
        <b>{dirty ? "Unsaved changes 未保存修改" : "修改任一数值或算式后才能保存"}</b>
        {dirty && (
          <>
            <input aria-label="Reason 修改原因" placeholder="Reason 修改原因（必填）" value={reason} onChange={(e) => setReason(e.target.value)} />
            <button className="btn-outline" onClick={() => setDraft(structuredClone(saved.content))}>
              Discard 放弃修改
            </button>
          </>
        )}
        <button className="btn-primary" disabled={!dirty || !reason.trim()} onClick={save}>
          Save as {nextVersion(saved.version)} 另存为 {nextVersion(saved.version)}
        </button>
        {error && <span className="error">{error}</span>}
      </div>
    </>
  );
}

function ParamRow({ p, changed, onChange }: { p: Param; changed: boolean; onChange: (p: Param) => void }) {
  return (
    <tr className={changed ? "changed" : ""}>
      <td>{p.label}</td>
      <td>
        <input type="number" step="any" aria-label={p.label} className="num" value={p.value ?? ""}
          onChange={(e) => onChange({ ...p, value: e.target.value === "" ? null : Number(e.target.value) })} />{" "}
        <span className="muted">{p.unit}</span>
      </td>
      <td>
        <select aria-label={`${p.label} 状态`} value={p.status} onChange={(e) => onChange({ ...p, status: e.target.value })}>
          {Object.entries(STATUS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </td>
    </tr>
  );
}

function TryCalc({ inputs, setInputs, defs, hidden, saved, draft }: {
  inputs: Record<string, unknown>;
  setInputs: (v: Record<string, unknown>) => void;
  defs: InputDef[];
  hidden: string[];
  saved: RuleVersion;
  draft: RuleContent | null;
}) {
  const [base, setBase] = useState<RunResult | null>(null);
  const [after, setAfter] = useState<RunResult | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const t = setTimeout(async () => {
      setError("");
      setBase(await send<RunResult>("POST", `/rules/${LINE}/run`, { inputs, version_id: saved.id }));
      if (!draft) return setAfter(null);
      try {
        setAfter(await send<RunResult>("POST", `/rules/${LINE}/run`, { inputs, content: draft }));
      } catch (err) {
        setAfter(null);
        setError((err as Error).message);
      }
    }, 300);
    return () => clearTimeout(t);
  }, [inputs, draft, saved.id]);

  const cabinet = base?.recommendation?.cabinet;
  return (
    <section className="card">
      <h2>
        Try calculation <span className="zh">试算</span>
      </h2>
      <p className="muted">默认填的是 143-Royal Plaza LED-1 的输入，箱体从产品库推荐。改了参数或算式，下面会同时显示「{saved.version}」和「修改后」的结果。点一行展开算式。</p>
      <InputsForm defs={defs} hidden={hidden} inputs={inputs} setInputs={setInputs} />
      {base && (
        <p>
          Cabinet 箱体：{cabinet ? `${cabinet.brand} ${cabinet.model}` : <span className="error">{base.recommendation.block ?? "—"}</span>}
          <span className="muted"> · Product Library 产品库 {base.library_version}</span>
        </p>
      )}
      {error && <p className="error">修改后的规则有误：{error}</p>}
      {base && <Choices result={base} onPick={(k, v) => setInputs({ ...inputs, [k]: v })} />}
      {base && <ResultsTable base={base} after={after} label={saved.version} />}
    </section>
  );
}
