import { useEffect, useId, useRef, useState } from "react";

/**
 * A button that opens a floating panel: menus (role="menu", arrow keys move
 * between items) or free-form panels such as the filter picker.
 *
 *   <Popover label="More" menu>{(close) => <button role="menuitem" …/>}</Popover>
 *
 * Closes on Escape (focus returns to the button), on a click outside, and
 * — for menus — after an item runs. Replaces the <details> dropdowns, which
 * stayed open when you clicked elsewhere and could not be closed with Esc.
 */
export default function Popover({
  label, icon = null, children, menu = false, align = "start", className = "",
  buttonClass = "tb-btn", panelClass = "", buttonProps = {}, title,
}) {
  const [open, setOpen] = useState(false);
  const wrap = useRef(null);
  const button = useRef(null);
  const panel = useRef(null);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    const away = (e) => { if (!wrap.current?.contains(e.target)) setOpen(false); };
    const esc = (e) => {
      if (e.key === "Escape") { setOpen(false); button.current?.focus(); }
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    if (menu) panel.current?.querySelector('[role="menuitem"], [role="menuitemcheckbox"]')?.focus();
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open, menu]);

  const onPanelKey = (e) => {
    if (!menu) return;
    const items = [...panel.current.querySelectorAll('[role="menuitem"], [role="menuitemcheckbox"]')];
    const i = items.indexOf(document.activeElement);
    const to = { ArrowDown: i + 1, ArrowUp: i - 1, Home: 0, End: items.length - 1 }[e.key];
    if (to === undefined || !items.length) return;
    e.preventDefault();
    items[(to + items.length) % items.length].focus();
  };

  const close = () => setOpen(false);
  return (
    <div className={`popover ${className}`} ref={wrap}>
      <button ref={button} type="button" className={buttonClass} aria-expanded={open}
        aria-haspopup={menu ? "menu" : "dialog"} aria-controls={open ? id : undefined}
        title={title} onClick={() => setOpen((o) => !o)} {...buttonProps}>
        {icon}{label}
      </button>
      {open && (
        <div ref={panel} id={id} className={`popover__panel popover__panel--${align} ${panelClass}`}
          role={menu ? "menu" : "dialog"} aria-label={typeof label === "string" ? label : title}
          onKeyDown={onPanelKey}
          onClick={(e) => { if (menu && e.target.closest('[role="menuitem"]')) close(); }}>
          {children(close)}
        </div>
      )}
    </div>
  );
}
