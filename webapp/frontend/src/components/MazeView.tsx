import { useEffect, useState } from "react";
import { fetchMaze } from "../api";
import { useT } from "../i18n";
import type { MazeData, MazeSolution } from "../types";
import FloorplanView from "./FloorplanView";

const NET_COLORS: Record<string, string> = {
  CLK: "#ffb300",
  TAIL: "#ab47bc",
  VINP: "#26c6da",
  VINN: "#66bb6a",
  OUTN: "#ef5350",
  OUTP: "#42a5f5",
};

function Grid({ data, sol }: { data: MazeData; sol: MazeSolution }) {
  const cs = 18; // cell size px
  const w = data.width * cs;
  const h = data.height * cs;
  const blockedSet = new Set(data.blocked.map(([x, y]) => `${x},${y}`));

  return (
    <svg width={w} height={h} className="maze-grid">
      <rect x={0} y={0} width={w} height={h} fill="#0d1117" />
      {/* grid lines */}
      {Array.from({ length: data.width + 1 }, (_, i) => (
        <line key={`v${i}`} x1={i * cs} y1={0} x2={i * cs} y2={h} stroke="#161b22" />
      ))}
      {Array.from({ length: data.height + 1 }, (_, i) => (
        <line key={`hl${i}`} x1={0} y1={i * cs} x2={w} y2={i * cs} stroke="#161b22" />
      ))}
      {/* blockages (devices / keep-outs) */}
      {data.blocked.map(([x, y], i) => (
        <rect key={`b${i}`} x={x * cs} y={y * cs} width={cs} height={cs}
          fill="#30363d" />
      ))}
      {/* net wires */}
      {Object.entries(sol.nets).map(([net, nr]) =>
        nr.cells.map(([x, y], i) => {
          const isPin = nr.pins.some(([px, py]) => px === x && py === y);
          if (blockedSet.has(`${x},${y}`)) return null;
          return (
            <rect
              key={`${net}-${i}`}
              x={x * cs + 2}
              y={y * cs + 2}
              width={cs - 4}
              height={cs - 4}
              rx={isPin ? 2 : 5}
              fill={NET_COLORS[net] ?? "#888"}
              opacity={isPin ? 1 : 0.55}
              stroke={isPin ? "#fff" : "none"}
              strokeWidth={isPin ? 1.5 : 0}
            >
              <title>{net}{isPin ? " pin" : ""} ({x},{y})</title>
            </rect>
          );
        }),
      )}
    </svg>
  );
}

export default function MazeView() {
  const { t } = useT();
  const [data, setData] = useState<MazeData | null>(null);
  const [mode, setMode] = useState<"optimized" | "naive">("optimized");
  const [view, setView] = useState<"demo" | "drag">("drag");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (view === "demo" && !data) fetchMaze().then(setData).catch((e) => setError(String(e)));
  }, [view, data]);

  const ModeTabs = (
    <div className="seg" style={{ marginBottom: 12, gridColumn: "1 / -1" }}>
      <button className={view === "drag" ? "" : "secondary"} onClick={() => setView("drag")}>
        {t("maze.mode.drag")}
      </button>
      <button className={view === "demo" ? "" : "secondary"} onClick={() => setView("demo")}>
        {t("maze.mode.demo")}
      </button>
    </div>
  );

  if (view === "drag") {
    return <div className="grid">{ModeTabs}<FloorplanView /></div>;
  }

  if (error) return <div className="fatal">Error: {error}</div>;
  if (!data) return <div className="grid">{ModeTabs}<div className="loading">{t("loading")}</div></div>;
  const sol = data[mode];

  return (
    <div className="grid">
      {ModeTabs}
      <section className="panel" style={{ gridColumn: "1 / -1" }}>
        <div className="panel-title">
          {t("maze.title")} ({data.netNames.length} nets)
          <span className={sol.failed.length ? "badge bad" : "badge ok"}>
            {sol.failed.length ? `${sol.failed.length} unrouted` : t("all.routed")}
          </span>
        </div>

        <div className="maze-wrap">
          <Grid data={data} sol={sol} />
          <div className="maze-side">
            <div className="seg">
              <button
                className={mode === "optimized" ? "" : "secondary"}
                onClick={() => setMode("optimized")}
              >
                {t("maze.optimized")}
              </button>
              <button
                className={mode === "naive" ? "" : "secondary"}
                onClick={() => setMode("naive")}
              >
                {t("maze.naive")}
              </button>
            </div>
            <div className="metrics" style={{ flexDirection: "column", gap: 10 }}>
              <div>
                <span className="metric-label">{t("maze.total.wl")}</span>
                <span className="metric-value">{sol.totalWirelength}</span>
              </div>
              <div>
                <span className="metric-label">{t("maze.total.bends")}</span>
                <span className="metric-value">{sol.totalBends}</span>
              </div>
              <div>
                <span className="metric-label">{t("maze.worst")}</span>
                <span className="metric-value">{data.worstWirelength}</span>
              </div>
            </div>
            <div className="legend" style={{ flexDirection: "column", gap: 6 }}>
              {data.netNames.map((n) => (
                <span key={n}>
                  <i className="sw" style={{ background: NET_COLORS[n], borderColor: NET_COLORS[n] }} />
                  {n} — wl {sol.nets[n].wirelength}
                </span>
              ))}
            </div>
            <p className="note">
              A* shortest path per net; nets routed sequentially so an earlier
              net blocks later ones. Net <strong>order</strong> changes the total
              ({data.optimized.totalWirelength} optimized vs {data.worstWirelength} worst)
              — a discrete optimization. Dark cells are device keep-outs;
              outlined squares are pins.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
