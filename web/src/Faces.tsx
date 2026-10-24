import { useState } from "react";
import { CornerInput, FaceInput, SourceValue, WorkspaceView } from "./api";
import { t, tOr } from "./i18n";

const LETTERS = "ABCDEFGHIJ";
const START_FACES: Record<string, number> = { L: 2, L_wall_floor: 2, outside_corner: 2, U: 3, cube: 4, custom: 2, curved: 1, ring: 1, wall_floor: 2 };
const CORNER_TYPE: Record<string, string> = { outside_corner: "outside_corner", L_wall_floor: "fold_wall_to_floor", wall_floor: "fold_wall_to_floor" };
const CORNER_TYPES = ["inside_90", "outside_corner", "fold_wall_to_floor"];
const ORIENTATIONS = ["wall", "floor", "ceiling"];
const KINDS = ["plan", "elevation", "spec", "other"];

export const shapeLabel = (s: string) => tOr(`shape.${s}`, s);
export const isMulti = (view: WorkspaceView, inputs: Record<string, unknown>) =>
  !!inputs.shape && inputs.shape !== view.shapes[0] && ((inputs.faces as FaceInput[] | undefined)?.length ?? 0) > 0;
const num = (s: string) => (s === "" ? null : Number(s));

function cornersFor(shape: string, faces: FaceInput[], old: CornerInput[]): CornerInput[] {
  if (shape === "curved" || shape === "ring") return [];
  return faces.slice(1).map((f, i) => {
    const pair: [string, string] = [faces[i].id, f.id];
    return old.find((c) => c.between[0] === pair[0] && c.between[1] === pair[1]) ?? { between: pair, type: CORNER_TYPE[shape] ?? "inside_90" };
  });
}

