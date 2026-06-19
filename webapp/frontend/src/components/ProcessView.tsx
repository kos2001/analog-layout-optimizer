import { useState } from "react";
import { adaptProcess } from "../api";
import type { AdaptResponse, AdaptSide } from "../types";
import LayoutCanvas from "./LayoutCanvas";

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
          Process change — describe it in natural language
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
    </div>
  );
}
