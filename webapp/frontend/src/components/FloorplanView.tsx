import { useEffect, useRef, useState } from "react";
import { fetchFloorplanScenario, routeFloorplan } from "../api";
import { useT } from "../i18n";
import type { FloorplanComponent, FloorplanData } from "../types";

const NET_COLORS: Record<string, string> = {
  CLK: "#ffb300", TAIL: "#ab47bc", VINP: "#26c6da",
  VINN: "#66bb6a", OUTN: "#ef5350", OUTP: "#42a5f5",
};
const CS = 18; // cell size px

export default function FloorplanView() {
  const { t } = useT();
  const [comps, setComps] = useState<FloorplanComponent[] | null>(null);
  const [data, setData] = useState<FloorplanData | null>(null);
  const [optimize, setOptimize] = useState(true);
  const [dim, setDim] = useState({ w: 28, h: 20 });
  const [drag, setDrag] = useState<string | null>(null);
  const [routing, setRouting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const svgRef = useRef<SVGSVGElement | null>(null);
  const grabRef = useRef({ dx: 0, dy: 0 }); // pointer offset within component (px)
  const reqRef = useRef(0);                  // request id, to drop stale responses

  useEffect(() => {
    fetchFloorplanScenario()
      .then((d) => { setData(d); setComps(d.components); setDim({ w: d.width, h: d.height }); })
      .catch((e) => setErr(String(e)));
  }, []);

  // Re-route whenever the placement (or optimize mode) changes — debounced so a
  // drag fires one solve per ~90 ms instead of per mouse-move.
  useEffect(() => {
    if (!comps) return;
    const id = window.setTimeout(async () => {
      const myReq = ++reqRef.current;
      setRouting(true);
      try {
        const d = await routeFloorplan(dim.w, dim.h, comps, optimize);
        if (myReq === reqRef.current) setData(d);
      } catch (e) { setErr(String(e)); }
      finally { if (myReq === reqRef.current) setRouting(false); }
    }, 90);
    return () => window.clearTimeout(id);
  }, [comps, optimize, dim.w, dim.h]);

  // Global pointer handlers while dragging.
  useEffect(() => {
    if (!drag) return;
    const onMove = (e: PointerEvent) => {
      const svg = svgRef.current;
      if (!svg) return;
      const r = svg.getBoundingClientRect();
      setComps((prev) => {
        if (!prev) return prev;
        const c = prev.find((k) => k.id === drag);
        if (!c) return prev;
        let nx = Math.round((e.clientX - r.left - grabRef.current.dx) / CS);
        let ny = Math.round((e.clientY - r.top - grabRef.current.dy) / CS);
        nx = Math.max(0, Math.min(nx, dim.w - c.w));
        ny = Math.max(0, Math.min(ny, dim.h - c.h));
        if (nx === c.x && ny === c.y) return prev;
        return prev.map((k) => (k.id === drag ? { ...k, x: nx, y: ny } : k));
      });
    };
    const onUp = () => setDrag(null);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [drag, dim.w, dim.h]);

  const startDrag = (e: React.PointerEvent, c: FloorplanComponent) => {
    const svg = svgRef.current;
    if (!svg) return;
    const r = svg.getBoundingClientRect();
    grabRef.current = { dx: e.clientX - r.left - c.x * CS, dy: e.clientY - r.top - c.y * CS };
    setDrag(c.id);
  };

  if (err) return <div className="fatal">Error: {err}</div>;
  if (!comps || !data) return <div className="loading">{t("loading")}</div>;

  const W = dim.w * CS, H = dim.h * CS;
  const blockedSet = new Set(data.blocked.map(([x, y]) => `${x},${y}`));

  return (
    <section className="panel" style={{ gridColumn: "1 / -1" }}>
      <div className="panel-title">
        {t("fp.title")}
        <span className={data.failed.length ? "badge bad" : "badge ok"}>
          {data.failed.length ? `${data.failed.length} ${t("fp.unrouted")}` : t("all.routed")}
        </span>
      </div>

      <div className="maze-wrap">
        <svg
          ref={svgRef} width={W} height={H} className="maze-grid"
          style={{ touchAction: "none", userSelect: "none" }}
        >
          <rect x={0} y={0} width={W} height={H} fill="#0d1117" />
          {Array.from({ length: dim.w + 1 }, (_, i) => (
            <line key={`v${i}`} x1={i * CS} y1={0} x2={i * CS} y2={H} stroke="#161b22" />
          ))}
          {Array.from({ length: dim.h + 1 }, (_, i) => (
            <line key={`h${i}`} x1={0} y1={i * CS} x2={W} y2={i * CS} stroke="#161b22" />
          ))}

          {/* routed wires (under components) */}
          {Object.entries(data.nets).map(([net, nr]) =>
            nr.cells.map(([x, y], i) => {
              if (blockedSet.has(`${x},${y}`)) return null;
              return (
                <rect key={`${net}-${i}`} x={x * CS + 4} y={y * CS + 4}
                  width={CS - 8} height={CS - 8} rx={4}
                  fill={NET_COLORS[net] ?? "#888"} opacity={0.5}>
                  <title>{net} ({x},{y})</title>
                </rect>
              );
            }),
          )}

          {/* draggable components */}
          {comps.map((c) => {
            const x = c.x * CS, y = c.y * CS, w = c.w * CS, h = c.h * CS;
            const failedPin = c.pins.some((p) => data.failed.includes(p.net));
            return (
              <g key={c.id} onPointerDown={(e) => startDrag(e, c)}
                style={{ cursor: drag === c.id ? "grabbing" : "grab" }}>
                <rect x={x + 1} y={y + 1} width={w - 2} height={h - 2} rx={4}
                  fill={drag === c.id ? "#3d444d" : "#2b313a"}
                  stroke={failedPin ? "var(--bad)" : "#586069"} strokeWidth={failedPin ? 2 : 1} />
                {c.w >= 3 && (
                  <text x={x + w / 2} y={y + h / 2 + 3} textAnchor="middle"
                    fontSize={9} fill="#c9d1d9" style={{ pointerEvents: "none" }}>
                    {c.label}
                  </text>
                )}
                {/* pins on the component boundary */}
                {c.pins.map((p, i) => (
                  <rect key={i} x={(c.x + p.dx) * CS + 3} y={(c.y + p.dy) * CS + 3}
                    width={CS - 6} height={CS - 6} rx={2}
                    fill={NET_COLORS[p.net] ?? "#888"} stroke="#fff" strokeWidth={1}
                    style={{ pointerEvents: "none" }}>
                    <title>{p.net} pin</title>
                  </rect>
                ))}
              </g>
            );
          })}
        </svg>

        <div className="maze-side">
          <p className="note" style={{ marginTop: 0 }}>{t("fp.help")}</p>
          <div className="seg">
            <button className={optimize ? "" : "secondary"} onClick={() => setOptimize(true)}>
              {t("fp.optimize")}
            </button>
            <button className={!optimize ? "" : "secondary"} onClick={() => setOptimize(false)}>
              {t("fp.fixed")}
            </button>
          </div>
          <div className="metrics" style={{ flexDirection: "column", gap: 10 }}>
            <div>
              <span className="metric-label">{t("maze.total.wl")}</span>
              <span className="metric-value">
                {data.totalWirelength}{routing ? " …" : ""}
              </span>
            </div>
            <div>
              <span className="metric-label">{t("maze.total.bends")}</span>
              <span className="metric-value">{data.totalBends}</span>
            </div>
            <div>
              <span className="metric-label">{t("fp.order")}</span>
              <span className="metric-value" style={{ fontSize: 11 }}>{data.order.join(" → ")}</span>
            </div>
          </div>
          <div className="legend" style={{ flexDirection: "column", gap: 6 }}>
            {data.netNames.map((n) => (
              <span key={n}>
                <i className="sw" style={{ background: NET_COLORS[n], borderColor: NET_COLORS[n] }} />
                {n} — wl {data.nets[n]?.wirelength ?? "—"}
                {data.failed.includes(n) && <b style={{ color: "var(--bad)" }}> ✗</b>}
              </span>
            ))}
          </div>
          <button className="secondary" style={{ marginTop: 6 }}
            onClick={() => fetchFloorplanScenario().then((d) => {
              setComps(d.components); setData(d); setDim({ w: d.width, h: d.height });
            })}>
            {t("fp.reset")}
          </button>
        </div>
      </div>
    </section>
  );
}
