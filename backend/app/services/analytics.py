"""Analytics computed live from the database tables: no stored or hand-written numbers.

Every metric carries its sample size and is defined in `DEFINITIONS`, so a chart can never imply more than
the data supports. Assessments made by the MOCK provider are broken out (and can be excluded) because they
say nothing about real AI behaviour.
"""
import statistics
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

DEFINITIONS = {
    "scope": "Requests whose submitted_at falls in [since, until]; assessments, decisions and findings are those of these requests.",
    "latest_assessment": "For status and risk distributions only the newest assessment version of each request is counted.",
    "processing_time": "Hours from the request's creation (audit log entry request.created) to its first approve/reject decision, "
                       "so documents carrying older business dates do not distort it.",
    "ai_agreement": "Among final decisions (approve/reject) with a clear AI signal: agreed = approve when the AI found no issues or "
                    "reject when it found issues. The AI never recommends approval; 'no issues found' is only the absence of findings.",
    "finding_review_agreement": "Share of reviewer verdicts on individual findings that are 'agree'.",
    "vendor_spread": "(highest - lowest) / lowest quotation total among quotations on one request in the request's currency; "
                     "needs two or more. No exchange rates are used.",
    "chosen_vs_lowest": "Requests where a quotation from the requested supplier exists: was it the lowest, and by how much was it "
                        "above the lowest when not?",
}

_REQS = ("reqs as (select * from purchase_requests where (cast(:since as timestamptz) is null or submitted_at >= cast(:since as timestamptz)) "
         "and (cast(:until as timestamptz) is null or submitted_at < cast(:until as timestamptz)))")
_ASSESS = "assess as (select a.* from assessments a join reqs r on r.id = a.request_id where (not :xm or not a.is_mock))"
_LATEST = "latest as (select distinct on (request_id) * from assess order by request_id, version desc)"


def _f(x):
    if x is None:
        return None
    return float(x) if isinstance(x, Decimal) else x


def _rows(session: Session, ctes: list[str], select_sql: str, params: dict) -> list[dict]:
    sql = ("with " + ", ".join(ctes) + " " if ctes else "") + select_sql
    return [{k: _f(v) for k, v in row.items()} for row in session.execute(text(sql), params).mappings().all()]


