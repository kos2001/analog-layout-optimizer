import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { http } from "./telemetry";

interface Store<T> {
  get: () => T;
  subscribe: (l: () => void) => () => void;
}

export function useStore<T>(store: Store<T>): T {
  return useSyncExternalStore(store.subscribe, store.get);
}

/** Hash route (#/view-id) so views are deep-linkable and survive reloads. */
export function useHashRoute(fallback: string): [string, (id: string) => void] {
  const read = () => window.location.hash.replace(/^#\/?/, "") || fallback;
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const on = () => setRoute(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  });
  const go = useCallback((id: string) => {
    window.location.hash = `/${id}`;
  }, []);
  return [route, go];
}

/** useState persisted to localStorage (per-browser UI preferences only). */
export function usePersisted<T>(key: string, initial: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? initial : (JSON.parse(raw) as T);
    } catch {
      return initial;
    }
  });
  const set = useCallback((next: T) => {
    setV(next);
    try {
      localStorage.setItem(key, JSON.stringify(next));
    } catch {
      /* storage blocked: keep in memory */
    }
  }, [key]);
  return [v, set];
}

export interface Health {
  status: string;
  version: string;
  executor: {
    mode: string;
    workers: number;
    started: boolean;
    fallbackReason: string | null;
    cache: { size: number; maxsize: number; hits: number; misses: number; shared: number; errors: number };
  };
  jobs: { total: number; maxRunning: number; [k: string]: number };
}

/** Backend health, polled; null while unreachable. */
export function useHealth(intervalMs = 4000): { health: Health | null; online: boolean } {
  const [health, setHealth] = useState<Health | null>(null);
  const [online, setOnline] = useState(true);
  useEffect(() => {
    let alive = true;
    const tick = () =>
      http<Health>("/api/health", { quiet: true })
        .then((h) => { if (alive) { setHealth(h); setOnline(true); } })
        .catch(() => { if (alive) setOnline(false); });
    tick();
    const id = window.setInterval(tick, intervalMs);
    return () => { alive = false; window.clearInterval(id); };
  }, [intervalMs]);
  return { health, online };
}
