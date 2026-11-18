import { getIdentity } from "./identity";

export const API_URL: string = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000";

/** RFC 7807 problem+json errors from the backend, with the server's own explanation kept intact. */
export class ApiError extends Error {
  constructor(public status: number, public title: string, public detail: string, public extra?: unknown) {
    super(detail || title);
  }
}

function headers(json: boolean): HeadersInit {
  const id = getIdentity();
  const h: Record<string, string> = { "x-demo-role": id.role, "x-demo-user": id.user };
  if (id.authority) h["x-demo-authority"] = id.authority;
  if (json) h["content-type"] = "application/json";
  return h;
}

async function parse<T>(res: Response): Promise<T> {
  if (res.ok) return (res.status === 204 ? undefined : await res.json()) as T;
  let body: { title?: string; detail?: string } = {};
  try {
    body = await res.json();
  } catch {
    /* not JSON */
  }
  throw new ApiError(res.status, body.title ?? res.statusText, body.detail ?? `Request failed (${res.status})`, body);
}

function url(path: string, params?: Record<string, string | number | boolean | undefined | null>): string {
  const u = new URL(path, API_URL);
  Object.entries(params ?? {}).forEach(([k, v]) => v !== undefined && v !== null && v !== "" && u.searchParams.set(k, String(v)));
  return u.toString();
}

async function call<T>(input: string, init: RequestInit): Promise<T> {
  try {
    return await parse<T>(await fetch(input, init));
  } catch (e) {
    if (e instanceof ApiError) throw e;
    throw new ApiError(0, "unreachable", `Cannot reach the API at ${API_URL}. Is the backend running?`);
  }
}

