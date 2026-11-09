import { useEffect, useState } from "react";
import { revQuery, WorkspaceView } from "./api";
import { lang, t } from "./i18n";

const KINDS = ["elevation", "plan", "section"] as const;

// 投影专属图（第 8 步）：立面融合区、平面机位、剖面遮挡。服务器按 P2–P10 的结果和已确认输入画，和 PDF、Word、演示稿是同一张图。
export default function ProjectionDrawings({ view }: { view: WorkspaceView }) {
  const [svgs, setSvgs] = useState<Record<string, string>>({});
  const base = `/api/proposals/${view.proposal.id}/projection`;
  useEffect(() => {
    Promise.all(KINDS.map((k) => fetch(`${base}/${k}.svg?lang=${lang()}${revQuery(view, "&")}`).then((r) => r.text())))
      .then((list) => setSvgs(Object.fromEntries(KINDS.map((k, i) => [k, list[i]]))));
  }, [view]);
  return (
    <section className="card">
      <h2>{t("pj.title")}</h2>
      <p className="muted">{t("pj.intro")}</p>
      {KINDS.map((k) => (
        <figure key={k} className="pj-drawing">
          <div className="wiring-wrap" dangerouslySetInnerHTML={{ __html: svgs[k] ?? "" }} />
          <figcaption className="row tight">
            <span className="muted small">{t(`pj.notes.${k}`)}</span>
            <span className="grow" />
            <a className="btn-outline small" href={`${base}/${k}.svg?lang=${lang()}${revQuery(view, "&")}`}>{t("pj.download")}</a>
          </figcaption>
        </figure>
      ))}
    </section>
  );
}
