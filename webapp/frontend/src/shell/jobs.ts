// Run manager client for the backend job API (/api/jobs). Heavy actions are
// submitted as jobs so they run off the request path, dedupe, hit the result
// cache, and stream per-stage progress over SSE; the dock lists them all.

import { ApiError, createStore, http, toast } from "./telemetry";

export type JobStatus = "queued" | "running" | "done" | "error" | "cancelled";

export interface JobStage {
  stage: string;
  wallS: number;
}

export interface JobSnapshot {
  job_id: string;
  kind: string;
  params: Record<string, unknown>;
  status: JobStatus;
  cache: "hit" | "miss" | null;
  createdAt: number;
  startedAt: number | null;
  finishedAt: number | null;
  queueSeconds: number | null;
  runSeconds: number | null;
  stages: JobStage[];
  error: string | null;
  result?: unknown;
}

export interface JobCounts {
  total: number;
  maxJobs: number;
  maxRunning: number;
  queued?: number;
  running?: number;
  done?: number;
  error?: number;
  cancelled?: number;
}

export const TERMINAL: ReadonlySet<JobStatus> = new Set(["done", "error", "cancelled"]);

// Display names are derived from (kind, params) rather than remembered per
// tab, so every window and every user sees the same name for the same run.
const KIND_LABEL: Record<string, string> = {
  "full-flow": "Full flow", flow: "P&R flow", "flow/gds": "GDS export",
  "flow/drc-klayout": "KLayout DRC", optimize: "Device optimization",
  joint: "Joint device + route optimization", maze: "Comparator maze routing",
  ppa: "PPA Pareto (NSGA-II)", opamp: "OTA sizing", "opamp/study": "OTA optimizer study",
  "opamp/spectre-eval": "Spectre AC evaluation", "opamp/ngspice-eval": "ngspice AC evaluation",
  "opamp/bode": "OTA Bode", pvt: "PVT corners", tcoil: "T-coil optimization",
  adapt: "Process adaptation", "process/effects": "Process effects",
  surrogate: "Surrogate active learning", skill: "SKILL generation", lvs: "LVS",
  antenna: "Antenna check", em: "EM check", lde: "LDE analysis",
  "common-centroid": "Common-centroid compare", scenario: "Routing scenario",
  "floorplan/scenario": "Floorplan scenario", "layout/shapes": "Layout shapes",
};

function paramSummary(kind: string, p: Record<string, unknown>): string[] {
  const out: string[] = [];
  if (kind === "full-flow") {
    out.push(Number(p.sweep) > 0 ? `${p.sweep}-seed sweep` : `seed ${p.seed ?? 0}`);
    if (p.sky130) out.push("SKY130");
    return out;
  }
  if (typeof p.place === "string") out.push(p.place);
  if (p.seed !== undefined) out.push(`seed ${p.seed}`);
  if (p.seeds !== undefined) out.push(`${p.seeds} seeds`);
  if (typeof p.model === "string") out.push(p.model);
  if (p.full === true) out.push("full grid");
  if (p.analog === true) out.push("analog-aware");
  if (typeof p.key === "string") out.push(p.key);
  return out;
}

export function describeJob(kind: string, params: Record<string, unknown> = {}): string {
  return [KIND_LABEL[kind] ?? kind, ...paramSummary(kind, params)].join(" · ");
}

export const jobLabel = (j: JobSnapshot) => describeJob(j.kind, j.params);

export const jobsStore = createStore<{ jobs: JobSnapshot[]; counts: JobCounts | null }>({
  jobs: [],
  counts: null,
});

export async function refreshJobs(): Promise<void> {
  const r = await http<{ jobs: JobSnapshot[]; counts: JobCounts }>("/api/jobs", { quiet: true });
  jobsStore.set({ jobs: [...r.jobs].sort((a, b) => b.createdAt - a.createdAt), counts: r.counts });
}

export async function cancelJob(id: string): Promise<void> {
  await http(`/api/jobs/${id}`, { method: "DELETE" });
  await refreshJobs();
}

/** Poll the job list: fast while anything is active, slow otherwise. */
export function startJobsPolling(): () => void {
  let timer = 0;
  let stopped = false;
  const tick = async () => {
    try {
      await refreshJobs();
    } catch {
      /* status bar shows connectivity; keep polling */
    }
    if (stopped) return;
    const active = jobsStore.get().jobs.some((j) => !TERMINAL.has(j.status));
    timer = window.setTimeout(tick, active ? 700 : 2500);
  };
  tick();
  return () => {
    stopped = true;
    window.clearTimeout(timer);
  };
}

interface RunOptions {
  onStage?: (s: JobStage) => void;
  /** toast on completion when the run took longer than this (seconds) */
  notifyAfterS?: number;
}

function waitTerminal(id: string, onStage?: (s: JobStage) => void): Promise<void> {
  return new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (!settled) {
        settled = true;
        resolve();
      }
    };
    const poll = async () => {
      while (!settled) {
        try {
          const s = await http<JobSnapshot>(`/api/jobs/${id}`, { quiet: true });
          if (TERMINAL.has(s.status)) return finish();
        } catch {
          return finish();
        }
        await new Promise((r) => setTimeout(r, 400));
      }
    };
    if (typeof EventSource === "undefined") {
      poll();
      return;
    }
    const es = new EventSource(`/api/jobs/${id}/events`);
    es.addEventListener("progress", (ev) => {
      const d = JSON.parse((ev as MessageEvent).data);
      if (d.stage) onStage?.({ stage: d.stage, wallS: d.wallS });
    });
    es.addEventListener("status", (ev) => {
      const d = JSON.parse((ev as MessageEvent).data);
      if (TERMINAL.has(d.status)) {
        es.close();
        finish();
      }
    });
    es.onerror = () => {
      // Proxy hiccup or server restart: fall back to polling.
      es.close();
      poll();
    };
  });
}

/** Submit a job, stream its stages, and resolve with its result. */
export async function runJob<T>(kind: string, params: Record<string, unknown> = {},
                                opts: RunOptions = {}): Promise<T> {
  const sub = await http<{ job_id: string; status: JobStatus }>("/api/jobs", {
    json: { kind, params },
  });
  refreshJobs().catch(() => {});
  if (!TERMINAL.has(sub.status)) await waitTerminal(sub.job_id, opts.onStage);
  const snap = await http<JobSnapshot>(`/api/jobs/${sub.job_id}`);
  const name = describeJob(kind, snap.params ?? params);
  refreshJobs().catch(() => {});
  if (snap.status !== "done") {
    const msg = snap.error ?? `job ${snap.status}`;
    toast("error", `${name} failed`, msg, 8000);
    throw new ApiError(500, msg);
  }
  const took = snap.runSeconds ?? 0;
  if (took >= (opts.notifyAfterS ?? 2)) {
    toast("ok", `${name} finished`, `${took.toFixed(1)} s`);
  }
  return snap.result as T;
}
