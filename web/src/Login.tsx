import { FormEvent, useEffect, useState } from "react";
import { api, send, User } from "./api";

const ROLES = ["Sales", "PM", "工程"];

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
        <h1>
          Choose your name <span className="zh">选择名字</span>
        </h1>
        <p className="muted">不用密码。名字用来记录每个 Rev 是谁做的、谁审的。</p>
        <div className="name-list">
          {users.map((u) => (
            <button key={u.id} className="btn-outline" onClick={() => choose(u)}>
              {u.name} {u.role && <span className="muted">· {u.role}</span>}
            </button>
          ))}
          {users.length === 0 && <p className="muted">还没有名字，先在下面添加。</p>}
        </div>
        <form className="row" onSubmit={add}>
          <input aria-label="Name 名字" placeholder="Name 名字" value={name} onChange={(e) => setName(e.target.value)} required />
          <select aria-label="Role 角色" value={role} onChange={(e) => setRole(e.target.value)}>
            {ROLES.map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
          <button className="btn-primary">Add name 添加名字</button>
        </form>
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  );
}
