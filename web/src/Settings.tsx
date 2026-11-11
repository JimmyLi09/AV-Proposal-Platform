import { FormEvent, useEffect, useState } from "react";
import { api, send, User } from "./api";
import { t } from "./i18n";
import { fmtDateTime, fmtSize } from "./labels";
import { roleLabel, ROLES } from "./Login";

type Backup = { name: string; size: number; at: string };
type Progress = { running: boolean; done: number; total: number; by: string; started: string; name: string | null; error: string | null };
type SettingsData = {
  users: (User & { proposals: number })[];
  server: { port: number; data_dir: string; kb_dir: string; backup_dir: string; project_platform: string; dwg: boolean; version: string | null };
  backups: Backup[];
  backup: Progress | null;
};

/** 设置：人员（加人、改角色）、审批规则、服务器与存储（只显示）、立即备份。 */
export default function Settings() {
  const [s, setS] = useState<SettingsData | null>(null);
  const [name, setName] = useState("");
  const [role, setRole] = useState(ROLES[1]);
  const [error, setError] = useState("");
  const load = () => api<SettingsData>("/settings").then(setS);
  useEffect(() => {
    load();
  }, []);
  useEffect(() => {  // 备份在后台做：做完前每秒刷新进度
    if (!s?.backup?.running) return;
    const timer = window.setTimeout(load, 1000);
    return () => window.clearTimeout(timer);
  }, [s]);
  if (!s) return null;

  async function add(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await send("POST", "/users", { name, role });
      setName("");
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  }
  const setUserRole = async (id: number, r: string) => {
    await send("PUT", `/users/${id}`, { role: r });
    await load();
  };
  async function backup() {
    setError("");
    try {
      await send("POST", "/backups", {});
    } catch (err) {
      setError((err as Error).message);
    }
    await load();
  }
  const sv = s.server;
  const b = s.backup;
  const rows: [string, string, string?][] = [
    [t("settings.platform"), `${location.host}`, t("settings.platformNote")],
    [t("settings.projectPlatform"), sv.project_platform || t("settings.notSet"), t("settings.projectPlatformNote")],
    [t("settings.dataDir"), sv.data_dir],
    [t("settings.kbDir"), sv.kb_dir],
    [t("settings.backupDir"), sv.backup_dir],
    [t("settings.dwg"), t(sv.dwg ? "settings.dwgYes" : "settings.dwgNo")],
    [t("settings.version"), sv.version ?? t("settings.devVersion")],
  ];

  return (
    <>
      <h1>{t("settings.title")}</h1>
      <p className="muted">{t("settings.intro")}</p>

      <section className="card">
        <h2>{t("settings.people")}</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("settings.name")}</th>
                <th>{t("settings.role")}</th>
                <th>{t("settings.proposals")}</th>
              </tr>
            </thead>
            <tbody>
              {s.users.map((u) => (
                <tr key={u.id}>
                  <td className="strong">{u.name}</td>
                  <td>
                    <select aria-label={`${u.name} ${t("settings.role")}`} value={u.role} onChange={(e) => setUserRole(u.id, e.target.value)}>
                      {(ROLES.includes(u.role) ? ROLES : [u.role, ...ROLES]).map((r) => (
                        <option key={r} value={r}>{r ? roleLabel(r) : "—"}</option>
                      ))}
                    </select>
                  </td>
                  <td>{u.proposals}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <form className="row" onSubmit={add}>
          <input aria-label={t("settings.name")} placeholder={t("settings.name")} value={name} onChange={(e) => setName(e.target.value)} required />
          <select aria-label={t("settings.role")} value={role} onChange={(e) => setRole(e.target.value)}>
            {ROLES.map((r) => (
              <option key={r} value={r}>{roleLabel(r)}</option>
            ))}
          </select>
          <button className="btn-outline">{t("settings.addName")}</button>
        </form>
        <p className="muted small">{t("settings.loginNote")}</p>
      </section>

      <section className="card">
        <h2>{t("settings.approval")}</h2>
        <p>{t("settings.approvalText")}</p>
        <p className="muted small">{t("settings.approvalRecorded")}</p>
      </section>

      <section className="card">
        <h2>{t("settings.server")}</h2>
        <div className="table-wrap">
          <table>
            <tbody>
              {rows.map(([k, v, note]) => (
                <tr key={k}>
                  <th>{k}</th>
                  <td className="mono">{v}</td>
                  <td className="muted small">{note ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted small">{t("settings.configNote")}</p>
      </section>

      <section className="card">
        <h2>{t("settings.backup")}</h2>
        <p className="muted">{t("settings.backupIntro")}</p>
        <div className="row">
          <button className="btn-primary" disabled={!!b?.running} onClick={backup}>{t("settings.backupNow")}</button>
          {b?.running && <span className="muted">{t("settings.backingUp", { done: b.done, total: b.total || "…" })}</span>}
          {b && !b.running && !b.error && b.name && <span className="ok-text">{t("settings.backupDone", { name: b.name })}</span>}
          {b?.error && <span className="error">{t("settings.backupError", { error: b.error })}</span>}
        </div>
        {error && <p className="error">{error}</p>}
        {s.backups.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("settings.backupName")}</th>
                  <th>{t("settings.backupSize")}</th>
                  <th>{t("settings.backupAt")}</th>
                </tr>
              </thead>
              <tbody>
                {s.backups.map((x) => (
                  <tr key={x.name}>
                    <td className="mono">{x.name}</td>
                    <td>{fmtSize(x.size)}</td>
                    <td>{fmtDateTime(x.at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="muted">{t("settings.noBackups")}</p>}
        <p className="muted small">{t("settings.restore")}</p>
      </section>
    </>
  );
}
