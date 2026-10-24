import { Fragment, useEffect, useRef, useState } from "react";
import { api, KbHit, KbItem, KbOverview, KbProject, KbRecord, send, Similar, SimilarReason } from "./api";
import { optionLabel } from "./Calc";
import { conf } from "./Confirm";
import { shapeLabel } from "./Faces";
import { t } from "./i18n";
import { fmtDate, lineLabel } from "./labels";

const TYPES = ["projects", "specs", "drawings", "boq", "templates"];

function fmt(v: unknown): string {
  if (Array.isArray(v)) return v.join("–");
  if (typeof v === "number") return v >= 100000 ? v.toLocaleString("en-US") : String(v);
  if (typeof v === "string") return optionLabel(v);
  return v === null || v === undefined ? "—" : String(v);
}

/** 项目记录一行写完：业务线 · 屏形 · 点间距 · 尺寸 · 环境 · 安装 / 投影机 · 投射比 */
export function recordSummary(r: KbRecord): string {
  const i = r.inputs;
  const [w, h] = r.line === "LED" ? [i.width_mm, i.height_mm] : [i.wall_width_mm, i.wall_height_mm];
  const parts = [lineLabel(r.line), shapeLabel(r.shape)];
  if (i.pixel_pitch_mm) parts.push(`P${i.pixel_pitch_mm}`);
  if (w && h) parts.push(`${w} × ${h} mm`);
  for (const k of ["environment", "installation"]) if (i[k]) parts.push(optionLabel(String(i[k])));
  if (i.projector) parts.push(String(i.projector));
  if (i.lens_throw_ratio) parts.push(`${i.lens_throw_ratio}:1`);
  return parts.join(" · ");
}

const actualSummary = (r: KbRecord, labels: Record<string, string>) =>
  Object.entries(r.actual).map(([k, v]) => `${labels[k] ?? k} ${v}`).join(" · ");

function reasonText(r: SimilarReason): string {
  switch (r.code) {
    case "shape":
      return t("kb.reason.shape", { shape: shapeLabel(String(r.shape)) });
    case "same":
      return t("kb.reason.same", { field: t(`kb.fields.${r.field}`), value: optionLabel(String(r.value)) });
    default:
      return t(`kb.reason.${r.code}`, r as Record<string, string | number>);
  }
}

