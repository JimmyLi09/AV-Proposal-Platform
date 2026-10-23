import { lang, t, tOr } from "./i18n";

export const LINES = ["LED", "PJ"];

export function lineLabel(line: string) {
  return t(`lines.${line}`);
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
