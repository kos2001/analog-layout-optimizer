import { useEffect, useMemo, useRef, useState } from "react";
import { Icon, type IconName } from "./icons";

export interface Command {
  id: string;
  title: string;
  hint?: string;        // right-aligned: group name or shortcut
  icon: IconName;
  run: () => void;
}

/** Subsequence match with a score that favours word starts and contiguity. */
function score(query: string, text: string): number {
  const q = query.toLowerCase();
  const s = text.toLowerCase();
  if (!q) return 1;
  if (s.includes(q)) return 100 - s.indexOf(q);
  let qi = 0, total = 0, run = 0;
  for (let i = 0; i < s.length && qi < q.length; i++) {
    if (s[i] === q[qi]) {
      run += 1;
      total += run + (i === 0 || s[i - 1] === " " ? 3 : 0);
      qi += 1;
    } else {
      run = 0;
    }
  }
  return qi === q.length ? total : -1;
}

export default function CommandPalette({ open, onClose, commands, placeholder, empty }: {
  open: boolean;
  onClose: () => void;
  commands: Command[];
  placeholder: string;
  empty: string;
}) {
  const [query, setQuery] = useState("");
  const [sel, setSel] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLDivElement>(null);

  const results = useMemo(
    () => commands
      .map((c) => ({ c, s: score(query, `${c.title} ${c.hint ?? ""}`) }))
      .filter((r) => r.s >= 0)
      .sort((a, b) => b.s - a.s)
      .map((r) => r.c),
    [commands, query],
  );

  useEffect(() => {
    if (open) {
      setQuery("");
      setSel(0);
      window.setTimeout(() => input.current?.focus(), 0);
    }
  }, [open]);

  useEffect(() => setSel(0), [query]);

  useEffect(() => {
    list.current?.querySelector<HTMLElement>(`[data-idx="${sel}"]`)?.scrollIntoView({ block: "nearest" });
  }, [sel]);

  if (!open) return null;

  const pick = (c: Command | undefined) => {
    if (!c) return;
    onClose();
    c.run();
  };

  return (
    <div className="palette-backdrop" onMouseDown={onClose}>
      <div className="palette" role="dialog" aria-modal="true" aria-label={placeholder}
           onMouseDown={(e) => e.stopPropagation()}>
        <div className="palette-input">
          <Icon name="search" />
          <input
            ref={input}
            value={query}
            placeholder={placeholder}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setSel((i) => Math.min(i + 1, results.length - 1)); }
              else if (e.key === "ArrowUp") { e.preventDefault(); setSel((i) => Math.max(i - 1, 0)); }
              else if (e.key === "Enter") { e.preventDefault(); pick(results[sel]); }
              else if (e.key === "Escape") { e.preventDefault(); onClose(); }
            }}
          />
          <kbd>esc</kbd>
        </div>
        <div className="palette-list" ref={list} role="listbox">
          {results.length === 0 && <div className="palette-empty">{empty}</div>}
          {results.map((c, i) => (
            <div key={c.id} data-idx={i} role="option" aria-selected={i === sel}
                 className={i === sel ? "palette-item on" : "palette-item"}
                 onMouseEnter={() => setSel(i)} onClick={() => pick(c)}>
              <Icon name={c.icon} />
              <span className="palette-title">{c.title}</span>
              {c.hint && <span className="palette-hint">{c.hint}</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
