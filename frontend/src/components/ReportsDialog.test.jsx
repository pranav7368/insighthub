import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({
  listReports: vi.fn(),
  getReportsStatus: vi.fn(),
  getSchema: vi.fn(),
  createReport: vi.fn(),
  previewReport: vi.fn(),
  setReportEnabled: vi.fn(),
  sendReportNow: vi.fn(),
  deleteReport: vi.fn(),
  errorText: (err, fallback = "Something went wrong") => err?.response?.data?.detail || fallback,
}));

import * as api from "../api";
import ReportsDialog from "./ReportsDialog";

const REPORT = {
  report_id: "rpt_1", name: "Weekly revenue", frequency: "weekly", measure: "revenue",
  recipients: ["ceo@x.com", "cfo@x.com"], enabled: true, last_sent_at: null, last_status: null,
};

beforeEach(() => {
  api.listReports.mockResolvedValue([REPORT]);
  api.getReportsStatus.mockResolvedValue({ email_configured: true });
  api.getSchema.mockResolvedValue([{ name: "revenue", role: "measure" }, { name: "region", role: "dimension" }]);
  api.createReport.mockResolvedValue(REPORT);
  api.previewReport.mockResolvedValue({ subject: "Weekly revenue: Revenue rose 2.7%", html: "<p>hello</p>" });
  api.sendReportNow.mockResolvedValue({ sent: 2 });
});

describe("ReportsDialog", () => {
  it("schedules a report for the chosen measure and frequency", async () => {
    render(<ReportsDialog datasetId="ds" onClose={vi.fn()} />);
    await screen.findByText("Weekly revenue");
    await userEvent.type(screen.getByLabelText("Name"), "Board pack");
    await userEvent.type(screen.getByLabelText("Recipients"), "a@b.co, c@d.org");
    await userEvent.selectOptions(screen.getByLabelText("How often"), "monthly");
    await userEvent.click(screen.getByRole("button", { name: "Schedule report" }));
    expect(api.createReport).toHaveBeenCalledWith("ds", {
      name: "Board pack", recipients: "a@b.co, c@d.org", frequency: "monthly", measure: "revenue",
    });
  });

  it("previews exactly what recipients get, sandboxed", async () => {
    render(<ReportsDialog datasetId="ds" onClose={vi.fn()} />);
    await screen.findByText("Weekly revenue");
    await userEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByText(/Revenue rose 2.7%/)).toBeInTheDocument();
    const frame = screen.getByTitle("Email preview");
    expect(frame).toHaveAttribute("sandbox", "");
    expect(frame).toHaveAttribute("srcdoc", "<p>hello</p>");
  });

  it("sends now and says to how many people", async () => {
    render(<ReportsDialog datasetId="ds" onClose={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Send now" }));
    expect(await screen.findByText("Sent “Weekly revenue” to 2 recipients.")).toBeInTheDocument();
  });

  it("warns when the server cannot send email, and shows why a send failed", async () => {
    api.getReportsStatus.mockResolvedValue({ email_configured: false });
    api.sendReportNow.mockRejectedValue({ response: { data: { detail: "email is not configured on this server" } } });
    render(<ReportsDialog datasetId="ds" onClose={vi.fn()} />);
    expect(await screen.findByText(/Email is not configured on this server yet/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Send now" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("email is not configured"));
  });
});
