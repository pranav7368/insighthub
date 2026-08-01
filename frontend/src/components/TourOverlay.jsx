import { useCallback, useEffect, useLayoutEffect, useState } from "react";

const CARD_W = 340;
const PAD = 8;      // spotlight breathing room around the target
const GAP = 14;     // distance from spotlight to the card

/** Steps whose anchor is not currently rendered are dropped, not shown empty. */
const liveSteps = (steps) =>
  steps.filter((s) => !s.target || document.querySelector(s.target));

function placeCard(rect) {
  if (!rect) {
    return { left: (window.innerWidth - CARD_W) / 2, top: Math.max(80, window.innerHeight / 2 - 120) };
  }
  const below = rect.bottom + GAP;
  const fitsBelow = below + 220 < window.innerHeight;
  const top = fitsBelow ? below : Math.max(12, rect.top - GAP - 220);
  const left = Math.min(
    Math.max(12, rect.left + rect.width / 2 - CARD_W / 2),
    window.innerWidth - CARD_W - 12
  );
  return { left, top };
}

/**
 * Spotlight product tour. The dark surround is one element's huge box-shadow
 * with a hole punched by its own bounds — cheap, and it follows the target on
 * scroll or resize. A separate transparent blocker keeps clicks off the app
 * while the tour is up.
 */
export default function TourOverlay({ steps, onFinish }) {
  // Computed AFTER commit, not in a useState initialiser. liveSteps() reads
  // the DOM, and a state initialiser runs before React has committed — so any
  // anchor rendered in the same commit as this component would be invisible
  // and its step dropped for the whole tour. Today the tour always mounts
  // after the app is on screen, so this is prevention rather than a fix, but
  // "steps silently disappear" is not a failure anyone would notice.
  const [visible, setVisible] = useState([]);
  const [i, setI] = useState(0);
  const [rect, setRect] = useState(null);

  useLayoutEffect(() => {
    setVisible(liveSteps(steps));
    setI(0);
  }, [steps]);

  const step = visible[i];
  const last = i === visible.length - 1;

  const measure = useCallback(() => {
    if (!step?.target) { setRect(null); return; }
    const el = document.querySelector(step.target);
    if (!el) { setRect(null); return; }
    const r = el.getBoundingClientRect();
    setRect({ top: r.top - PAD, left: r.left - PAD, width: r.width + PAD * 2, height: r.height + PAD * 2,
              bottom: r.bottom + PAD });
  }, [step]);

  useLayoutEffect(() => {
    if (!step) return;
    if (step.target) {
      document.querySelector(step.target)?.scrollIntoView({ block: "center", inline: "nearest" });
    }
    measure();
  }, [step, measure]);

  useEffect(() => {
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [measure]);

  const next = useCallback(() => (last ? onFinish() : setI((n) => n + 1)), [last, onFinish]);
  const back = useCallback(() => setI((n) => Math.max(0, n - 1)), []);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onFinish();
      else if (e.key === "ArrowRight" || e.key === "Enter") { e.preventDefault(); next(); }
      else if (e.key === "ArrowLeft") back();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [next, back, onFinish]);

  if (!step) return null;
  const card = placeCard(rect);

  return (
    <div className="tour" role="dialog" aria-modal="true" aria-labelledby="tour-title">
      <div className="tour__blocker" onClick={(e) => e.stopPropagation()} />
      {rect && (
        <div className="tour__spot" style={{ top: rect.top, left: rect.left, width: rect.width, height: rect.height }} />
      )}
      <div className="tour__card" style={{ left: card.left, top: card.top, width: CARD_W }}>
        <div className="tour__progress">
          {visible.map((s, n) => (
            <span key={s.id} className={`tour__dot${n === i ? " is-on" : ""}`} />
          ))}
        </div>
        <h3 id="tour-title">{step.title}</h3>
        <p>{step.body}</p>
        <div className="tour__actions">
          <button className="tour__skip" onClick={onFinish}>Skip tour</button>
          {i > 0 && <button className="views-btn" onClick={back}>Back</button>}
          <button className="views-btn views-btn--accent" onClick={next} autoFocus>
            {last ? "Get started" : "Next"}
          </button>
        </div>
      </div>
    </div>
  );
}
