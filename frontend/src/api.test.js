import { describe, expect, it } from "vitest";

import { errorText } from "./api";

/**
 * errorText exists because rendering FastAPI's 422 body straight into JSX
 * throws "Objects are not valid as a React child" and blanks the page — which
 * is exactly what the signup screen used to do. These cases are the shapes the
 * API actually returns.
 */
describe("errorText", () => {
  it("uses a plain string detail", () => {
    expect(errorText({ response: { data: { detail: "dataset not found" } } }))
      .toBe("dataset not found");
  });

  it("joins the messages out of a 422 validation array", () => {
    const err = {
      response: {
        data: {
          detail: [
            { type: "value_error", loc: ["body", "email"], msg: "not a valid email address" },
            { type: "too_short", loc: ["body", "password"], msg: "string too short" },
          ],
        },
      },
    };
    const text = errorText(err);
    expect(text).toContain("not a valid email address");
    expect(text).toContain("string too short");
    expect(typeof text).toBe("string");
  });

  it("returns a string for every shape, so JSX can never receive an object", () => {
    const shapes = [
      undefined,
      null,
      {},
      { response: {} },
      { response: { data: {} } },
      { response: { data: { detail: null } } },
      { response: { data: { detail: [] } } },
      { response: { data: { detail: [{ nothing: "useful" }] } } },
      { response: { data: { detail: { nested: "object" } } } },
      new Error("network down"),
    ];
    for (const shape of shapes) {
      expect(typeof errorText(shape)).toBe("string");
      expect(errorText(shape).length).toBeGreaterThan(0);
    }
  });

  it("prefers the caller's fallback over the generic one", () => {
    expect(errorText({}, "Could not load that template."))
      .toBe("Could not load that template.");
  });

  it("falls back when the array carries no usable messages", () => {
    const err = { response: { data: { detail: [{ loc: ["body"] }] } } };
    expect(errorText(err, "Upload failed")).toBe("Upload failed");
  });

  it("does not treat an empty string detail as usable", () => {
    expect(errorText({ response: { data: { detail: "" } } }, "fallback")).toBe("fallback");
  });
});
