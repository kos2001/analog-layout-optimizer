import { useEffect, useState } from "react";
import { fetchFlow } from "../api";
import { useT } from "../i18n";
import type { FlowData } from "../types";
import { fetchGds } from "../api";
import RouteGrid, { netColorFactory } from "./RouteGrid";

function SignoffPanel({ data }: { data: FlowData }) {
  const { t } = useT();
  const so = data.signoff;
  const pass = so.verdict === "PASS";
  return (
    <div style={{
      border: `1px solid ${pass ? "var(--ok)" : "var(--bad)"}`, borderRadius: 8,
      padding: "10px 14px", margin: "6px 0 12px", background: "#0d1117",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <strong style={{ fontSize: 13 }}>{t("flow.signoff")}</strong>
        <span className={pass ? "badge ok" : "badge bad"} style={{ fontSize: 13 }}>
          {pass ? `✓ ${t("flow.signoff.pass")}` : `✗ ${t("flow.signoff.fail")}`}
        </span>
        {so.drcWarnings > 0 && (
          <span style={{ fontSize: 12, color: "var(--muted)" }}>{so.drcWarnings} {t("flow.warnings")}</span>
        )}
      </div>
      <div style={{ display: "flex", gap: 18, flexWrap: "wrap", marginTop: 8 }}>
        {so.checks.map((c) => (
          <div key={c.name} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ color: c.status === "pass" ? "var(--ok)" : "var(--bad)", fontWeight: 700 }}>
              {c.status === "pass" ? "✓" : "✗"}
            </span>
            <span style={{ fontSize: 12 }}><b>{c.name}</b> <span style={{ color: "var(--muted)" }}>— {c.detail}</span></span>
          </div>
        ))}
      </div>
    </div>
  );
}

function PostLayoutPanel({ data }: { data: FlowData }) {
  const { t } = useT();
  const pl = data.postlayout;
  const row = (label: string, pre: number, post: number, unit: string, lowerWorse = true) => {
    const degraded = lowerWorse ? post < pre - 0.05 : post > pre + 0.05;
    return (
      <tr>
        <td>{label}</td>
        <td>{pre}{unit}</td>
        <td style={{ color: degraded ? "var(--bad)" : "var(--ok)" }}>{post}{unit}</td>
      </tr>
    );
  };
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "10px 14px", margin: "0 0 12px", background: "#0d1117" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <strong style={{ fontSize: 13 }}>{t("flow.post.title")}</strong>
        <span className={pl.stable ? "badge ok" : "badge bad"} style={{ fontSize: 12 }}>
          {pl.stable ? t("flow.post.stable") : t("flow.post.unstable")}
        </span>
        <span style={{ fontSize: 12, color: pl.deltaPM < -10 ? "var(--bad)" : "var(--muted)" }}>
          ΔPM {pl.deltaPM}°
        </span>
      </div>
      <div style={{ display: "flex", gap: 24, flexWrap: "wrap", marginTop: 8 }}>
        <table className="tcoil-table" style={{ fontSize: 12, maxWidth: 320 }}>
          <thead><tr><th></th><th>{t("flow.post.schem")}</th><th>{t("flow.post.post")}</th></tr></thead>
          <tbody>
            {row("gain", pl.pre.gain_db, pl.post.gain_db, " dB", false)}
            {row("GBW", pl.pre.gbw_mhz, pl.post.gbw_mhz, " MHz")}
            {row("PM", pl.pre.pm_deg, pl.post.pm_deg, "°")}
          </tbody>
        </table>
        <div className="metrics" style={{ flexDirection: "column", gap: 6, fontSize: 12 }}>
          <strong style={{ fontSize: 12, color: "var(--muted)" }}>{t("flow.post.critical")}</strong>
          {Object.entries(pl.critical).map(([net, p]) => (
            <span key={net} style={{ color: "var(--muted)" }}>
              <b style={{ color: "var(--text)" }}>{net}</b>: wl {p.wirelength}, {p.C_fF} fF, {p.R_ohm} Ω
            </span>
          ))}
          {pl.post.p_n2_mhz != null && (
            <span style={{ color: "var(--muted)" }}>n2 parasitic pole ≈ {pl.post.p_n2_mhz} MHz</span>
          )}
        </div>
      </div>
      <p className="note" style={{ marginTop: 8 }}>{t("flow.post.note")}</p>
    </div>
  );
}

