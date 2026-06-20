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

function FlowGrid({ data, netColor, hover, setHover, showDrc }: {
  data: FlowData; netColor: (n: string) => string;
  hover: string | null; setHover: (n: string | null) => void; showDrc: boolean;
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
      {/* DRC violation markers */}
      {showDrc && data.routing.drc.violations.map((v, i) => {
        const col = v.rule === "corner" ? "#ffd54f" : "#ff1744";
        return v.cells.map((c, j) => {
          const cx = c[0] * cs + cs / 2, cy = c[1] * cs + cs / 2, r = cs * 0.42;
          return (
            <g key={`d${i}-${j}`}>
              <circle cx={cx} cy={cy} r={r} fill="none" stroke={col} strokeWidth={1.6} />
              <line x1={cx - r * 0.6} y1={cy - r * 0.6} x2={cx + r * 0.6} y2={cy + r * 0.6} stroke={col} strokeWidth={1.4} />
              <line x1={cx - r * 0.6} y1={cy + r * 0.6} x2={cx + r * 0.6} y2={cy - r * 0.6} stroke={col} strokeWidth={1.4} />
              <title>{v.rule}: {v.message}</title>
            </g>
          );
        });
      })}
    </svg>
  );
}

function SignoffPanel({ data }: { data: FlowData }) {
  const { t } = useT();
  const so = data.signoff;
  const pass = so.verdict === "PASS";
  return (
    <div style={{
      border: `1px solid ${pass ? "var(--ok)" : "var(--bad)"}`, borderRadius: 8,
      padding: "10px 14px", margin: "6px 0 12px", background: "#0d1117",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <strong style={{ fontSize: 13 }}>{t("flow.signoff")}</strong>
        <span className={pass ? "badge ok" : "badge bad"} style={{ fontSize: 13 }}>
          {pass ? `✓ ${t("flow.signoff.pass")}` : `✗ ${t("flow.signoff.fail")}`}
        </span>
        {so.drcWarnings > 0 && (
          <span style={{ fontSize: 12, color: "var(--muted)" }}>{so.drcWarnings} {t("flow.warnings")}</span>
        )}
      </div>
      <div style={{ display: "flex", gap: 18, flexWrap: "wrap", marginTop: 8 }}>
        {so.checks.map((c) => (
          <div key={c.name} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ color: c.status === "pass" ? "var(--ok)" : "var(--bad)", fontWeight: 700 }}>
              {c.status === "pass" ? "✓" : "✗"}
            </span>
            <span style={{ fontSize: 12 }}><b>{c.name}</b> <span style={{ color: "var(--muted)" }}>— {c.detail}</span></span>
          </div>
        ))}
      </div>
    </div>
  );
}

function PostLayoutPanel({ data }: { data: FlowData }) {
  const { t } = useT();
  const pl = data.postlayout;
  const row = (label: string, pre: number, post: number, unit: string, lowerWorse = true) => {
    const degraded = lowerWorse ? post < pre - 0.05 : post > pre + 0.05;
    return (
      <tr>
        <td>{label}</td>
        <td>{pre}{unit}</td>
        <td style={{ color: degraded ? "var(--bad)" : "var(--ok)" }}>{post}{unit}</td>
      </tr>
    );
  };
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "10px 14px", margin: "0 0 12px", background: "#0d1117" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <strong style={{ fontSize: 13 }}>{t("flow.post.title")}</strong>
        <span className={pl.stable ? "badge ok" : "badge bad"} style={{ fontSize: 12 }}>
          {pl.stable ? t("flow.post.stable") : t("flow.post.unstable")}
        </span>
        <span style={{ fontSize: 12, color: pl.deltaPM < -10 ? "var(--bad)" : "var(--muted)" }}>
          ΔPM {pl.deltaPM}°
        </span>
      </div>
      <div style={{ display: "flex", gap: 24, flexWrap: "wrap", marginTop: 8 }}>
        <table className="tcoil-table" style={{ fontSize: 12, maxWidth: 320 }}>
          <thead><tr><th></th><th>{t("flow.post.schem")}</th><th>{t("flow.post.post")}</th></tr></thead>
          <tbody>
            {row("gain", pl.pre.gain_db, pl.post.gain_db, " dB", false)}
            {row("GBW", pl.pre.gbw_mhz, pl.post.gbw_mhz, " MHz")}
            {row("PM", pl.pre.pm_deg, pl.post.pm_deg, "°")}
          </tbody>
        </table>
        <div className="metrics" style={{ flexDirection: "column", gap: 6, fontSize: 12 }}>
          <strong style={{ fontSize: 12, color: "var(--muted)" }}>{t("flow.post.critical")}</strong>
          {Object.entries(pl.critical).map(([net, p]) => (
            <span key={net} style={{ color: "var(--muted)" }}>
              <b style={{ color: "var(--text)" }}>{net}</b>: wl {p.wirelength}, {p.C_fF} fF, {p.R_ohm} Ω
            </span>
          ))}
          {pl.post.p_n2_mhz != null && (
            <span style={{ color: "var(--muted)" }}>n2 parasitic pole ≈ {pl.post.p_n2_mhz} MHz</span>
          )}
        </div>
      </div>
      <p className="note" style={{ marginTop: 8 }}>{t("flow.post.note")}</p>
    </div>
  );
}

export default function FlowView() {
  const { t } = useT();
  const [place, setPlace] = useState<"sa" | "random">("sa");
  const [seed, setSeed] = useState(1);
  const [data, setData] = useState<FlowData | null>(null);
  const [busy, setBusy] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [showDrc, setShowDrc] = useState(true);

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
          <button className={showDrc ? "" : "secondary"} onClick={() => setShowDrc((s) => !s)}>{t("flow.drc.toggle")}</button>
        </div>

        {data && <SignoffPanel data={data} />}
        {data && <PostLayoutPanel data={data} />}

        {busy || !data || !r ? <div className="loading">{t("flow.running")}</div> : (
          <div className="maze-wrap">
            <FlowGrid data={data} netColor={netColor} hover={hover} setHover={setHover} showDrc={showDrc} />
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
