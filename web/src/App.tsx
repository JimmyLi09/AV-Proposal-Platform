import { useEffect, useState } from "react";
import { api, User } from "./api";
import Login from "./Login";
import ProjectDetail from "./ProjectDetail";
import Projects from "./Projects";
import Products from "./Products";
import Rules from "./Rules";
import Templates from "./Templates";
import Workspace from "./Workspace";

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
  const proposalId = hash.match(/^#\/proposals\/(\d+)/)?.[1];
  const page = hash.startsWith("#/rules") ? "rules" : hash.startsWith("#/products") ? "products"
    : hash.startsWith("#/templates") ? "templates" : "projects";

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
        <a href="#/" className={`nav-item ${page === "projects" ? "active" : ""}`}>
          Projects<span className="zh">项目</span>
        </a>
        <a href="#/products" className={`nav-item ${page === "products" ? "active" : ""}`}>
          Product Library<span className="zh">产品库</span>
        </a>
        <a href="#/rules" className={`nav-item ${page === "rules" ? "active" : ""}`}>
          Rules Engine<span className="zh">规则引擎</span>
        </a>
        <a href="#/templates" className={`nav-item ${page === "templates" ? "active" : ""}`}>
          Templates<span className="zh">模板</span>
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
        <main className="main">
          {page === "rules" ? <Rules /> : page === "products" ? <Products /> : page === "templates" ? <Templates />
            : proposalId ? <Workspace id={Number(proposalId)} />
            : projectId ? <ProjectDetail id={Number(projectId)} /> : <Projects />}
        </main>
      </div>
    </div>
  );
}