def overview(session: Session, *, since: date | None = None, until: date | None = None, exclude_mock: bool = False) -> dict:
    params = {
        "since": datetime.combine(since, datetime.min.time(), tzinfo=UTC) if since else None,
        "until": datetime.combine(until + timedelta(days=1), datetime.min.time(), tzinfo=UTC) if until else None,
        "xm": exclude_mock,
    }

    def q(ctes, sql):
        return _rows(session, ctes, sql, params)

    by_status = {r["status"]: r["n"] for r in q([_REQS], "select status, count(*) n from reqs group by status")}
    weekly = q([_REQS], "select to_char(date_trunc('week', submitted_at), 'YYYY-MM-DD') week, count(*) n from reqs group by 1 order by 1")

    providers = q([_REQS, _ASSESS], """
        select coalesce(provider, 'rules-only') provider, coalesce(model, '-') model, is_mock, count(*) n,
               avg(latency_ms) avg_ms, percentile_cont(0.5) within group (order by latency_ms) p50_ms,
               percentile_cont(0.95) within group (order by latency_ms) p95_ms,
               sum(input_tokens) input_tokens, sum(output_tokens) output_tokens, sum(est_cost_usd) est_cost_usd
        from assess group by 1, 2, 3 order by n desc""")
    status_mix = {r["compliance_status"]: r["n"] for r in q([_REQS, _ASSESS, _LATEST],
                  "select compliance_status, count(*) n from latest group by 1")}
    risk = {r["overall_risk"]: r["n"] for r in q([_REQS, _ASSESS, _LATEST], "select overall_risk, count(*) n from latest group by 1")}
    n_latest = sum(status_mix.values())

    cats = q([_REQS, _ASSESS, _LATEST], "select f.category, f.source, count(*) n from findings f join latest l on l.id = f.assessment_id group by 1, 2")
    top_rules = q([_REQS, _ASSESS, _LATEST], """
        select f.rule_code, f.category, count(*) n, max(f.title) example_title
        from findings f join latest l on l.id = f.assessment_id
        where f.category <> 'compliant' group by 1, 2 order by n desc, f.rule_code limit 15""")
    llm_calls = q([_REQS, _ASSESS], """
        select c.status, count(*) n, sum(c.input_tokens) input_tokens, sum(c.output_tokens) output_tokens, sum(c.retries) retries
        from llm_calls c join assess a on a.id = c.assessment_id group by 1""")

    decisions = {r["action"]: r["n"] for r in q([_REQS], "select d.action, count(*) n from decisions d join reqs r on r.id = d.request_id group by 1")}
    timing_sql = """
        select count(*) n, avg(h) avg_hours, percentile_cont(0.5) within group (order by h) median_hours,
               percentile_cont(0.9) within group (order by h) p90_hours
        from (select extract(epoch from (f.ts - s.ts)) / 3600 as h from {finish} f join started s using (request_id)) t"""
    started = "started as (select r.id request_id, min(al.ts) ts from reqs r join audit_log al on al.entity_type = 'request' and al.entity_id = r.id::text and al.action = 'request.created' group by r.id)"
    first_final = "first_final as (select d.request_id, min(d.created_at) ts from decisions d join reqs r on r.id = d.request_id where d.action in ('approve', 'reject') group by 1)"
    first_assess = "first_assess as (select request_id, min(created_at) ts from assess group by 1)"
    to_decision = q([_REQS, started, first_final], timing_sql.format(finish="first_final"))[0]
    to_assessment = q([_REQS, _ASSESS, started, first_assess], timing_sql.format(finish="first_assess"))[0]

    agreement = {r["bucket"]: r["n"] for r in q([_REQS], """
        , d as (select d.* from decisions d join reqs r on r.id = d.request_id where d.action in ('approve', 'reject'))
        select case when d.action = 'approve' and a.compliance_status = 'no_issues_found' then 'agreed_with_ai'
                    when d.action = 'reject' and a.compliance_status = 'issues_found' then 'agreed_with_ai'
                    when d.action = 'approve' and a.compliance_status = 'issues_found' then 'approved_despite_ai_issues'
                    when d.action = 'reject' and a.compliance_status = 'no_issues_found' then 'rejected_despite_clean_ai'
                    else 'no_clear_ai_signal' end bucket, count(*) n
        from d left join assessments a on a.id = d.assessment_id
        where (not :xm or a.id is null or not a.is_mock) group by 1""")}
    reviews = q([_REQS], """
        select fr.verdict, f.category, count(*) n from finding_reviews fr join decisions d on d.id = fr.decision_id
        join reqs r on r.id = d.request_id join findings f on f.id = fr.finding_id group by 1, 2""")

    queue = q([_REQS], """
        select (select count(*) from reqs where status in ('submitted', 'assessed')) awaiting_decision,
               (select count(*) from reqs r where r.status = 'submitted' and not exists (select 1 from assessments a where a.request_id = r.id)) awaiting_assessment,
               (select count(*) from reqs where status = 'info_requested') awaiting_requester""")[0]

    clear = sum(agreement.get(k, 0) for k in ("agreed_with_ai", "approved_despite_ai_issues", "rejected_despite_clean_ai"))
    verdicts = Counter()
    for r in reviews:
        verdicts[r["verdict"]] += r["n"]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "filters": {"since": since.isoformat() if since else None, "until": until.isoformat() if until else None, "exclude_mock": exclude_mock},
        "basis": "Computed live from the database. In the demo this is synthetic data; mock-provider assessments are listed separately.",
        "requests": {"total": sum(by_status.values()), "by_status": by_status, "submitted_per_week": weekly,
                     "queue": queue},
        "assessments": {
            "by_provider": providers, "total": sum(p["n"] for p in providers), "requests_with_assessment": n_latest,
            "latest_status_mix": status_mix, "latest_risk_distribution": risk,
            "latency_ms": {"note": "per provider in by_provider; free-tier rate-limit waits inflate real-provider latency"},
            "llm_calls": llm_calls,
        },
        "findings": {"by_category_and_source": cats, "top_rules": top_rules},
        "decisions": {
            "total": sum(decisions.values()), "by_action": decisions,
            "hours_to_first_assessment": to_assessment, "hours_to_first_decision": to_decision,
            "ai_agreement": {"buckets": agreement, "decisions_with_clear_signal": clear,
                             "agreement_rate": round(agreement.get("agreed_with_ai", 0) / clear, 4) if clear else None},
            "finding_reviews": {"total": sum(verdicts.values()), "by_verdict": dict(verdicts),
                                "agree_rate": round(verdicts["agree"] / sum(verdicts.values()), 4) if verdicts else None},
        },
        "vendors": _vendor_insights(session, params),
        "definitions": DEFINITIONS,
    }


