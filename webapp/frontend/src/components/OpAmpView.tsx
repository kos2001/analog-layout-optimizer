import { useEffect, useState } from "react";
import { fetchOpamp, fetchOpampBode, fetchOpampStudy, fetchPreflight, fetchSpectreEval, fetchNgspiceEval, fetchPVT } from "../api";
import { useT } from "../i18n";
import type { BodeData, NgspiceEval, OpAmpResult, OpAmpStudy, Preflight, SpectreEval, PVTData } from "../types";

function BodePanel({ bode }: { bode: BodeData }) {
  const W = 380, H = 200, padL = 40, padB = 24, padT = 10, padR = 10;
  const lx0 = Math.log10(bode.freq[0]), lx1 = Math.log10(bode.freq[bode.freq.length - 1]);
  const top = Math.max(...bode.magDb) + 5, bot = -40;
  const px = (f: number) => padL + ((Math.log10(f) - lx0) / (lx1 - lx0)) * (W - padL - padR);
  const py = (d: number) => padT + ((top - d) / (top - bot)) * (H - padT - padB);
  const path = bode.magDb.map((d, i) => `${i ? "L" : "M"} ${px(bode.freq[i]).toFixed(1)} ${py(d).toFixed(1)}`).join(" ");
  return (
    <svg width={W} height={H} className="bode">
      <rect width={W} height={H} fill="#0d1117" />
      {[0, -20].map((d) => (
        <g key={d}><line x1={padL} y1={py(d)} x2={W - padR} y2={py(d)} stroke="#161b22" />
          <text x={6} y={py(d) + 4} className="axis">{d}dB</text></g>
      ))}
      <line x1={padL} y1={py(top - 3)} x2={W - padR} y2={py(top - 3)} stroke="#6e40aa" strokeDasharray="3 3" />
      <path d={path} fill="none" stroke="#42a5f5" strokeWidth={2} />
      <text x={W - padR} y={H - 8} textAnchor="end" className="axis">Hz (log) →</text>
    </svg>
  );
}

