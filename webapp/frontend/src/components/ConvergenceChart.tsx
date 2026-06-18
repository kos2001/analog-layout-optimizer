import type { Frame } from "../types";

interface Props {
  frames: Frame[];
  current: number; // index of currently-shown frame
  width?: number;
  height?: number;
}

// Small SVG line chart of bbox area vs. optimization iteration, with a marker
// on the frame currently rendered in the layout view.
export default function ConvergenceChart({
  frames,
  current,
  width = 560,
  height = 150,
}: Props) {
  if (frames.length === 0) {
    return (
      <div className="chart-empty">Run optimization to see convergence.</div>
    );
  }

  const padL = 44;
  const padR = 10;
  const padT = 12;
  const padB = 22;
  const areas = frames.map((f) => f.area);
  const amin = Math.min(...areas);
  const amax = Math.max(...areas);
  const span = amax - amin || 1;
  const n = frames.length;

  const px = (i: number) =>
    padL + (i / Math.max(n - 1, 1)) * (width - padL - padR);
  const py = (a: number) =>
    padT + (1 - (a - amin) / span) * (height - padT - padB);

  const path = frames
    .map((f, i) => `${i === 0 ? "M" : "L"} ${px(i).toFixed(1)} ${py(f.area).toFixed(1)}`)
    .join(" ");

  const cur = frames[Math.min(current, n - 1)];

  return (
    <svg width={width} height={height} className="conv-chart">
      <rect x={0} y={0} width={width} height={height} fill="#0d1117" />
      {/* y-axis labels */}
      <text x={6} y={py(amax) + 4} className="axis">
        {amax.toFixed(2)}
      </text>
      <text x={6} y={py(amin) + 4} className="axis">
        {amin.toFixed(2)}
      </text>
      <text x={6} y={height - 6} className="axis">
        µm²
      </text>
      <line
        x1={padL}
        y1={padT}
        x2={padL}
        y2={height - padB}
        stroke="#30363d"
      />
      <path d={path} fill="none" stroke="#42a5f5" strokeWidth={2} />
      {/* current-frame marker */}
      <circle
        cx={px(Math.min(current, n - 1))}
        cy={py(cur.area)}
        r={4}
        fill={cur.isClean ? "#43a047" : "#ff1744"}
      />
      <text x={width - 10} y={height - 6} textAnchor="end" className="axis">
        iter {cur.iter} · {cur.area.toFixed(3)} µm²
      </text>
    </svg>
  );
}
