import { useEffect, useMemo, useState } from "react";
import { fetchPPA } from "../api";
import { useT } from "../i18n";
import type { PPAData, PPAPoint } from "../types";

// area -> color (low area = green/good, high = red/costly)
function areaColor(a: number, lo: number, hi: number): string {
  const t = hi > lo ? (a - lo) / (hi - lo) : 0;
  const r = Math.round(80 + t * 175), g = Math.round(200 - t * 150);
  return `rgb(${r},${g},90)`;
}

function selectByWeights(front: PPAPoint[], wp: number, wa: number, wf: number): PPAPoint | null {
  if (!front.length) return null;
  const pw = front.map((p) => p.power_mw), ar = front.map((p) => p.area_um2), gb = front.map((p) => p.gbw_mhz);
  const norm = (v: number, arr: number[]) => {
    const lo = Math.min(...arr), hi = Math.max(...arr);
    return hi > lo ? (v - lo) / (hi - lo) : 0;
  };
  const tot = wp + wa + wf || 1;
  let best: PPAPoint | null = null, bestScore = Infinity;
  for (const p of front) {
    const s = (wp / tot) * norm(p.power_mw, pw) + (wa / tot) * norm(p.area_um2, ar)
      + (wf / tot) * (1 - norm(p.gbw_mhz, gb));
    if (s < bestScore) { best = p; bestScore = s; }
  }
  return best;
}

function ParetoScatter({ data, chosen }: { data: PPAData; chosen: PPAPoint | null }) {
  const W = 540, H = 360, padL = 56, padB = 44, padT = 16, padR = 16;
  const allPow = [...data.pareto.map((p) => p.power_mw), ...data.cloud.map((p) => p.power_mw)];
  const allGbw = [...data.pareto.map((p) => p.gbw_mhz), ...data.cloud.map((p) => p.gbw_mhz)];
  const x0 = Math.min(...allPow), x1 = Math.max(...allPow);
  const y0 = Math.min(...allGbw), y1 = Math.max(...allGbw);
  const aLo = data.ranges.area_um2[0], aHi = data.ranges.area_um2[1];
  const sx = (v: number) => padL + ((v - x0) / (x1 - x0 || 1)) * (W - padL - padR);
  const sy = (v: number) => H - padB - ((v - y0) / (y1 - y0 || 1)) * (H - padT - padB);

  return (
    <svg width={W} height={H} className="bode" style={{ maxWidth: "100%" }}>
      <rect width={W} height={H} fill="#0d1117" />
      {/* axes */}
      <line x1={padL} y1={H - padB} x2={W - padR} y2={H - padB} stroke="#30363d" />
      <line x1={padL} y1={padT} x2={padL} y2={H - padB} stroke="#30363d" />
      {[0, 0.25, 0.5, 0.75, 1].map((t) => {
        const xv = x0 + t * (x1 - x0), yv = y0 + t * (y1 - y0);
        return (
          <g key={t}>
            <text x={sx(xv)} y={H - padB + 16} textAnchor="middle" className="axis">{xv.toFixed(2)}</text>
            <text x={padL - 8} y={sy(yv) + 4} textAnchor="end" className="axis">{yv.toFixed(0)}</text>
          </g>
        );
      })}
      <text x={(W) / 2} y={H - 6} textAnchor="middle" className="axis">power (mW) →</text>
      <text x={14} y={H / 2} textAnchor="middle" className="axis" transform={`rotate(-90 14 ${H / 2})`}>GBW (MHz) →</text>
      {/* dominated cloud */}
      {data.cloud.map((p, i) => (
        <circle key={`c${i}`} cx={sx(p.power_mw)} cy={sy(p.gbw_mhz)} r={2.2} fill="#6e7681" opacity={0.4} />
      ))}
      {/* pareto front (colored by area) */}
      {data.pareto.map((p, i) => (
        <circle key={`p${i}`} cx={sx(p.power_mw)} cy={sy(p.gbw_mhz)} r={4.5}
          fill={areaColor(p.area_um2, aLo, aHi)} stroke="#0d1117" strokeWidth={0.5}>
          <title>GBW {p.gbw_mhz} MHz · P {p.power_mw} mW · A {p.area_um2} µm² · gain {p.gain_db} dB · PM {p.pm_deg}°</title>
        </circle>
      ))}
      {/* chosen */}
      {chosen && (
        <circle cx={sx(chosen.power_mw)} cy={sy(chosen.gbw_mhz)} r={9} fill="none"
          stroke="#fff" strokeWidth={2.5} />
      )}
    </svg>
  );
}

