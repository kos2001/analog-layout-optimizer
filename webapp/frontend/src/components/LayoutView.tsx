import { useEffect, useState } from "react";
import { fetchLayoutShapes } from "../api";
import { useT } from "../i18n";
import type { LayoutShapes } from "../types";

export default function LayoutView() {
  const { t } = useT();
  const [which, setWhich] = useState<"ota" | "mirror">("ota");
  const [data, setData] = useState<LayoutShapes | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setData(null); setErr(null);
    fetchLayoutShapes(which).then(setData).catch((e) => setErr(String(e)));
  }, [which]);

  if (err) return <div className="fatal">Error: {err}</div>;

  const W = 820, H = 520, pad = 16;
  let sx = (x: number) => x, sy = (y: number) => y, scale = 1;
  if (data) {
    const [x0, y0, x1, y1] = data.bbox;
    const w = x1 - x0 || 1, h = y1 - y0 || 1;
    scale = Math.min((W - 2 * pad) / w, (H - 2 * pad) / h);
    const ox = (W - w * scale) / 2, oy = (H - h * scale) / 2;
    sx = (x: number) => ox + (x - x0) * scale;
    sy = (y: number) => H - (oy + (y - y0) * scale);   // y-up world -> y-down screen
  }
  const toggle = (n: string) =>
    setHidden((s) => { const c = new Set(s); c.has(n) ? c.delete(n) : c.add(n); return c; });

  return (
    <div className="grid">
      <section className="panel" style={{ gridColumn: "1 / -1" }}>
        <div className="panel-title">
          {t("lay.title")}
          {data && <span className="badge">{data.topCell} · {data.nPolygons} polygons</span>}
        </div>
        <div className="seg" style={{ marginBottom: 8 }}>
          <button className={which === "ota" ? "" : "secondary"} onClick={() => setWhich("ota")}>{t("lay.ota")}</button>
          <button className={which === "mirror" ? "" : "secondary"} onClick={() => setWhich("mirror")}>{t("lay.mirror")}</button>
        </div>
        {!data ? <div className="loading">{t("loading")}</div> : (
          <div className="maze-wrap">
            <svg width={W} height={H} style={{ background: "#0b0d12", borderRadius: 8, maxWidth: "100%" }}>
              {data.layers.map((L) => hidden.has(L.name) ? null : (
                <g key={L.name}>
                  {L.polys.map((poly, i) => (
                    <polygon key={i}
                      points={poly.map(([x, y]) => `${sx(x).toFixed(1)},${sy(y).toFixed(1)}`).join(" ")}
                      fill={L.color} fillOpacity={0.45} stroke={L.color} strokeWidth={0.6} strokeOpacity={0.9} />
                  ))}
                  {L.labels.map((lb, i) => (
                    <text key={`t${i}`} x={sx(lb.x)} y={sy(lb.y)} fontSize={9} fill="#fff"
                      textAnchor="middle" style={{ pointerEvents: "none" }}>{lb.text}</text>
                  ))}
                </g>
              ))}
            </svg>
            <div className="maze-side">
              <div className="legend" style={{ flexDirection: "column", gap: 4 }}>
                {data.layers.map((L) => (
                  <label key={L.name} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, cursor: "pointer", opacity: hidden.has(L.name) ? 0.4 : 1 }}>
                    <input type="checkbox" checked={!hidden.has(L.name)} onChange={() => toggle(L.name)} />
                    <i className="sw" style={{ background: L.color, borderColor: L.color }} />
                    {L.name} <span style={{ color: "var(--muted)" }}>{L.layer}/{L.datatype} · {L.polys.length}</span>
                  </label>
                ))}
              </div>
              <p className="note">{t("lay.note")}</p>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
