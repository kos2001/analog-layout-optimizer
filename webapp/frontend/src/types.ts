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

// --- Interactive floorplan (drag-place -> dynamic routing) ---
export interface FloorplanPin { net: string; dx: number; dy: number; }
export interface FloorplanComponent {
  id: string; label: string;
  x: number; y: number; w: number; h: number;
  pins: FloorplanPin[];
}
export interface FloorplanData {
  width: number;
  height: number;
  blocked: [number, number][];
  components: FloorplanComponent[];
  netNames: string[];
  order: string[];
  optimized: boolean;
  totalWirelength: number;
  totalBends: number;
  failed: string[];
  nets: Record<string, MazeNet>;
}

// --- Complex routing scenarios (multi-layer + algorithms) ---
export interface ScenarioNet {
  pins: number[][];        // [x,y] or [x,y,layer]
  cells: number[][];
  wirelength: number;
  vias?: number;
  routed: boolean;
}
export interface DRCViolation {
  rule: string; nets: string[]; cells: number[][]; message: string;
}
export interface DRCReport {
  clean: boolean;
  counts: Record<string, number>;
  total: number;
  violations: DRCViolation[];
  checkedRules: string[];
}
export interface ScenarioAlgo {
  algo: string;
  ms: number;
  totalWirelength: number;
  totalVias?: number;
  failed: string[];
  nets: Record<string, ScenarioNet>;
  order?: string[] | null;
  iterations?: number;
  converged?: boolean;
  overused?: number;
  drc?: DRCReport;
}
export interface DiffVariant {
  matched: boolean;
  mismatch: number;
  coupled: number;
  routed: boolean;
  lenA: number;
  lenB: number;
  nets: Record<string, ScenarioNet>;
}
export interface ScenarioData {
  width: number;
  height: number;
  layers?: number;
  blocked: number[][];     // [x,y] (2D) or [x,y,layer] (multilayer)
  info: { key: string; title: string; desc: string };
  kind: "multinet" | "diffpair";
  netNames?: string[];
  algos?: Record<string, ScenarioAlgo>;
  variants?: Record<string, DiffVariant>;
}
export interface ScenarioCase { key: string; title: string; }

// --- Common-centroid matched array ---
export interface CCRect {
  device: string; row: number; col: number;
  x0: number; y0: number; x1: number; y1: number;
}
export interface CCLayout {
  strategy: string; rows: number; cols: number; pitch: number;
  rects: CCRect[];
  centroidA: number[]; centroidB: number[]; centroidOffset: number;
  mismatchX: number; mismatchY: number; mismatchDiag: number;
  bbox: { x0: number; y0: number; x1: number; y1: number };
}
export interface CCCompare { rows: number; cols: number; strategies: CCLayout[]; }

// --- PPA (power / performance / area) multi-objective ---
export interface PPAPoint {
  power_mw: number; area_um2: number; gbw_mhz: number;
  gain_db: number; pm_deg: number; feasible: boolean;
  sizing: { wl1: number; wl3: number; wl6: number;
    itail_uA: number; i6_uA: number; cc_pF: number };
}
export interface PPAData {
  pareto: PPAPoint[];
  cloud: { power_mw: number; area_um2: number; gbw_mhz: number }[];
  chosen: PPAPoint | null;
  weights: { power: number; area: number; perf: number };
  ranges: { power_mw: number[]; area_um2: number[]; gbw_mhz: number[] };
  nParetoFront: number;
  constraints: { gain_floor_db: number; pm_min_deg: number };
}

// --- Schematic -> placement -> routing flow ---
export interface FlowComponent {
  id: string; label: string; kind: string;
  x: number; y: number; w: number; h: number;
  pins: { net: string; dx: number; dy: number }[];
}
export interface FlowRouting {
  blocked: number[][];
  netNames: string[];
  totalWirelength: number;
  totalVias: number;
  failed: string[];
  converged: boolean;
  iterations: number;
  nets: Record<string, ScenarioNet>;
  drc: DRCReport;
}
export interface SignoffCheck { name: string; status: string; detail: string; }
export interface SignoffLVS {
  clean: boolean;
  opens: { net: string; components: number }[];
  shorts: { nets: string[] }[];
  floating: string[];
  nDevicesChecked: number;
  nSchematicNets: number;
  nLayoutNodes: number;
}
export interface Signoff {
  verdict: string;
  checks: SignoffCheck[];
  drc: DRCReport;
  lvs: SignoffLVS;
  drcErrors: number;
  drcWarnings: number;
}
export interface PostLayoutSpec { gain_db: number; gbw_mhz: number; pm_deg: number; p_n2_mhz?: number | null; }
export interface NetParasitic { R_ohm: number; C_fF: number; wirelength: number; vias: number; coupling: number; }
export interface PostLayout {
  pre: PostLayoutSpec;
  post: PostLayoutSpec;
  deltaPM: number;
  critical: Record<string, NetParasitic>;
  parasitics: Record<string, NetParasitic>;
  stable: boolean;
}
export interface FlowData {
  width: number; height: number; layers: number; place: string;
  hpwl: number;
  netlist: Record<string, string[]>;
  components: FlowComponent[];
  routing: FlowRouting;
  signoff: Signoff;
  postlayout: PostLayout;
}
export interface GdsStats {
  topCell: string; polygons: number;
  counts: { metal: number; via: number; device: number };
  layers: { layer: number; datatype: number }[];
  bbox_um: number[][] | null; area_um2: number; pitch_um: number;
}
export interface GdsExport { filename: string; gdsBase64: string; bytes: number; stats: GdsStats; }

