import { useEffect, useState } from "react";
import { fetchFullFlow } from "../api";
import { useT } from "../i18n";
import { Icon } from "../shell/icons";
import type { JobStage } from "../shell/jobs";
import type { FullFlowData } from "../types";
import RouteGrid, { netColorFactory } from "./RouteGrid";

const STATUS_ICON: Record<string, string> = { pass: "✓", fail: "✗", warn: "!", info: "•" };

// Engine stages, in pipeline order, as the backend profiler names them.
const PIPELINE = ["sizing", "placement", "routing", "signoff", "postlayout"] as const;
const SWEEP = 4;

function StageItem({ name, status, detail, last }: {
  name: string; status: string; detail: string; last: boolean;
}) {
  return (
    <div className={`stage ${status}`}>
      <div className="stage-rail">
        <div className="stage-dot">{status === "live" ? <i className="spinner" /> : STATUS_ICON[status] ?? "•"}</div>
        {!last && <div className="stage-line" />}
      </div>
      <div className="stage-text">
        <div className="stage-name">{name}</div>
        <div className="stage-detail">{detail}</div>
      </div>
    </div>
  );
}

/** While a run is in flight: which engine stages have reported, and how often. */
function LiveTimeline({ progress, sky130, elapsed }: {
  progress: JobStage[]; sky130: boolean; elapsed: number;
}) {
  const { t } = useT();
  const steps = sky130 ? [...PIPELINE, "silicon"] : [...PIPELINE];
  const seen = (s: string) => progress.filter((p) => p.stage === s);
  const firstOpen = steps.findIndex((s) => seen(s).length < SWEEP);
  return (
    <div className="ff-stages">
      {steps.map((s, i) => {
        const done = seen(s);
        const wall = done.reduce((a, p) => a + p.wallS, 0);
        const status = done.length >= SWEEP ? "pass" : i === firstOpen ? "live" : done.length ? "live" : "pending";
        const detail = done.length
          ? `${done.length}/${SWEEP} ${t("ff.seeds")} · ${wall.toFixed(2)} s`
          : status === "live" ? `${t("ff.running")} ${elapsed.toFixed(1)} s` : t("ff.pending");
        return <StageItem key={s} name={t(`ff.stage.${s}`)} status={status} detail={detail}
                          last={i === steps.length - 1} />;
      })}
    </div>
  );
}

export default function FullFlowView() {
  const { t } = useT();
  const [data, setData] = useState<FullFlowData | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [sky130, setSky130] = useState(false);
  const [hover, setHover] = useState<string | null>(null);
  const [progress, setProgress] = useState<JobStage[]>([]);
  const [startedAt, setStartedAt] = useState(0);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (!busy) return;
    const id = window.setInterval(() => setNow(Date.now()), 200);
    return () => window.clearInterval(id);
  }, [busy]);

  const run = async () => {
    setBusy(true); setErr(null); setProgress([]); setStartedAt(Date.now()); setNow(Date.now());
    try {
      // Deterministic best-of-N sweep: the backend ranks seeds by sign-off
      // (LVS clean, all nets routed, DRC, post-layout PM) and returns the best.
      setData(await fetchFullFlow("sa", 0, sky130, SWEEP, (s) => setProgress((p) => [...p, s])));
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  const pass = data?.verdict === "PASS";
  const names = data ? Object.keys(data.netlist) : [];

  return (
    <div className="grid">
      <section className="panel" style={{ gridColumn: "1 / -1" }}>
        <div className="panel-title">
          {t("ff.title")}
          {data && !busy && (
            <span className={pass ? "badge ok" : "badge bad"}>{pass ? t("ff.verdict.pass") : data.verdict}</span>
          )}
        </div>
        <p className="note" style={{ marginTop: 0 }}>{t("ff.note")}</p>
        <div className="ff-toolbar">
          <button onClick={run} disabled={busy}>
            {busy ? <i className="spinner" /> : <Icon name="play" size={14} />}
            {busy ? t("ff.running") : t("ff.run")}
          </button>
          <label className="ff-check">
            <input type="checkbox" checked={sky130} disabled={busy} onChange={(e) => setSky130(e.target.checked)} />
            {t("ff.sky130")}
          </label>
          {sky130 && <span className="hint">{t("ff.sky130.slow")}</span>}
        </div>
        {err && <p className="note bad">{err}</p>}

        {busy && (
          <div className="ff-body" style={{ marginTop: 16 }}>
            <LiveTimeline progress={progress} sky130={sky130} elapsed={(now - startedAt) / 1000} />
          </div>
        )}

        {data && !busy && (
          <>
            <div className={pass ? "ff-verdict pass" : "ff-verdict fail"}>
              <span className={pass ? "badge ok" : "badge bad"} style={{ fontSize: 13 }}>
                {pass ? `✓ ${t("ff.verdict.pass")}` : `✗ ${data.verdict}`}
              </span>
              <span>
                {data.sizing.power_mw} mW · GBW {data.sizing.gbw_mhz} MHz · gain {data.sizing.gain_db} dB ·
                HPWL {data.hpwl} · WL {data.routing.totalWirelength}
                {data.sweep && ` · best seed ${data.sweep.bestSeed}/${data.sweep.seeds.length} (${data.sweep.verdicts.filter((v) => v === "PASS").length} PASS)`}
              </span>
            </div>

            <div className="ff-body">
              <div className="ff-stages">
                {data.stages.map((s, i) => (
                  <StageItem key={s.name} {...s} last={i === data.stages.length - 1} />
                ))}
              </div>
              <div className="ff-route">
                <RouteGrid data={data} netColor={netColorFactory(names)}
                  hover={hover} setHover={setHover} showDrc />
              </div>
            </div>
          </>
        )}
        {!data && !busy && <p className="note">{t("ff.hint")}</p>}
      </section>
    </div>
  );
}
