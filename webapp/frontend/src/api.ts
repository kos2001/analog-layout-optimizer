// Typed API client. Interactive, sub-100 ms calls go straight to their
// endpoint; anything that runs an optimizer, a router sweep or a simulator is
// submitted through the run manager (/api/jobs), so it shows up in the Runs
// dock with live stage progress and shares the backend result cache. Job
// results are byte-identical to the direct endpoint responses.

import { runJob } from "./shell/jobs";
import { http } from "./shell/telemetry";
import type {
  AdaptResponse, AgentResp, AntennaResult, BodeData, BridgeData, CCCompare, Config,
  EmResult, FloorplanComponent, FloorplanData, FlowData, FullFlowData, GdsExport,
  KlayoutDrc, LayoutPayload, LayoutShapes, LdeResult, LvsResult, MazeData, NgspiceEval,
  OpAmpResult, OpAmpStudy, OptimizeResult, Params, PPAData, Preflight, ProcessEffects,
  PVTData, ScenarioCase, ScenarioData, SkillData, SpectreEval, SurrogateData, TcoilCurve,
  TcoilData, TcoilGeom,
} from "./types";
import type { JobStage } from "./shell/jobs";

type Place = "sa" | "random";
type OnStage = (s: JobStage) => void;

// --- device / joint layout ---------------------------------------------------
export const fetchConfig = () => http<Config>("/api/config");
export const evaluate = (params: Params) =>
  http<LayoutPayload>("/api/evaluate", { json: params });
export const optimize = (seed = 0, maxiter = 60) =>
  runJob<OptimizeResult>("optimize", { seed, maxiter });
export const optimizeJoint = (seed = 0, maxiter = 60) =>
  runJob<OptimizeResult>("joint", { seed, maxiter });

// --- routing ------------------------------------------------------------------
export const fetchMaze = () => runJob<MazeData>("maze", {});
export const fetchScenarioCases = () => http<{ cases: ScenarioCase[] }>("/api/scenarios");
export const fetchScenario = (key: string) => http<ScenarioData>(`/api/scenarios/${key}`);
export const fetchCommonCentroid = (rows = 4, cols = 4) =>
  http<CCCompare>(`/api/common-centroid?rows=${rows}&cols=${cols}`);
export const fetchFloorplanScenario = () => http<FloorplanData>("/api/floorplan/scenario");
export const routeFloorplan = (width: number, height: number,
                               components: FloorplanComponent[], optimize: boolean) =>
  http<FloorplanData>("/api/floorplan/route", { json: { width, height, components, optimize } });

// --- schematic -> P&R -> sign-off ------------------------------------------------
export const fetchFlow = (place: Place, seed = 0, analog = false) =>
  runJob<FlowData>("flow", { place, seed, analog });
export const fetchFullFlow = (place: Place, seed = 0, sky130 = false, sweep = 0,
                              onStage?: OnStage) =>
  runJob<FullFlowData>("full-flow", { place, seed, sky130, sweep }, { onStage });
export const fetchGds = (place: Place, seed = 0) =>
  runJob<GdsExport>("flow/gds", { place, seed });
export const fetchKlayoutDrc = (place: Place, seed = 0) =>
  runJob<KlayoutDrc>("flow/drc-klayout", { place, seed });
export const fetchLvs = () => http<LvsResult>("/api/lvs");
export const fetchAntenna = () => http<AntennaResult>("/api/antenna");
export const fetchEm = () => http<EmResult>("/api/em");
export const fetchLde = () => http<LdeResult>("/api/lde");
export const fetchLayoutShapes = (which: "ota" | "mirror" | "diffpair" = "ota") =>
  http<LayoutShapes>(`/api/layout/shapes?which=${which}`);

// --- PPA / analog sizing -------------------------------------------------------
export const fetchPPA = (wPower: number, wArea: number, wPerf: number, seed = 0) =>
  runJob<PPAData>("ppa", { w_power: wPower, w_area: wArea, w_perf: wPerf, seed });
export const fetchOpamp = () => runJob<OpAmpResult>("opamp", {});
export const fetchOpampStudy = () =>
  runJob<OpAmpStudy>("opamp/study", { seeds: 4 });
export const fetchPreflight = () => http<Preflight>("/api/opamp/preflight");
export const fetchSpectreEval = () =>
  runJob<SpectreEval>("opamp/spectre-eval", {});
export const fetchNgspiceEval = (model: "generic" | "sky130" = "generic") =>
  runJob<NgspiceEval>("opamp/ngspice-eval", { model });
export const fetchOpampBode = () => http<BodeData>("/api/opamp/bode");
export const fetchPVT = (full = false) =>
  runJob<PVTData>("pvt", { full });

// --- RF / process / surrogate --------------------------------------------------
export const fetchTcoil = () => runJob<TcoilData>("tcoil", {});
export const evalTcoil = (L: number, k: number, Cb: number) =>
  http<TcoilCurve>("/api/tcoil/eval", { json: { L, k, Cb } });
export const geomTcoil = (b: {
  turns: number; width: number; spacing: number; inner: number;
  r_ohm: number; cl_ff: number; cb: number;
}) => http<TcoilGeom>("/api/tcoil/geometry", { json: b });
export const adaptProcess = (nl: string) =>
  runJob<AdaptResponse>("adapt", { nl });
export const processEffects = (nl: string, tech: Record<string, number>) =>
  runJob<ProcessEffects>("process/effects", { nl, tech });
export const fetchSurrogate = () =>
  runJob<SurrogateData>("surrogate", {});

// --- Virtuoso bridge / agent ---------------------------------------------------
export const fetchSkill = () => runJob<SkillData>("skill", {});
export const fetchBridge = () => http<BridgeData>("/api/bridge");
export const askAgent = (prompt: string) => http<AgentResp>("/api/agent", { json: { prompt } });
