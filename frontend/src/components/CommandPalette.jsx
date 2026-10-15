import { useEffect, useMemo, useRef, useState } from "react";
import { searchCommands } from "../palette";

/**
 * Ctrl/⌘ K: find any number, segment, section, view or action by typing.
 * A combobox over a listbox (WAI-ARIA pattern): focus stays in the input,
 * ↑ ↓ move the active option, Enter runs it, Esc closes.
 */
export default function CommandPalette({ commands, onClose }) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef(null);
  const listRef = useRef(null);
  const results = useMemo(() => searchCommands(commands, query), [commands, query]);

  useEffect(() => { inputRef.current?.focus(); }, []);
  useEffect(() => { setActive(0); }, [query]);
  useEffect(() => {
    listRef.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const run = (cmd) => {
    if (!cmd) return;
    onClose();
    cmd.run();
  };
  const onKey = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((i) => Math.min(results.length - 1, i + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => Math.max(0, i - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); run(results[active]); }
    else if (e.key === "Escape") { e.preventDefault(); onClose(); }
  };

  let lastGroup = null;
  return (
    <div className="palette-backdrop no-export" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Search the dashboard">
        <input ref={inputRef} className="palette__input" value={query} onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKey} placeholder="Search numbers, segments, sections, views…"
          role="combobox" aria-expanded="true" aria-controls="palette-list" aria-autocomplete="list"
          aria-activedescendant={results[active] ? `palette-opt-${active}` : undefined} />
        <ul className="palette__list" id="palette-list" role="listbox" ref={listRef} aria-label="Results">
          {results.length === 0 && <li className="palette__empty" role="presentation">Nothing matches “{query}”.</li>}
          {results.map((c, i) => {
            const header = !query.trim() && c.group !== lastGroup;
            lastGroup = c.group;
            return [
              header && <li key={`h-${c.group}`} className="palette__group" role="presentation">{c.group}</li>,
              <li key={c.id} id={`palette-opt-${i}`} data-index={i} role="option" aria-selected={i === active}
                className={`palette__item${i === active ? " is-active" : ""}`}
                onMouseMove={() => setActive(i)} onClick={() => run(c)}>
                <span className="palette__label">{c.label}</span>
                {query.trim() ? <span className="palette__tag">{c.group}</span>
                  : c.hint ? <span className="palette__hint">{c.hint}</span> : null}
              </li>,
            ];
          })}
        </ul>
        <div className="palette__foot" aria-hidden>
          <span><kbd>↑</kbd><kbd>↓</kbd> move</span><span><kbd>Enter</kbd> open</span><span><kbd>Esc</kbd> close</span>
          <span>right-click any number for more</span>
        </div>
      </div>
    </div>
  );
}