def _vendor_insights(session: Session, params: dict) -> dict:
    counts = _rows(session, [], """
        select count(*) vendors, count(*) filter (where tax_id is null) without_tax_id,
               count(*) filter (where contact_json ? 'conflicts' and jsonb_array_length(contact_json->'conflicts') > 0) with_conflicts,
               count(*) filter (where contact_json ? 'alias_review') with_alias_review,
               (select count(*) from quotations) quotations from vendors""", params)[0]
    rows = _rows(session, [_REQS], """
        select q.request_id, q.vendor_id, q.currency, q.total, coalesce(v.canonical_name, 'unknown vendor') vendor, r.supplier_id, r.currency request_currency
        from quotations q join reqs r on r.id = q.request_id left join vendors v on v.id = q.vendor_id where q.total is not null""", params)
    by_req: dict = {}
    for r in rows:
        if r["currency"] == r["request_currency"]:
            by_req.setdefault(r["request_id"], []).append(r)
    spreads, wins, bids, premiums, chosen_n, chosen_lowest = [], Counter(), Counter(), [], 0, 0
    for quotes in by_req.values():
        if len(quotes) < 2:
            continue
        lo = min(quotes, key=lambda x: x["total"])
        hi = max(quotes, key=lambda x: x["total"])
        if lo["total"] > 0:
            spreads.append((hi["total"] - lo["total"]) / lo["total"])
        for qt in quotes:
            bids[qt["vendor"]] += 1
        wins[lo["vendor"]] += 1
        chosen = next((x for x in quotes if x["vendor_id"] and x["vendor_id"] == x["supplier_id"]), None)
        if chosen is not None:
            chosen_n += 1
            if chosen["total"] <= lo["total"]:
                chosen_lowest += 1
            elif lo["total"] > 0:
                premiums.append((chosen["total"] - lo["total"]) / lo["total"])
    return {
        **counts,
        "quotation_comparison": {
            "requests_compared": len(spreads),
            "avg_spread_pct": round(statistics.mean(spreads) * 100, 1) if spreads else None,
            "median_spread_pct": round(statistics.median(spreads) * 100, 1) if spreads else None,
            "requests_with_spread_over_25pct": sum(s > 0.25 for s in spreads),
            "lowest_bidder_wins": [{"vendor": v, "wins": wins[v], "bids": bids[v]} for v in sorted(bids, key=lambda x: (-wins[x], x))],
            "chosen_vs_lowest": {"requests_with_chosen_quote": chosen_n, "chosen_was_lowest": chosen_lowest,
                                 "avg_premium_pct_when_not_lowest": round(statistics.mean(premiums) * 100, 1) if premiums else None},
        },
    }
