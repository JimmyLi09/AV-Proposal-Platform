import { useEffect, useState } from "react";
import { api, InputDef, KbReference, Param, RuleContent, RuleVersion, RunResult, send } from "./api";
import { Choices, InputsForm, nextVersion, ResultsTable, STATUSES, StatusChip } from "./Calc";
import { t, tOr } from "./i18n";
import { fmtDate, LineTabs } from "./labels";


export default function Rules({ line }: { line: string }) {
  const [saved, setSaved] = useState<RuleVersion | null>(null);
  const [draft, setDraft] = useState<RuleContent | null>(null);
  const [versions, setVersions] = useState<RuleVersion[]>([]);
  const [inputs, setInputs] = useState<Record<string, unknown> | null>(null);
  const [refs, setRefs] = useState<KbReference[]>([]);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");

  async function load() {
    const v = await api<RuleVersion>(`/rules/${line}`);
    setSaved(v);
    setDraft(structuredClone(v.content));
    setVersions(await api<RuleVersion[]>(`/rules/${line}/versions`));
  }

  useEffect(() => {
    load();
    api<{ input: Record<string, unknown> }>(`/rules/${line}/sample`).then((s) => setInputs(s.input));
    api<KbReference[]>(`/kb/references/${line}`).then(setRefs);
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
      await send("POST", `/rules/${line}`, { base_id: saved!.id, reason, content: draft });
      setReason("");
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const groups = [...new Set(draft.params.map((p) => p.group))];
  const L = (s?: string) => (s ? saved.text[s] ?? s : ""); // 规则集里的标签、说明按界面语言显示，内容本身不变

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t("nav.rules")}</h1>
          <p className="muted">{t("rules.intro")}</p>
        </div>
        <span className="tag">
          {t("rules.tag", { version: saved.version })} · {fmtDate(saved.created_at)}
          {saved.created_by && ` · ${saved.created_by}`}
        </span>
      </div>

      <div className="row">
        <LineTabs page="rules" line={line} />
        {STATUSES.map((s) => (
          <StatusChip key={s} status={s} />
        ))}
      </div>

      <section className="card">
        <h2>{t("calc.params")}</h2>
        {groups.map((g) => (
          <div key={g} className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{L(g)}</th>
                  <th>{t("rules.value")}</th>
                  <th>{t("common.status")}</th>
                </tr>
              </thead>
              <tbody>
                {draft.params.map((p, i) =>
                  p.group !== g ? null : (
                    <ParamRow key={p.name} p={p} L={L} changed={JSON.stringify(p) !== JSON.stringify(saved.content.params[i])}
                      onChange={(next) => update((c) => (c.params[i] = next))} />
                  ),
                )}
              </tbody>
            </table>
          </div>
        ))}
      </section>

      <section className="card">
        <h2>{t("rules.formulas")}</h2>
        <p className="muted">{t("rules.formulasIntro")}</p>
        {draft.rules.map((rule, ri) => (
          <div key={rule.id} className="rule">
            <div className="rule-head">
              <b>
                {rule.id} {L(rule.title)}
              </b>
              <span className="muted">{L(rule.note)}</span>
            </div>
            {refs.some((r) => r.rule_id === rule.id) && (
              <div className="kb-refs small">
                <b>{t("rules.kbRefs")}</b>
                {refs.filter((r) => r.rule_id === rule.id).map((r) => (
                  <div key={r.id} className="muted">
                    {r.label} · {t("rules.kbRef", { key: r.key, actual: r.actual, rule: r.rule_value ?? "—", version: r.rules_version, by: r.decided_by ?? "" })}
                  </div>
                ))}
              </div>
            )}
            {rule.step ? (
              <p className="muted">{t("rules.step", { step: rule.step })}</p>
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
                          <input className="mono when" aria-label={t("rules.whenLabel", { rule: rule.id, name: out.name, no: ci + 1 })} placeholder={t("rules.whenHint")}
                            value={c.when ?? ""} onChange={(e) => at((cs) => (cs[ci].when = e.target.value || null))} />
                        )}
                        <input className="mono expr" aria-label={t("rules.exprLabel", { rule: rule.id, name: out.name, no: ci + 1 })} value={c.expr}
                          onChange={(e) => at((cs) => (cs[ci].expr = e.target.value))} />
                        {out.cases.length > 1 && (
                          <button className="btn-link" onClick={() => at((cs) => cs.splice(ci, 1))}>
                            {t("common.remove")}
                          </button>
                        )}
                      </div>
                    );
                  })}
                  <button className="btn-link"
                    onClick={() => update((d) => d.rules[ri].outputs![oi].cases.unshift({ when: "", expr: out.cases[0].expr }))}>
                    {t("rules.addTier")}
                  </button>
                </div>
              ))
            )}
          </div>
        ))}
      </section>

      <TryCalc line={line} inputs={inputs} setInputs={setInputs} defs={draft.inputs.map((d) => ({ ...d, label: L(d.label), unit: L(d.unit) }))} hidden={saved.product_fed} saved={saved} draft={dirty ? draft : null} />

      <section className="card">
        <h2>{t("versions.title")}</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("versions.version")}</th>
                <th>{t("versions.date")}</th>
                <th>{t("versions.by")}</th>
                <th>{t("versions.reason")}</th>
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
        <b>{dirty ? t("versions.unsaved") : t("rules.nothingToSave")}</b>
        {dirty && (
          <>
            <input aria-label={t("versions.reason")} placeholder={t("versions.reasonHint")} value={reason} onChange={(e) => setReason(e.target.value)} />
            <button className="btn-outline" onClick={() => setDraft(structuredClone(saved.content))}>
              {t("versions.discard")}
            </button>
          </>
        )}
        <button className="btn-primary" disabled={!dirty || !reason.trim()} onClick={save}>
          {t("rules.saveAs", { version: nextVersion(saved.version) })}
        </button>
        {error && <span className="error">{error}</span>}
      </div>
    </>
  );
}

