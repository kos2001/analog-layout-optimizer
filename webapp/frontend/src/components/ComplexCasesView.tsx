import { useEffect, useState } from "react";
import { fetchScenario, fetchScenarioCases, fetchCommonCentroid } from "../api";
import { useT } from "../i18n";
import type {
  CCCompare, CCLayout, ScenarioAlgo, ScenarioCase, ScenarioData, ScenarioNet,
} from "../types";

const NET_PALETTE = [
  "#42a5f5", "#ef5350", "#66bb6a", "#ffb300", "#ab47bc", "#26c6da",
  "#ff7043", "#8d6e63", "#ec407a", "#9ccc65",
];
const colorOf = (i: number) => NET_PALETTE[i % NET_PALETTE.length];

// ----- routing-grid renderer (handles 2-D and multi-layer) -----
function ScenarioGrid({ data, nets, netNames, failed }: {
  data: ScenarioData; nets: Record<string, ScenarioNet>;
  netNames: string[]; failed: string[];
}) {
  const cs = Math.max(8, Math.min(16, Math.floor(720 / data.width)));
  const W = data.width * cs, H = data.height * cs;
  const ml = (data.layers ?? 1) > 1;

  // blocked per layer
  const blk0 = new Set<string>(), blk1 = new Set<string>();
  for (const b of data.blocked) {
    const [x, y, l] = b;
    if (!ml || l === 0) blk0.add(`${x},${y}`);
    if (ml && l === 1) blk1.add(`${x},${y}`);
  }
  const failedSet = new Set(failed);

  return (
    <svg width={W} height={H} className="maze-grid" style={{ maxWidth: "100%" }}>
      <rect width={W} height={H} fill="#0d1117" />
      {/* blockages: layer0 (H straps/macros) vs layer1 (V straps) */}
      {[...blk0].map((k) => {
        const [x, y] = k.split(",").map(Number);
        const both = blk1.has(k);
        return <rect key={`b0${k}`} x={x * cs} y={y * cs} width={cs} height={cs}
          fill={both ? "#3a4048" : "#2a2f37"} />;
      })}
      {[...blk1].filter((k) => !blk0.has(k)).map((k) => {
        const [x, y] = k.split(",").map(Number);
        return <rect key={`b1${k}`} x={x * cs} y={y * cs} width={cs} height={cs}
          fill="#1f2a33" stroke="#243947" strokeWidth={0.5} />;
      })}
      {/* wires */}
      {netNames.map((n, i) => {
        const nr = nets[n];
        if (!nr) return null;
        const col = colorOf(i);
        // detect via cells: same (x,y) appears on both layers
        const xy = new Map<string, Set<number>>();
        for (const c of nr.cells) {
          const key = `${c[0]},${c[1]}`;
          const lyr = c[2] ?? 0;
          if (!xy.has(key)) xy.set(key, new Set());
          xy.get(key)!.add(lyr);
        }
        return (
          <g key={n} opacity={failedSet.has(n) ? 0.25 : 1}>
            {nr.cells.map((c, j) => {
              const lyr = c[2] ?? 0;
              return <rect key={j} x={c[0] * cs + 1.5} y={c[1] * cs + 1.5}
                width={cs - 3} height={cs - 3} rx={lyr === 1 ? 1 : 4}
                fill={col} opacity={lyr === 1 ? 0.45 : 0.9} />;
            })}
            {[...xy.entries()].filter(([, s]) => s.size > 1).map(([key], j) => {
              const [x, y] = key.split(",").map(Number);
              return <circle key={`v${j}`} cx={x * cs + cs / 2} cy={y * cs + cs / 2}
                r={Math.max(1.5, cs / 6)} fill="#fff" />;
            })}
          </g>
        );
      })}
    </svg>
  );
}

