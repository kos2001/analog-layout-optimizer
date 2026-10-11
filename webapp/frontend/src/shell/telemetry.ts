// Client-side telemetry shared by the shell: every API call is logged to the
// console panel, and errors / notable events surface as toasts. A tiny
// pub/sub store keeps this free of React context plumbing.

export interface ApiLogEntry {
  id: number;
  at: number;
  method: string;
  url: string;
  status: number | null;   // null = network failure
  ms: number;
  note?: string;
}

export type ToastKind = "info" | "ok" | "warn" | "error";

export interface Toast {
  id: number;
  kind: ToastKind;
  title: string;
  detail?: string;
}

type Listener = () => void;

export function createStore<T>(initial: T) {
  let value = initial;
  const listeners = new Set<Listener>();
  return {
    get: () => value,
    set(next: T) {
      value = next;
      listeners.forEach((l) => l());
    },
    subscribe(l: Listener) {
      listeners.add(l);
      return () => listeners.delete(l);
    },
  };
}

const MAX_LOG = 300;
let seq = 0;

export const apiLog = createStore<ApiLogEntry[]>([]);
export const toasts = createStore<Toast[]>([]);

export function logApi(entry: Omit<ApiLogEntry, "id" | "at">) {
  const next = [...apiLog.get(), { ...entry, id: ++seq, at: Date.now() }];
  apiLog.set(next.length > MAX_LOG ? next.slice(-MAX_LOG) : next);
}

export function clearApiLog() {
  apiLog.set([]);
}

export function toast(kind: ToastKind, title: string, detail?: string, ttlMs = 5000) {
  const id = ++seq;
  toasts.set([...toasts.get(), { id, kind, title, detail }].slice(-4));
  if (ttlMs > 0) window.setTimeout(() => dismissToast(id), ttlMs);
}

export function dismissToast(id: number) {
  toasts.set(toasts.get().filter((t) => t.id !== id));
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export type HttpInit = RequestInit & { json?: unknown; quiet?: boolean };

/** fetch + JSON with status checking and console logging (``quiet`` skips
 * the console, for background polling). */
export async function http<T>(url: string, init?: HttpInit): Promise<T> {
  const method = init?.method ?? (init?.json !== undefined ? "POST" : "GET");
  const req: RequestInit = { ...init, method };
  if (init?.json !== undefined) {
    req.headers = { "Content-Type": "application/json", ...(init.headers ?? {}) };
    req.body = JSON.stringify(init.json);
  }
  const log = init?.quiet ? () => {} : logApi;
  const t0 = performance.now();
  let res: Response;
  try {
    res = await fetch(url, req);
  } catch (e) {
    log({ method, url, status: null, ms: performance.now() - t0, note: String(e) });
    throw new ApiError(0, "Backend unreachable — is the API server running on :8011?");
  }
  const ms = performance.now() - t0;
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body?.detail === "string" ? body.detail : JSON.stringify(body?.detail ?? body);
    } catch {
      /* non-JSON error body */
    }
    log({ method, url, status: res.status, ms, note: detail });
    throw new ApiError(res.status, `${res.status} ${detail}`);
  }
  log({ method, url, status: res.status, ms, note: res.headers.get("x-cache") ?? undefined });
  return (await res.json()) as T;
}
