import { useEffect, useState } from "react";
import { api, User } from "./api";
import Login from "./Login";
import ProjectDetail from "./ProjectDetail";
import Projects from "./Projects";

function useHash() {
  const [hash, setHash] = useState(location.hash);
  useEffect(() => {
    const onChange = () => setHash(location.hash);
    addEventListener("hashchange", onChange);
    return () => removeEventListener("hashchange", onChange);
  }, []);
  return hash;
}

export default function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const hash = useHash();

  useEffect(() => {
    api<User | null>("/session").then(setUser);
  }, []);

  if (user === undefined) return null;
  if (user === null) return <Login onLogin={setUser} />;

  const projectId = hash.match(/^#\/projects\/(\d+)/)?.[1];

  async function switchName() {
    await api("/session", { method: "DELETE" });
    setUser(null);
  }

  return (
    <div className="shell">
      <nav className="side" aria-label="Main menu">
        <div className="brand">
          <div className="brand-name">AUDAX</div>
          <div className="brand-sub">AV PROPOSAL PLATFORM</div>
        </div>
        <a href="#/" className="nav-item active">
          Projects<span className="zh">项目</span>
        </a>
      </nav>
      <div className="body">
        <header className="top">
          <div className="grow" />
          <span>
            <b>{user.name}</b> {user.role && <span className="muted">· {user.role}</span>}
          </span>
          <button className="btn-link" onClick={switchName}>
            Switch name 切换名字
          </button>
        </header>
        <main className="main">{projectId ? <ProjectDetail id={Number(projectId)} /> : <Projects />}</main>
      </div>
    </div>
  );
}
