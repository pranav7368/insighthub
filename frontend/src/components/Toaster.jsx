import { useEffect, useRef, useState } from "react";
import { subscribe } from "../toast";
import Icon from "./Icon";

const MAX = 3;

/**
 * Renders toasts from toast(). Both live regions are always in the DOM so
 * screen readers pick up messages added later; hovering a toast pauses its
 * timer so it can be read.
 */
export default function Toaster() {
  const [items, setItems] = useState([]);
  const timers = useRef(new Map());

  const dismiss = (id) => {
    clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    setItems((list) => list.filter((t) => t.id !== id));
  };
  const arm = (t) => {
    clearTimeout(timers.current.get(t.id));
    timers.current.set(t.id, setTimeout(() => dismiss(t.id), t.timeout));
  };

  useEffect(() => {
    const live = timers.current;
    const off = subscribe((t) => {
      setItems((list) => [...list, t].slice(-MAX));
      arm(t);
    });
    return () => { off(); live.forEach(clearTimeout); live.clear(); };
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  const render = (t) => (
    <div key={t.id} className={`toast toast--${t.kind}`}
      onMouseEnter={() => clearTimeout(timers.current.get(t.id))} onMouseLeave={() => arm(t)}>
      <span className="toast__icon" aria-hidden>{t.kind === "error" ? "!" : t.kind === "info" ? "i" : "✓"}</span>
      <span className="toast__msg">{t.message}</span>
      <button className="toast__x" onClick={() => dismiss(t.id)} aria-label="Dismiss"><Icon name="close" size={14} /></button>
    </div>
  );

  return (
    <div className="toaster no-export">
      <div role="status" aria-live="polite">{items.filter((t) => t.kind !== "error").map(render)}</div>
      <div role="alert" aria-live="assertive">{items.filter((t) => t.kind === "error").map(render)}</div>
    </div>
  );
}
