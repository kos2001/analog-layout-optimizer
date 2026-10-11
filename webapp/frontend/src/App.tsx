import { Component, Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useT } from "./i18n";
import CommandPalette, { type Command } from "./shell/CommandPalette";
import { useHashRoute, useHealth, usePersisted, useStore } from "./shell/hooks";
import { Icon } from "./shell/icons";
import { TERMINAL, jobsStore, startJobsPolling } from "./shell/jobs";
import RunDock, { type DockTab } from "./shell/RunDock";
import StatusBar from "./shell/StatusBar";
import { toast } from "./shell/telemetry";
import Toasts from "./shell/Toasts";
import { DEFAULT_VIEW, GROUPS, VIEWS, viewById } from "./shell/views";

/** Keeps one broken view from taking down the whole workspace. */
class ViewBoundary extends Component<{ children: ReactNode; resetKey: string }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidUpdate(prev: { resetKey: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }
  render() {
    if (this.state.error) {
      return (
        <div className="view-error">
          <Icon name="alert" size={20} />
          <div>
            <strong>This view failed to render.</strong>
            <code>{String(this.state.error.message ?? this.state.error)}</code>
            <button className="secondary" onClick={() => this.setState({ error: null })}>Retry</button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

const isMac = typeof navigator !== "undefined" && /Mac|iP(hone|ad)/.test(navigator.platform);
const MOD = isMac ? "⌘" : "Ctrl+";

export default function App() {
  const { t, lang, setLang } = useT();
  const [route, go] = useHashRoute(DEFAULT_VIEW);
  const view = viewById(route) ?? viewById(DEFAULT_VIEW)!;
  const group = GROUPS.find((g) => g.id === view.group)!;

  const [navCollapsed, setNavCollapsed] = usePersisted("alo.nav.collapsed", false);
  const [dockOpen, setDockOpen] = usePersisted("alo.dock.open", true);
  const [dockTab, setDockTab] = usePersisted<DockTab>("alo.dock.tab", "runs");
  const [dockH, setDockH] = usePersisted("alo.dock.height", 220);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);

  const { health, online } = useHealth();
  const { jobs } = useStore(jobsStore);
  const active = jobs.filter((j) => !TERMINAL.has(j.status)).length;

  useEffect(() => startJobsPolling(), []);

  useEffect(() => {
    document.title = `${t(view.label)} · Analog Layout Optimizer`;
    setMobileNav(false);
  }, [view, t]);

  // Unhandled API failures from any view surface as a toast, not a silent console error.
  useEffect(() => {
    const on = (e: PromiseRejectionEvent) => {
      toast("error", t("toast.request.failed"), String(e.reason?.message ?? e.reason), 8000);
    };
    window.addEventListener("unhandledrejection", on);
    return () => window.removeEventListener("unhandledrejection", on);
  }, [t]);

  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); setPaletteOpen((o) => !o); }
      else if (mod && e.key.toLowerCase() === "j") { e.preventDefault(); setDockOpen(!dockOpen); }
      else if (mod && e.key.toLowerCase() === "b") { e.preventDefault(); setNavCollapsed(!navCollapsed); }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [dockOpen, navCollapsed, setDockOpen, setNavCollapsed]);

  const openRuns = () => { setDockTab("runs"); setDockOpen(true); };

  const commands: Command[] = useMemo(() => [
    ...VIEWS.map((v) => ({
      id: `view:${v.id}`, title: t(v.label), hint: t(GROUPS.find((g) => g.id === v.group)!.label),
      icon: v.icon, run: () => go(v.id),
    })),
    { id: "dock:runs", title: t("cmd.runs"), hint: `${MOD}J`, icon: "play", run: openRuns },
    { id: "dock:console", title: t("cmd.console"), icon: "terminal",
      run: () => { setDockTab("console"); setDockOpen(true); } },
    { id: "dock:toggle", title: t("cmd.dock"), hint: `${MOD}J`, icon: "dock", run: () => setDockOpen(!dockOpen) },
    { id: "nav:toggle", title: t("cmd.nav"), hint: `${MOD}B`, icon: "sidebar",
      run: () => setNavCollapsed(!navCollapsed) },
    { id: "lang", title: lang === "en" ? "한국어로 전환" : "Switch to English", icon: "globe",
      run: () => setLang(lang === "en" ? "ko" : "en") },
  ], [t, lang, dockOpen, navCollapsed]);

  // Drag the dock's top edge to resize it.
  const drag = useRef<{ y: number; h: number } | null>(null);
  useEffect(() => {
    const move = (e: PointerEvent) => {
      if (!drag.current) return;
      const h = drag.current.h + (drag.current.y - e.clientY);
      setDockH(Math.max(120, Math.min(window.innerHeight * 0.7, h)));
    };
    const up = () => { drag.current = null; document.body.classList.remove("resizing"); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
  }, [setDockH]);

  const ViewComponent = view.component;

  return (
    <div className={`shell${navCollapsed ? " nav-collapsed" : ""}${mobileNav ? " nav-mobile-open" : ""}`}>
      <header className="topbar">
        <button className="icon-btn nav-toggle" title={`${t("cmd.nav")} (${MOD}B)`}
                onClick={() => (window.innerWidth < 860 ? setMobileNav(!mobileNav) : setNavCollapsed(!navCollapsed))}>
          <Icon name="sidebar" />
        </button>
        <a className="brand" href="#/fullflow">
          <img src="/icon.svg" alt="" width={22} height={22} />
          <span className="brand-name">Analog Layout Optimizer</span>
        </a>
        <nav className="crumbs" aria-label="breadcrumb">
          <span>{t(group.label)}</span>
          <Icon name="chevron" size={12} />
          <span className="crumb-current">{t(view.label)}</span>
        </nav>
        <button className="search-btn" onClick={() => setPaletteOpen(true)}>
          <Icon name="search" size={14} />
          <span>{t("palette.trigger")}</span>
          <kbd>{MOD}K</kbd>
        </button>
        <div className="topbar-right">
          <button className={active ? "run-indicator on" : "run-indicator"} onClick={openRuns}
                  title={t("dock.runs")}>
            {active ? <i className="spinner" /> : <Icon name="play" size={13} />}
            <span className="run-indicator-text">{active ? `${active} ${t("dock.active")}` : t("dock.runs")}</span>
          </button>
          <div className="seg-mini" role="group" aria-label="language">
            <button className={lang === "en" ? "on" : ""} onClick={() => setLang("en")}>EN</button>
            <button className={lang === "ko" ? "on" : ""} onClick={() => setLang("ko")}>한</button>
          </div>
          <button className={dockOpen ? "icon-btn on" : "icon-btn"} title={`${t("cmd.dock")} (${MOD}J)`}
                  onClick={() => setDockOpen(!dockOpen)}>
            <Icon name="dock" />
          </button>
        </div>
      </header>

      <aside className="sidenav" aria-label="views">
        {GROUPS.map((g) => (
          <div key={g.id} className="nav-group">
            <div className="nav-group-label">{t(g.label)}</div>
            {VIEWS.filter((v) => v.group === g.id).map((v) => (
              <a key={v.id} href={`#/${v.id}`} title={t(v.label)}
                 className={v.id === view.id ? "nav-item on" : "nav-item"}
                 aria-current={v.id === view.id ? "page" : undefined}>
                <Icon name={v.icon} />
                <span>{t(v.label)}</span>
              </a>
            ))}
          </div>
        ))}
      </aside>
      <div className="nav-scrim" onClick={() => setMobileNav(false)} />

      <main className="workspace">
        <div className="view-header">
          <div>
            <h1>{t(view.label)}</h1>
            <p>{t(view.desc)}</p>
          </div>
        </div>
        <div className="view-body">
          <ViewBoundary resetKey={view.id}>
            <Suspense fallback={<div className="skeleton" aria-busy="true"><div /><div /><div /></div>}>
              <ViewComponent />
            </Suspense>
          </ViewBoundary>
        </div>
      </main>

      {dockOpen && (
        <div className="dock-wrap" style={{ height: dockH }}>
          <div className="dock-handle" onPointerDown={(e) => {
            drag.current = { y: e.clientY, h: dockH };
            document.body.classList.add("resizing");
          }} />
          <RunDock tab={dockTab} setTab={setDockTab} onClose={() => setDockOpen(false)} />
        </div>
      )}

      <StatusBar health={health} online={online} onOpenRuns={openRuns} />
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} commands={commands}
                      placeholder={t("palette.placeholder")} empty={t("palette.empty")} />
      <Toasts />
    </div>
  );
}
