import { useEffect, useState } from "react";
import { fetchBridge, fetchSkill } from "../api";
import { useT } from "../i18n";
import type { BridgeData, SkillData } from "../types";

export default function BridgeView() {
  const { t } = useT();
  const [data, setData] = useState<BridgeData | null>(null);
  const [skill, setSkill] = useState<SkillData | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetchBridge().then(setData).catch((e) => setErr(String(e)));
    fetchSkill().then(setSkill).catch(() => {});
  }, []);

  const downloadIl = () => {
    if (!skill) return;
    const blob = new Blob([skill.il], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${skill.cell}.il`;
    a.click();
  };

  if (err) return <div className="fatal">Error: {err}</div>;
  if (!data) return <div className="loading">Checking virtuoso_bridge…</div>;

  return (
    <div className="grid">
      <section className="panel" style={{ gridColumn: "1 / -1" }}>
        <div className="panel-title">
          {t("bridge.title")}
          <span className={data.allOk ? "badge ok" : "badge bad"}>
            {data.allOk ? "all checks pass" : "some failed"}
          </span>
        </div>
        {data.checks.map((c) => (
          <div key={c.name} style={{
            display: "flex", gap: 10, alignItems: "baseline", padding: "8px 0",
            borderBottom: "1px solid var(--border)",
          }}>
            <span style={{ color: c.ok ? "var(--ok)" : "var(--bad)", fontSize: 16 }}>{c.ok ? "✓" : "✗"}</span>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 14 }}>{c.name}</div>
              <code style={{ fontSize: 11, color: "var(--muted)", wordBreak: "break-all" }}>{c.sample}</code>
            </div>
          </div>
        ))}
        <p className="note">
          The TCP round-trip exercises the bridge's core mechanism (JSON request → STX/NAK framing)
          against a fake in-process daemon — the whole client/protocol/parser machinery works with
          no Virtuoso. Only a real <code>evalstring</code> in Virtuoso (and real Spectre numerics)
          still need the actual tool.
        </p>
      </section>

      <section className="panel" style={{ gridColumn: "1 / -1" }}>
        <div className="panel-title">
          {t("bridge.server")}
          <span className={data.preflight.ready ? "badge ok" : "badge bad"}>
            {data.preflight.ready ? "Spectre ready" : "not connected"}
          </span>
        </div>
        <div style={{ display: "flex", gap: 18, fontSize: 13, color: "var(--muted)" }}>
          <span>bridge .env: {data.preflight.bridge_env ? "✓" : "✗"}</span>
          <span>spectre: {data.preflight.spectre ? "✓" : "✗"}</span>
        </div>
        <ul className="drc-list" style={{ color: "var(--muted)", marginTop: 8 }}>
          {data.preflight.guidance.map((g, i) => <li key={i}>{g}</li>)}
        </ul>
      </section>

      {skill && (
        <section className="panel" style={{ gridColumn: "1 / -1" }}>
          <div className="panel-title">
            {t("skill.title")}
            <span>
              <button className="secondary" style={{ marginRight: 6 }}
                onClick={() => navigator.clipboard.writeText(skill.il)}>Copy</button>
              <button className="secondary" onClick={downloadIl}>Download .il</button>
            </span>
          </div>
          <p className="note" style={{ marginTop: 0 }}>
            {skill.cell} · {skill.shapeCount} shapes · {skill.commands.length} SKILL commands
            (via virtuoso_bridge layout.ops builders)
          </p>
          <pre style={{
            background: "#0d1117", border: "1px solid var(--border)", borderRadius: 8,
            padding: 12, maxHeight: 240, overflow: "auto", fontSize: 11, color: "#9cdcfe",
          }}>{skill.commands.slice(0, 14).join("\n")}{skill.commands.length > 14 ? `\n… (+${skill.commands.length - 14} more)` : ""}</pre>
          <p className="note">{skill.note}</p>
        </section>
      )}
    </div>
  );
}
