import { Fragment, useEffect, useState } from "react";
import { useT } from "../i18n";
import { usePersisted, useStore } from "./hooks";
import { Icon, type IconName } from "./icons";
import { TERMINAL, cancelJob, jobLabel, jobsStore, type JobSnapshot, type JobStatus } from "./jobs";
import { apiLog, clearApiLog } from "./telemetry";

export type DockTab = "runs" | "console";

const STATUS_ICON: Record<JobStatus, IconName> = {
  queued: "clock", running: "play", done: "check", error: "alert", cancelled: "stop",
};

export const fmtSeconds = (s: number | null | undefined) =>
  s == null ? "—" : s < 1 ? `${Math.round(s * 1000)} ms` : `${s.toFixed(s < 10 ? 2 : 1)} s`;

function useNow(ms = 1000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), ms);
    return () => window.clearInterval(id);
  }, [ms]);
  return now;
}

function ago(epochS: number, now: number) {
  const d = Math.max(0, now / 1000 - epochS);
  if (d < 5) return "now";
  if (d < 60) return `${Math.floor(d)}s`;
  if (d < 3600) return `${Math.floor(d / 60)}m`;
  return `${Math.floor(d / 3600)}h`;
}

const STAGE_HUES = ["#4c8dff", "#a371f7", "#3fb9a0", "#d29922", "#f778ba", "#79c0ff", "#56d364"];

/** Proportional stage bar: each segment is a stage's share of wall time. */
function StageBar({ job, cachedLabel }: { job: JobSnapshot; cachedLabel: string }) {
  const total = job.stages.reduce((a, s) => a + s.wallS, 0);
  if (!job.stages.length && job.cache === "hit") {
    return <span className="stage-cached">{cachedLabel}</span>;
  }
  if (!job.stages.length) {
    return <div className={job.status === "running" ? "stagebar indeterminate" : "stagebar"} />;
  }
  return (
    <div className="stagebar" title={job.stages.map((s) => `${s.stage} ${fmtSeconds(s.wallS)}`).join("\n")}>
      {job.stages.map((s, i) => (
        <span key={`${s.stage}-${i}`} style={{
          flexGrow: Math.max(s.wallS, total * 0.02), background: STAGE_HUES[i % STAGE_HUES.length],
        }} />
      ))}
    </div>
  );
}

