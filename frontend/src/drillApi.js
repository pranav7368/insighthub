// Where the details panel gets its numbers from. Signed in, that is the
// workspace API; on a share link it is the public, token-scoped API, which
// answers aggregates only. The panel reads `mode` and the null entries to hide
// what a share link cannot offer (rows, ask, price/volume/mix, and change
// analysis on a date-limited link).
import { createContext, useContext } from "react";
import * as api from "./api";

// wrappers, not direct references: resolved at call time
export const memberDrillApi = {
  mode: "member",
  inspect: (...a) => api.getInspect(...a),
  breakdown: (...a) => api.getBreakdown(...a),
  variance: (...a) => api.getVariance(...a),
  pvm: (...a) => api.getPvm(...a),
};

export function publicDrillApi(token, { changeAnalysis = true } = {}) {
  return {
    mode: "public",
    inspect: (_datasetId, s) => api.getPublicInspect(token, s),
    breakdown: (_datasetId, s, dimension, limit) => api.getPublicBreakdown(token, s, dimension, limit),
    variance: changeAnalysis ? (_datasetId, s, opts) => api.getPublicVariance(token, s, opts) : null,
    pvm: null,
  };
}

export const DrillApiContext = createContext(memberDrillApi);
export const useDrillApi = () => useContext(DrillApiContext);