function MultiNet({ data }: { data: ScenarioData }) {
  const { t } = useT();
  const [algo, setAlgo] = useState<"fixed" | "best" | "negotiated">("negotiated");
  const a: ScenarioAlgo | undefined = data.algos?.[algo];
  if (!a) return null;
  const names = data.netNames ?? [];

  return (
    <div className="maze-wrap">
      <ScenarioGrid data={data} nets={a.nets} netNames={names} failed={a.failed} />
      <div className="maze-side">
        <div className="seg">
          {(["fixed", "best", "negotiated"] as const).map((k) => (
            <button key={k} className={algo === k ? "" : "secondary"} onClick={() => setAlgo(k)}>
              {t(`cx.algo.${k}`)}
            </button>
          ))}
        </div>
        <div className="metrics" style={{ flexDirection: "column", gap: 8 }}>
          <div><span className="metric-label">{t("cx.failed")}</span>
            <span className="metric-value" style={{ color: a.failed.length ? "var(--bad)" : "var(--ok)" }}>
              {a.failed.length ? `${a.failed.length} (${a.failed.join(", ")})` : "0 ✓"}
            </span></div>
          <div><span className="metric-label">{t("maze.total.wl")}</span>
            <span className="metric-value">{a.totalWirelength}</span></div>
          <div><span className="metric-label">vias</span>
            <span className="metric-value">{a.totalVias ?? "—"}</span></div>
          <div><span className="metric-label">{t("cx.time")}</span>
            <span className="metric-value">{a.ms} ms</span></div>
          {algo === "negotiated" && (
            <div><span className="metric-label">PathFinder</span>
              <span className="metric-value" style={{ fontSize: 12 }}>
                {a.iterations} iters · {a.converged ? "converged ✓" : `over ${a.overused}`}
              </span></div>
          )}
        </div>
        <p className="note" style={{ marginTop: 4 }}>{data.info.desc}</p>
        <p className="note">
          {t("cx.legend.layer")} · {t("cx.legend.via")}
        </p>
      </div>
    </div>
  );
}

function DiffPair({ data }: { data: ScenarioData }) {
  const { t } = useT();
  const [v, setV] = useState<"independent" | "matched">("matched");
  const variant = data.variants?.[v];
  if (!variant) return null;
  return (
    <div className="maze-wrap">
      <ScenarioGrid data={data} nets={variant.nets} netNames={["INP", "INN"]} failed={[]} />
      <div className="maze-side">
        <div className="seg">
          <button className={v === "matched" ? "" : "secondary"} onClick={() => setV("matched")}>
            {t("cx.matched")}
          </button>
          <button className={v === "independent" ? "" : "secondary"} onClick={() => setV("independent")}>
            {t("cx.independent")}
          </button>
        </div>
        <div className="metrics" style={{ flexDirection: "column", gap: 8 }}>
          <div><span className="metric-label">{t("cx.coupled")}</span>
            <span className="metric-value" style={{ color: variant.coupled > 10 ? "var(--ok)" : "var(--bad)" }}>
              {variant.coupled} cells</span></div>
          <div><span className="metric-label">{t("cx.mismatch")}</span>
            <span className="metric-value">{variant.mismatch}</span></div>
          <div><span className="metric-label">INP / INN len</span>
            <span className="metric-value">{variant.lenA} / {variant.lenB}</span></div>
        </div>
        <div className="legend" style={{ flexDirection: "column", gap: 6 }}>
          <span><i className="sw" style={{ background: colorOf(0), borderColor: colorOf(0) }} />INP</span>
          <span><i className="sw" style={{ background: colorOf(1), borderColor: colorOf(1) }} />INN</span>
        </div>
        <p className="note">{data.info.desc}</p>
      </div>
    </div>
  );
}

// ----- common-centroid mini layout -----
function CCGrid({ lay }: { lay: CCLayout }) {
  const cs = 26;
  const W = lay.cols * cs, H = lay.rows * cs;
  const sx = (x: number) => x * cs, sy = (y: number) => y * cs;
  const A = "#42a5f5", B = "#ff7043";
  return (
    <svg width={W} height={H} style={{ background: "#0d1117", borderRadius: 6 }}>
      {lay.rects.map((r, i) => (
        <g key={i}>
          <rect x={sx(r.x0)} y={sy(r.y0)} width={cs} height={cs}
            fill={r.device === "A" ? A : B} opacity={0.78}
            stroke="#0d1117" strokeWidth={1} />
          <text x={sx(r.x0) + cs / 2} y={sy(r.y0) + cs / 2 + 4} textAnchor="middle"
            fontSize={11} fill="#0d1117" fontWeight={700}>{r.device}</text>
        </g>
      ))}
      {/* centroid markers (coincide for common-centroid) */}
      <circle cx={sx(lay.centroidA[0])} cy={sy(lay.centroidA[1])} r={5}
        fill="none" stroke="#fff" strokeWidth={2} />
      <circle cx={sx(lay.centroidB[0])} cy={sy(lay.centroidB[1])} r={8}
        fill="none" stroke="#ffd54f" strokeWidth={2} strokeDasharray="3 2" />
    </svg>
  );
}

