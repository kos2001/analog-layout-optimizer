import type { LayoutPayload, RectShape } from "../types";

// Per-layer fill/stroke, evoking a Virtuoso layer palette.
const LAYER_STYLE: Record<string, { fill: string; stroke: string }> = {
  OD: { fill: "#2e7d3233", stroke: "#43a047" }, // diffusion    - green
  PO: { fill: "#c6280033", stroke: "#ff7043" }, // poly         - red/orange
  M1: { fill: "#1565c033", stroke: "#42a5f5" }, // metal1 ring  - blue
  M2: { fill: "#8e24aa55", stroke: "#ce93d8" }, // metal2 route - purple
  VIA12: { fill: "#fdd835cc", stroke: "#fff176" }, // via       - yellow
};
const DEFAULT_STYLE = { fill: "#88888833", stroke: "#aaaaaa" };
const VIOLATION = { fill: "#e5393566", stroke: "#ff1744" };

interface Props {
  layout: LayoutPayload;
  width?: number;
  height?: number;
}

export default function LayoutCanvas({ layout, width = 560, height = 420 }: Props) {
  const { bbox, rects } = layout;
  const pad = 0.15; // micron padding around the bbox
  const vx0 = bbox.x0 - pad;
  const vy0 = bbox.y0 - pad;
  const vw = bbox.x1 - bbox.x0 + 2 * pad;
  const vh = bbox.y1 - bbox.y0 + 2 * pad;

  // Fit the design into the viewport while preserving aspect ratio.
  const scale = Math.min(width / vw, height / vh);
  const ox = (width - vw * scale) / 2;
  const oy = (height - vh * scale) / 2;

  // World (microns, y-up) -> screen (px, y-down).
  const sx = (x: number) => ox + (x - vx0) * scale;
  const sy = (y: number) => height - (oy + (y - vy0) * scale);

  const drawRect = (r: RectShape, i: number) => {
    const style = r.violated
      ? VIOLATION
      : LAYER_STYLE[r.layer] ?? DEFAULT_STYLE;
    const x = sx(r.x0);
    const y = sy(r.y1); // top edge in screen space
    const w = (r.x1 - r.x0) * scale;
    const h = (r.y1 - r.y0) * scale;
    return (
      <rect
        key={i}
        x={x}
        y={y}
        width={Math.max(w, 0.5)}
        height={Math.max(h, 0.5)}
        fill={style.fill}
        stroke={style.stroke}
        strokeWidth={r.violated ? 2 : 1}
      >
        <title>
          {r.layer} ({r.x0.toFixed(3)}, {r.y0.toFixed(3)}) → (
          {r.x1.toFixed(3)}, {r.y1.toFixed(3)})
        </title>
      </rect>
    );
  };

  return (
    <svg
      width={width}
      height={height}
      className="layout-canvas"
      role="img"
      aria-label="differential-pair layout"
    >
      <rect x={0} y={0} width={width} height={height} fill="#0d1117" />
      {/* bounding box of the cell */}
      <rect
        x={sx(bbox.x0)}
        y={sy(bbox.y1)}
        width={(bbox.x1 - bbox.x0) * scale}
        height={(bbox.y1 - bbox.y0) * scale}
        fill="none"
        stroke="#30363d"
        strokeDasharray="4 3"
      />
      {rects.map(drawRect)}
    </svg>
  );
}
