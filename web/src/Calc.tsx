import { Fragment, useState } from "react";
import { InputDef, RuleResult, RunResult } from "./api";

export const STATUS: Record<string, string> = {
  set: "Set 已定",
  review: "Under review 审核中",
  sample: "Sample value 示例值 · 待填",
  empty: "Empty 未填",
};

export function StatusChip({ status }: { status: string }) {
  return <span className={`tag st-${status}`}>{STATUS[status] ?? status}</span>;
}

export function CheckChip({ check }: { check: string | null }) {
  if (!check) return null;
  const label: Record<string, string> = { PASS: "PASS 通过", NOTE: "NOTE 提示", BLOCK: "BLOCK 阻断" };
  return <span className={`tag ck-${check}`}>{label[check] ?? check}</span>;
}

export function nextVersion(v: string) {
  const m = v.match(/^v(\d+)\.(\d+)$/);
  return m ? `v${m[1]}.${Number(m[2]) + 1}` : v;
}

export function InputField({ def, value, onChange }: { def: InputDef; value: unknown; onChange: (v: unknown) => void }) {
  const num = (s: string) => (s === "" ? null : Number(s));
  if (def.type === "choice")
    return (
      <select aria-label={def.label} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
        <option value="">—</option>
        {def.options!.map((o) => (
          <option key={o}>{o}</option>
        ))}
      </select>
    );
  if (def.type === "range") {
    const [lo, hi] = (value as (number | null)[] | null) ?? [null, null];
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

export function SizesInput({ label, text, onChange }: { label: string; text: string; onChange: (v: unknown) => void }) {
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

/** 输入表单；hidden 里的字段由产品库带出，不用手填。 */
export function InputsForm({ defs, hidden, inputs, setInputs }: {
  defs: InputDef[];
  hidden: string[];
  inputs: Record<string, unknown>;
  setInputs: (v: Record<string, unknown>) => void;
}) {
  return (
    <div className="form inputs">
      {defs.filter((d) => !hidden.includes(d.name)).map((d) => (
        <label key={d.name}>
          {d.label} {d.unit && <span className="muted">({d.unit})</span>}
          <InputField def={d} value={inputs[d.name]} onChange={(v) => setInputs({ ...inputs, [d.name]: v })} />
        </label>
      ))}
    </div>
  );
}

/** 尺寸不是模组整数倍时，给两个最近的有效尺寸让人选。 */
export function Choices({ result, onPick }: { result: RunResult; onPick: (name: string, value: number) => void }) {
  const entries = Object.entries(result.choices);
  if (!entries.length) return null;
  return (
    <p className="warn">
      尺寸不是模组的整数倍，请先选一个有效尺寸：
      {entries.map(([k, opts]) => (
        <span key={k}>
          {" "}
          {k}{" "}
          {opts.map((o) => (
            <button key={o} className="btn-outline small" onClick={() => onPick(k, o)}>
              {o}
            </button>
          ))}
        </span>
      ))}
    </p>
  );
}

/** 计算依据：每条规则的结果、代入数值的算式、状态；点一行展开。after 有值时并排显示修改后的结果。 */
export function ResultsTable({ base, after, label }: { base: RunResult; after?: RunResult | null; label: string }) {
  const [open, setOpen] = useState<string | null>(null);
  const afterById = Object.fromEntries((after?.rules ?? []).map((r) => [r.id, r]));
  if (!base.rules.length) return null;
  return (
    <div className="table-wrap">
      <table className="calc">
        <thead>
          <tr>
            <th>Rule 规则</th>
            <th>Result 结果 · {label}</th>
            {after && <th>After change 修改后</th>}
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
                  {after && <td>{a ? <Outcome r={a} /> : "—"}</td>}
                  <td className="mono small">{(a ?? r).trace}</td>
                  <td>
                    <StatusChip status={(a ?? r).status} />
                  </td>
                </tr>
                {open === r.id && (
                  <tr>
                    <td colSpan={after ? 5 : 4}>
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
  );
}

export function Outcome({ r }: { r: RuleResult }) {
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
          {l.expr ? `${l.name} = ${l.expr} → ${l.substituted} = ` : `${l.name} = `}
          <b>{l.display}</b> {l.unit}
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
