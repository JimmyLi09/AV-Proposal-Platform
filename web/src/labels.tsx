export const LINE_LABEL: Record<string, string> = {
  LED: "LED Screen LED 屏",
  PJ: "Projection 投影 · 单面墙",
};

const STATUS_LABEL: Record<string, string> = {
  draft: "Draft 草稿",
  confirming: "Awaiting confirmation 待确认",
  calculated: "Calculated 已计算",
};

export function StatusTag({ status, rev }: { status: string; rev: number }) {
  return (
    <span className="tag">
      {STATUS_LABEL[status] ?? status} · Rev {rev}
    </span>
  );
}

export function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function fmtSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