/** 确认输入时列出的 3 个相似以往项目（只用人确认过的项目记录）。 */
export function SimilarProjects({ list }: { list: Similar[] }) {
  if (list.length === 0) return null;
  return (
    <div className="similar">
      <h3>{t("kb.similar.title")}</h3>
      <p className="muted small">{t("kb.similar.intro")}</p>
      <div className="tiles">
        {list.map((s) => (
          <div key={s.id} className="tile">
            <div className="row tight">
              <b>{s.key}</b>
              {s.standard && <span className="tag ck-PASS">{t("kb.standard.tag")}</span>}
              <span className="grow" />
              <span className="muted small">{t("kb.similar.score", { score: s.score })}</span>
            </div>
            <div className="small">{recordSummary(s.record)}</div>
            <div className="muted small">{s.reasons.map(reasonText).join(" · ")}</div>
            <div className="small">
              {s.files.map((f) => (
                <a key={f.id} href={`/api/kb/files/${f.id}`} target="_blank" rel="noreferrer" className="file-link">
                  {f.name}
                </a>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function targetLabel(target: string) {
  return t(`kb.target.${target}`);
}

function describe(i: KbItem): { what: string; detail: React.ReactNode; to: string } {
  if (i.kind === "product")
    return {
      what: t("kb.item.product", { model: i.model! }),
      detail: i.fields!.map((f) => (
        <div key={f.name} className={f.changed ? "strong" : "muted"}>
          {f.label} {fmt(f.value)}
          {f.changed && f.current !== null && ` ${t("kb.item.was", { value: fmt(f.current) })}`}
          {f.changed && f.current === null && ` ${t("kb.item.wasEmpty")}`}
        </div>
      )),
      to: t(i.from_reference ? "kb.to.productAdd" : "kb.to.product", { line: lineLabel(i.line) }),
    };
  if (i.kind === "template") {
    const row = i.row!;
    const qty = typeof row.qty === "string" ? t("kb.item.byArea") : `${row.qty} ${row.unit}`;
    return {
      what: `${t("kb.item.template")}${t("common.colon")}${i.original}`,
      detail: (
        <>
          <div className="mono small">{row.title}</div>
          {row.specs.map((s) => (
            <div key={s} className="mono small muted">- {s}</div>
          ))}
          <div className="muted small">
            {qty} · {t("kb.item.inFiles", { n: i.files! })}
          </div>
        </>
      ),
      to: t("kb.to.template", { line: lineLabel(i.line) }),
    };
  }
  if (i.kind === "project")
    return {
      what: t("kb.item.project", { key: i.key! }),
      detail: (
        <>
          <div>{recordSummary(i.record!)}</div>
          {Object.keys(i.record!.actual).length > 0 && (
            <div className="muted small">{t("kb.actual")}{t("common.colon")}{actualSummary(i.record!, i.labels)}</div>
          )}
        </>
      ),
      to: t("kb.to.project"),
    };
  return {
    what: t("kb.item.rule", { rule: `${i.rule_id} ${i.rule_title}` }),
    detail: t("kb.item.ruleDetail", { key: i.key!, label: i.labels[i.name!] ?? i.name!, rule: fmt(i.rule_value),
      actual: fmt(i.actual), version: i.rules_version! }),
    to: t("kb.to.rule"),
  };
}

export default function Knowledge() {
  const [kb, setKb] = useState<KbOverview | null>(null);
  const [items, setItems] = useState<KbItem[]>([]);
  const [projects, setProjects] = useState<KbProject[]>([]);
  const [show, setShow] = useState<"pending" | "decided">("pending");
  const [error, setError] = useState("");
  const timer = useRef<number | undefined>(undefined);

  async function loadLists(s = show) {
    setItems(await api<KbItem[]>(`/kb/items?status=${s}`));
    setProjects(await api<KbProject[]>("/kb/projects"));
  }

  async function watch(prevAt: string | undefined, idle = 0) {
    const o = await api<KbOverview>("/kb");
    setKb(o);
    const done = !o.progress && o.last_scan?.at !== prevAt;
    if (done || idle > 5) return loadLists();
    timer.current = window.setTimeout(() => watch(prevAt, o.progress ? 0 : idle + 1), 1500);
  }

  useEffect(() => {
    api<KbOverview>("/kb").then((o) => {
      setKb(o);
      if (o.progress) watch(o.last_scan?.at);
    });
    loadLists();
    return () => clearTimeout(timer.current);
  }, []);

  if (!kb) return null;

  async function run(p: Promise<unknown>) {
    setError("");
    try {
      await p;
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function startScan() {
    await run(send("POST", "/kb/scan", {}).then(() => watch(kb!.last_scan?.at)));
  }

  async function toggleType(key: string) {
    const types = kb!.types.filter((x) => (x.key === key ? !x.enabled : x.enabled)).map((x) => x.key);
    await run(send<KbOverview>("PUT", "/kb/types", { types }).then(setKb));
  }

  async function decide(i: KbItem, action: "adopt" | "reject" | "undo") {
    await run(send("POST", `/kb/items/${i.id}/${action}`, {}).then(async () => {
      setKb(await api<KbOverview>("/kb"));
      await loadLists();
    }));
  }

  async function setStandard(p: KbProject, standard: boolean) {
    await run(send<KbProject>("PUT", `/kb/projects/${p.id}/standard`, { standard }).then(() => loadLists()));
  }

  const kpis: [string, number, string][] = [
    [t("kb.kpi.files"), kb.counts.files, ""],
    [t("kb.kpi.read"), kb.counts.read, "ok"],
    [t("kb.kpi.pending"), kb.counts.pending, "warn"],
    [t("kb.kpi.failed"), kb.counts.failed, "bad"],
  ];
  const last = kb.last_scan;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t("nav.knowledge")}</h1>
          <p className="muted">{t("kb.intro")}</p>
        </div>
        <span className="tag ck-PASS">{t("kb.local")}</span>
      </div>
      <p className="note">
        <b>{t("kb.noQty")}</b>
        {t("kb.noQtyText")}
      </p>

      <div className="tiles">
        {kpis.map(([label, value, tone]) => (
          <div key={label} className={`tile kpi ${tone}`}>
            <div className="muted small">{label}</div>
            <div className="tile-value">{value.toLocaleString("en-US")}</div>
          </div>
        ))}
      </div>

      <section className="card">
        <h2>{t("kb.import.title")}</h2>
        <div className="row">
          <span className="muted">{t("kb.import.folder")}</span>
          <code className="folder">{kb.folder}</code>
          {!kb.exists && <span className="error small">{t("kb.import.noFolder")}</span>}
        </div>
        <div className="row tight" role="group" aria-label={t("kb.import.types")}>
          {kb.types.map((x) => (
            <button key={x.key} className={`pill ${x.enabled ? "active" : ""}`} aria-pressed={x.enabled} onClick={() => toggleType(x.key)}>
              {t(`kb.types.${x.key}`)} <span className="muted small">{x.files}</span>
            </button>
          ))}
        </div>
        <div className="row">
          <button className="btn-primary" disabled={!!kb.progress} onClick={startScan}>
            {t("kb.import.scan")}
          </button>
          <span className="muted small">
            {kb.progress
              ? t("kb.import.scanning", { done: kb.progress.done, total: kb.progress.total })
              : last
                ? t("kb.import.last", { at: fmtDate(last.at), time: new Date(last.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
                    new: last.new, changed: last.changed, removed: last.removed, failed: last.failed })
                : t("kb.import.never")}
          </span>
        </div>
        <Upload onDone={() => watch(kb.last_scan?.at)} onError={setError} />
        <p className="muted small">{t("kb.import.note", { at: kb.scan_at })}</p>
        {kb.failed.length > 0 && (
          <details>
            <summary className="error small">{t("kb.import.failed", { n: kb.failed.length })}</summary>
            <ul className="plain small">
              {kb.failed.map((f) => (
                <li key={f.id}>
                  {f.rel_path} · {f.note}
                </li>
              ))}
            </ul>
          </details>
        )}
        {error && <p className="error">{error}</p>}
      </section>

      <Search />

      <section className="card">
        <div className="row">
          <h2 className="grow">{t("kb.learnedTitle")}</h2>
          {(["pending", "decided"] as const).map((s) => (
            <button key={s} className={`pill ${show === s ? "active" : ""}`}
              onClick={() => { setShow(s); loadLists(s); }}>
              {t(`kb.show.${s}`)}
            </button>
          ))}
        </div>
        <p className="muted small">
          {show === "pending" ? (items.length ? t("kb.pendingLeft", { n: items.length }) : t("kb.allDone")) : t("kb.decidedIntro")}
        </p>
        {items.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("kb.learned")}</th>
                  <th>{t("kb.from")}</th>
                  <th>{t("kb.goesTo")}</th>
                  <th>{t("confirm.confidence")}</th>
                  <th>{t("kb.action")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((i) => {
                  const d = describe(i);
                  return (
                    <tr key={i.id} className={i.status === "pending" ? "" : "decided"}>
                      <td>
                        <div className="strong">{d.what}</div>
                        <div className="small">{d.detail}</div>
                      </td>
                      <td className="small">
                        {i.source ? (
                          <a href={`/api/kb/files/${i.source.id}`} target="_blank" rel="noreferrer">
                            {i.source.name}
                          </a>
                        ) : "—"}
                        {i.location && ` · ${i.location}`}
                      </td>
                      <td className="small">{d.to}</td>
                      <td>
                        <span className={`tag conf-${i.confidence}`}>{conf(i.confidence)}</span>
                      </td>
                      <td className="nowrap">
                        {i.status === "pending" ? (
                          <>
                            <button className="btn-primary small" onClick={() => decide(i, "adopt")}>
                              {t("kb.adopt")}
                            </button>{" "}
                            <button className="btn-outline small" onClick={() => decide(i, "reject")}>
                              {t("kb.reject")}
                            </button>
                          </>
                        ) : (
                          <>
                            <div className={`small ${i.status === "adopted" ? "ok-text" : "muted"}`}>
                              {i.status === "adopted"
                                ? t("kb.adopted", { target: targetLabel(i.result!.target), version: i.result!.version ?? "" })
                                : t("kb.rejected")}
                            </div>
                            <div className="muted small">
                              {i.decided_by} · {i.decided_at && fmtDate(i.decided_at)}
                            </div>
                            <button className="btn-link" onClick={() => decide(i, "undo")}>
                              {t("kb.undo")}
                            </button>
                          </>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <Projects projects={projects} onStandard={setStandard} />

      <section className="card">
        <h2>{t("kb.used.title")}</h2>
        <div className="tiles">
          {["similar", "product", "boq", "regression"].map((k) => (
            <div key={k} className="tile">
              <b>{t(`kb.used.${k}`)}</b>
              <span className="muted small">{t(`kb.used.${k}Text`)}</span>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}

function Upload({ onDone, onError }: { onDone: () => void; onError: (e: string) => void }) {
  const [type, setType] = useState("specs");
  const [project, setProject] = useState("");
  const [files, setFiles] = useState<FileList | null>(null);
  const input = useRef<HTMLInputElement>(null);

  async function upload() {
    const body = new FormData();
    body.append("doc_type", type);
    body.append("project", project);
    for (const f of Array.from(files ?? [])) body.append("files", f);
    onError("");
    try {
      await api("/kb/upload", { method: "POST", body });
      setFiles(null);
      if (input.current) input.current.value = "";
      onDone();
    } catch (err) {
      onError((err as Error).message);
    }
  }

  return (
    <div className="row">
      <span className="muted">{t("kb.upload.title")}</span>
      <select aria-label={t("kb.upload.type")} value={type} onChange={(e) => setType(e.target.value)}>
        {TYPES.map((k) => (
          <option key={k} value={k}>
            {t(`kb.types.${k}`)}
          </option>
        ))}
      </select>
      {type === "projects" && (
        <input aria-label={t("kb.upload.project")} placeholder={t("kb.upload.projectHint")} value={project}
          onChange={(e) => setProject(e.target.value)} />
      )}
      <input ref={input} type="file" multiple aria-label={t("kb.upload.files")} onChange={(e) => setFiles(e.target.files)} />
      <button className="btn-outline" disabled={!files?.length} onClick={upload}>
        {t("kb.upload.button")}
      </button>
    </div>
  );
}

function Search() {
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [hits, setHits] = useState<KbHit[] | null>(null);

  async function search() {
    const params = new URLSearchParams({ q, ...(type ? { doc_type: type } : {}) });
    setHits(await api<KbHit[]>(`/kb/search?${params}`));
  }

  return (
    <section className="card">
      <h2>{t("kb.search.title")}</h2>
      <div className="row">
        <input className="grow" aria-label={t("kb.search.title")} placeholder={t("kb.search.hint")} value={q}
          onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} />
        <select aria-label={t("kb.search.type")} value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">{t("kb.search.all")}</option>
          {TYPES.map((k) => (
            <option key={k} value={k}>
              {t(`kb.types.${k}`)}
            </option>
          ))}
        </select>
        <button className="btn-outline" disabled={!q.trim()} onClick={search}>
          {t("kb.search.button")}
        </button>
      </div>
      {hits && hits.length === 0 && <p className="muted">{t("kb.search.none")}</p>}
      {hits && hits.length > 0 && (
        <ul className="plain hits">
          {hits.map((h, n) => (
            <li key={n}>
              <a href={`/api/kb/files/${h.file.id}`} target="_blank" rel="noreferrer" className="strong">
                {h.file.name}
              </a>{" "}
              <span className="tag">{t(`kb.types.${h.file.doc_type}`)}</span>
              {h.project && <span className="muted small"> · {h.project}</span>}
              {h.location && <span className="muted small"> · {h.location}</span>}
              {h.snippet && <div className="muted small">{h.snippet}</div>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Projects({ projects, onStandard }: { projects: KbProject[]; onStandard: (p: KbProject, v: boolean) => void }) {
  return (
    <section className="card">
      <h2>{t("kb.projects.title")}</h2>
      <p className="muted small">{t("kb.projects.intro")}</p>
      {projects.length === 0 ? (
        <p className="muted">{t("kb.projects.none")}</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("kb.projects.project")}</th>
                <th>{t("kb.projects.record")}</th>
                <th>{t("kb.projects.files")}</th>
                <th>{t("kb.standard.title")}</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <Fragment key={p.id}>
                  <tr>
                    <td className="strong">{p.key}</td>
                    <td className="small">
                      {p.record ? (
                        <>
                          <div>{recordSummary(p.record)}</div>
                          {Object.keys(p.record.actual).length > 0 && (
                            <div className="muted">{t("kb.actual")}{t("common.colon")}{actualSummary(p.record, p.labels)}</div>
                          )}
                          <div className="muted">
                            {t("kb.projects.version", { v: p.record_version })} · {p.record_by} · {p.record_at && fmtDate(p.record_at)}
                          </div>
                        </>
                      ) : (
                        <span className="muted">{t("kb.projects.noRecord")}</span>
                      )}
                    </td>
                    <td className="small">
                      <details>
                        <summary>{t("kb.projects.fileCount", { n: p.files.length })}</summary>
                        {p.files.map((f) => (
                          <div key={f.id}>
                            <a href={`/api/kb/files/${f.id}`} target="_blank" rel="noreferrer">
                              {f.name}
                            </a>
                          </div>
                        ))}
                      </details>
                    </td>
                    <td className="small">
                      <label className="check">
                        <input type="checkbox" checked={p.standard.manual} onChange={(e) => onStandard(p, e.target.checked)} />
                        {t("kb.standard.tick")}
                      </label>
                      {p.standard.list && <span className="tag ck-PASS">{t("kb.standard.list")}</span>}
                      {p.standard.manual && p.standard.by && (
                        <div className="muted">
                          {p.standard.by} · {p.standard.at && fmtDate(p.standard.at)}
                        </div>
                      )}
                    </td>
                  </tr>
                  {p.compare && (
                    <tr className="sub-row">
                      <td />
                      <td colSpan={3}>
                        <Compare p={p} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Compare({ p }: { p: KbProject }) {
  const c = p.compare!;
  if (c.skipped) return <p className="muted small">{t("kb.compare.skipped")}</p>;
  return (
    <div className="compare">
      <div className="small strong">{t("kb.compare.title", { version: c.rules_version })}</div>
      <table className="small">
        <thead>
          <tr>
            <th>{t("kb.compare.item")}</th>
            <th>{t("kb.compare.rule")}</th>
            <th>{t("kb.compare.ruleValue")}</th>
            <th>{t("kb.compare.actual")}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {c.rows.map((r) => (
            <tr key={r.name}>
              <td>{p.labels[r.name] ?? r.name}</td>
              <td>{r.rule_id ?? "—"}</td>
              <td>{fmt(r.rule)}</td>
              <td>{fmt(r.actual)}</td>
              <td>{r.rule === null ? <span className="muted">—</span> : <span className={`tag ck-${r.match ? "PASS" : "NOTE"}`}>
                {t(r.match ? "kb.compare.same" : "kb.compare.diff")}</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {c.missing.length > 0 && (
        <p className="muted small">{t("kb.compare.missing", { names: c.missing.map((m) => p.labels[m] ?? m).join(t("common.listSep")) })}</p>
      )}
    </div>
  );
}
