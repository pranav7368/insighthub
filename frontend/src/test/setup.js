import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// Unmount between tests so a stray component cannot influence the next one.
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  localStorage.clear();
});

// jsdom implements neither of these, and components legitimately use both.
window.scrollTo = () => {};
Element.prototype.scrollIntoView = function scrollIntoView() {};
