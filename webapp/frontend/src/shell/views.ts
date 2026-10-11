// Single source of truth for navigation: every workspace view, grouped by
// design stage. The shell, router and command palette all read this table.

import { lazy, type ComponentType, type LazyExoticComponent } from "react";
import type { IconName } from "./icons";

export interface ViewDef {
  id: string;
  group: GroupId;
  icon: IconName;
  label: string;        // i18n key (existing tab.* keys)
  desc: string;         // i18n key, one-line description in the view header
  component: LazyExoticComponent<ComponentType>;
}

export type GroupId = "flow" | "layout" | "analysis" | "integration";

export const GROUPS: { id: GroupId; label: string }[] = [
  { id: "flow", label: "nav.group.flow" },
  { id: "layout", label: "nav.group.layout" },
  { id: "analysis", label: "nav.group.analysis" },
  { id: "integration", label: "nav.group.integration" },
];

export const VIEWS: ViewDef[] = [
  { id: "fullflow", group: "flow", icon: "flow", label: "tab.fullflow", desc: "desc.fullflow",
    component: lazy(() => import("../components/FullFlowView")) },
  { id: "flow", group: "flow", icon: "schematic", label: "tab.flow", desc: "desc.flow",
    component: lazy(() => import("../components/FlowView")) },
  { id: "device", group: "layout", icon: "chip", label: "tab.layout", desc: "desc.device",
    component: lazy(() => import("../components/DeviceView")) },
  { id: "layoutview", group: "layout", icon: "layers", label: "tab.layoutview", desc: "desc.layoutview",
    component: lazy(() => import("../components/LayoutView")) },
  { id: "comparator", group: "layout", icon: "route", label: "tab.comparator", desc: "desc.comparator",
    component: lazy(() => import("../components/MazeView")) },
  { id: "complex", group: "layout", icon: "grid", label: "tab.complex", desc: "desc.complex",
    component: lazy(() => import("../components/ComplexCasesView")) },
  { id: "ppa", group: "analysis", icon: "chart", label: "tab.ppa", desc: "desc.ppa",
    component: lazy(() => import("../components/PPAView")) },
  { id: "opamp", group: "analysis", icon: "opamp", label: "tab.opamp", desc: "desc.opamp",
    component: lazy(() => import("../components/OpAmpView")) },
  { id: "tcoil", group: "analysis", icon: "coil", label: "tab.tcoil", desc: "desc.tcoil",
    component: lazy(() => import("../components/TCoilView")) },
  { id: "process", group: "analysis", icon: "process", label: "tab.process", desc: "desc.process",
    component: lazy(() => import("../components/ProcessView")) },
  { id: "surrogate", group: "analysis", icon: "sparkles", label: "tab.surrogate", desc: "desc.surrogate",
    component: lazy(() => import("../components/SurrogateView")) },
  { id: "bridge", group: "integration", icon: "bridge", label: "tab.bridge", desc: "desc.bridge",
    component: lazy(() => import("../components/BridgeView")) },
  { id: "agent", group: "integration", icon: "agent", label: "tab.agent", desc: "desc.agent",
    component: lazy(() => import("../components/AgentConsole")) },
];

export const DEFAULT_VIEW = "fullflow";
export const viewById = (id: string) => VIEWS.find((v) => v.id === id);
