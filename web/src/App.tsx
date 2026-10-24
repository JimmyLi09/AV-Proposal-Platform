import { useEffect, useState } from "react";
import { api, send, User } from "./api";
import { Lang, lang as currentLang, setLang, t } from "./i18n";
import Knowledge from "./Knowledge";
import Login, { roleLabel } from "./Login";
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
  const [lang, setLangState] = useState<Lang>(currentLang());
  const hash = useHash();

  function applyLang(l: Lang) {
    setLang(l);
    setLangState(l);
  }

  function signIn(u: User | null) {
    if (u) applyLang(u.lang); // 按用户保存的语言：换页、刷新、下次登录都保持
    setUser(u);
  }

  useEffect(() => {
    api<User | null>("/session").then(signIn);
  }, []);

  if (user === undefined) return null;
  if (user === null) return <Login onLogin={signIn} />;

  async function toggleLang() {
    const next: Lang = lang === "zh" ? "en" : "zh";
    applyLang(next);
    setUser(await send<User>("PUT", "/session/lang", { lang: next }));
  }

  const projectId = hash.match(/^#\/projects\/(\d+)/)?.[1];
  const proposalId = hash.match(/^#\/proposals\/(\d+)/)?.[1];
  const page = hash.startsWith("#/rules") ? "rules" : hash.startsWith("#/products") ? "products"
    : hash.startsWith("#/templates") ? "templates" : hash.startsWith("#/knowledge") ? "knowledge" : "projects";
  const line = hash.match(/^#\/(?:rules|products|templates)\/(LED|PJ)/)?.[1] ?? "LED"; // 库类页面按业务线分（CR-7）

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
          {t("nav.projects")}
        </a>
        <a href="#/products" className={`nav-item ${page === "products" ? "active" : ""}`}>
          {t("nav.products")}
        </a>
        <a href="#/rules" className={`nav-item ${page === "rules" ? "active" : ""}`}>
          {t("nav.rules")}
        </a>
        <a href="#/templates" className={`nav-item ${page === "templates" ? "active" : ""}`}>
          {t("nav.templates")}
        </a>
        <a href="#/knowledge" className={`nav-item ${page === "knowledge" ? "active" : ""}`}>
          {t("nav.knowledge")}
        </a>
      </nav>
      <div className="body">
        <header className="top">
          <div className="grow" />
          <span>
            <b>{user.name}</b> {user.role && <span className="muted">· {roleLabel(user.role)}</span>}
          </span>
          <button className="btn-link" onClick={switchName}>
            {t("nav.switchName")}
          </button>
          <button className="btn-outline lang-toggle" onClick={toggleLang} aria-label={t("nav.langLabel")}>
            {lang === "zh" ? "EN" : "中文"}
          </button>
        </header>
        <main className="main" key={lang /* 换语言后重新载入当前页，服务器按新语言返回 */}>
          {page === "rules" ? <Rules key={line} line={line} /> : page === "products" ? <Products key={line} line={line} />
            : page === "templates" ? <Templates key={line} line={line} />
            : page === "knowledge" ? <Knowledge />
            : proposalId ? <Workspace key={proposalId} id={Number(proposalId)} />
            : projectId ? <ProjectDetail id={Number(projectId)} /> : <Projects />}
        </main>
      </div>
    </div>
  );
}
