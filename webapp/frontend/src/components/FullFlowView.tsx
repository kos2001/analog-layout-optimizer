import { useState } from "react";
import { fetchFullFlow } from "../api";
import { useT } from "../i18n";
import type { FullFlowData } from "../types";
import RouteGrid, { netColorFactory } from "./RouteGrid";

const STATUS_COLOR: Record<string, string> = {
  pass: "var(--ok)", fail: "var(--bad)", warn: "#ffb300", info: "var(--muted)",
};
const STATUS_ICON: Record<string, string> = { pass: "✓", fail: "✗", warn: "!", info: "•" };

function StageCard({ name, status, detail, last }: {
  name: string; status: string; detail: string; last: boolean;
}) {
  const col = STATUS_COLOR[status] ?? "var(--muted)";
  return (
    <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
        <div style={{
          width: 26, height: 26, borderRadius: "50%", border: `2px solid ${col}`,
          color: col, display: "flex", alignItems: "center", justifyContent: "center",
          fontWeight: 700, fontSize: 14, flexShrink: 0,
        }}>{STATUS_ICON[status] ?? "•"}</div>
        {!last && <div style={{ width: 2, flex: 1, minHeight: 18, background: "#30363d" }} />}
      </div>
      <div style={{ paddingBottom: 14 }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>{name}</div>
        <div style={{ fontSize: 12, color: "var(--muted)" }}>{detail}</div>
      </div>
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

  const run = async () => {
    setBusy(true); setErr(null);
    try {
      const seed = Math.floor(Math.random() * 1e6);
      setData(await fetchFullFlow("sa", seed, sky130));
    } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };

  const pass = data?.verdict === "PASS";
  const names = data ? Object.keys(data.netlist) : [];

  return (
    <div className="grid">
      <section className="panel" style={{ gridColumn: "1 / -1" }}>
        <div className="panel-title">{t("ff.title")}</div>
        <p className="note" style={{ marginTop: 0 }}>{t("ff.note")}</p>
        <div className="actions" style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <button onClick={run} disabled={busy}>{busy ? t("ff.running") : `▶ ${t("ff.run")}`}</button>
          <label style={{ fontSize: 13, color: "var(--muted)", display: "flex", gap: 6, alignItems: "center" }}>
            <input type="checkbox" checked={sky130} onChange={(e) => setSky130(e.target.checked)} />
            {t("ff.sky130")}
          </label>
          {sky130 && <span className="note" style={{ margin: 0 }}>{t("ff.sky130.slow")}</span>}
        </div>
        {err && <p className="note" style={{ color: "var(--bad)" }}>{err}</p>}

        {data && (
          <>
            <div style={{
              border: `1px solid ${pass ? "var(--ok)" : "var(--bad)"}`, borderRadius: 8,
              padding: "8px 14px", margin: "12px 0", display: "flex", gap: 12, alignItems: "center",
            }}>
              <span className={pass ? "badge ok" : "badge bad"} style={{ fontSize: 14 }}>
                {pass ? `✓ ${t("ff.verdict.pass")}` : `✗ ${data.verdict}`}
              </span>
              <span style={{ fontSize: 13, color: "var(--muted)" }}>
                {data.sizing.power_mw} mW · GBW {data.sizing.gbw_mhz} MHz · gain {data.sizing.gain_db} dB ·
                HPWL {data.hpwl} · WL {data.routing.totalWirelength}
              </span>
            </div>

            <div style={{ display: "flex", gap: 28, flexWrap: "wrap" }}>
              <div style={{ minWidth: 320 }}>
                {data.stages.map((s, i) => (
                  <StageCard key={s.name} {...s} last={i === data.stages.length - 1} />
                ))}
              </div>
              <div style={{ flex: 1, minWidth: 360 }}>
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