export interface KlayoutDrcLayer {
  layer: string; gds: number[]; polygons: number;
  min_width_um: number; min_space_um: number;
  width_violations: number; space_violations: number; samples: number[][];
}
export interface KlayoutDrc {
  available: boolean; error?: string; tool?: string;
  clean?: boolean; total?: number; layers?: KlayoutDrcLayer[];
}

export interface LvsResult {
  tool: string; cell: string; match: boolean;
  devices: { counts: Record<string, number> };
  layout_netlist: string;
}

export interface LayoutLayer {
  layer: number; datatype: number; name: string; color: string;
  polys: number[][][]; labels: { text: string; x: number; y: number }[];
}
export interface LayoutShapes {
  which: string; topCell: string; dbu: number; bbox: number[];
  layers: LayoutLayer[]; nPolygons: number;
}

export interface FlowStage { name: string; status: string; detail: string; }
export interface FlowSizing {
  feasible: boolean; gain_db: number; gbw_mhz: number; pm_deg: number; power_mw: number;
  wl1: number; wl6: number; itail_uA: number; cc_pF: number;
}
export interface FlowSilicon { model: string; gain_db: number; gbw_mhz: number; pm_deg: number; }
export interface FullFlowData extends FlowData {
  stages: FlowStage[];
  verdict: string;
  sizing: FlowSizing;
  silicon: FlowSilicon | null;
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

// --- Op-amp (OTA) ---
export interface SpecRow { name: string; value: number; unit: string; target: number; pass: boolean; }
export interface OpAmpResult {
  feasible: boolean;
  power_mw: number;
  specs: SpecRow[];
  sizing: Record<string, number>;
  overdrives: Record<string, number>;
}
export interface StudyRow {
  strategy: string; feasible: number; n: number;
  best_mw: number; mean_mw: number; std_mw: number;
}
export interface OpAmpStudy { results: StudyRow[]; note: string; }
export interface Preflight { bridge_env: boolean; spectre: boolean; ready: boolean; guidance: string[]; }
export interface SpectreSpecs { gain_db: number; gbw_mhz: number; pm_deg: number; power_mw: number; }
export interface SpectreEval {
  pdk: string;
  analytic: SpectreSpecs;
  spectre?: SpectreSpecs;
  status: string;
  error?: string;
  preflight?: Preflight;
}

// --- Process change (adapt) ---
export interface AdaptSide {
  layout: LayoutPayload;
  totalArea: number;
  deviceArea: number;
  wirelength: number;
  drcClean: boolean;
  device: Record<string, number>;
  routing: Record<string, number>;
}
export interface AdaptResponse {
  overrides: Record<string, number>;
  before: AdaptSide;
  after: AdaptSide;
  areaDeltaPct: number;
  topology: { fingers: number; nets: string[] };
}

// --- Surrogate / SKILL / Bridge / Bode / Agent ---
export interface SurrogateRound {
  index: number; fomPred: number; fomTruth: number; predError: number;
  holdoutRmse: number; holdoutR2: number; meets: boolean; expensiveCalls: number;
}
export interface SurrogateData {
  target: number; rounds: SurrogateRound[];
  best: { area: number; fomTruth: number };
  expensiveCalls: number; surrogateCalls: number; savings: number;
}
export interface SkillData { cell: string; shapeCount: number; commands: string[]; il: string; note: string; }
export interface BridgeCheck { name: string; ok: boolean; sample: string; }
export interface BridgeData { checks: BridgeCheck[]; allOk: boolean; preflight: Preflight; }
export interface BodeData { freq: number[]; magDb: number[]; phaseDeg: number[]; }
export interface AgentResp { ok: boolean; reply?: string; error?: string; }

// --- T-coil physical geometry ---
export interface TcoilGeom {
  path: [number, number][];
  width: number; dOut: number; L_nH: number; k: number;
  wireUm: number; areaUm2: number; normL: number;
  bwExtension: number; peakingDb: number;
  freq: number[]; magDb: number[];
}

// --- Full process-change effects ---
export interface EffectRow { category: string; modeled: boolean; what: string; tool: string; }
export interface ProcessEffects {
  drc_overrides: Record<string, number>;
  geometry: { before_area: number; after_area: number; area_delta_pct: number; drc_clean: boolean };
  device: null | {
    before: { power_mw: number; gain_db: number; gbw_mhz: number; pm_deg: number; feasible: boolean };
    after: { power_mw: number; gain_db: number; gbw_mhz: number; pm_deg: number; feasible: boolean };
    vdd_before: number; vdd_after: number;
  };
  taxonomy: EffectRow[];
}

// --- ngspice (open-source) eval ---
export interface SimSpecs { gain_db: number; gbw_mhz: number; pm_deg: number; power_mw: number; }
export interface NgspiceEval {
  backend: string; model: string; available: boolean;
  modelKind?: string; sky130Available?: boolean;
  analytic: SimSpecs; sim?: SimSpecs; status: string; error?: string;
}

export interface PVTCorner {
  process: string; temp_c: number; vdd: number;
  gain_db: number; gbw_mhz: number; pm_deg: number;
}
export interface PVTData {
  available: boolean; error?: string;
  nCorners?: number; corners?: PVTCorner[];
  worst?: { gain_db: number; gbw_mhz: number; pm_deg: number };
  nominal?: PVTCorner; stable?: boolean;
}