function CommonCentroid() {
  const { t } = useT();
  const [cc, setCc] = useState<CCCompare | null>(null);
  useEffect(() => { fetchCommonCentroid(4, 4).then(setCc).catch(() => {}); }, []);
  if (!cc) return <div className="loading">{t("loading")}</div>;
  const best = Math.max(...cc.strategies.map((s) => s.mismatchDiag)) || 1;
  return (
    <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
      {cc.strategies.map((s) => (
        <div key={s.strategy} style={{ textAlign: "center" }}>
          <div className="panel-title" style={{ fontSize: 13, justifyContent: "center" }}>
            {t(`cx.cc.${s.strategy}`)}
            {s.mismatchDiag === 0 && <span className="badge ok">matched</span>}
          </div>
          <CCGrid lay={s} />
          <div className="metrics" style={{ justifyContent: "center", gap: 14, marginTop: 8 }}>
            <div><span className="metric-label">{t("cx.cc.offset")}</span>
              <span className="metric-value" style={{ color: s.centroidOffset === 0 ? "var(--ok)" : "var(--text)" }}>
                {s.centroidOffset}</span></div>
            <div><span className="metric-label">{t("cx.cc.gradmm")}</span>
              <span className="metric-value" style={{ color: s.mismatchDiag === 0 ? "var(--ok)" : "var(--bad)" }}>
                {s.mismatchDiag}</span></div>
          </div>
          <div style={{ height: 6, background: "#161b22", borderRadius: 3, marginTop: 6 }}>
            <div style={{ width: `${(s.mismatchDiag / best) * 100}%`, height: 6, borderRadius: 3,
              background: s.mismatchDiag === 0 ? "var(--ok)" : "#ef5350" }} />
          </div>
        </div>
      ))}
    </div>
  );
}

export default function ComplexCasesView() {
  const { t } = useT();
  const [cases, setCases] = useState<ScenarioCase[]>([]);
  const [key, setKey] = useState<string>("bus_channel");
  const [data, setData] = useState<ScenarioData | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { fetchScenarioCases().then((r) => setCases(r.cases)).catch(() => {}); }, []);
  useEffect(() => {
    setBusy(true); setErr(null);
    fetchScenario(key).then(setData).catch((e) => setErr(String(e))).finally(() => setBusy(false));
  }, [key]);

  return (
    <div className="grid">
      <section className="panel" style={{ gridColumn: "1 / -1" }}>
        <div className="panel-title">
          {t("cx.routing.title")}
          {data && <span className="badge">{data.kind === "diffpair" ? t("cx.diffpair") : `${data.netNames?.length} nets`}</span>}
        </div>
        <div className="seg" style={{ marginBottom: 10, flexWrap: "wrap" }}>
          {cases.map((c) => (
            <button key={c.key} className={key === c.key ? "" : "secondary"} onClick={() => setKey(c.key)}>
              {t(`cx.case.${c.key}`)}
            </button>
          ))}
        </div>
        {err && <p className="note" style={{ color: "var(--bad)" }}>{err}</p>}
        {busy || !data ? <div className="loading">{t("loading")}</div>
          : data.kind === "diffpair" ? <DiffPair data={data} /> : <MultiNet data={data} />}
        <p className="note" style={{ marginTop: 12 }}>{t("cx.algo.note")}</p>
      </section>

      <section className="panel" style={{ gridColumn: "1 / -1" }}>
        <div className="panel-title">{t("cx.cc.title")}</div>
        <CommonCentroid />
        <p className="note" style={{ marginTop: 12 }}>{t("cx.cc.note")}</p>
      </section>
    </div>
  );
}
