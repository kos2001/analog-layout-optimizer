import { useState } from "react";
import { fetchSurrogate } from "../api";
import { useT } from "../i18n";
import type { SurrogateData } from "../types";

function Chart({ data }: { data: SurrogateData }) {
  const W = 620, H = 280, padL = 44, padB = 28, padT = 14, padR = 12;
  const n = data.rounds.length;
  const all = data.rounds.flatMap((r) => [r.fomPred, r.fomTruth]);
  const lo = Math.min(...all, data.target), hi = Math.max(...all, data.target);
  const span = hi - lo || 1;
  const px = (i: number) => padL + (i / Math.max(n - 1, 1)) * (W - padL - padR);
  const py = (v: number) => padT + (1 - (v - lo) / span) * (H - padT - padB);
  const line = (sel: (r: SurrogateData["rounds"][0]) => number) =>
    data.rounds.map((r, i) => `${i ? "L" : "M"} ${px(i).toFixed(1)} ${py(sel(r)).toFixed(1)}`).join(" ");
  return (
    <svg width={W} height={H} className="conv-chart">
      <rect width={W} height={H} fill="#0d1117" />
      <line x1={padL} y1={py(data.target)} x2={W - padR} y2={py(data.target)}
        stroke="#d29922" strokeDasharray="4 3" />
      <text x={W - padR} y={py(data.target) - 4} textAnchor="end" className="axis">target {data.target}</text>
      <path d={line((r) => r.fomTruth)} fill="none" stroke="#3fb950" strokeWidth={2} />
      <path d={line((r) => r.fomPred)} fill="none" stroke="#42a5f5" strokeWidth={2} strokeDasharray="5 3" />
      {data.rounds.map((r, i) => (
        <circle key={i} cx={px(i)} cy={py(r.fomTruth)} r={3}
          fill={r.meets ? "#3fb950" : "#ff5252"} />
      ))}
      <text x={padL} y={H - 8} className="axis">round 0</text>
      <text x={W - padR} y={H - 8} textAnchor="end" className="axis">round {n - 1}</text>
    </svg>
  );
}

export default function SurrogateView() {
  const { t } = useT();
  const [data, setData] = useState<SurrogateData | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const run = async () => {
    setBusy(true); setErr(null);
    try { setData(await fetchSurrogate()); }
    catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };

  return (
    <div className="grid">
      <section className="panel" style={{ gridColumn: "1 / -1" }}>
        <div className="panel-title">
          {t("sur.title")}
          <button onClick={run} disabled={busy}>{busy ? "Running…" : "Run active learning"}</button>
        </div>
        {err && <p className="note" style={{ color: "var(--bad)" }}>{err}</p>}
        {!data ? (
          <p className="note">
            A GP surrogate replaces the expensive ground-truth (Spectre/PEX stand-in) inside the
            optimization loop. Each round: optimize on the surrogate → validate the proposed design
            against the truth → retrain. Click to run.
          </p>
        ) : (
          <div className="maze-wrap">
            <Chart data={data} />
            <div className="maze-side">
              <div className="metrics" style={{ flexDirection: "column", gap: 10 }}>
                <div><span className="metric-label">expensive (ground-truth) calls</span>
                  <span className="metric-value">{data.expensiveCalls}</span></div>
                <div><span className="metric-label">surrogate calls (cheap)</span>
                  <span className="metric-value">{data.surrogateCalls.toLocaleString()}</span></div>
                <div><span className="metric-label">savings</span>
                  <span className="metric-value" style={{ color: "var(--accent)" }}>{data.savings}× fewer</span></div>
                <div><span className="metric-label">best (truth-verified)</span>
                  <span className="metric-value">FoM {data.best.fomTruth} ✓</span></div>
              </div>
              <div className="legend" style={{ flexDirection: "column", gap: 6, marginTop: 10 }}>
                <span><i className="sw" style={{ background: "#3fb950", borderColor: "#3fb950" }} /> ground truth</span>
                <span><i className="sw" style={{ background: "#42a5f5", borderColor: "#42a5f5" }} /> surrogate prediction</span>
                <span style={{ color: "#d29922" }}>— — target</span>
              </div>
            </div>
          </div>
        )}
        {data && (
          <table className="tcoil-table" style={{ marginTop: 14 }}>
            <thead><tr><th>round</th><th>pred</th><th>truth</th><th>err</th><th>holdout R²</th><th>meets</th><th>exp. calls</th></tr></thead>
            <tbody>
              {data.rounds.map((r) => (
                <tr key={r.index}>
                  <td>{r.index}</td><td>{r.fomPred}</td><td>{r.fomTruth}</td><td>{r.predError}</td>
                  <td>{r.holdoutR2}</td>
                  <td style={{ color: r.meets ? "var(--ok)" : "var(--bad)" }}>{r.meets ? "✓" : "✗"}</td>
                  <td>{r.expensiveCalls}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {data && (
          <p className="note">
            Prediction error shrinks round over round as the surrogate retrains where it matters;
            the validation step catches over-optimistic predictions (✗). The surrogate absorbed
            <strong> {data.savings}× </strong> the expensive evaluations.
          </p>
        )}
      </section>
    </div>
  );
}