function ParamRow({ p, L, changed, onChange }: { p: Param; L: (s?: string) => string; changed: boolean; onChange: (p: Param) => void }) {
  return (
    <tr className={changed ? "changed" : ""}>
      <td>{L(p.label)}</td>
      <td>
        <input type="number" step="any" aria-label={L(p.label)} className="num" value={p.value ?? ""}
          onChange={(e) => onChange({ ...p, value: e.target.value === "" ? null : Number(e.target.value) })} />{" "}
        <span className="muted">{L(p.unit)}</span>
      </td>
      <td>
        <select aria-label={`${L(p.label)} · ${t("common.status")}`} value={p.status} onChange={(e) => onChange({ ...p, status: e.target.value })}>
          {STATUSES.map((k) => (
            <option key={k} value={k}>
              {tOr(`calc.status.${k}`, k)}
            </option>
          ))}
        </select>
      </td>
    </tr>
  );
}

function TryCalc({ line, inputs, setInputs, defs, hidden, saved, draft }: {
  line: string;
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
    const timer = setTimeout(async () => {
      setError("");
      setBase(await send<RunResult>("POST", `/rules/${line}/run`, { inputs, version_id: saved.id }));
      if (!draft) return setAfter(null);
      try {
        setAfter(await send<RunResult>("POST", `/rules/${line}/run`, { inputs, content: draft }));
      } catch (err) {
        setAfter(null);
        setError((err as Error).message);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [inputs, draft, saved.id]);

  const cabinet = base?.recommendation?.cabinet;
  return (
    <section className="card">
      <h2>{t("rules.try")}</h2>
      <p className="muted">{t("rules.tryIntro", { version: saved.version })}</p>
      <InputsForm defs={defs} hidden={hidden} inputs={inputs} setInputs={setInputs} />
      {base && (
        <p>
          {t("ws.cabinet")}
          {t("common.colon")}
          {cabinet ? `${cabinet.brand} ${cabinet.model}` : <span className="error">{base.recommendation.block ?? "—"}</span>}
          <span className="muted">
            {" "}
            · {t("nav.products")} {base.library_version}
          </span>
        </p>
      )}
      {error && <p className="error">{t("rules.draftError", { error })}</p>}
      {base && <Choices result={base} onPick={(k, v) => setInputs({ ...inputs, [k]: v })} />}
      {base && <ResultsTable base={base} after={after} label={saved.version} />}
    </section>
  );
}
