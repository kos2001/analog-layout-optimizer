import { useT } from "../i18n";
import type { Health } from "./hooks";
import { useStore } from "./hooks";
import { Icon } from "./icons";
import { jobsStore } from "./jobs";

export default function StatusBar({ health, online, onOpenRuns }: {
  health: Health | null; online: boolean; onOpenRuns: () => void;
}) {
  const { t } = useT();
  const { counts } = useStore(jobsStore);
  const c = health?.executor.cache;
  const lookups = c ? c.hits + c.misses : 0;
  const running = counts?.running ?? 0;
  const queued = counts?.queued ?? 0;
  return (
    <footer className="statusbar">
      <div className="sb-group">
        <span className={online ? "sb-item" : "sb-item bad"}>
          <i className={online ? "dot ok" : "dot bad"} />
          {online ? t("sb.connected") : t("sb.offline")}
        </span>
        {health && (
          <>
            <span className="sb-item" title={t("sb.engine.title")}>
              <Icon name="chip" size={12} />{t("sb.engine")} {health.version.slice(0, 8)}
            </span>
            <span className="sb-item" title={health.executor.fallbackReason ?? t("sb.pool.title")}>
              <Icon name="server" size={12} />
              {health.executor.mode} × {health.executor.workers}
            </span>
          </>
        )}
      </div>
      <div className="sb-group">
        <button className="sb-item sb-btn" onClick={onOpenRuns}>
          {running > 0 && <i className="spinner" />}
          {t("sb.jobs").replace("{r}", String(running)).replace("{q}", String(queued))}
        </button>
        {c && (
          <span className="sb-item" title={`${c.size}/${c.maxsize} entries · ${c.shared} shared in-flight`}>
            <Icon name="database" size={12} />
            {t("sb.cache")} {lookups ? `${Math.round((100 * c.hits) / lookups)}%` : "—"} ({c.hits}/{lookups})
          </span>
        )}
        <span className="sb-item muted"><kbd>⌘K</kbd></span>
      </div>
    </footer>
  );
}
