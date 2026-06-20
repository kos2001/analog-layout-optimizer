import type { Config, LayoutPayload, OptimizeResult, Params } from "./types";

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

export async function fetchConfig(): Promise<Config> {
  return jsonOrThrow<Config>(await fetch("/api/config"));
}

export async function evaluate(params: Params): Promise<LayoutPayload> {
  return jsonOrThrow<LayoutPayload>(
    await fetch("/api/evaluate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    }),
  );
}

export async function optimize(
  seed = 0,
  maxiter = 60,
): Promise<OptimizeResult> {
  return jsonOrThrow<OptimizeResult>(
    await fetch("/api/optimize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ seed, maxiter }),
    }),
  );
}

export async function optimizeJoint(
  seed = 0,
  maxiter = 60,
): Promise<OptimizeResult> {
  return jsonOrThrow<OptimizeResult>(
    await fetch("/api/joint", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ seed, maxiter }),
    }),
  );
}

import type { MazeData, TcoilData, TcoilCurve } from "./types";

export async function fetchMaze(): Promise<MazeData> {
  return jsonOrThrow<MazeData>(await fetch("/api/maze"));
}

export async function fetchTcoil(): Promise<TcoilData> {
  return jsonOrThrow<TcoilData>(await fetch("/api/tcoil"));
}

export async function evalTcoil(L: number, k: number, Cb: number): Promise<TcoilCurve> {
  return jsonOrThrow<TcoilCurve>(
    await fetch("/api/tcoil/eval", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ L, k, Cb }),
    }),
  );
}

import type { OpAmpResult, OpAmpStudy, Preflight, SpectreEval } from "./types";

export async function fetchOpamp(): Promise<OpAmpResult> {
  return jsonOrThrow<OpAmpResult>(await fetch("/api/opamp"));
}
export async function fetchOpampStudy(): Promise<OpAmpStudy> {
  return jsonOrThrow<OpAmpStudy>(await fetch("/api/opamp/study?seeds=4"));
}
export async function fetchPreflight(): Promise<Preflight> {
  return jsonOrThrow<Preflight>(await fetch("/api/opamp/preflight"));
}
export async function fetchSpectreEval(): Promise<SpectreEval> {
  return jsonOrThrow<SpectreEval>(await fetch("/api/opamp/spectre-eval"));
}

import type { AdaptResponse } from "./types";

export async function adaptProcess(nl: string): Promise<AdaptResponse> {
  return jsonOrThrow<AdaptResponse>(
    await fetch("/api/adapt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nl }),
    }),
  );
}

import type { SurrogateData, SkillData, BridgeData, BodeData, AgentResp } from "./types";

export const fetchSurrogate = () => fetch("/api/surrogate").then((r) => r.json() as Promise<SurrogateData>);
export const fetchSkill = () => fetch("/api/skill").then((r) => r.json() as Promise<SkillData>);
export const fetchBridge = () => fetch("/api/bridge").then((r) => r.json() as Promise<BridgeData>);
export const fetchOpampBode = () => fetch("/api/opamp/bode").then((r) => r.json() as Promise<BodeData>);
export async function askAgent(prompt: string): Promise<AgentResp> {
  return jsonOrThrow<AgentResp>(await fetch("/api/agent", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  }));
}

import type { TcoilGeom } from "./types";

export async function geomTcoil(b: {
  turns: number; width: number; spacing: number; inner: number;
  r_ohm: number; cl_ff: number; cb: number;
}): Promise<TcoilGeom> {
  return jsonOrThrow<TcoilGeom>(await fetch("/api/tcoil/geometry", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(b),
  }));
}

import type { ProcessEffects } from "./types";

export async function processEffects(nl: string, tech: Record<string, number>): Promise<ProcessEffects> {
  return jsonOrThrow<ProcessEffects>(await fetch("/api/process/effects", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nl, tech }),
  }));
}

import type { NgspiceEval } from "./types";

export const fetchNgspiceEval = (model: "generic" | "sky130" = "generic") =>
  fetch(`/api/opamp/ngspice-eval?model=${model}`).then((r) => r.json() as Promise<NgspiceEval>);

import type { FloorplanComponent, FloorplanData } from "./types";

export const fetchFloorplanScenario = () =>
  fetch("/api/floorplan/scenario").then((r) => r.json() as Promise<FloorplanData>);

export async function routeFloorplan(
  width: number, height: number, components: FloorplanComponent[], optimize: boolean,
): Promise<FloorplanData> {
  return jsonOrThrow<FloorplanData>(
    await fetch("/api/floorplan/route", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ width, height, components, optimize }),
    }),
  );
}

import type { ScenarioCase, ScenarioData, CCCompare } from "./types";

export const fetchScenarioCases = () =>
  fetch("/api/scenarios").then((r) => r.json() as Promise<{ cases: ScenarioCase[] }>);
export const fetchScenario = (key: string) =>
  fetch(`/api/scenarios/${key}`).then((r) => r.json() as Promise<ScenarioData>);
export const fetchCommonCentroid = (rows = 4, cols = 4) =>
  fetch(`/api/common-centroid?rows=${rows}&cols=${cols}`).then((r) => r.json() as Promise<CCCompare>);

import type { PPAData } from "./types";

export const fetchPPA = (wPower: number, wArea: number, wPerf: number, seed = 0) =>
  fetch(`/api/ppa?w_power=${wPower}&w_area=${wArea}&w_perf=${wPerf}&seed=${seed}`)
    .then((r) => r.json() as Promise<PPAData>);

import type { FlowData } from "./types";

export const fetchFlow = (place: "sa" | "random", seed = 0) =>
  fetch(`/api/flow?place=${place}&seed=${seed}`).then((r) => r.json() as Promise<FlowData>);

import type { FullFlowData } from "./types";

export const fetchFullFlow = (place: "sa" | "random", seed = 0, sky130 = false) =>
  fetch(`/api/full-flow?place=${place}&seed=${seed}&sky130=${sky130}`)
    .then((r) => r.json() as Promise<FullFlowData>);