export default function OpAmpView() {
  const { t } = useT();
  const [design, setDesign] = useState<OpAmpResult | null>(null);
  const [study, setStudy] = useState<OpAmpStudy | null>(null);
  const [pf, setPf] = useState<Preflight | null>(null);
  const [se, setSe] = useState<SpectreEval | null>(null);
  const [ng, setNg] = useState<NgspiceEval | null>(null);
  const [backend, setBackend] = useState<"spectre" | "ngspice">("ngspice");
  const [ngModel, setNgModel] = useState<"generic" | "sky130">("generic");
  const [bode, setBode] = useState<BodeData | null>(null);
  const [pvt, setPvt] = useState<PVTData | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetchOpamp().then(setDesign).catch((e) => setErr(String(e)));
    fetchPreflight().then(setPf).catch(() => {});
    fetchOpampBode().then(setBode).catch(() => {});
  }, []);

  const run = (name: string, fn: () => Promise<void>) => async () => {
    setBusy(name); setErr(null);
    try { await fn(); } catch (e) { setErr(String(e)); } finally { setBusy(null); }
  };

  if (err) return <div className="fatal">Error: {err}</div>;

  const maxPow = study ? Math.max(...study.results.map((r) => r.mean_mw)) : 1;

  return (
    <div className="grid">
      {/* Sizing result */}
      <section className="panel">
        <div className="panel-title">
          {t("opamp.title")}
          {design && (
            <span className={design.feasible ? "badge ok" : "badge bad"}>
              {design.feasible ? "specs met" : "infeasible"}
            </span>
          )}
        </div>
        {!design ? (
          <div className="loading">Sizing…</div>
        ) : (
          <>
            <table className="tcoil-table">
              <thead><tr><th></th><th>achieved</th><th>target</th><th></th></tr></thead>
              <tbody>
                {design.specs.map((s) => (
                  <tr key={s.name}>
                    <td>{s.name}</td>
                    <td>{s.value} {s.unit}</td>
                    <td>≥ {s.target}</td>
                    <td style={{ color: s.pass ? "var(--ok)" : "var(--bad)" }}>
                      {s.pass ? "✓" : "✗"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="metrics" style={{ marginTop: 12 }}>
              <div>
                <span className="metric-label">power (objective)</span>
                <span className="metric-value">{design.power_mw} mW</span>
              </div>
            </div>
            <p className="note">
              Sizing (W/L): M1 {design.sizing.wl1}, M3 {design.sizing.wl3}, M5 {design.sizing.wl5},
              M6 {design.sizing.wl6}, M7 {design.sizing.wl7} · Itail {design.sizing.itail_uA} µA ·
              I6 {design.sizing.i6_uA} µA · Cc {design.sizing.cc_pF} pF.
            </p>
            {bode && (
              <>
                <div className="panel-title" style={{ marginTop: 8 }}>{t("opamp.bode")}</div>
                <BodePanel bode={bode} />
                <p className="note">−3 dB line dashed; DC gain {bode.magDb[0].toFixed(1)} dB.</p>
              </>
            )}
          </>
        )}
      </section>

      {/* Optimizer study */}
      <section className="panel">
        <div className="panel-title">
          {t("opamp.study")}
          <button onClick={run("study", async () => setStudy(await fetchOpampStudy()))}
            disabled={busy !== null}>
            {busy === "study" ? "Running…" : "Compare"}
          </button>
        </div>
        {!study ? (
          <p className="note">
            Runs random search / DE-linear / DE-log / DE-log+refine across seeds.
            Click Compare (takes a few seconds).
          </p>
        ) : (
          <>
            {study.results.map((r) => {
              const win = r.strategy === "de_log" || r.strategy === "de_log_refine";
              return (
                <div key={r.strategy} style={{ marginBottom: 8 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
                    <span style={{ color: win ? "var(--accent)" : "var(--text)" }}>{r.strategy}</span>
                    <span style={{ color: "var(--muted)", fontVariantNumeric: "tabular-nums" }}>
                      {r.mean_mw} mW ± {r.std_mw}
                    </span>
                  </div>
                  <div style={{ height: 8, background: "#161b22", borderRadius: 4 }}>
                    <div style={{
                      width: `${(r.mean_mw / maxPow) * 100}%`, height: 8, borderRadius: 4,
                      background: win ? "var(--accent)" : "#6e7681",
                    }} />
                  </div>
                </div>
              );
            })}
            <p className="note">{study.note}</p>
          </>
        )}
      </section>

      {/* Simulation backend: commercial (Spectre) vs open-source (ngspice) */}
      <section className="panel" style={{ gridColumn: "1 / -1" }}>
        <div className="panel-title">
          Closed-loop verify — commercial vs open-source backend
          {backend === "ngspice" && ng && (
            <span className={ng.available ? "badge ok" : "badge bad"}>
              {ng.modelKind === "sky130"
                ? (ng.sky130Available ? "SKY130 silicon" : "SKY130 PDK missing")
                : (ng.available ? "ngspice ready" : "ngspice not installed")}
            </span>
          )}
          {backend === "spectre" && pf && (
            <span className={pf.ready ? "badge ok" : "badge bad"}>
              {pf.ready ? "Spectre ready" : "not connected"}
            </span>
          )}
        </div>
        <div className="seg" style={{ marginBottom: 10 }}>
          <button className={backend === "ngspice" ? "" : "secondary"} onClick={() => setBackend("ngspice")}>
            ngspice (open-source)
          </button>
          <button className={backend === "spectre" ? "" : "secondary"} onClick={() => setBackend("spectre")}>
            Spectre (Cadence)
          </button>
        </div>
        {backend === "ngspice" && (
          <div className="seg" style={{ marginBottom: 10 }}>
            <button className={ngModel === "generic" ? "" : "secondary"} onClick={() => setNgModel("generic")}>
              generic level-1
            </button>
            <button className={ngModel === "sky130" ? "" : "secondary"} onClick={() => setNgModel("sky130")}>
              SKY130 (real PDK)
            </button>
          </div>
        )}
        <button
          onClick={backend === "ngspice"
            ? run("v", async () => setNg(await fetchNgspiceEval(ngModel)))
            : run("v", async () => setSe(await fetchSpectreEval()))}
          disabled={busy !== null}>
          {busy === "v" ? "Verifying…" : t("opamp.verify")}
        </button>

        {backend === "ngspice" && ng && (
          <div style={{ marginTop: 12 }}>
            <table className="tcoil-table">
              <thead><tr><th></th><th>gain dB</th><th>GBW MHz</th><th>PM deg</th><th>power mW</th></tr></thead>
              <tbody>
                <tr><td>analytic model</td><td>{ng.analytic.gain_db}</td><td>{ng.analytic.gbw_mhz}</td>
                  <td>{ng.analytic.pm_deg}</td><td>{ng.analytic.power_mw}</td></tr>
                {ng.sim ? (
                  <tr><td>real ngspice ({ng.model})</td><td>{ng.sim.gain_db}</td><td>{ng.sim.gbw_mhz}</td>
                    <td>{ng.sim.pm_deg}</td><td>{ng.sim.power_mw}</td></tr>
                ) : (
                  <tr><td colSpan={5} style={{ color: "var(--muted)" }}>ngspice — {ng.error}</td></tr>
                )}
              </tbody>
            </table>
            <p className="note">
              {ng.modelKind === "sky130"
                ? "Real SkyWater SKY130 BSIM devices (sky130_fd_pr__nfet/pfet_01v8, tt corner) via the open PDK — silicon-grade numbers. They differ from the analytic square-law model: that gap is exactly why post-layout sim matters."
                : "Real open-source AC sweep (ngspice level-1). GBW & PM track the analytic model; switch to SKY130 (real PDK) above for silicon-grade device physics."}
            </p>
          </div>
        )}

        {backend === "spectre" && se && (
          <div style={{ marginTop: 12 }}>
            <table className="tcoil-table">
              <thead><tr><th></th><th>gain dB</th><th>GBW MHz</th><th>PM deg</th><th>power mW</th></tr></thead>
              <tbody>
                <tr><td>analytic model</td><td>{se.analytic.gain_db}</td><td>{se.analytic.gbw_mhz}</td>
                  <td>{se.analytic.pm_deg}</td><td>{se.analytic.power_mw}</td></tr>
                {se.spectre ? (
                  <tr><td>real Spectre ({se.pdk})</td><td>{se.spectre.gain_db}</td><td>{se.spectre.gbw_mhz}</td>
                    <td>{se.spectre.pm_deg}</td><td>{se.spectre.power_mw}</td></tr>
                ) : (
                  <tr><td colSpan={5} style={{ color: "var(--muted)" }}>Spectre not connected — {se.error}</td></tr>
                )}
              </tbody>
            </table>
            {se.status === "spectre_unavailable" && se.preflight && (
              <ul className="drc-list" style={{ color: "var(--muted)", marginTop: 8 }}>
                {se.preflight.guidance.map((g, i) => <li key={i}>{g}</li>)}
              </ul>
            )}
          </div>
        )}
        <p className="note">
          Same params → specs contract for both backends. ngspice gives a real,
          license-free closed loop now; Spectre is the commercial path via
          virtuoso-bridge. Swapping the backend doesn't change the optimizer.
        </p>
      </section>

      {/* PVT corner analysis on real SKY130 */}
      <section className="panel" style={{ gridColumn: "1 / -1" }}>
        <div className="panel-title">
          PVT corners — worst-case across process / voltage / temperature (SKY130)
          {pvt?.available && pvt.stable !== undefined && (
            <span className={pvt.stable ? "badge ok" : "badge bad"}>
              {pvt.stable ? "robust (PM > 45° all corners)" : "fails a corner"}
            </span>
          )}
        </div>
        <button
          onClick={run("pvt", async () => setPvt(await fetchPVT(false)))}
          disabled={busy !== null}>
          {busy === "pvt" ? "Sweeping corners… (~1 min)" : "Run PVT (3 corners, real SKY130)"}
        </button>
        <span className="note" style={{ marginLeft: 10 }}>
          each corner is a real ~15 s ngspice run
        </span>
        {pvt && !pvt.available && (
          <p className="note" style={{ color: "var(--muted)", marginTop: 8 }}>{pvt.error}</p>
        )}
        {pvt?.available && pvt.corners && (
          <div style={{ marginTop: 12 }}>
            <table className="tcoil-table">
              <thead><tr><th>corner</th><th>gain dB</th><th>GBW MHz</th><th>PM deg</th></tr></thead>
              <tbody>
                {pvt.corners.map((c, i) => (
                  <tr key={i}>
                    <td>{c.process} · {c.temp_c}°C · {c.vdd}V{c.process === pvt.nominal?.process && c.temp_c === pvt.nominal?.temp_c ? " (nominal)" : ""}</td>
                    <td>{c.gain_db}</td><td>{c.gbw_mhz}</td>
                    <td style={{ color: c.pm_deg < 45 ? "var(--bad)" : "var(--text)" }}>{c.pm_deg}</td>
                  </tr>
                ))}
                {pvt.worst && (
                  <tr style={{ fontWeight: 700 }}>
                    <td>worst case</td><td>{pvt.worst.gain_db}</td><td>{pvt.worst.gbw_mhz}</td>
                    <td style={{ color: pvt.worst.pm_deg < 45 ? "var(--bad)" : "var(--ok)" }}>{pvt.worst.pm_deg}</td>
                  </tr>
                )}
              </tbody>
            </table>
            <p className="note">
              Real SKY130 BSIM across slow/typical/fast process × hot/cold × supply ±10%.
              A design that meets spec at nominal can still fail a corner — worst-case
              sign-off is what tape-out actually requires. (Use the CLI <code>alo.py pvt --full</code>
              for all 27 corners.)
            </p>
          </div>
        )}
      </section>
    </div>
  );
}
