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
