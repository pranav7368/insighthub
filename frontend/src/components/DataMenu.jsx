import { useEffect, useLayoutEffect, useRef, useState } from "react";

/**
 * The right-click menu on a data point: every way into that number from where
 * the pointer is. A WAI-ARIA menu — focus moves into it, ↑ ↓ / Home / End
 * move, Enter runs, Esc or a click elsewhere closes.
 */
export default function DataMenu({ x, y, title, items, onClose }) {
  const ref = useRef(null);
  const [pos, setPos] = useState({ left: x, top: y });

  // keep the menu on screen
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    setPos({
      left: Math.max(8, Math.min(x, window.innerWidth - r.width - 8)),
      top: Math.max(8, Math.min(y, window.innerHeight - r.height - 8)),
    });
  }, [x, y]);

  useEffect(() => {
    ref.current?.querySelector('[role="menuitem"]')?.focus();
    const away = (e) => { if (!ref.current?.contains(e.target)) onClose(); };
    const esc = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("mousedown", away);
    window.addEventListener("keydown", esc);
    window.addEventListener("scroll", onClose, true);
    window.addEventListener("resize", onClose);
    return () => {
      window.removeEventListener("mousedown", away);
      window.removeEventListener("keydown", esc);
      window.removeEventListener("scroll", onClose, true);
      window.removeEventListener("resize", onClose);
    };
  }, [onClose]);

  const move = (e) => {
    const all = [...ref.current.querySelectorAll('[role="menuitem"]')];
    const i = all.indexOf(document.activeElement);
    const to = { ArrowDown: i + 1, ArrowUp: i - 1, Home: 0, End: all.length - 1 }[e.key];
    if (to === undefined) return;
    e.preventDefault();
    all[(to + all.length) % all.length]?.focus();
  };

  return (
    <div ref={ref} className="data-menu no-export" role="menu" aria-label={title}
      style={{ left: pos.left, top: pos.top }} onKeyDown={move}>
      <div className="data-menu__title" aria-hidden>{title}</div>
      {items.map((it) => (
        <button key={it.label} role="menuitem" className="data-menu__item" tabIndex={-1}
          onClick={() => { onClose(); it.run(); }}>
          <span>{it.label}</span>
          {it.hint && <span className="data-menu__hint">{it.hint}</span>}
        </button>
      ))}
    </div>
  );
}