function Weight({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <span style={{ width: 130, fontSize: 13, color: "var(--muted)" }}>{label}</span>
      <input type="range" min={0} max={1} step={0.05} value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))} style={{ flex: 1 }} />
      <span style={{ width: 34, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{value.toFixed(2)}</span>
    </div>
  );
}

export default function PPAView() {
  const { t } = useT();
  const [data, setData] = useState<PPAData | null>(null);
  const [busy, setBusy] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [w, setW] = useState({ power: 0.5, area: 0.3, perf: 0.8 });

  const load = (seed = 0) => {
    setBusy(true); setErr(null);
    fetchPPA(1, 1, 1, seed).then((d) => setData(d)).catch((e) => setErr(String(e))).finally(() => setBusy(false));
  };
  useEffect(() => { load(0); }, []);

  const chosen = useMemo(
    () => (data ? selectByWeights(data.pareto, w.power, w.area, w.perf) : null),
    [data, w],
  );

  if (err) return <div className="fatal">Error: {err}</div>;

  return (
    <div className="grid">
      <section className="panel" style={{ gridColumn: "1 / -1" }}>
        <div className="panel-title">
          {t("ppa.title")}
          {data && <span className="badge">{data.nParetoFront} {t("ppa.front")}</span>}
        </div>
        {busy || !data ? <div className="loading">{t("ppa.running")}</div> : (
          <div className="maze-wrap">
            <ParetoScatter data={data} chosen={chosen} />
            <div className="maze-side" style={{ minWidth: 320 }}>
              <p className="note" style={{ marginTop: 0 }}>{t("ppa.scatter.note")}</p>
              <div style={{ display: "flex", flexDirection: "column", gap: 8, margin: "8px 0" }}>
                <strong style={{ fontSize: 12, color: "var(--muted)" }}>{t("ppa.pref")}</strong>
                <Weight label={t("ppa.w.power")} value={w.power} onChange={(v) => setW({ ...w, power: v })} />
                <Weight label={t("ppa.w.area")} value={w.area} onChange={(v) => setW({ ...w, area: v })} />
                <Weight label={t("ppa.w.perf")} value={w.perf} onChange={(v) => setW({ ...w, perf: v })} />
              </div>
              {chosen && (
                <div className="metrics" style={{ flexDirection: "column", gap: 8 }}>
                  <strong style={{ fontSize: 12, color: "var(--accent)" }}>{t("ppa.chosen")}</strong>
                  <div><span className="metric-label">power</span><span className="metric-value">{chosen.power_mw} mW</span></div>
                  <div><span className="metric-label">GBW</span><span className="metric-value">{chosen.gbw_mhz} MHz</span></div>
                  <div><span className="metric-label">area</span><span className="metric-value">{chosen.area_um2} µm²</span></div>
                  <div><span className="metric-label">gain / PM</span><span className="metric-value">{chosen.gain_db} dB / {chosen.pm_deg}°</span></div>
                  <p className="note">
                    Itail {chosen.sizing.itail_uA} µA · I6 {chosen.sizing.i6_uA} µA ·
                    Cc {chosen.sizing.cc_pF} pF · M1 {chosen.sizing.wl1} · M6 {chosen.sizing.wl6}
                  </p>
                </div>
              )}
              <button className="secondary" onClick={() => load(Math.floor(Math.random() * 1e6))} style={{ marginTop: 6 }}>
                {t("ppa.rerun")}
              </button>
            </div>
          </div>
        )}
        {data && (
          <p className="note" style={{ marginTop: 12 }}>
            {t("ppa.ranges")}: power {data.ranges.power_mw[0]}–{data.ranges.power_mw[1]} mW ·
            GBW {data.ranges.gbw_mhz[0]}–{data.ranges.gbw_mhz[1]} MHz ·
            area {data.ranges.area_um2[0]}–{data.ranges.area_um2[1]} µm². {t("ppa.constraint.note")}
            (gain ≥ {data.constraints.gain_floor_db} dB, PM ≥ {data.constraints.pm_min_deg}°).
          </p>
        )}
      </section>
    </div>
  );
}
