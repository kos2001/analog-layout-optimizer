import { useState } from "react";
import { adaptProcess, processEffects } from "../api";
import { useT } from "../i18n";
import type { AdaptResponse, AdaptSide, ProcessEffects } from "../types";
import LayoutCanvas from "./LayoutCanvas";

// "Shrink to a finer node" preset: higher µCox, shorter-channel (higher λ),
// lower supply — the device-model side of a process change.
const SHRINK_TECH = { kp_n_mult: 1.5, kp_p_mult: 1.5, lambda_mult: 1.4, vdd: 0.9 };

function EffectsPanel({ nl }: { nl: string }) {
  const [r, setR] = useState<ProcessEffects | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try { setR(await processEffects(nl, SHRINK_TECH)); } finally { setBusy(false); }
  };
  return (
    <section className="panel" style={{ gridColumn: "1 / -1" }}>
      <div className="panel-title">
        What a foundry process change actually affects
        <button onClick={run} disabled={busy}>
          {busy ? "Computing…" : "Show full effects (shrink node)"}
        </button>
      </div>
      {!r ? (
        <p className="note">
          A node change is more than DRC: it also changes the device model, supply,
          metal stack, and reliability rules. Click to quantify the modeled ones and
          list the rest.
        </p>
      ) : (
        <>
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap", marginBottom: 10 }}>
            <div className="metrics" style={{ flexDirection: "column", gap: 6 }}>
              <strong style={{ fontSize: 12, color: "var(--muted)" }}>DRC geometry (placement+routing)</strong>
              <span className="note">area {r.geometry.before_area} → {r.geometry.after_area} µm²
                ({r.geometry.area_delta_pct >= 0 ? "+" : ""}{r.geometry.area_delta_pct}%), DRC {r.geometry.drc_clean ? "clean ✓" : "✗"}</span>
            </div>
            {r.device && (
              <div className="metrics" style={{ flexDirection: "column", gap: 6 }}>
                <strong style={{ fontSize: 12, color: "var(--muted)" }}>
                  Device model + supply (VDD {r.device.vdd_before}→{r.device.vdd_after} V): OTA re-size
                </strong>
                <span className="note">
                  power {r.device.before.power_mw}→{r.device.after.power_mw} mW ·
                  gain {r.device.before.gain_db}→{r.device.after.gain_db} dB ·
                  GBW {r.device.before.gbw_mhz}→{r.device.after.gbw_mhz} MHz ·
                  <span style={{ color: r.device.after.feasible ? "var(--ok)" : "var(--bad)" }}>
                    {" "}{r.device.after.feasible ? "still meets specs ✓" : "no longer meets specs ✗ (re-design)"}</span>
                </span>
              </div>
            )}
          </div>
          <table className="tcoil-table">
            <thead><tr><th>category</th><th>handled</th><th>what changes</th></tr></thead>
            <tbody>
              {r.taxonomy.map((e) => (
                <tr key={e.category}>
                  <td>{e.category}</td>
                  <td style={{ color: e.modeled ? "var(--ok)" : "var(--muted)" }}>
                    {e.modeled ? "✓ modeled" : "noted"}</td>
                  <td style={{ color: "var(--muted)" }}>{e.what}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="note">
            Schematic/topology stays fixed for the geometry adapt; but the device-model
            change can break performance (gain/GBW), so the sizing — and sometimes the
            schematic — must be revisited. EM / density / antenna / matching are listed
            as the next constraints to add.
          </p>
        </>
      )}
    </section>
  );
}

const EXAMPLES = [
  "Migrate to a coarser node: min poly pitch 0.30 um, metal spacing 0.12 um, gate length 0.06, drive total W/L 3.0",
  "Tighten the metal: min metal spacing 0.05 um, via size 0.03 um",
  "공정이 바뀌어 min poly pitch 0.25 um, guard ring gap 0.30 um로 맞춰줘",
];

function Side({ title, side }: { title: string; side: AdaptSide }) {
  return (
    <div style={{ flex: 1, minWidth: 300 }}>
      <div className="panel-title" style={{ marginBottom: 6 }}>
        {title}
        <span className={side.drcClean ? "badge ok" : "badge bad"}>
          {side.drcClean ? "DRC clean" : "violations"}
        </span>
      </div>
      <LayoutCanvas layout={side.layout} width={420} height={300} />
      <div className="metrics" style={{ marginTop: 10 }}>
        <div>
          <span className="metric-label">total area</span>
          <span className="metric-value">{side.totalArea.toFixed(3)} µm²</span>
        </div>
        <div>
          <span className="metric-label">wirelength</span>
          <span className="metric-value">{side.wirelength.toFixed(2)} µm</span>
        </div>
      </div>
      <p className="note">
        pitch {side.device.finger_pitch} · w_finger {side.device.w_finger} · L {side.device.l} ·
        rail_pitch {side.routing.rail_pitch} · via {side.routing.via_size}
      </p>
    </div>
  );
}

export default function ProcessView() {
  const { t } = useT();
  const [text, setText] = useState(EXAMPLES[0]);
  const [res, setRes] = useState<AdaptResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true); setErr(null);
    try { setRes(await adaptProcess(text)); }
    catch (e) { setErr(String(e)); }
    finally { setBusy(false); }
  };

  return (
    <div className="grid">
      <section className="panel" style={{ gridColumn: "1 / -1" }}>
        <div className="panel-title">
          {t("process.title")}
        </div>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={3}
          style={{
            width: "100%", background: "#0d1117", color: "var(--text)",
            border: "1px solid var(--border)", borderRadius: 8, padding: 10,
            fontFamily: "inherit", fontSize: 14, resize: "vertical",
          }}
        />
        <div className="actions" style={{ marginTop: 10, flexWrap: "wrap" }}>
          <button onClick={submit} disabled={busy}>
            {busy ? "Re-optimizing…" : "▶ Adapt placement + routing"}
          </button>
          {EXAMPLES.map((ex, i) => (
            <button key={i} className="secondary" onClick={() => setText(ex)} disabled={busy}>
              example {i + 1}
            </button>
          ))}
        </div>
        {err && <p className="note" style={{ color: "var(--bad)" }}>{err}</p>}

        {res && (
          <>
            <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 8 }}>
              <span className="note">
                parsed: {Object.entries(res.overrides).map(([k, v]) => `${k}=${v}`).join(", ") || "(none)"}
              </span>
            </div>
            <div style={{ display: "flex", gap: 24, marginTop: 12, flexWrap: "wrap" }}>
              <Side title="Before (current process)" side={res.before} />
              <Side title="After (new process)" side={res.after} />
            </div>
            <p className="note" style={{ marginTop: 12 }}>
              total area {res.before.totalArea.toFixed(3)} → {res.after.totalArea.toFixed(3)} µm²
              {" "}(<strong>{res.areaDeltaPct >= 0 ? "+" : ""}{res.areaDeltaPct}%</strong>).
              Schematic fixed: {res.topology.fingers} fingers, {res.topology.nets.length} nets —
              only placement (device geometry) and routing were re-optimized to the new DRC/spec.
            </p>
          </>
        )}
      </section>
      <EffectsPanel nl={text} />
    </div>
  );
}
