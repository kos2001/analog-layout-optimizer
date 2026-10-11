// Stroke icon set (24x24 grid, currentColor) for the shell. Inline SVG keeps
// the app dependency-free and offline.

import type { ReactNode } from "react";

const P = {
  flow: <><circle cx="5" cy="6" r="2" /><circle cx="19" cy="6" r="2" /><circle cx="12" cy="18" r="2" />
    <path d="M7 6h10M6 8l5 8M18 8l-5 8" /></>,
  schematic: <><path d="M3 12h4l2-5 3 10 3-10 2 5h4" /></>,
  chip: <><rect x="6" y="6" width="12" height="12" rx="1.5" /><rect x="9.5" y="9.5" width="5" height="5" />
    <path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3" /></>,
  layers: <><path d="M12 3 3 8l9 5 9-5-9-5Z" /><path d="m3 13 9 5 9-5" /></>,
  route: <><path d="M4 20V9h6V4h10" /><path d="M8 20v-5h8v-4h4" /><circle cx="4" cy="20" r="1.5" />
    <circle cx="20" cy="4" r="1.5" /></>,
  grid: <><rect x="3.5" y="3.5" width="7" height="7" rx="1" /><rect x="13.5" y="3.5" width="7" height="7" rx="1" />
    <rect x="3.5" y="13.5" width="7" height="7" rx="1" /><path d="M13.5 17h7M17 13.5v7" /></>,
  chart: <><path d="M4 20V4M4 20h16" /><circle cx="8" cy="15" r="1.3" /><circle cx="11" cy="10" r="1.3" />
    <circle cx="15" cy="8" r="1.3" /><circle cx="19" cy="7" r="1.3" /></>,
  opamp: <><path d="M6 4v16l13-8L6 4Z" /><path d="M2 9h4M2 15h4M19 12h3M8.5 9h2M9.5 8v2M8.5 15h2" /></>,
  coil: <><path d="M3 12h3c0-3 3-3 3 0s3 3 3 0 3-3 3 0 3 3 3 0h3" /></>,
  process: <><path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.7 3h10.6a2 2 0 0 0 1.7-3l-5-9V3" /><path d="M7.5 15h9" /></>,
  sparkles: <><path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8L12 3Z" />
    <path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8L19 15Z" /></>,
  bridge: <><path d="M3 17h18M5 17V9M19 17V9M3 9c3 0 6-3 9-3s6 3 9 3" /><path d="M9 17v-6M15 17v-6" /></>,
  agent: <><rect x="4" y="7" width="16" height="12" rx="3" /><path d="M12 3v4M9 12h.01M15 12h.01M9.5 16h5" /></>,
  search: <><circle cx="11" cy="11" r="6.5" /><path d="m20 20-4.2-4.2" /></>,
  play: <><path d="M7 4.5v15l12-7.5-12-7.5Z" /></>,
  x: <><path d="M6 6l12 12M18 6 6 18" /></>,
  check: <><path d="m5 12.5 4.5 4.5L19 7.5" /></>,
  alert: <><path d="M12 3 2.5 20h19L12 3Z" /><path d="M12 10v4.5M12 17.5h.01" /></>,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v5.5M12 7.5h.01" /></>,
  dock: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 14h18" /></>,
  sidebar: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16" /></>,
  globe: <><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c3 3.2 3 14.8 0 18M12 3c-3 3.2-3 14.8 0 18" /></>,
  server: <><rect x="3.5" y="4" width="17" height="7" rx="1.5" /><rect x="3.5" y="13" width="17" height="7" rx="1.5" />
    <path d="M7 7.5h.01M7 16.5h.01" /></>,
  database: <><ellipse cx="12" cy="6" rx="7.5" ry="2.8" /><path d="M4.5 6v12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8V6" />
    <path d="M4.5 12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8" /></>,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  stop: <><rect x="6" y="6" width="12" height="12" rx="1.5" /></>,
  terminal: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="m7 9 3 3-3 3M12.5 15H17" /></>,
  trash: <><path d="M4 7h16M9 7V4h6v3M6.5 7l1 13h9l1-13" /></>,
  chevron: <><path d="m9 6 6 6-6 6" /></>,
  command: <><path d="M9 6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3V6Z" /></>,
} satisfies Record<string, ReactNode>;

export type IconName = keyof typeof P;

export function Icon({ name, size = 16, className }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round"
         aria-hidden="true">
      {P[name]}
    </svg>
  );
}
