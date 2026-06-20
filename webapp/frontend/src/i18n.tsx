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
  "loading": { en: "Loading…", ko: "불러오는 중…" },

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
