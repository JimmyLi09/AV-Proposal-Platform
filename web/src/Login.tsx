import { FormEvent, useEffect, useState } from "react";
import { api, send, User } from "./api";
import { t, tOr } from "./i18n";

const ROLES = ["Sales", "PM", "工程"]; // 存的是这几个值，显示按界面语言

export function roleLabel(role: string) {
  return tOr(`login.roles.${role}`, role);
}

export default function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const [users, setUsers] = useState<User[]>([]);
  const [name, setName] = useState("");
  const [role, setRole] = useState(ROLES[1]);
  const [error, setError] = useState("");

  useEffect(() => {
    api<User[]>("/users").then(setUsers);
  }, []);

  async function choose(u: User) {
    onLogin(await send<User>("POST", "/session", { user_id: u.id }));
  }

  async function add(e: FormEvent) {
    e.preventDefault();
    try {
      await choose(await send<User>("POST", "/users", { name, role }));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="login">
      <div className="card login-card">
        <div className="brand">
          <div className="brand-name">AUDAX</div>
          <div className="brand-sub">AV PROPOSAL PLATFORM</div>
        </div>
        <h1>{t("login.title")}</h1>
        <p className="muted">{t("login.intro")}</p>
        <div className="name-list">
          {users.map((u) => (
            <button key={u.id} className="btn-outline" onClick={() => choose(u)}>
              {u.name} {u.role && <span className="muted">· {roleLabel(u.role)}</span>}
            </button>
          ))}
          {users.length === 0 && <p className="muted">{t("login.none")}</p>}
        </div>
        <form className="row" onSubmit={add}>
          <input aria-label={t("login.name")} placeholder={t("login.name")} value={name} onChange={(e) => setName(e.target.value)} required />
          <select aria-label={t("login.role")} value={role} onChange={(e) => setRole(e.target.value)}>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {roleLabel(r)}
              </option>
            ))}
          </select>
          <button className="btn-primary">{t("login.add")}</button>
        </form>
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  );
}
