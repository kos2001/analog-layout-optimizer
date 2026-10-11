import { useEffect, useRef, useState } from "react";
import { evaluate, fetchConfig, optimize, optimizeJoint } from "../api";
import { useT } from "../i18n";
import type { Config, LayoutPayload, OptimizeResult, Params } from "../types";
import ConvergenceChart from "./ConvergenceChart";
import LayoutCanvas from "./LayoutCanvas";
import ParamSliders from "./ParamSliders";

// Device-level layout: live DRC-checked evaluation as sliders move, plus
// device-only and joint (device + interconnect) optimization with replay.
export default function DeviceView() {
  const { t } = useT();
  const [config, setConfig] = useState<Config | null>(null);
  const [params, setParams] = useState<Params | null>(null);
  const [layout, setLayout] = useState<LayoutPayload | null>(null);
  const [opt, setOpt] = useState<OptimizeResult | null>(null);
  const [frameIdx, setFrameIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const debounce = useRef<number | null>(null);
  const replaying = opt !== null && playing;

  // Initial load.
  useEffect(() => {
    fetchConfig()
      .then((cfg) => {
        setConfig(cfg);
        setParams(cfg.defaults);
      })
      .catch((e) => setError(String(e)));
  }, []);

  // Debounced live evaluation when sliders move (manual mode only). While an
  // optimization result is shown (opt != null) the layout comes from its
  // frames, so manual evaluation must stay off or it would overwrite the
  // routed/joint layout with a device-only one.
  useEffect(() => {
    if (!params || opt) return;
    if (debounce.current) window.clearTimeout(debounce.current);
    debounce.current = window.setTimeout(() => {
      evaluate(params)
        .then(setLayout)
        .catch((e) => setError(String(e)));
    }, 80);
    return () => {
      if (debounce.current) window.clearTimeout(debounce.current);
    };
  }, [params, opt]);

  // Animation playback through optimization frames.
  useEffect(() => {
    if (!opt || !playing) return;
    if (frameIdx >= opt.frames.length - 1) {
      setPlaying(false);
      return;
    }
    const t = window.setTimeout(() => setFrameIdx((i) => i + 1), 120);
    return () => window.clearTimeout(t);
  }, [opt, playing, frameIdx]);

  // While replaying, the shown layout + slider positions track the frame.
  useEffect(() => {
    if (!opt) return;
    const f = opt.frames[Math.min(frameIdx, opt.frames.length - 1)];
    setLayout(f.layout);
    setParams(f.params);
  }, [opt, frameIdx]);

  const run = async (fn: () => Promise<typeof opt>) => {
    setBusy(true);
    setError(null);
    try {
      const result = await fn();
      setOpt(result);
      setFrameIdx(0);
      setPlaying(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const runOptimize = () => run(() => optimize(0, 60));
  const runJoint = () => run(() => optimizeJoint(0, 60));

  const resetManual = () => {
    setOpt(null);
    setPlaying(false);
    if (config) setParams(config.defaults);
  };

  return (
    <>
      {error && <div className="fatal">Error: {error}</div>}
      {!error && !(config && params && layout) && (
        <div className="loading">{t("loading")}</div>
      )}
      {config && params && layout && (
      <div className="grid">
        <section className="panel layout-panel">
          <div className="panel-title">
            {t("layout.title")}
            <span className={layout.isClean ? "badge ok" : "badge bad"}>
              {layout.isClean ? t("drc.clean") : `${layout.violations.length} violation(s)`}
            </span>
          </div>
          <LayoutCanvas layout={layout} />
          <div className="metrics">
            <div>
              <span className="metric-label">
                {layout.deviceArea != null ? t("total.area") : t("bbox.area")}
              </span>
              <span className="metric-value">{layout.area.toFixed(4)} µm²</span>
            </div>
            {layout.deviceArea != null ? (
              <>
                <div>
                  <span className="metric-label">{t("device.area")}</span>
                  <span className="metric-value">{layout.deviceArea.toFixed(4)} µm²</span>
                </div>
                <div>
                  <span className="metric-label">{t("wirelength")}</span>
                  <span className="metric-value">
                    {layout.wirelength?.toFixed(2)} µm
                  </span>
                </div>
              </>
            ) : (
              <div>
                <span className="metric-label">W_total</span>
                <span className="metric-value">
                  {(config.config.nf * params.w_finger).toFixed(3)} / {config.config.w_min_total} µm
                </span>
              </div>
            )}
          </div>
          <div className="legend">
            <span><i className="sw od" /> OD diffusion</span>
            <span><i className="sw po" /> PO poly</span>
            <span><i className="sw m1" /> M1 guard ring</span>
            <span><i className="sw m2" /> M2 routing</span>
            <span><i className="sw via" /> via</span>
            <span><i className="sw vio" /> DRC violation</span>
          </div>
        </section>

        <section className="panel controls-panel">
          <div className="panel-title">{t("params.title")}</div>
          <ParamSliders
            config={config}
            params={params}
            disabled={replaying}
            onChange={(p) => {
              // Manually editing a parameter drops back to manual mode so live
              // evaluation resumes (and the optimization result is dismissed).
              if (opt) {
                setOpt(null);
                setPlaying(false);
              }
              setParams(p);
            }}
          />

          <div className="actions">
            <button onClick={runOptimize} disabled={busy}>
              {busy ? t("btn.optimizing") : t("btn.optimize.device")}
            </button>
            <button onClick={runJoint} disabled={busy}>
              {t("btn.joint")}
            </button>
            <button className="secondary" onClick={resetManual} disabled={busy}>
              {t("btn.reset")}
            </button>
          </div>

          {opt && (
            <div className="replay">
              <div className="replay-controls">
                <button onClick={() => setPlaying((p) => !p)}>
                  {playing ? t("btn.pause") : t("btn.play")}
                </button>
                <input
                  type="range"
                  min={0}
                  max={opt.frames.length - 1}
                  value={frameIdx}
                  onChange={(e) => {
                    setPlaying(false);
                    setFrameIdx(Number(e.target.value));
                  }}
                />
                <span className="frame-label">
                  {frameIdx + 1}/{opt.frames.length}
                </span>
              </div>
              <p className="opt-summary">
                {opt.nEvals} evaluations · best area{" "}
                <strong>{opt.best.area.toFixed(4)} µm²</strong> ·{" "}
                {opt.best.isClean ? "DRC clean ✓" : "has violations ✗"}
              </p>
            </div>
          )}
        </section>

        <section className="panel chart-panel">
          <div className="panel-title">{t("conv.title")}</div>
          <ConvergenceChart frames={opt?.frames ?? []} current={frameIdx} />
        </section>

        <section className="panel drc-panel">
          <div className="panel-title">{t("drc.status")}</div>
          {layout.isClean ? (
            <p className="drc-clean">All geometric rules and the drive spec are met.</p>
          ) : (
            <ul className="drc-list">
              {layout.violations.map((v, i) => (
                <li key={i}>{v}</li>
              ))}
            </ul>
          )}
          <p className="note">
            Geometric DRC (min width / spacing / enclosure) + drive-strength spec
            are checked in Python. Real PDK DRC/LVS and parasitics are the only
            steps that need Virtuoso.
          </p>
        </section>
      </div>
      )}
    </>
  );
}