/** 屏形与分面（CR-7 · S1 / S2 / P18）：先判断屏形；多面屏每一面单独输入尺寸，资料对不上的列出各份资料的值。 */
export default function ShapeFaces({ view, inputs, setInputs }: {
  view: WorkspaceView;
  inputs: Record<string, unknown>;
  setInputs: (v: Record<string, unknown>) => void;
}) {
  const led = view.proposal.business_line === "LED";
  const shape = (inputs.shape as string | undefined) ?? view.shapes[0];
  const faces = (inputs.faces as FaceInput[] | undefined) ?? [];
  const corners = (inputs.corners as CornerInput[] | undefined) ?? [];
  const multi = shape !== view.shapes[0];
  const [open, setOpen] = useState<string | null>(null);

  function setShape(s: string) {
    if (s === view.shapes[0]) {
      const rest = { ...inputs };
      delete rest.faces;
      delete rest.corners;
      return setInputs({ ...rest, shape: s });
    }
    const list = faces.length ? faces : Array.from({ length: START_FACES[s] ?? 2 }, (_, i) =>
      ({ id: LETTERS[i], name: "", orientation: (s === "L_wall_floor" || s === "wall_floor") && i > 0 ? "floor" : "wall", width_mm: null, height_mm: null }));
    setInputs({ ...inputs, shape: s, faces: list, corners: cornersFor(s, list, corners) });
  }
  const setFaces = (list: FaceInput[]) => setInputs({ ...inputs, faces: list, corners: cornersFor(shape, list, corners) });
  const setFace = (i: number, patch: Partial<FaceInput>) => setFaces(faces.map((f, j) => (j === i ? { ...f, ...patch } : f)));
  const setCorner = (i: number, patch: Partial<CornerInput>) =>
    setInputs({ ...inputs, corners: corners.map((c, j) => (j === i ? { ...c, ...patch } : c)) });
  const field = (k: string) => (e: { target: { value: string } }) => setInputs({ ...inputs, [k]: num(e.target.value) });

  return (
    <section className="card">
      <h2>{t("faces.title")}</h2>
      <p className="muted">{t(led ? "faces.introLed" : "faces.introPj")}</p>
      <div className="row">
        <label className="row tight">
          {t("faces.shape")}
          <select aria-label={t("faces.shape")} value={shape} onChange={(e) => setShape(e.target.value)}>
            {view.shapes.map((s) => (
              <option key={s} value={s}>
                {shapeLabel(s)}
              </option>
            ))}
          </select>
        </label>
        {view.shape_guess !== shape && (
          <span className="muted small">
            {t("faces.guess", { shape: shapeLabel(view.shape_guess) })}{" "}
            <button className="btn-link" onClick={() => setShape(view.shape_guess)}>
              {t("faces.useGuess")}
            </button>
          </span>
        )}
      </div>
      {multi && (
        <>
          <div className="table-wrap">
            <table className="faces">
              <thead>
                <tr>
                  <th>{t("faces.face")}</th>
                  <th>{t("faces.name")}</th>
                  {led && <th>{t("faces.orientation")}</th>}
                  <th>{t("faces.width")}</th>
                  <th>{t("faces.height")}</th>
                  {led ? (
                    <>
                      <th>{t("faces.signal")}</th>
                      <th>{t("faces.power")}</th>
                      <th>{t("faces.special")}</th>
                    </>
                  ) : (
                    <>
                      <th>{t("faces.depth")}</th>
                      <th>{t("faces.mountHeight")}</th>
                    </>
                  )}
                  <th />
                </tr>
              </thead>
              <tbody>
                {faces.map((f, i) => (
                  <FaceRow key={f.id} f={f} led={led} open={open === f.id} onOpen={() => setOpen(open === f.id ? null : f.id)}
                    onChange={(patch) => setFace(i, patch)} onRemove={faces.length > 1 ? () => setFaces(faces.filter((_, j) => j !== i)) : undefined} />
                ))}
              </tbody>
            </table>
          </div>
          <div className="row">
            <button className="btn-outline" onClick={() => setFaces([...faces, { id: LETTERS[faces.length] ?? `F${faces.length + 1}`, name: "", orientation: "wall", width_mm: null, height_mm: null }])}>
              {t("faces.add")}
            </button>
            <span className="muted small">{t(led ? "faces.perFaceLed" : "faces.perFacePj")}</span>
          </div>
          {corners.length > 0 && (
            <>
              <h3>{t("faces.corners")}</h3>
              {corners.map((c, i) => (
                <div key={c.between.join("/")} className="row tight">
                  <b>{c.between.join(" / ")}</b>
                  <select aria-label={`${c.between.join(" / ")} ${t("faces.cornerType")}`} value={c.type} onChange={(e) => setCorner(i, { type: e.target.value })}>
                    {CORNER_TYPES.map((k) => (
                      <option key={k} value={k}>
                        {t(`faces.cornerTypes.${k}`)}
                      </option>
                    ))}
                  </select>
                  {led ? (
                    c.type === "inside_90" && <input className="wide" aria-label={t("faces.overlap")} placeholder={t("faces.overlapHint")}
                      value={c.overlap ?? ""} onChange={(e) => setCorner(i, { overlap: e.target.value })} />
                  ) : (
                    <input className="wide" aria-label={t("faces.resolution")} placeholder={t("faces.resolutionHint")}
                      value={c.resolution ?? ""} onChange={(e) => setCorner(i, { resolution: e.target.value })} />
                  )}
                </div>
              ))}
            </>
          )}
          {led && (
            <div className="form inputs">
              <label>
                {t("faces.weight")} <span className="muted">(kg)</span>
                <input type="number" step="any" className="num" value={(inputs.total_weight_kg as number | null) ?? ""} onChange={field("total_weight_kg")} />
              </label>
              <label>
                {t("faces.refCircuits")}
                <input type="number" step="any" className="num" value={(inputs.reference_circuits as number | null) ?? ""} onChange={field("reference_circuits")} />
              </label>
              <label>
                {t("faces.refData")}
                <input type="number" step="any" className="num" value={(inputs.reference_data_cables as number | null) ?? ""} onChange={field("reference_data_cables")} />
              </label>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function FaceRow({ f, led, open, onOpen, onChange, onRemove }: {
  f: FaceInput;
  led: boolean;
  open: boolean;
  onOpen: () => void;
  onChange: (patch: Partial<FaceInput>) => void;
  onRemove?: () => void;
}) {
  const text = (k: keyof FaceInput) => ({ value: (f[k] as string | undefined) ?? "", onChange: (e: { target: { value: string } }) => onChange({ [k]: e.target.value }) });
  const number = (k: keyof FaceInput) => ({ type: "number", step: "any", className: "num", value: (f[k] as number | null | undefined) ?? "",
    onChange: (e: { target: { value: string } }) => onChange({ [k]: num(e.target.value) }) });
  const sources = (f.width_sources?.length ?? 0) + (f.height_sources?.length ?? 0);
  const cols = led ? 9 : 7;
  return (
    <>
      <tr>
        <td className="strong">{f.id}</td>
        <td><input aria-label={`${f.id} ${t("faces.name")}`} {...text("name")} /></td>
        {led && (
          <td>
            <select aria-label={`${f.id} ${t("faces.orientation")}`} value={f.orientation ?? "wall"} onChange={(e) => onChange({ orientation: e.target.value })}>
              {ORIENTATIONS.map((o) => (
                <option key={o} value={o}>
                  {t(`faces.orientations.${o}`)}
                </option>
              ))}
            </select>
          </td>
        )}
        <td><input aria-label={`${f.id} ${t("faces.width")}`} {...number("width_mm")} /></td>
        <td><input aria-label={`${f.id} ${t("faces.height")}`} {...number("height_mm")} /></td>
        {led ? (
          <>
            <td><input aria-label={`${f.id} ${t("faces.signal")}`} {...text("signal_point")} /></td>
            <td><input aria-label={`${f.id} ${t("faces.power")}`} {...text("power_point")} /></td>
            <td>
              <input aria-label={`${f.id} ${t("faces.protection")}`} placeholder={t("faces.protection")} {...text("protection")} />
              <input aria-label={`${f.id} ${t("faces.load")}`} placeholder={t("faces.load")} {...text("load")} />
            </td>
          </>
        ) : (
          <>
            <td><input aria-label={`${f.id} ${t("faces.depth")}`} {...number("depth_mm")} /></td>
            <td><input aria-label={`${f.id} ${t("faces.mountHeight")}`} {...number("mount_height_m")} /></td>
          </>
        )}
        <td className="nowrap">
          {led && (
            <button className="btn-link" onClick={onOpen}>
              {t("faces.sources", { n: sources })}
            </button>
          )}
          {onRemove && (
            <button className="btn-link" onClick={onRemove}>
              {t("common.remove")}
            </button>
          )}
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={cols}>
            <Sources label={t("faces.width")} list={f.width_sources ?? []} onChange={(l) => onChange({ width_sources: l })}
              onUse={(v) => onChange({ width_mm: v })} chosen={f.width_mm ?? null} />
            <Sources label={t("faces.height")} list={f.height_sources ?? []} onChange={(l) => onChange({ height_sources: l })}
              onUse={(v) => onChange({ height_mm: v })} chosen={f.height_mm ?? null} />
          </td>
        </tr>
      )}
    </>
  );
}

/** S7：同一尺寸在不同资料里的值。值不一样又没选定时不能计算；点「用这个」选定。 */
function Sources({ label, list, onChange, onUse, chosen }: {
  label: string;
  list: SourceValue[];
  onChange: (l: SourceValue[]) => void;
  onUse: (v: number) => void;
  chosen: number | null;
}) {
  const set = (i: number, patch: Partial<SourceValue>) => onChange(list.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  return (
    <div className="detail">
      <b>
        {label} · {t("faces.sourceTitle")}
      </b>
      {list.map((s, i) => (
        <div key={i} className="row tight">
          <input aria-label={t("faces.sourceName")} placeholder={t("faces.sourceName")} value={s.src} onChange={(e) => set(i, { src: e.target.value })} />
          <select aria-label={t("faces.sourceKind")} value={s.kind} onChange={(e) => set(i, { kind: e.target.value })}>
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {t(`faces.kinds.${k}`)}
              </option>
            ))}
          </select>
          <input type="number" step="any" className="num" aria-label={t("faces.sourceValue")} value={s.value ?? ""}
            onChange={(e) => set(i, { value: Number(e.target.value) })} />
          {chosen === s.value ? <span className="tag ck-PASS">{t("faces.chosen")}</span> : (
            <button className="btn-link" onClick={() => onUse(s.value)}>
              {t("faces.use")}
            </button>
          )}
          <button className="btn-link" onClick={() => onChange(list.filter((_, j) => j !== i))}>
            {t("common.remove")}
          </button>
        </div>
      ))}
      <button className="btn-link" onClick={() => onChange([...list, { src: "", kind: "plan", value: 0 }])}>
        {t("faces.addSource")}
      </button>
    </div>
  );
}
