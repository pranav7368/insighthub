// A tiny app-wide toast channel. Anything can call toast(); the one <Toaster/>
// mounted by the app renders them. No context or provider to thread through.

const listeners = new Set();
let seq = 0;

/**
 * Show a short confirmation. kind: "success" | "error" | "info".
 * Errors stay up longer and are announced assertively.
 */
export function toast(message, { kind = "success", timeout } = {}) {
  const t = { id: ++seq, message, kind, timeout: timeout ?? (kind === "error" ? 7000 : 4000) };
  listeners.forEach((fn) => fn(t));
  return t.id;
}

export const toastError = (message) => toast(message, { kind: "error" });

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
