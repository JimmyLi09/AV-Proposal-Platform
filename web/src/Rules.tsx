import { Fragment, useEffect, useState } from "react";
import { api, InputDef, Param, RuleContent, RuleResult, RuleVersion, RunResult, send } from "./api";
import { fmtDate } from "./labels";

const LINE = "LED";

export const STATUS: Record<string, string> = {
  set: "Set 已定",
  review: "Under review 审核中",
  sample: "Sample value 示例值 · 待填",
  empty: "Empty 未填",
};

export function StatusChip({ status }: { status: string }) {
  return <span className={`tag st-${status}`}>{STATUS[status] ?? status}</span>;
}

function CheckChip({ check }: { check: string | null }) {
  if (!check) return null;
  const label: Record<string, string> = { PASS: "PASS 通过", NOTE: "NOTE 提示", BLOCK: "BLOCK 阻断" };
  return <span className={`tag ck-${check}`}>{label[check] ?? check}</span>;
}

function nextVersion(v: string) {
  const m = v.match(/^v(\d+)\.(\d+)$/);
  return m ? `v${m[1]}.${Number(m[2]) + 1}` : v;
}

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

      <TryCalc inputs={inputs} setInputs={setInputs} defs={draft.inputs} saved={saved} draft={dirty ? draft : null} />

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

function InputField({ def, value, onChange }: { def: InputDef; value: unknown; onChange: (v: unknown) => void }) {
  const num = (s: string) => (s === "" ? null : Number(s));
  if (def.type === "choice")
    return (
      <select aria-label={def.label} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
        {def.options!.map((o) => (
          <option key={o}>{o}</option>
        ))}
      </select>
    );
  if (def.type === "range") {
    const [lo, hi] = (value as number[] | null) ?? [null, null];
    return (
      <span className="row tight">
        <input type="number" step="any" className="num" aria-label={`${def.label} min`} value={lo ?? ""} onChange={(e) => onChange([num(e.target.value), hi])} />
        –
        <input type="number" step="any" className="num" aria-label={`${def.label} max`} value={hi ?? ""} onChange={(e) => onChange([lo, num(e.target.value)])} />
      </span>
    );
  }
  if (def.type === "sizes") {
    const text = ((value as number[][] | null) ?? []).map((s) => s.join("x")).join(", ");
    return <SizesInput label={def.label} text={text} onChange={onChange} />;
  }
  return <input type="number" step="any" className="num" aria-label={def.label} value={(value as number | null) ?? ""} onChange={(e) => onChange(num(e.target.value))} />;
}

function SizesInput({ label, text, onChange }: { label: string; text: string; onChange: (v: unknown) => void }) {
  const [raw, setRaw] = useState(text);
  return (
    <input aria-label={label} value={raw} placeholder="640x480, 640x640"
      onChange={(e) => {
        setRaw(e.target.value);
        const sizes = e.target.value.split(",").map((s) => s.trim().split(/[x×*]/).map(Number));
        if (sizes.every((s) => s.length === 2 && s.every((n) => n > 0))) onChange(sizes);
      }} />
  );
}

function TryCalc({ inputs, setInputs, defs, saved, draft }: {
  inputs: Record<string, unknown>;
  setInputs: (v: Record<string, unknown>) => void;
  defs: InputDef[];
  saved: RuleVersion;
  draft: RuleContent | null;
}) {
  const [base, setBase] = useState<RunResult | null>(null);
  const [after, setAfter] = useState<RunResult | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<string | null>(null);

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

  const afterById = Object.fromEntries((after?.rules ?? []).map((r) => [r.id, r]));

  return (
    <section className="card">
      <h2>
        Try calculation <span className="zh">试算</span>
      </h2>
      <p className="muted">默认填的是 143-Royal Plaza LED-1 的输入。改了参数或算式，下面会同时显示「{saved.version}」和「修改后」的结果。点一行展开算式。</p>
      <div className="form inputs">
        {defs.map((d) => (
          <label key={d.name}>
            {d.label} {d.unit && <span className="muted">({d.unit})</span>}
            <InputField def={d} value={inputs[d.name]} onChange={(v) => setInputs({ ...inputs, [d.name]: v })} />
          </label>
        ))}
      </div>
      {error && <p className="error">修改后的规则有误：{error}</p>}
      {base && Object.keys(base.choices).length > 0 && (
        <p className="warn">
          尺寸不是模组的整数倍，请先选一个有效尺寸：
          {Object.entries(base.choices).map(([k, opts]) => (
            <span key={k}>
              {" "}
              {k}{" "}
              {opts.map((o) => (
                <button key={o} className="btn-outline small" onClick={() => setInputs({ ...inputs, [k]: o })}>
                  {o}
                </button>
              ))}
            </span>
          ))}
        </p>
      )}
      {base && base.rules.length > 0 && (
        <div className="table-wrap">
          <table className="calc">
            <thead>
              <tr>
                <th>Rule 规则</th>
                <th>Result 结果 · {saved.version}</th>
                {draft && <th>After change 修改后</th>}
                <th>As calculated 计算式</th>
                <th>Status 状态</th>
              </tr>
            </thead>
            <tbody>
              {base.rules.map((r) => {
                const a = afterById[r.id];
                const differs = a && (a.display !== r.display || a.check !== r.check || a.trace !== r.trace);
                return (
                  <Fragment key={r.id}>
                    <tr className={`clickable ${differs ? "changed" : ""}`} onClick={() => setOpen(open === r.id ? null : r.id)}>
                      <td className="strong">
                        {r.id} {r.title}
                      </td>
                      <td>
                        <Outcome r={r} />
                      </td>
                      {draft && <td>{a ? <Outcome r={a} /> : "—"}</td>}
                      <td className="mono small">{(a ?? r).trace}</td>
                      <td>
                        <StatusChip status={(a ?? r).status} />
                      </td>
                    </tr>
                    {open === r.id && (
                      <tr>
                        <td colSpan={draft ? 5 : 4}>
                          <Detail r={a ?? r} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Outcome({ r }: { r: RuleResult }) {
  if (r.error) return <span className="error">{r.error}</span>;
  if (r.missing.length) return <span className="warn">缺少：{r.missing.join(", ")}</span>;
  return (
    <span>
      {r.display} <CheckChip check={r.check} />
    </span>
  );
}

function Detail({ r }: { r: RuleResult }) {
  return (
    <div className="detail">
      <p>
        <b>Why this number 数字由来：</b>
        {r.note}
      </p>
      {r.lines.map((l) => (
        <div key={l.name} className="mono small">
          {l.when && <span className="muted">当 {l.when}：</span>}
          {l.name} = {l.expr ?? ""} {l.substituted && `→ ${l.substituted}`} = <b>{l.display}</b> {l.unit}
        </div>
      ))}
      {r.params.length > 0 && (
        <p>
          <b>Parameters 参数：</b>
          {r.params.map((p) => (
            <span key={p.name} className="param">
              {p.label} {p.value ?? "—"} {p.unit} <StatusChip status={p.status} />
            </span>
          ))}
        </p>
      )}
    </div>
  );
}