export const api = {
  get: <T>(path: string, params?: Record<string, string | number | boolean | undefined | null>) =>
    call<T>(url(path, params), { headers: headers(false) }),
  post: <T>(path: string, body?: unknown) =>
    call<T>(url(path), { method: "POST", headers: headers(true), body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) => call<T>(url(path), { method: "PUT", headers: headers(true), body: JSON.stringify(body) }),
  upload: <T>(path: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return call<T>(url(path), { method: "POST", headers: headers(false), body: form });
  },
};

/* ------------------------------------------------------------------ types (the parts the UI reads) */
export interface RequestSummary {
  id: string; request_no: string; requester_name: string | null; department: string | null; supplier_name: string | null;
  currency: string | null; total_amount: string | null; status: string; submitted_at: string; is_synthetic: boolean;
}
export interface RequestItem { description: string; quantity: string; unit_cost: string | null; line_total: string | null }
export interface RequestDocument { id: string; filename: string; doc_type: string; role: string | null }
export interface RequestDetail extends RequestSummary { justification: string | null; category: string | null; items: RequestItem[]; documents: RequestDocument[] }

export interface Evidence { kind: string; chunk_id: string | null; quote: string | null; ref: Record<string, unknown> }
export interface Finding {
  id: string; category: string; source: "rule" | "llm"; rule_code: string | null; title: string; explanation: string;
  severity: string | null; confidence: number | null; evidence: Evidence[];
}
export interface NextStep { action: string; reason: string; clause_ref: string | null }
export interface Assessment {
  id: string; request_id: string; version: number; overall_risk: string; compliance_status: string; confidence: number | null;
  confidence_note: string; summary: string; is_mock: boolean; provider: string | null; model: string | null;
  prompt_versions: Record<string, string>; latency_ms: number | null; tokens: { input: number | null; output: number | null };
  est_cost_usd: number | null; created_at: string; financial_risks: { type: string; detail: string }[]; next_steps: NextStep[];
  missing_info: { rule_code: string; title: string; detail: string }[]; findings: Finding[]; decision_required: string;
}
export interface AssessmentListItem { id: string; version: number; overall_risk: string; compliance_status: string; is_mock: boolean; provider: string | null; created_at: string }

export interface IntakeIssue { code: string; kind: string; severity: string; field: string; message: string }
export interface Intake {
  request_no: string; generated_by: string;
  summary: { issues: number; errors: number; possible_duplicates: number; split_findings: number; quotations_attached: number };
  issues: IntakeIssue[];
  duplicates: { other_request_no: string; kind: string; score: number; days_apart: number; reasons: string[] }[];
  splits: { code: string; severity: string; message: string; threshold_usd: string; combined_total: string | null }[];
}

export interface ComparisonQuote {
  label: string; vendor: string; currency: string | null; total: string | null; subtotal: string | null; tax: string | null;
  delivery_days: number | null; payment_terms: string | null; net_days: number | null; advance_pct: string | null;
  validity_days_from_request: number | null; valid_until: string | null;
}
export interface Comparison {
  basis: string; currency?: string; quotes: ComparisonQuote[]; notes: string[];
  ranking: { rank: number; label: string; vendor: string; total?: string; subtotal?: string }[];
  item_rows: { description: string; median_unit_price?: number; cells: Record<string, { quantity: string | null; unit_price: string | null; description: string; ratio_to_median?: number }> }[];
  flags: { code: string; severity: string; message: string; vendor?: string; item?: string }[];
}

export interface HistoryEvent { ts: string; actor_type: string; actor: string | null; action: string; detail: Record<string, unknown> }
export interface Decision {
  id: string; action: string; reasoning: string; created_at: string; reviewer: { name: string; role: string } | null;
  ai_recommendation_at_decision: { version: number; status: string; risk: string; is_mock: boolean } | null;
  went_against_ai_signal: boolean;
  finding_reviews: { finding_id: string; title: string; category: string; verdict: string; note: string | null }[];
}
export interface History {
  status: string; note: string; timeline: HistoryEvent[]; ai_assessments: { id: string; version: number; status: string; risk: string; is_mock: boolean; created_at: string }[];
  decisions: Decision[]; information_requests: { id: string; message: string; created_at: string; resolved_at: string | null }[];
}
export interface QueueItem {
  id: string; request_no: string; requester: string | null; supplier: string | null; total: string | null; currency: string | null;
  status: string; age_days: number; has_open_info_request: boolean; needs_assessment: boolean;
  required_approval: { authority: string; clause: string } | null;
  latest_assessment: { id: string; version: number; risk: string; status: string; is_mock: boolean; findings: Record<string, number> } | null;
}

export interface PolicySummary { id: string; code: string; title: string; version: string; category: string | null; effective_from: string; effective_to: string | null; status: string; chunks: number; embedded_chunks: number }
export interface PolicyDetail extends PolicySummary { clauses: { id: string; section_path: string; text: string; page: number | null }[] }
export interface PolicySearch {
  query: string; mode: string; embedding_model: string; timings_ms: Record<string, number>;
  relevance: { relevant: boolean; best_similarity: number | null; reason: string; threshold: number };
  hits: { chunk_id: string; policy_code: string; section_path: string; text: string; dense_similarity: number | null; rrf_score: number }[];
}

export interface DocumentSummary {
  id: string; filename: string; doc_type: string; doc_type_confidence: number | null; language: string | null; status: string;
  page_count: number | null; ocr_used: boolean; is_synthetic: boolean; created_at: string;
}
export interface DocumentDetail extends DocumentSummary {
  pages: { page_no: number; text: string }[]; chunk_count: number;
  extraction: null | {
    schema: string; method: string; data: Record<string, unknown>;
    provenance: Record<string, { page: number; text: string }>; validation_issues: { field: string; code: string; message: string }[];
  };
}

export interface VendorSummary { id: string; name: string; country: string | null; tax_id: string | null; quotations: number; gaps: number }
export interface VendorDetail {
  id: string; name: string; aliases: string[]; tax_id: string | null; country: string | null; contact: Record<string, string>;
  gaps: { code: string; severity: string; message: string }[]; basis: string;
  quotations: { id: string; quote_no: string | null; issue_date: string | null; currency: string | null; total: string | null; payment_terms: string | null; request_id: string | null }[];
}

export interface AuditEntry { id: number; ts: string; actor_type: string; actor: string | null; action: string; entity_type: string; entity_id: string | null; payload: Record<string, unknown>; hash: string; prev_hash: string }
export interface AuditVerify { ok: boolean; entries_checked: number; first_bad_id: number | null; head_hash: string | null; verified_at: string; scope?: string }

export interface Health { status: string; read_only?: boolean; checks: { database: { ok: boolean }; pgvector: { ok: boolean }; embedding: { provider: string; model: string; loaded: boolean | null }; llm: { provider: string; mock: boolean } } }

type Counts = Record<string, number>;
export interface Overview {
  generated_at: string; basis: string; filters: { since: string | null; until: string | null; exclude_mock: boolean };
  requests: { total: number; by_status: Counts; submitted_per_week: { week: string; n: number }[]; queue: { awaiting_decision: number; awaiting_assessment: number; awaiting_requester: number } };
  assessments: {
    total: number; requests_with_assessment: number; latest_status_mix: Counts; latest_risk_distribution: Counts;
    by_provider: { provider: string; model: string; is_mock: boolean; n: number; avg_ms: number | null; p50_ms: number | null; p95_ms: number | null; input_tokens: number | null; output_tokens: number | null; est_cost_usd: number | null }[];
    llm_calls: { status: string; n: number; input_tokens: number | null; output_tokens: number | null; retries: number | null }[];
  };
  findings: { by_category_and_source: { category: string; source: string; n: number }[]; top_rules: { rule_code: string; category: string; n: number; example_title: string }[] };
  decisions: {
    total: number; by_action: Counts;
    hours_to_first_assessment: { n: number; avg_hours: number | null; median_hours: number | null; p90_hours: number | null };
    hours_to_first_decision: { n: number; avg_hours: number | null; median_hours: number | null; p90_hours: number | null };
    ai_agreement: { buckets: Counts; decisions_with_clear_signal: number; agreement_rate: number | null };
    finding_reviews: { total: number; by_verdict: Counts; agree_rate: number | null };
  };
  vendors: {
    vendors: number; without_tax_id: number; with_conflicts: number; with_alias_review: number; quotations: number;
    quotation_comparison: {
      requests_compared: number; avg_spread_pct: number | null; median_spread_pct: number | null; requests_with_spread_over_25pct: number;
      lowest_bidder_wins: { vendor: string; wins: number; bids: number }[];
      chosen_vs_lowest: { requests_with_chosen_quote: number; chosen_was_lowest: number; avg_premium_pct_when_not_lowest: number | null };
    };
  };
  definitions: Record<string, string>;
}
