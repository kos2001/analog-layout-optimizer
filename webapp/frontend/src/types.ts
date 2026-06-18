// Wire types mirroring the FastAPI backend payloads.

export type ParamKey =
  | "w_finger"
  | "l"
  | "finger_pitch"
  | "guard_gap"
  | "gr_width";

export type Params = Record<ParamKey, number>;

export interface Config {
  order: ParamKey[];
  bounds: Record<ParamKey, [number, number]>;
  rules: {
    min_l: number;
    min_w: number;
    min_poly_pitch: number;
    min_gr_gap: number;
    min_gr_width: number;
  };
  config: {
    nf: number;
    w_min_total: number;
    layer_poly: string;
    layer_diff: string;
    layer_gr: string;
  };
  defaults: Params;
}

export interface RectShape {
  layer: string;
  purpose: string;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  violated: boolean;
}

export interface BBox {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface LayoutPayload {
  name: string;
  rects: RectShape[];
  bbox: BBox;
  area: number;
  objective: number;
  penalty?: number;
  isClean: boolean;
  violations: string[];
  // Present on routed/joint payloads:
  deviceArea?: number;
  wirelength?: number;
  viaCount?: number;
  connected?: boolean;
}

export interface Frame {
  iter: number;
  params: Params;
  area: number;
  objective: number;
  isClean: boolean;
  violations: string[];
  layout: LayoutPayload;
}

export interface OptimizeResult {
  nEvals: number;
  best: {
    params: Params & Partial<Record<string, number>>;
    area: number;
    deviceArea?: number;
    wirelength?: number;
    isClean: boolean;
    violations: string[];
    layout: LayoutPayload;
  };
  frames: Frame[];
}

// --- Maze (comparator routing) ---
export interface MazeNet {
  pins: [number, number][];
  cells: [number, number][];
  wirelength: number;
  bends: number;
  routed: boolean;
}
export interface MazeSolution {
  order: string[];
  totalWirelength: number;
  totalBends: number;
  failed: string[];
  nets: Record<string, MazeNet>;
}
export interface MazeData {
  width: number;
  height: number;
  blocked: [number, number][];
  netNames: string[];
  naive: MazeSolution;
  optimized: MazeSolution;
  worstWirelength: number;
}

// --- T-coil ---
export interface TcoilCurve {
  magDb: number[];
  bw: number;
  bwExtension: number;
  peakingDb: number;
  params: { L: number; k: number; Cb: number };
}
export interface TcoilData {
  freq: number[];
  curves: { none: TcoilCurve; shunt: TcoilCurve; tcoil: TcoilCurve };
  thresholdDb: number;
}
