import { useEffect, useState } from "react";
import { fetchFlow } from "../api";
import { useT } from "../i18n";
import type { FlowData, FlowComponent } from "../types";

const NET_PALETTE = [
  "#42a5f5", "#ef5350", "#66bb6a", "#ffb300", "#ab47bc", "#26c6da",
  "#ff7043", "#ec407a", "#9ccc65", "#8d6e63",
];
const KIND_FILL: Record<string, string> = {
  nmos: "#1c3b57", pmos: "#532a1c", cap: "#3a2a52", port: "#30363d",
};

function FlowGrid({ data, netColor, hover, setHover }: {
  data: FlowData; netColor: (n: string) => string;
  hover: string | null; setHover: (n: string | null) => void;
}) {
  const cs = Math.max(10, Math.floor(620 / data.width));
  const W = data.width * cs, H = data.height * cs;

  return (
    <svg width={W} height={H} className="maze-grid" style={{ maxWidth: "100%" }}>
      <rect width={W} height={H} fill="#0d1117" />
      {Array.from({ length: data.width + 1 }, (_, i) => (
        <line key={`v${i}`} x1={i * cs} y1={0} x2={i * cs} y2={H} stroke="#11161d" />
      ))}
      {Array.from({ length: data.height + 1 }, (_, i) => (
        <line key={`h${i}`} x1={0} y1={i * cs} x2={W} y2={i * cs} stroke="#11161d" />
      ))}
      {/* routed wires (under device blocks) */}
      {data.routing.netNames.map((n) => {
        const nr = data.routing.nets[n];
        if (!nr) return null;
        const dim = hover && hover !== n;
        const col = netColor(n);
        const xy = new Map<string, Set<number>>();
        for (const c of nr.cells) {
          const k = `${c[0]},${c[1]}`;
          if (!xy.has(k)) xy.set(k, new Set());
          xy.get(k)!.add(c[2] ?? 0);
        }
        return (
          <g key={n} opacity={dim ? 0.12 : 1} onMouseEnter={() => setHover(n)} onMouseLeave={() => setHover(null)}>
            {nr.cells.map((c, j) => (
              <rect key={j} x={c[0] * cs + 1} y={c[1] * cs + 1} width={cs - 2} height={cs - 2}
                rx={(c[2] ?? 0) === 1 ? 1 : 3} fill={col} opacity={(c[2] ?? 0) === 1 ? 0.4 : 0.85} />
            ))}
            {[...xy.entries()].filter(([, s]) => s.size > 1).map(([k], j) => {
              const [x, y] = k.split(",").map(Number);
              return <circle key={`v${j}`} cx={x * cs + cs / 2} cy={y * cs + cs / 2} r={Math.max(1.5, cs / 6)} fill="#fff" />;
            })}
          </g>
        );
      })}
      {/* device blocks + terminal pins */}
      {data.components.map((c: FlowComponent) => {
        const x = c.x * cs, y = c.y * cs, w = c.w * cs, h = c.h * cs;
        const touch = hover && c.pins.some((p) => p.net === hover);
        return (
          <g key={c.id}>
            <rect x={x + 1} y={y + 1} width={w - 2} height={h - 2} rx={3}
              fill={KIND_FILL[c.kind] ?? "#30363d"}
              stroke={touch ? "#fff" : "#586069"} strokeWidth={touch ? 1.8 : 1} />
            {c.kind !== "port" && (
              <text x={x + w / 2} y={y + h / 2 + 3} textAnchor="middle" fontSize={9}
                fill="#c9d1d9" style={{ pointerEvents: "none" }}>{c.label}</text>
            )}
            {c.pins.map((p, i) => (
              <rect key={i} x={(c.x + p.dx) * cs + 2.5} y={(c.y + p.dy) * cs + 2.5}
                width={cs - 5} height={cs - 5} rx={2}
                fill={netColor(p.net)} stroke={hover === p.net ? "#fff" : "#0d1117"} strokeWidth={1}
                onMouseEnter={() => setHover(p.net)} onMouseLeave={() => setHover(null)}>
                <title>{c.label}.{/* terminal */}{p.net}</title>
              </rect>
            ))}
          </g>
        );
      })}
    </svg>
  );
}

export default function FlowView() {
  const { t } = useT();
  const [place, setPlace] = useState<"sa" | "random">("sa");
  const [seed, setSeed] = useState(0);
  const [data, setData] = useState<FlowData | null>(null);
  const [busy, setBusy] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);

  useEffect(() => {
    setBusy(true); setErr(null);
    fetchFlow(place, seed).then(setData).catch((e) => setErr(String(e))).finally(() => setBusy(false));
  }, [place, seed]);

  if (err) return <div className="fatal">Error: {err}</div>;

  const names = data ? Object.keys(data.netlist) : [];
  const netColor = (n: string) => NET_PALETTE[Math.max(0, names.indexOf(n)) % NET_PALETTE.length];
  const r = data?.routing;

  return (
    <div className="grid">
      <section className="panel" style={{ gridColumn: "1 / -1" }}>
        <div className="panel-title">
          {t("flow.title")}
          {r && <span className={r.failed.length ? "badge bad" : "badge ok"}>
            {r.failed.length ? `${r.failed.length} unrouted` : t("all.routed")}</span>}
        </div>
        <div className="seg" style={{ marginBottom: 6 }}>
          <button className={place === "sa" ? "" : "secondary"} onClick={() => setPlace("sa")}>{t("flow.sa")}</button>
          <button className={place === "random" ? "" : "secondary"} onClick={() => setPlace("random")}>{t("flow.random")}</button>
          <button className="secondary" onClick={() => setSeed(Math.floor(Math.random() * 1e6))}>{t("flow.rerun")}</button>
        </div>

        {busy || !data || !r ? <div className="loading">{t("flow.running")}</div> : (
          <div className="maze-wrap">
            <FlowGrid data={data} netColor={netColor} hover={hover} setHover={setHover} />
            <div className="maze-side" style={{ minWidth: 280 }}>
              <div className="metrics" style={{ flexDirection: "column", gap: 8 }}>
                <div><span className="metric-label">{t("flow.hpwl")}</span><span className="metric-value">{data.hpwl}</span></div>
                <div><span className="metric-label">{t("maze.total.wl")}</span><span className="metric-value">{r.totalWirelength}</span></div>
                <div><span className="metric-label">vias</span><span className="metric-value">{r.totalVias}</span></div>
              </div>
              <div className="panel-title" style={{ fontSize: 13, marginTop: 6 }}>{t("flow.netlist")}</div>
              <div style={{ maxHeight: 320, overflowY: "auto" }}>
                <table className="tcoil-table" style={{ fontSize: 12 }}>
                  <tbody>
                    {names.map((n) => (
                      <tr key={n} onMouseEnter={() => setHover(n)} onMouseLeave={() => setHover(null)}
                        style={{ background: hover === n ? "#1c2128" : "transparent", cursor: "default" }}>
                        <td style={{ whiteSpace: "nowrap" }}>
                          <i className="sw" style={{ background: netColor(n), borderColor: netColor(n) }} />{n}
                        </td>
                        <td style={{ color: "var(--muted)" }}>{data.netlist[n].join(", ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
        <p className="note" style={{ marginTop: 12 }}>{t("flow.note")}</p>
      </section>
    </div>
  );
}
