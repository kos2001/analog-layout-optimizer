import { useEffect, useRef, useState } from "react";
import { evalTcoil, fetchTcoil, geomTcoil } from "../api";
import type { TcoilCurve, TcoilData, TcoilGeom } from "../types";

function SpiralSVG({ geom }: { geom: TcoilGeom }) {
  const S = 280;
  const pad = 14;
  const ext = Math.max(geom.dOut, 1);
  const scale = (S - 2 * pad) / ext;
  const tx = (x: number) => S / 2 + x * scale;
  const ty = (y: number) => S / 2 + y * scale;
  const d = geom.path.map((p, i) => `${i ? "L" : "M"} ${tx(p[0]).toFixed(1)} ${ty(p[1]).toFixed(1)}`).join(" ");
  const start = geom.path[0], end = geom.path[geom.path.length - 1];
  return (
    <svg width={S} height={S} className="bode">
      <rect width={S} height={S} fill="#0d1117" />
      <path d={d} fill="none" stroke="#ce93d8" strokeWidth={Math.max(geom.width * scale, 2)}
        strokeLinejoin="round" strokeLinecap="round" opacity={0.9} />
      {/* terminals: A (start), B (end), center tap (mid) */}
      <circle cx={tx(start[0])} cy={ty(start[1])} r={5} fill="#42a5f5" />
      <circle cx={tx(end[0])} cy={ty(end[1])} r={5} fill="#3fb950" />
      <text x={tx(start[0]) + 6} y={ty(start[1]) - 6} className="axis">A</text>
      <text x={tx(end[0]) + 6} y={ty(end[1]) - 6} className="axis">B</text>
      <text x={6} y={S - 8} className="axis">{geom.dOut.toFixed(0)} µm</text>
    </svg>
  );
}

const G0 = { turns: 3, width: 3, spacing: 2, inner: 30, r_ohm: 300, cl_ff: 30, cb: 0.14 };

function CoilLayout() {
  const [g, setG] = useState(G0);
  const [res, setRes] = useState<TcoilGeom | null>(null);
  const deb = useRef<number | null>(null);
  useEffect(() => {
    if (deb.current) window.clearTimeout(deb.current);
    deb.current = window.setTimeout(() => { geomTcoil(g).then(setRes).catch(() => {}); }, 90);
  }, [g]);

  const sliders: [keyof typeof g, string, number, number, number][] = [
    ["turns", "turns n", 1, 8, 0.5],
    ["width", "trace width µm", 1, 8, 0.5],
    ["spacing", "spacing µm", 1, 8, 0.5],
    ["inner", "inner µm", 10, 80, 2],
    ["r_ohm", "node R Ω", 50, 600, 10],
    ["cl_ff", "node C_L fF", 10, 150, 5],
  ];
  return (
    <section className="panel" style={{ gridColumn: "1 / -1" }}>
      <div className="panel-title">
        Coil layout — geometry determines L, k, and the response
        {res && <span className={Math.abs(res.peakingDb) < 0.5 ? "badge ok" : "badge bad"}>
          {res.bwExtension.toFixed(2)}× BW</span>}
      </div>
      <div className="maze-wrap">
        {res ? <SpiralSVG geom={res} /> : <div className="loading">…</div>}
        <div className="maze-side">
          {res && (
            <table className="tcoil-table">
              <tbody>
                <tr><td>extracted L</td><td>{res.L_nH} nH</td></tr>
                <tr><td>coupling k</td><td>{res.k}</td></tr>
                <tr><td>outer size</td><td>{res.dOut} µm</td></tr>
                <tr><td>metal length</td><td>{res.wireUm} µm</td></tr>
                <tr><td>area</td><td>{res.areaUm2} µm²</td></tr>
                <tr><td>normalized L</td><td>{res.normL}</td></tr>
                <tr><td>BW extension</td><td>{res.bwExtension}× </td></tr>
                <tr><td>peaking</td><td>{res.peakingDb} dB</td></tr>
              </tbody>
            </table>
          )}
          <div className="sliders" style={{ marginTop: 10 }}>
            {sliders.map(([key, label, lo, hi, step]) => (
              <div className="slider-row" key={key}>
                <label><span className="slider-name">{label}</span>
                  <span className="slider-val">{g[key]}</span></label>
                <input type="range" min={lo} max={hi} step={step} value={g[key]}
                  onChange={(e) => setG({ ...g, [key]: Number(e.target.value) })} />
              </div>
            ))}
          </div>
        </div>
      </div>
      <p className="note">
        A symmetric square spiral (purple = metal, A/B = terminals). Inductance from
        the modified-Wheeler formula, coupling k from the winding — so the drawn coil
        sets the electrical (L, k). The response depends on the node it drives (R, C_L):
        the same coil is maximally-flat on a high-Z node but over-peaks on 50 Ω.
      </p>
    </section>
  );
}

const COLORS = {
  none: "#8b949e",
  shunt: "#ffa726",
  tcoil: "#42a5f5",
  custom: "#ec407a",
};

