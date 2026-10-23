import { useEffect, useState } from "react";
import { api, RuleResult, send, Suggestion, WorkspaceView } from "./api";
import { CheckChip, Choices, Outcome, ResultsTable, StatusChip } from "./Calc";
import AnnotateTab from "./Annotate";
import BoqTab from "./Boq";
import ConfirmInputs from "./Confirm";
import DiagramTab from "./Diagram";
import DrawingTab from "./Drawing";
import { t } from "./i18n";
import { lineLabel, StatusTag } from "./labels";
import { productStatus } from "./Products";

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
    const timer = setTimeout(() => api<WorkspaceView>(`/proposals/${id}`).then(setView), 1500);
    return () => clearTimeout(timer);
  }, [reading, view, id]);

  if (!view) return error ? <p className="error">{error}</p> : null;
  const { proposal, rev, result } = view;
  const saveInputs = (cabinet_id: string | null = rev.cabinet_id) =>
    apply(send<WorkspaceView>("PUT", `/proposals/${id}/inputs`, { inputs, cabinet_id }));

  return (
    <>
      <div>
        <a href={`#/projects/${view.project.id}`}>← {t("ws.project")}</a>
        <h1>
          {proposal.name} <span className="sub">{lineLabel(proposal.business_line)}</span>
        </h1>
        <p className="muted">
          <StatusTag status={rev.status} rev={rev.rev_no} /> ·{" "}
          {t("ws.versions", { rules: view.rules_version, library: view.library_version, template: view.template_version })}
        </p>
      </div>

      <ConfirmInputs view={view} inputs={inputs} setInputs={setInputs} onApply={apply} error={error} />
      {result && <Choices result={result} onPick={(k, v) => setInputs({ ...inputs, [k]: v })} />}

      {result && (
        <>
          <div className="row">
            {["rec", "calc", "diagram", "boq", "annotate", "drawing"].map((k) => (
              <button key={k} className={`pill ${tab === k ? "active" : ""}`} onClick={() => setTab(k)}>
                {t(`ws.tabs.${k}`)}
              </button>
            ))}
          </div>
          {tab === "rec" && <Recommendation view={view} onCabinet={(cid) => saveInputs(cid)}
            onLibrary={() => apply(api<WorkspaceView>(`/proposals/${id}`))} />}
          {tab === "calc" && (
            <section className="card">
              <h2>{t("ws.tabs.calc")}</h2>
              <p className="muted">{t("ws.calcIntro")}</p>
              <ResultsTable base={result} label={view.rules_version} />
            </section>
          )}
          {tab === "diagram" && (result.diagram ? <DiagramTab view={view} diagram={result.diagram} />
            : <section className="card"><p className="muted">{t("ws.noDiagram")}</p></section>)}
          {tab === "boq" && view.boq && <BoqTab view={view} boq={view.boq} onApply={apply} />}
          {tab === "annotate" && <AnnotateTab view={view} onSaved={() => apply(api<WorkspaceView>(`/proposals/${id}`))} />}
          {tab === "drawing" && (view.drawing ? <DrawingTab view={view} drawing={view.drawing} onApply={apply} />
            : <section className="card"><p className="muted">{t("ws.noDrawing")}</p></section>)}
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
        <h2>{t("ws.tabs.rec")}</h2>
        {rec.missing.length > 0 && <p className="warn">{t("ws.missing", { names: rec.missing.join(", ") })}</p>}
        {rec.block && (
          <p className="error">
            {rec.block} <a href="#/products">{t("nav.products")} →</a>
          </p>
        )}
        {rec.cabinet && (
          <div className="row">
            <label className="row tight">
              {t("ws.cabinet")}
              <select aria-label={t("ws.cabinet")} value={rec.cabinet.id} onChange={(e) => onCabinet(e.target.value)}>
                {rec.candidates.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.brand} {c.model}
                    {t("common.paren", { x: productStatus(c.status) })}
                  </option>
                ))}
              </select>
            </label>
            <span>
              · {t("ws.controller")}
              {t("common.colon")}
              {value("F11", "controller") ?? "—"} · {t("ws.processor")}
              {t("common.colon")}
              {value("F13", "processor") ?? "—"}
            </span>
            {sample && <span className="tag st-sample">{t("common.sample")}</span>}
          </div>
        )}
        <p className="muted">{t("ws.fromLibrary", { version: view.library_version })}</p>
        <div className="tiles">
          {TILES.filter((rid) => byId[rid]).map((rid) => (
            <div key={rid} className="tile">
              <div className="muted small">{byId[rid].title}</div>
              <div className="tile-value">
                <Outcome r={byId[rid]} />
              </div>
              <div className="mono small muted">{byId[rid].trace}</div>
              <div className="small">
                {rid} · {view.rules_version} <StatusChip status={byId[rid].status} />
              </div>
            </div>
          ))}
        </div>
      </section>

      {(result.suggestions ?? []).length > 0 && <Suggestions items={result.suggestions!} onAdded={onLibrary} />}

      <section className="card">
        <h2>{t("ws.checks")}</h2>
        <ul className="checks">
          {rec.block && (
            <li>
              <CheckChip check="BLOCK" /> {rec.block}
            </li>
          )}
          {checks.map((r) => (
            <li key={r.id}>
              <CheckChip check={r.check} /> {r.id} {r.title}
              {r.note && r.check !== "PASS" ? t("common.colon") + r.note : ""}
            </li>
          ))}
          {byId.F11?.check === "PASS" && byId.F11.note && (
            <li>
              <CheckChip check="NOTE" /> {byId.F11.note}
            </li>
          )}
        </ul>
        {blocked && <p className="error">{t("ws.blocked")}</p>}
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
      <h2>{t("ws.suggested")}</h2>
      <p className="muted">{t("ws.suggestedIntro")}</p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t("ws.model")}</th>
              <th>{t("ws.load")}</th>
              <th>{t("ws.ports")}</th>
              <th>{t("ws.verdict")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((s) => (
              <tr key={s.id}>
                <td className="strong">
                  {s.model} <span className="tag st-sample">{t("ws.checkDatasheet")}</span> {s.remark && <span className="muted small">{s.remark}</span>}
                </td>
                <td>
                  {s.capacity_px / 1e6} MP · {t("ws.loadPct", { pct: s.load_pct })}
                </td>
                <td>
                  {s.ports_used} / {s.ports}
                </td>
                <td>
                  {s.status === "no" ? <span className="error">{s.label + t("common.colon") + s.reason}</span>
                    : <span className={`tag ${s.status === "recommended" ? "ck-PASS" : ""}`}>{s.label}</span>}
                  {s.note && <span className="tag ck-NOTE">{s.note}</span>}
                </td>
                <td>
                  {s.status !== "no" && (
                    <button className="btn-outline small" onClick={() => add(s.id)}>
                      {t("ws.addToLibrary")}
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
