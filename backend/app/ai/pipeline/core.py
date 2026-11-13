"""Assessment pipeline core: rules -> retrieval + LLM reasoning -> verification -> aggregation.
Pure with respect to storage: callers persist the returned AssessmentResult."""
import time
from dataclasses import dataclass, field

from app.ai.guards.verifier import Rejected
from app.ai.pipeline.aggregate import aggregate
from app.ai.pipeline.context import AssessmentContext, PolicyCorpus
from app.ai.pipeline.llm_stage import run_llm_stage
from app.ai.providers.base import LLMProvider
from app.rules.policy_rules import RuleFinding, evaluate_rules


@dataclass
class AssessmentResult:
    overall_risk: str
    compliance_status: str
    confidence: float
    summary: str
    findings: list[RuleFinding]
    missing_info: list[dict]
    financial_risks: list[dict]
    next_steps: list[dict]
    counts: dict
    checks_run: list[str]
    llm_calls: list[dict] = field(default_factory=list)
    llm_rejected: list[Rejected] = field(default_factory=list)
    llm_notes: str | None = None
    clauses_shown_to_llm: list[str] = field(default_factory=list)
    prompt_versions: dict = field(default_factory=dict)
    provider: str | None = None
    model: str | None = None
    is_mock: bool = False
    latency_ms: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None


def assess(ctx: AssessmentContext, corpus: PolicyCorpus, provider: LLMProvider | None, *,
           min_similarity: float) -> AssessmentResult:
    start = time.perf_counter()
    findings, ran = evaluate_rules(ctx, corpus)
    stage = run_llm_stage(ctx, corpus, provider, min_similarity=min_similarity)
    findings = [*findings, *stage.findings]

    # Retrieval is "relevant" if the policy corpus returned clauses above the gate for this request.
    relevance_ok = bool(stage.clauses_shown) or stage.skipped_reason == "no LLM provider configured"
    agg = aggregate(findings, ran, ctx, llm_dropped=len(stage.rejected), relevance_ok=relevance_ok)

    tokens_in = [c["input_tokens"] for c in stage.calls if c.get("input_tokens") is not None]
    tokens_out = [c["output_tokens"] for c in stage.calls if c.get("output_tokens") is not None]
    return AssessmentResult(
        overall_risk=agg["overall_risk"], compliance_status=agg["compliance_status"], confidence=agg["confidence"],
        summary=agg["summary"], findings=findings, missing_info=agg["missing_info"],
        financial_risks=agg["financial_risks"], next_steps=agg["next_steps"], counts=agg["counts"],
        checks_run=sorted(ran), llm_calls=stage.calls, llm_rejected=stage.rejected, llm_notes=stage.skipped_reason,
        clauses_shown_to_llm=stage.clauses_shown,
        prompt_versions={stage.prompt.name: stage.prompt.label, "sha256": stage.prompt.sha256} if stage.prompt else {},
        provider=provider.name if provider else None, model=provider.model if provider else None,
        is_mock=bool(provider and provider.is_mock), latency_ms=int((time.perf_counter() - start) * 1000),
        input_tokens=sum(tokens_in) if tokens_in else None, output_tokens=sum(tokens_out) if tokens_out else None,
    )