export default function FlowView() {
  const { t } = useT();
  const [place, setPlace] = useState<"sa" | "random">("sa");
  const [seed, setSeed] = useState(1);
  const [data, setData] = useState<FlowData | null>(null);
  const [busy, setBusy] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [showDrc, setShowDrc] = useState(true);
  const [gdsNote, setGdsNote] = useState<string | null>(null);

  useEffect(() => {
    setBusy(true); setErr(null);
    fetchFlow(place, seed).then(setData).catch((e) => setErr(String(e))).finally(() => setBusy(false));
  }, [place, seed]);

  const exportGds = async () => {
    setGdsNote("exporting…");
    try {
      const g = await fetchGds(place, seed);
      const bytes = Uint8Array.from(atob(g.gdsBase64), (c) => c.charCodeAt(0));
      const url = URL.createObjectURL(new Blob([bytes], { type: "application/octet-stream" }));
      const a = document.createElement("a");
      a.href = url; a.download = g.filename; a.click();
      URL.revokeObjectURL(url);
      const s = g.stats;
      setGdsNote(`${g.filename}: ${s.polygons} polygons · ${s.counts.metal} metal / ${s.counts.via} vias / ${s.counts.device} devices · ${s.area_um2} µm² · ${(g.bytes / 1024).toFixed(1)} KB · layers ${s.layers.map((l) => `${l.layer}/${l.datatype}`).join(", ")}`);
    } catch (e) { setGdsNote(String(e)); }
  };

  if (err) return <div className="fatal">Error: {err}</div>;

  const names = data ? Object.keys(data.netlist) : [];
  const netColor = netColorFactory(names);
  const r = data?.routing;

  return (
    <div className="grid">
      <section className="panel" style={{ gridColumn: "1 / -1" }}>
        <div className="panel-title">
          {t("flow.title")}
          {r && <span className={r.failed.length ? "badge bad" : "badge ok"}>
            {r.failed.length ? `${r.failed.length} unrouted` : t("all.routed")}</span>}
        </div>
        <div className="seg" style={{ marginBottom: 6 }}>
          <button className={place === "sa" ? "" : "secondary"} onClick={() => setPlace("sa")}>{t("flow.sa")}</button>
          <button className={place === "random" ? "" : "secondary"} onClick={() => setPlace("random")}>{t("flow.random")}</button>
          <button className="secondary" onClick={() => setSeed(Math.floor(Math.random() * 1e6))}>{t("flow.rerun")}</button>
          <button className={showDrc ? "" : "secondary"} onClick={() => setShowDrc((s) => !s)}>{t("flow.drc.toggle")}</button>
          <button className="secondary" onClick={exportGds} disabled={busy}>{t("flow.gds")}</button>
        </div>
        {gdsNote && <p className="note" style={{ marginTop: 0 }}>{gdsNote}</p>}

        {data && <SignoffPanel data={data} />}
        {data && <PostLayoutPanel data={data} />}

        {busy || !data || !r ? <div className="loading">{t("flow.running")}</div> : (
          <div className="maze-wrap">
            <RouteGrid data={data} netColor={netColor} hover={hover} setHover={setHover} showDrc={showDrc} />
            <div className="maze-side" style={{ minWidth: 280 }}>
              <div className="metrics" style={{ flexDirection: "column", gap: 8 }}>
                <div><span className="metric-label">{t("flow.hpwl")}</span><span className="metric-value">{data.hpwl}</span></div>
                <div><span className="metric-label">{t("maze.total.wl")}</span><span className="metric-value">{r.totalWirelength}</span></div>
                <div><span className="metric-label">vias</span><span className="metric-value">{r.totalVias}</span></div>
              </div>
              <div className="panel-title" style={{ fontSize: 13, marginTop: 6 }}>{t("flow.netlist")}</div>
              <div style={{ maxHeight: 320, overflowY: "auto" }}>
                <table className="tcoil-table" style={{ fontSize: 12 }}>
                  <tbody>
                    {names.map((n) => (
                      <tr key={n} onMouseEnter={() => setHover(n)} onMouseLeave={() => setHover(null)}
                        style={{ background: hover === n ? "#1c2128" : "transparent", cursor: "default" }}>
                        <td style={{ whiteSpace: "nowrap" }}>
                          <i className="sw" style={{ background: netColor(n), borderColor: netColor(n) }} />{n}
                        </td>
                        <td style={{ color: "var(--muted)" }}>{data.netlist[n].join(", ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
        <p className="note" style={{ marginTop: 12 }}>{t("flow.note")}</p>
      </section>
    </div>
  );
}
