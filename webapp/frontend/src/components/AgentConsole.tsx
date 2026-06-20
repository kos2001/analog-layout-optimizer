import { useState } from "react";
import { askAgent } from "../api";
import { useT } from "../i18n";

interface Turn { role: "user" | "agent" | "error"; text: string; }

const SUGGESTIONS = [
  "analog-layout-optimizer로 OTA를 최소전력 사이징하고 gain/GBW/PM/power 보고해줘",
  "comparator를 maze 라우팅하고 총 wirelength를 알려줘",
  "공정이 바뀌어 min poly pitch 0.3, metal spacing 0.12로 P&R 재조정해줘",
];

export default function AgentConsole() {
  const { t } = useT();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState(SUGGESTIONS[0]);
  const [busy, setBusy] = useState(false);

  const send = async () => {
    const prompt = input.trim();
    if (!prompt || busy) return;
    setTurns((t) => [...t, { role: "user", text: prompt }]);
    setBusy(true);
    try {
      const r = await askAgent(prompt);
      setTurns((t) => [...t, r.ok
        ? { role: "agent", text: r.reply || "(empty)" }
        : { role: "error", text: r.error || "agent error" }]);
    } catch (e) {
      setTurns((t) => [...t, { role: "error", text: String(e) }]);
    } finally { setBusy(false); }
  };

  return (
    <div className="grid">
      <section className="panel" style={{ gridColumn: "1 / -1" }}>
        <div className="panel-title">
          {t("agent.title")}
        </div>
        <div style={{
          minHeight: 200, maxHeight: 360, overflowY: "auto", background: "#0d1117",
          border: "1px solid var(--border)", borderRadius: 8, padding: 12, marginBottom: 10,
        }}>
          {turns.length === 0 && (
            <p className="note">
              Type a request; the Hermes agent (analog_opt persona) calls our alo.py tools and
              reports. Requires the virtuoso-bridge gateway running with a valid token. Examples ↓
            </p>
          )}
          {turns.map((t, i) => (
            <div key={i} style={{ marginBottom: 10 }}>
              <span style={{
                fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em",
                color: t.role === "user" ? "var(--accent)" : t.role === "error" ? "var(--bad)" : "var(--ok)",
              }}>{t.role}</span>
              <div style={{ whiteSpace: "pre-wrap", fontSize: 13, marginTop: 2 }}>{t.text}</div>
            </div>
          ))}
          {busy && <p className="note">agent thinking… (gpt-5.5 + tool execution)</p>}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <input value={input} onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            placeholder={t("agent.placeholder")} style={{
              flex: 1, background: "#0d1117", color: "var(--text)",
              border: "1px solid var(--border)", borderRadius: 8, padding: 10, fontSize: 14,
            }} />
          <button onClick={send} disabled={busy}>{busy ? "…" : "Send"}</button>
        </div>
        <div className="actions" style={{ flexWrap: "wrap", marginTop: 8 }}>
          {SUGGESTIONS.map((s, i) => (
            <button key={i} className="secondary" onClick={() => setInput(s)} disabled={busy}
              style={{ fontSize: 11 }}>예시 {i + 1}</button>
          ))}
        </div>
        <p className="note">
          Routes to the Hermes <code>virtuoso-bridge</code> profile's OpenAI-compatible endpoint.
          If it says unreachable, start the gateway / refresh the codex token.
        </p>
      </section>
    </div>
  );
}