function RunsTable({ hideCached }: { hideCached: boolean }) {
  const { t } = useT();
  const { jobs: all } = useStore(jobsStore);
  const jobs = hideCached ? all.filter((j) => j.cache !== "hit") : all;
  const now = useNow();
  const [open, setOpen] = useState<string | null>(null);

  if (!jobs.length) {
    return <div className="dock-empty"><Icon name="play" size={18} />{t("runs.empty")}</div>;
  }
  return (
    <table className="runs">
      <thead>
        <tr>
          <th>{t("runs.status")}</th><th>{t("runs.job")}</th><th>{t("runs.stages")}</th>
          <th className="num">{t("runs.queue")}</th><th className="num">{t("runs.runtime")}</th>
          <th>{t("runs.cache")}</th><th className="num">{t("runs.started")}</th><th />
        </tr>
      </thead>
      <tbody>
        {jobs.map((j) => (
          <Fragment key={j.job_id}>
            <tr className={open === j.job_id ? "on" : ""}
                onClick={() => setOpen(open === j.job_id ? null : j.job_id)}>
              <td>
                <span className={`status-pill ${j.status}`}>
                  <Icon name={STATUS_ICON[j.status]} size={12} />{t(`runs.st.${j.status}`)}
                </span>
              </td>
              <td className="runs-job">
                <span>{jobLabel(j)}</span><code>{j.kind}</code>
              </td>
              <td className="runs-stages"><StageBar job={j} cachedLabel={t("runs.cached")} /></td>
              <td className="num">{fmtSeconds(j.queueSeconds)}</td>
              <td className="num">
                {j.status === "running" && j.startedAt
                  ? fmtSeconds(now / 1000 - j.startedAt)
                  : fmtSeconds(j.runSeconds)}
              </td>
              <td>{j.cache === "hit" ? <span className="tag ok">HIT</span> : <span className="tag">miss</span>}</td>
              <td className="num muted">{ago(j.createdAt, now)}</td>
              <td className="num">
                {j.status === "queued" && (
                  <button className="icon-btn" title={t("runs.cancel")}
                          onClick={(e) => { e.stopPropagation(); cancelJob(j.job_id); }}>
                    <Icon name="x" size={14} />
                  </button>
                )}
              </td>
            </tr>
            {open === j.job_id && (
              <tr className="runs-detail">
                <td colSpan={8}>
                  <div className="runs-detail-grid">
                    <div>
                      <div className="kv-label">job id</div><code>{j.job_id}</code>
                      <div className="kv-label">params</div><code>{JSON.stringify(j.params)}</code>
                      {j.error && (<><div className="kv-label">error</div><code className="bad">{j.error}</code></>)}
                    </div>
                    <div>
                      <div className="kv-label">{t("runs.stages")}</div>
                      {j.stages.length === 0 && <span className="muted">—</span>}
                      {j.stages.map((s, i) => (
                        <div key={i} className="stage-row">
                          <i style={{ background: STAGE_HUES[i % STAGE_HUES.length] }} />
                          <span>{s.stage}</span><span className="num">{fmtSeconds(s.wallS)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </td>
              </tr>
            )}
          </Fragment>
        ))}
      </tbody>
    </table>
  );
}

function ConsoleLog() {
  const { t } = useT();
  const log = useStore(apiLog);
  if (!log.length) return <div className="dock-empty"><Icon name="terminal" size={18} />{t("console.empty")}</div>;
  return (
    <div className="console">
      {[...log].reverse().map((e) => (
        <div key={e.id} className="console-line">
          <span className="muted">{new Date(e.at).toLocaleTimeString([], { hour12: false })}</span>
          <span className="console-method">{e.method}</span>
          <span className={e.status === null || e.status >= 400 ? "bad" : "ok"}>{e.status ?? "ERR"}</span>
          <span className="console-url">{e.url}</span>
          <span className="num muted">{Math.round(e.ms)} ms</span>
          {e.note && <span className="console-note">{e.note}</span>}
        </div>
      ))}
    </div>
  );
}

export default function RunDock({ tab, setTab, onClose }: {
  tab: DockTab; setTab: (t: DockTab) => void; onClose: () => void;
}) {
  const { t } = useT();
  const [hideCached, setHideCached] = usePersisted("alo.runs.hideCached", false);
  const { jobs } = useStore(jobsStore);
  const log = useStore(apiLog);
  const active = jobs.filter((j) => !TERMINAL.has(j.status)).length;
  return (
    <section className="dock" aria-label={t("dock.title")}>
      <div className="dock-bar">
        <div className="dock-tabs" role="tablist">
          <button role="tab" aria-selected={tab === "runs"} className={tab === "runs" ? "on" : ""}
                  onClick={() => setTab("runs")}>
            <Icon name="play" size={13} />{t("dock.runs")}
            <span className="count">{active ? `${active} ${t("dock.active")}` : jobs.length}</span>
          </button>
          <button role="tab" aria-selected={tab === "console"} className={tab === "console" ? "on" : ""}
                  onClick={() => setTab("console")}>
            <Icon name="terminal" size={13} />{t("dock.console")}<span className="count">{log.length}</span>
          </button>
        </div>
        <div className="dock-actions">
          {tab === "runs" && (
            <label className="dock-filter">
              <input type="checkbox" checked={hideCached} onChange={(e) => setHideCached(e.target.checked)} />
              {t("runs.hideCached")}
            </label>
          )}
          {tab === "console" && (
            <button className="icon-btn" title={t("console.clear")} onClick={clearApiLog}>
              <Icon name="trash" size={14} />
            </button>
          )}
          <button className="icon-btn" title={`${t("dock.hide")} (⌘J)`} onClick={onClose}>
            <Icon name="x" size={14} />
          </button>
        </div>
      </div>
      <div className="dock-body">{tab === "runs" ? <RunsTable hideCached={hideCached} /> : <ConsoleLog />}</div>
    </section>
  );
}
