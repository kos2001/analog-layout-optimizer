import type { FlowData, FlowComponent } from "../types";

export const NET_PALETTE = [
  "#42a5f5", "#ef5350", "#66bb6a", "#ffb300", "#ab47bc", "#26c6da",
  "#ff7043", "#ec407a", "#9ccc65", "#8d6e63",
];
const KIND_FILL: Record<string, string> = {
  nmos: "#1c3b57", pmos: "#532a1c", cap: "#3a2a52", port: "#30363d",
};

export function netColorFactory(names: string[]) {
  return (n: string) => NET_PALETTE[Math.max(0, names.indexOf(n)) % NET_PALETTE.length];
}

/** Placed devices + routed wires (multi-layer, via dots) + optional DRC markers. */
export default function RouteGrid({ data, netColor, hover, setHover, showDrc }: {
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
                <title>{c.label}.{p.net}</title>
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
