import { createContext, useContext, useState, type ReactNode } from "react";

export type Lang = "en" | "ko";

// key -> { en, ko }. t(key) returns current lang, falling back to en, then key.
const S: Record<string, { en: string; ko: string }> = {
  // shell
  "app.title": { en: "Analog Layout Optimizer", ko: "아날로그 레이아웃 옵티마이저" },
  "app.subtitle": { en: "Agentic analog layout experiments — no Virtuoso in the loop",
                    ko: "에이전트형 아날로그 레이아웃 실험 — 루프에 Virtuoso 없음" },
  "tab.layout": { en: "Layout / Joint", ko: "레이아웃 / Joint" },
  "tab.comparator": { en: "Comparator (maze)", ko: "Comparator (maze)" },
  "tab.tcoil": { en: "T-coil", ko: "T-coil" },
  "tab.opamp": { en: "Op-amp (OTA)", ko: "Op-amp (OTA)" },
  "tab.process": { en: "Process change", ko: "공정 변경" },
  "tab.surrogate": { en: "Surrogate", ko: "Surrogate" },
  "tab.bridge": { en: "Bridge / SKILL", ko: "Bridge / SKILL" },
  "tab.agent": { en: "Agent", ko: "Agent" },
  "tab.complex": { en: "Complex cases", ko: "복잡 사례" },
  "tab.ppa": { en: "PPA", ko: "PPA" },
  "tab.flow": { en: "Schematic → P&R", ko: "Schematic → P&R" },
  "loading": { en: "Loading…", ko: "불러오는 중…" },

  // schematic -> placement -> routing flow
  "flow.title": { en: "Schematic → placement → routing (one netlist)", ko: "Schematic → 배치 → 배선 (하나의 netlist)" },
  "flow.sa": { en: "SA placement", ko: "SA 배치" },
  "flow.random": { en: "Random placement", ko: "랜덤 배치" },
  "flow.rerun": { en: "Re-place (new seed)", ko: "재배치 (새 seed)" },
  "flow.running": { en: "Placing + routing…", ko: "배치+배선 중…" },
  "flow.hpwl": { en: "HPWL (placement cost)", ko: "HPWL (배치 비용)" },
  "flow.netlist": { en: "Netlist (net → terminals) — hover to highlight", ko: "Netlist (넷 → 단자) — 마우스 올리면 강조" },
  "flow.note": {
    en: "The OTA netlist is the single source of truth: each terminal becomes a pin on its net, and same-net pins become one router net — placement pins and routing nets can't drift apart. SA placement minimizes HPWL, and a tighter HPWL yields a shorter route (compare SA vs random). Hover a net to see it across the netlist, the device pins, and the wires.",
    ko: "OTA netlist이 단일 진실원천입니다: 각 단자가 그 넷의 핀이 되고, 같은 넷 핀들이 하나의 라우터 넷이 됩니다 — 배치 핀과 배선 넷이 어긋날 수 없습니다. SA 배치는 HPWL을 최소화하고, HPWL이 작을수록 배선이 짧아집니다(SA vs 랜덤 비교). 넷에 마우스를 올리면 netlist·소자 핀·배선에서 동시에 강조됩니다." },

  // PPA
  "ppa.title": { en: "PPA optimization — power / performance / area Pareto front", ko: "PPA 최적화 — 전력/성능/면적 Pareto front" },
  "ppa.front": { en: "Pareto designs", ko: "Pareto 설계" },
  "ppa.running": { en: "Running NSGA-II…", ko: "NSGA-II 실행 중…" },
  "ppa.scatter.note": {
    en: "Each dot is a design: x=power, y=GBW (performance), color=area (green small → red large). The colored front is Pareto-optimal; gray dots are dominated. No single best — only trade-offs.",
    ko: "점 하나가 설계: x=전력, y=GBW(성능), 색=면적(초록 작음→빨강 큼). 색칠된 front가 Pareto 최적, 회색은 지배됨. 단일 최적은 없고 trade-off만 존재." },
  "ppa.pref": { en: "Preference weights (pick a point on the front)", ko: "선호 가중치 (front에서 한 점 선택)" },
  "ppa.w.power": { en: "minimize power", ko: "전력 최소화" },
  "ppa.w.area": { en: "minimize area", ko: "면적 최소화" },
  "ppa.w.perf": { en: "maximize GBW", ko: "GBW 최대화" },
  "ppa.chosen": { en: "Chosen design (white ring)", ko: "선택된 설계 (흰 원)" },
  "ppa.rerun": { en: "Re-run NSGA-II", ko: "NSGA-II 재실행" },
  "ppa.ranges": { en: "Front spans", ko: "Front 범위" },
  "ppa.constraint.note": { en: "All feasible", ko: "전부 제약 충족" },

  // complex cases — routing scenarios + common-centroid
  "cx.routing.title": { en: "Real-work routing cases — algorithm comparison", ko: "실무 라우팅 사례 — 알고리즘 비교" },
  "cx.diffpair": { en: "diff pair", ko: "차동쌍" },
  "cx.case.bus_channel": { en: "Bus / channel", ko: "버스/채널" },
  "cx.case.macro_power_grid": { en: "Macros + power grid", ko: "매크로+전원그리드" },
  "cx.case.diff_pair": { en: "Differential pair", ko: "차동쌍" },
  "cx.algo.fixed": { en: "Fixed-order A*", ko: "고정순서 A*" },
  "cx.algo.best": { en: "Best-order A*", ko: "최적순서 A*" },
  "cx.algo.negotiated": { en: "Negotiated (PathFinder)", ko: "협상(PathFinder)" },
  "cx.failed": { en: "unrouted nets", ko: "미배선 넷" },
  "cx.time": { en: "solve time", ko: "풀이 시간" },
  "cx.matched": { en: "Matched (bundle)", ko: "매칭(번들)" },
  "cx.independent": { en: "Independent", ko: "독립 라우팅" },
  "cx.coupled": { en: "coupling (adjacent)", ko: "커플링(인접)" },
  "cx.mismatch": { en: "length mismatch", ko: "길이 불일치" },
  "cx.legend.layer": { en: "bright=M-even (H), dim=M-odd (V)", ko: "밝은=짝수층(H), 흐린=홀수층(V)" },
  "cx.legend.via": { en: "white dot = via", ko: "흰 점 = via" },
  "cx.algo.note": {
    en: "A* is optimal per single net, but routing nets sequentially makes the result depend on net order (NP-hard). Fixed/best-order A* can strand nets or burn vias; PathFinder negotiated congestion shares tracks and reroutes all — order-independent.",
    ko: "A*는 단일 넷 최단경로엔 최적이지만, 넷을 순차 라우팅하면 결과가 넷 순서에 의존(NP-hard)합니다. 고정/최적순서 A*는 넷을 못 깔거나 via를 낭비할 수 있고, PathFinder 협상 라우팅은 트랙을 공유하며 전부 다시 깝니다 — 순서 무관." },
  "cx.cc.title": { en: "Common-centroid matched array (layout)", ko: "공통중심 매칭 배열 (레이아웃)" },
  "cx.cc.simple": { en: "Simple (segregated)", ko: "단순(분리)" },
  "cx.cc.interdigitated": { en: "Interdigitated", ko: "인터디지테이션" },
  "cx.cc.common_centroid": { en: "Common-centroid", ko: "공통중심" },
  "cx.cc.offset": { en: "centroid offset", ko: "중심 거리" },
  "cx.cc.gradmm": { en: "gradient mismatch", ko: "그래디언트 불일치" },
  "cx.cc.note": {
    en: "A/B unit cells of a matched pair. A linear process gradient (oxide, implant, stress) adds equally to A and B only when their centroids coincide — common-centroid drives both centroid offset and gradient mismatch to zero; the dashed yellow ring (B centroid) sits on the white ring (A centroid).",
    ko: "매칭쌍의 A/B 단위셀. 선형 공정 그래디언트(산화막·임플란트·스트레스)는 두 소자의 중심이 일치할 때만 A·B에 동일하게 더해집니다 — 공통중심은 중심거리와 그래디언트 불일치를 0으로 만듭니다(노란 점선=B중심이 흰 원=A중심에 겹침)." },

  // common
  "drc.clean": { en: "DRC clean", ko: "DRC 정상" },
  "all.routed": { en: "all routed", ko: "전부 라우팅됨" },
  "specs.met": { en: "specs met", ko: "스펙 충족" },
  "total.area": { en: "total cell area", ko: "전체 셀 면적" },
  "bbox.area": { en: "bbox area", ko: "바운딩박스 면적" },
  "device.area": { en: "device area", ko: "소자 면적" },
  "wirelength": { en: "wirelength", ko: "배선 길이" },

  // layout tab
  "layout.title": { en: "Layout", ko: "레이아웃" },
  "params.title": { en: "Parameters", ko: "파라미터" },
  "btn.optimize.device": { en: "▶ Optimize device", ko: "▶ 소자 최적화" },
  "btn.optimizing": { en: "Optimizing…", ko: "최적화 중…" },
  "btn.joint": { en: "▶ Joint (device+routing)", ko: "▶ Joint (소자+배선)" },
  "btn.reset": { en: "Reset", ko: "초기화" },
  "btn.play": { en: "▶ Play", ko: "▶ 재생" },
  "btn.pause": { en: "⏸ Pause", ko: "⏸ 일시정지" },
  "conv.title": { en: "Convergence — area vs. iteration", ko: "수렴 — 면적 vs 반복" },
  "conv.empty": { en: "Run optimization to see convergence.", ko: "최적화를 실행하면 수렴 곡선이 보입니다." },
  "drc.status": { en: "DRC / spec status", ko: "DRC / 스펙 상태" },

  // comparator
  "maze.title": { en: "StrongARM comparator — maze routing", ko: "StrongARM comparator — maze 라우팅" },
  "maze.optimized": { en: "Optimized order", ko: "최적화 순서" },
  "maze.naive": { en: "Naive order", ko: "나이브 순서" },
  "maze.total.wl": { en: "total wirelength", ko: "총 배선 길이" },
  "maze.total.bends": { en: "total bends", ko: "총 꺾임" },
  "maze.worst": { en: "worst order (for contrast)", ko: "최악 순서 (대조용)" },
  "maze.mode.demo": { en: "Order demo", ko: "순서 데모" },
  "maze.mode.drag": { en: "Drag-place (live)", ko: "드래그 배치 (실시간)" },

  // interactive floorplan
  "fp.title": { en: "Drag-place floorplan — live re-routing", ko: "드래그 배치 플로어플랜 — 실시간 재배선" },
  "fp.help": { en: "Drag any device or pad. The maze router re-solves on every move.", ko: "소자/패드를 드래그하세요. 움직일 때마다 maze 라우터가 다시 풉니다." },
  "fp.unrouted": { en: "unrouted", ko: "미배선" },
  "fp.optimize": { en: "Optimize net order", ko: "넷 순서 최적화" },
  "fp.fixed": { en: "Fixed order", ko: "고정 순서" },
  "fp.order": { en: "net order used", ko: "사용된 넷 순서" },
  "fp.reset": { en: "Reset placement", ko: "배치 초기화" },

  // tcoil
  "tcoil.title": { en: "Bridged T-coil — bandwidth extension (magnitude response)",
                   ko: "Bridged T-coil — 대역폭 확장 (크기 응답)" },
  "coil.title": { en: "Coil layout — geometry determines L, k, and the response",
                  ko: "코일 레이아웃 — 기하가 L, k, 응답을 결정" },
  "coil.extractedL": { en: "extracted L", ko: "추출 L" },
  "coil.k": { en: "coupling k", ko: "결합계수 k" },
  "coil.outer": { en: "outer size", ko: "외곽 크기" },
  "coil.metal": { en: "metal length", ko: "금속 길이" },
  "coil.area": { en: "area", ko: "면적" },
  "coil.normL": { en: "normalized L", ko: "정규화 L" },
  "coil.bw": { en: "BW extension", ko: "대역폭 확장" },
  "coil.peaking": { en: "peaking", ko: "피킹" },

  // opamp
  "opamp.title": { en: "Two-stage Miller OTA — min-power sizing", ko: "2단 Miller OTA — 최소전력 사이징" },
  "opamp.bode": { en: "AC magnitude (sized design)", ko: "AC 크기 (사이징 결과)" },
  "opamp.study": { en: "Optimizer experiment — which algorithm wins?", ko: "옵티마이저 실험 — 어떤 알고리즘이 이길까?" },
  "opamp.compare": { en: "Compare", ko: "비교" },
  "opamp.spectre": { en: "Real-Spectre backend (closed loop)", ko: "실 Spectre 백엔드 (closed loop)" },
  "opamp.verify": { en: "Verify with Spectre", ko: "Spectre로 검증" },
  "power.obj": { en: "power (objective)", ko: "전력 (목적함수)" },

  // process
  "process.title": { en: "Process change — describe it in natural language",
                     ko: "공정 변경 — 자연어로 입력하세요" },
  "process.adapt": { en: "▶ Adapt placement + routing", ko: "▶ 배치+배선 재조정" },
  "process.reoptimizing": { en: "Re-optimizing…", ko: "재최적화 중…" },
  "process.before": { en: "Before (current process)", ko: "변경 전 (현재 공정)" },
  "process.after": { en: "After (new process)", ko: "변경 후 (새 공정)" },

  // surrogate
  "sur.title": { en: "Surrogate-assisted optimization — learn the expensive FoM, call it rarely",
                 ko: "Surrogate 기반 최적화 — 비싼 FoM을 학습해 드물게 호출" },
  "sur.run": { en: "Run active learning", ko: "능동학습 실행" },
  "sur.running": { en: "Running…", ko: "실행 중…" },
  "sur.expensive": { en: "expensive (ground-truth) calls", ko: "비싼 (ground-truth) 호출" },
  "sur.cheap": { en: "surrogate calls (cheap)", ko: "surrogate 호출 (저렴)" },
  "sur.savings": { en: "savings", ko: "절감" },

  // bridge
  "bridge.title": { en: "virtuoso_bridge — features verified WITHOUT Virtuoso",
                    ko: "virtuoso_bridge — Virtuoso 없이 검증된 기능들" },
  "bridge.allok": { en: "all checks pass", ko: "모든 체크 통과" },
  "bridge.server": { en: "Real server connection (preflight)", ko: "실서버 연결 (preflight)" },
  "bridge.notconn": { en: "not connected", ko: "미연결" },
  "skill.title": { en: "Generated SKILL — the bridge's output for the optimized cell",
                   ko: "생성된 SKILL — 최적 셀에 대한 브리지 출력" },
  "skill.copy": { en: "Copy", ko: "복사" },
  "skill.download": { en: "Download .il", ko: ".il 다운로드" },

  // agent
  "agent.title": { en: "Hermes agent console — natural language → tools (gpt-5.5 via api_server 8650)",
                   ko: "Hermes 에이전트 콘솔 — 자연어 → 도구 (api_server 8650의 gpt-5.5)" },
  "agent.send": { en: "Send", ko: "전송" },
  "agent.thinking": { en: "agent thinking… (gpt-5.5 + tool execution)", ko: "에이전트 생각 중… (gpt-5.5 + 도구 실행)" },
  "agent.placeholder": { en: "ask the agent…", ko: "에이전트에게 물어보세요…" },
};

interface Ctx {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: string) => string;
}

const LangContext = createContext<Ctx>({ lang: "en", setLang: () => {}, t: (k) => k });

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(
    (localStorage.getItem("alo_lang") as Lang) || "en",
  );
  const setLang = (l: Lang) => {
    localStorage.setItem("alo_lang", l);
    setLangState(l);
  };
  const t = (key: string) => S[key]?.[lang] ?? S[key]?.en ?? key;
  return <LangContext.Provider value={{ lang, setLang, t }}>{children}</LangContext.Provider>;
}

export const useT = () => useContext(LangContext);
