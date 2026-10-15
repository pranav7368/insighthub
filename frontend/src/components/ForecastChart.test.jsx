import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ForecastChart from "./ForecastChart";

const base = {
  method: "holt_winters", label: "Holt-Winters (seasonal smoothing)",
  history: [{ period: "2025-01", value: 10 }, { period: "2025-02", value: 12 }],
  forecast: [{ period: "2025-03", value: 13, lower: 11, upper: 15 }],
  moving_avg: [null, null],
};

describe("ForecastChart", () => {
  it("names the model and how far it has been off on this series", () => {
    render(<ForecastChart measure="revenue" subtype={null} forecast={{
      ...base, accuracy: { mape: 4.2, mae: 12.5, tests: 21, months: 8, candidates: [{}, {}, {}, {}, {}] },
    }} />);
    expect(screen.getByText(/next month · Holt-Winters/)).toBeInTheDocument();
    expect(screen.getByText(/testing 5 standard models against what actually happened over the last 8 months/))
      .toBeInTheDocument();
    expect(screen.getByText(/off by 4.2% on average/)).toBeInTheDocument();
  });

  it("makes no accuracy claim when there was too little history to test", () => {
    render(<ForecastChart measure="revenue" subtype={null} forecast={{ ...base, accuracy: null }} />);
    expect(screen.queryByText(/standard models/)).toBeNull();
  });
});
