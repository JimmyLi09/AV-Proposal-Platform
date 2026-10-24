import { lang, t, tOr } from "./i18n";

export const LINES = ["LED", "PJ"];

export function lineLabel(line: string) {
  return t(`lines.${line}`);
}

/** 库类页面（产品库 / 规则 / 模板）顶部的业务线切换。 */
export function LineTabs({ page, line }: { page: string; line: string }) {
  return (
    <span className="row tight" role="tablist" aria-label={t("project.line")}>
      {LINES.map((l) => (
        <a key={l} href={`#/${page}/${l}`} className={`pill ${l === line ? "active" : ""}`}>
          {lineLabel(l)}
        </a>
      ))}
    </span>
  );
}

export function StatusTag({ status, rev }: { status: string; rev: number }) {
  return (
    <span className="tag">
      {tOr(`status.${status}`, status)} · Rev {rev}
    </span>
  );
}

export function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString(lang() === "zh" ? "zh-CN" : "en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function fmtSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
