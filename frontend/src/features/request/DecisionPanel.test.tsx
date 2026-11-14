import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../../components/ui";
import type { Assessment, Decision, Finding, RequestDetail } from "../../lib/api";
import { PERSONAS, setIdentity } from "../../lib/identity";
import { DecisionPanel } from "./DecisionPanel";

const request = (over: Partial<RequestDetail> = {}): RequestDetail => ({
  id: "r1", request_no: "PR-1", requester_name: "Layla Hassan", department: "Finance", supplier_name: "Orion", currency: "USD",
  total_amount: "12000.00", status: "assessed", submitted_at: "2026-03-10T00:00:00Z", is_synthetic: true, justification: "Needed", category: null,
  items: [], documents: [], ...over,
});
const finding = (id: string, category: string): Finding => ({ id, category, source: "rule", rule_code: "R-X", title: `Finding ${id}`, explanation: "", severity: null, confidence: null, evidence: [] });
const assessment = (findings: Finding[]): Assessment => ({
  id: "a1", request_id: "r1", version: 1, overall_risk: "high", compliance_status: "issues_found", confidence: 0.8, confidence_note: "", summary: "",
  is_mock: true, provider: "mock", model: "m", prompt_versions: {}, latency_ms: 1, tokens: { input: null, output: null }, est_cost_usd: null,
  created_at: "2026-03-10T00:00:00Z", financial_risks: [], next_steps: [], missing_info: [], findings, decision_required: "",
});

function renderPanel(props: Partial<React.ComponentProps<typeof DecisionPanel>> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}><ToastProvider>
      <DecisionPanel request={request()} assessment={assessment([finding("f1", "compliant")])} latestId="a1" lastDecision={undefined} openInfo={undefined} {...props} />
    </ToastProvider></QueryClientProvider>,
  );
}
const persona = (user: string) => setIdentity(PERSONAS.find((p) => p.user === user)!);

describe("DecisionPanel", () => {
  it("tells a requester that only reviewers decide", () => {
    persona("Layla Hassan");
    persona("Layla Hassan");
    setIdentity({ ...PERSONAS[0], user: "Someone Else" });
    renderPanel();
    expect(screen.getByText(/Only reviewers record decisions/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approve request/i })).not.toBeInTheDocument();
  });

  it("blocks the requester from deciding on their own request", () => {
    setIdentity({ role: "reviewer", user: "layla hassan", authority: "finance director", label: "Custom" });
    renderPanel();
    expect(screen.getByText(/segregation of duties/)).toBeInTheDocument();
  });

  it("explains an insufficient approval level and keeps approve disabled", async () => {
    persona("Rami Haddad"); // procurement officer, request needs a finance director
    renderPanel();
    await userEvent.type(screen.getByLabelText("Your reasoning"), "Checked everything carefully");
    expect(screen.getByText(/needs the finance director or higher/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /approve request/i })).toBeDisabled();
    await userEvent.click(screen.getByRole("radio", { name: /reject/i }));
    expect(screen.getByRole("button", { name: /reject request/i })).toBeEnabled(); // rejecting needs no level
  });

  it("requires reasoning before anything can be submitted", async () => {
    persona("Dina Samir");
    renderPanel();
    expect(screen.getByRole("button", { name: /approve request/i })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Your reasoning"), "short");
    expect(screen.getByText(/at least 10 characters/i, { selector: "li" })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Your reasoning"), " but now it is long enough");
    expect(screen.getByRole("button", { name: /approve request/i })).toBeEnabled();
  });

  it("makes approving over a confirmed violation depend on a documented override", async () => {
    persona("Dina Samir");
    renderPanel({ assessment: assessment([finding("f1", "confirmed_violation")]) });
    await userEvent.type(screen.getByLabelText("Your reasoning"), "Reviewed with the supplier by phone");
    const approve = screen.getByRole("button", { name: /approve request/i });
    expect(approve).toBeDisabled();
    expect(screen.getByText(/mark each one “disagree” and explain why/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Verdict on Finding f1"), "disagree");
    expect(approve).toBeDisabled(); // a verdict alone is not enough
    await userEvent.type(screen.getByLabelText("Why you disagree with Finding f1"), "Supplier corrected the quote");
    expect(approve).toBeEnabled();
    await userEvent.selectOptions(screen.getByLabelText("Verdict on Finding f1"), "agree");
    expect(approve).toBeDisabled(); // agreeing with a violation and approving contradicts itself
  });

  it("refuses to decide against anything but the latest assessment", async () => {
    persona("Dina Samir");
    renderPanel({ latestId: "a2" });
    await userEvent.type(screen.getByLabelText("Your reasoning"), "Reviewed the older version only");
    expect(screen.getByText(/Switch to the latest assessment version/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /approve request/i })).toBeDisabled();
  });

  it("shows the final record, with a note when it went against the AI, and no form", () => {
    persona("Dina Samir");
    const decision: Decision = {
      id: "d1", action: "approve", reasoning: "Approved after a call with the supplier", created_at: "2026-11-14T10:00:00Z",
      reviewer: { name: "Dina Samir", role: "reviewer" }, ai_recommendation_at_decision: { version: 1, status: "issues_found", risk: "high", is_mock: true },
      went_against_ai_signal: true, finding_reviews: [{ finding_id: "f1", title: "Finding f1", category: "confirmed_violation", verdict: "disagree", note: "Fixed" }],
    };
    renderPanel({ request: request({ status: "approved" }), lastDecision: decision });
    expect(screen.getByText("Approved")).toBeInTheDocument();
    expect(screen.getByText(/went against what the AI assessment found/)).toBeInTheDocument();
    expect(screen.getByText(/cannot be edited/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Your reasoning")).not.toBeInTheDocument();
  });

  it("lets anyone answer an open information request", async () => {
    persona("Layla Hassan");
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ resolved_requests: 1 }), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    renderPanel({ request: request({ status: "info_requested" }), openInfo: { message: "Please attach two more quotations", created_at: "2026-11-14T10:00:00Z" } });
    expect(screen.getByText("Please attach two more quotations")).toBeInTheDocument();
    const send = screen.getByRole("button", { name: "Send reply" });
    expect(send).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Reply to the reviewer"), "Two quotations attached");
    await userEvent.click(send);
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(String(fetchMock.mock.calls[0][0])).toContain("/requests/r1/info-response");
    vi.unstubAllGlobals();
  });
});