function Bode({
  freq,
  series,
}: {
  freq: number[];
  series: { name: string; color: string; magDb: number[] }[];
}) {
  const W = 640;
  const H = 320;
  const padL = 46;
  const padB = 30;
  const padT = 12;
  const padR = 12;
  const topDb = 4;
  const botDb = -18;

  const lx0 = Math.log10(freq[0]);
  const lx1 = Math.log10(freq[freq.length - 1]);
  const px = (f: number) =>
    padL + ((Math.log10(f) - lx0) / (lx1 - lx0)) * (W - padL - padR);
  const py = (db: number) =>
    padT + ((topDb - db) / (topDb - botDb)) * (H - padT - padB);

  const path = (mag: number[]) =>
    mag
      .map((d, i) => `${i === 0 ? "M" : "L"} ${px(freq[i]).toFixed(1)} ${py(d).toFixed(1)}`)
      .join(" ");

  const decades = [0.1, 1, 10];
  return (
    <svg width={W} height={H} className="bode">
      <rect x={0} y={0} width={W} height={H} fill="#0d1117" />
      {/* dB gridlines */}
      {[0, -3, -6, -12].map((db) => (
        <g key={db}>
          <line x1={padL} y1={py(db)} x2={W - padR} y2={py(db)}
            stroke={db === -3 ? "#6e40aa" : "#161b22"}
            strokeDasharray={db === -3 ? "4 3" : undefined} />
          <text x={6} y={py(db) + 4} className="axis">{db} dB</text>
        </g>
      ))}
      {decades.map((f) => (
        <g key={f}>
          <line x1={px(f)} y1={padT} x2={px(f)} y2={H - padB} stroke="#161b22" />
          <text x={px(f) - 6} y={H - 10} className="axis">{f}</text>
        </g>
      ))}
      <text x={W - padR} y={H - 10} textAnchor="end" className="axis">rad/s →</text>
      {series.map((s) => (
        <path key={s.name} d={path(s.magDb)} fill="none" stroke={s.color} strokeWidth={2} />
      ))}
    </svg>
  );
}

export default function TCoilView() {
  const [data, setData] = useState<TcoilData | null>(null);
  const [custom, setCustom] = useState<TcoilCurve | null>(null);
  const [LkCb, setLkCb] = useState({ L: 0.3, k: 0.6, Cb: 0.15 });
  const [error, setError] = useState<string | null>(null);
  const deb = useRef<number | null>(null);

  useEffect(() => {
    fetchTcoil().then(setData).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (deb.current) window.clearTimeout(deb.current);
    deb.current = window.setTimeout(() => {
      evalTcoil(LkCb.L, LkCb.k, LkCb.Cb).then(setCustom).catch(() => {});
    }, 80);
  }, [LkCb]);

  if (error) return <div className="fatal">Error: {error}</div>;
  if (!data) return <div className="loading">Loading T-coil…</div>;

  const series = [
    { name: "no coil (RC)", color: COLORS.none, magDb: data.curves.none.magDb },
    { name: "shunt peaking", color: COLORS.shunt, magDb: data.curves.shunt.magDb },
    { name: "T-coil (max-flat)", color: COLORS.tcoil, magDb: data.curves.tcoil.magDb },
  ];
  if (custom) series.push({ name: "custom", color: COLORS.custom, magDb: custom.magDb });

  const rows = [
    ["no coil (RC)", COLORS.none, data.curves.none],
    ["shunt peaking", COLORS.shunt, data.curves.shunt],
    ["T-coil (max-flat)", COLORS.tcoil, data.curves.tcoil],
  ] as const;

  return (
    <div className="grid">
      <section className="panel" style={{ gridColumn: "1 / -1" }}>
        <div className="panel-title">
          Bridged T-coil — bandwidth extension (magnitude response)
          <span className="badge ok">{data.curves.tcoil.bwExtension.toFixed(2)}× BW</span>
        </div>
        <div className="maze-wrap">
          <Bode freq={data.freq} series={series} />
          <div className="maze-side">
            <table className="tcoil-table">
              <thead>
                <tr><th></th><th>BW</th><th>peak</th></tr>
              </thead>
              <tbody>
                {rows.map(([name, color, c]) => (
                  <tr key={name}>
                    <td><i className="sw" style={{ background: color, borderColor: color }} /> {name}</td>
                    <td>{c.bwExtension.toFixed(2)}×</td>
                    <td>{c.peakingDb.toFixed(2)} dB</td>
                  </tr>
                ))}
                {custom && (
                  <tr>
                    <td><i className="sw" style={{ background: COLORS.custom, borderColor: COLORS.custom }} /> custom</td>
                    <td>{custom.bwExtension.toFixed(2)}×</td>
                    <td>{custom.peakingDb.toFixed(2)} dB</td>
                  </tr>
                )}
              </tbody>
            </table>

            <div className="sliders" style={{ marginTop: 12 }}>
              {(["L", "k", "Cb"] as const).map((key) => {
                const max = key === "k" ? 0.95 : key === "L" ? 2 : 1.5;
                return (
                  <div className="slider-row" key={key}>
                    <label>
                      <span className="slider-name">custom {key}</span>
                      <span className="slider-val">{LkCb[key].toFixed(3)}</span>
                    </label>
                    <input type="range" min={0} max={max} step={0.005}
                      value={LkCb[key]}
                      onChange={(e) => setLkCb({ ...LkCb, [key]: Number(e.target.value) })} />
                  </div>
                );
              })}
            </div>
            <p className="note">
              Closed-form Z(s)=V_T/I_in (derived analytically). The bare RC load
              sets the reference; shunt peaking reaches ~1.8×, the max-flat
              bridged T-coil ~3× (textbook). Drag L/k/Cb to see the custom curve;
              push peaking up and bandwidth grows but the response rings.
            </p>
          </div>
        </div>
      </section>
      <CoilLayout />
    </div>
  );
}
