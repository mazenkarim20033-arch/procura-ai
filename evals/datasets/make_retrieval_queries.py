"""Builds retrieval_queries.json: hand-written queries with gold relevant clauses.

Labels are written from the policy text in data/synthetic/policies.py BEFORE any retrieval system is run
against them. Clause refs look like "P2-1.3" = policy PRC-002, clause 1.3. Queries are written as
paraphrases/scenarios (not copies of clause wording) so lexical overlap alone does not trivially win.
Negatives have no relevant clause: the relevance gate should reject them.

    python evals/datasets/make_retrieval_queries.py
"""
import json
from pathlib import Path

# (clause_ref, paraphrased question, scenario-style query)
PER_CLAUSE = [
    ("P1-1.1", "Which purchases does the purchasing authority policy cover?", "Does the rule apply to a service contract bought for the warehouse team?"),
    ("P1-1.2", "Can we place an order before approval is given?", "The supplier asked for a signed purchase order today but nobody has signed off yet."),
    ("P1-1.3", "How are foreign currency amounts compared with the limits?", "A quote is in euros and I need to know which exchange rate decides the approval band."),
    ("P1-2.1", "Who signs off small purchases?", "I want to buy a USD 800 printer for my department, who can approve it?"),
    ("P1-2.2", "Which approver handles mid-sized spend?", "A USD 7,500 monitor order needs whose approval?"),
    ("P1-2.3", "Who has to approve spend of tens of thousands?", "We are about to commit USD 32,000 on network equipment, who approves?"),
    ("P1-2.4", "Which executive must approve very large purchases?", "A USD 80,000 renovation order needs approval from whom?"),
    ("P1-3.1", "Can an employee approve their own request?", "I raised the request and I am also the department manager, can I approve it myself?"),
    ("P1-3.2", "Do approvers have to explain their decisions?", "A reviewer rejected a request without comments, is that acceptable?"),
    ("P2-1.1", "Do tiny purchases need competing quotes?", "Ordering USD 600 of stationery, do I need to collect quotations?"),
    ("P2-1.2", "How many quotes for a purchase between one and five thousand dollars?", "A USD 3,200 chair order, how many written quotes are needed?"),
    ("P2-1.3", "How many suppliers must quote for mid-range purchases?", "Buying 20 laptops for USD 22,000, how many quotations do we need?"),
    ("P2-1.4", "When is a formal tender required?", "A USD 40,000 consulting engagement, can we just request quotes?"),
    ("P2-2.1", "How long must a supplier quote stay valid?", "The quotation expires 14 days after the request date, is that long enough?"),
    ("P2-2.2", "What information must a quotation contain?", "A vendor sent a quote without a quotation number and no currency, is it acceptable?"),
    ("P2-2.3", "What happens if a quote has calculation mistakes?", "The subtotal on the supplier offer does not add up to the line prices."),
    ("P2-3.1", "When can we buy from only one supplier?", "Only one vendor offers this proprietary part, what do we need to file?"),
    ("P2-3.2", "Are urgent purchases exempt from competitive quotes?", "The server room is flooding and we need pumps today, do we still need quotations?"),
    ("P3-1.1", "Do large orders have to go to pre-approved vendors?", "A USD 9,000 order to a supplier that is not on our vendor list."),
    ("P3-1.2", "How does a vendor get onto the approved list?", "A new supplier wants to be registered, what do procurement officers check?"),
    ("P3-2.1", "Must staff declare ties to suppliers?", "My cousin owns the company we want to buy from, what should I do?"),
    ("P3-2.2", "Who may not be involved in choosing a supplier?", "An employee who hid a financial interest in a vendor sits on the selection panel."),
    ("P3-3.1", "How should the supplier be named in a request?", "The request lists the supplier as just Orion, is that enough?"),
    ("P3-3.2", "Must the vendor name on quotes and invoices match the request?", "The invoice is from a different company name than the one on the purchase request."),
    ("P4-1.1", "Who reviews IT equipment purchases?", "Marketing wants to buy tablets, does anyone need to review it first?"),
    ("P4-1.2", "Can staff choose any laptop model?", "A manager wants a gaming laptop that is not on the standard list."),
    ("P4-1.3", "When is a technical justification needed for hardware?", "One workstation costs USD 3,500, is extra paperwork required?"),
    ("P4-2.1", "Do software licences need security approval?", "We plan to buy a new design software licence, who checks it?"),
    ("P4-2.2", "Do expensive subscriptions need legal review?", "A SaaS subscription at USD 15,000 per year needs a contract check by whom?"),
    ("P4-2.3", "Who must hold the software licence?", "A developer wants to buy a licence in their own name and expense it."),
    ("P5-1.1", "When is legal review mandatory for contracts?", "A USD 25,000 maintenance agreement is ready to sign, is legal review needed?"),
    ("P5-1.2", "What must a contract state?", "The draft agreement has no end date or payment terms, is it complete?"),
    ("P5-2.1", "What is the shortest allowed payment period?", "A supplier wants payment within 15 days."),
    ("P5-2.2", "Can we agree very long payment terms?", "The vendor offers net 90 days, who needs to approve that?"),
    ("P5-2.3", "How much can we pay upfront?", "The supplier asks for 50% advance payment on a service contract."),
    ("P5-3.1", "What must consulting agreements define?", "A consultancy proposal lacks deliverables and sign-off steps."),
    ("P5-3.2", "Can work start before the contract is executed?", "The vendor wants to begin onsite work Monday but we have not signed yet."),
    ("P6-1.1", "Is it allowed to break one order into several smaller ones?", "Someone plans three USD 4,000 orders to stay under the approval limit."),
    ("P6-1.2", "How are repeat orders to one supplier treated?", "We bought USD 3,000 of furniture last week and want another USD 3,000 from the same vendor."),
    ("P6-2.1", "Is a business reason required on requests?", "A request has an empty justification field."),
    ("P6-2.2", "What justification applies to non-standard items?", "I need an item that is not in the catalog, what explanation should I include?"),
    ("P6-3.1", "What counts as an emergency purchase?", "Is replacing a broken printer that is slowing the team an emergency?"),
    ("P6-3.2", "How soon must emergency purchases be approved after the fact?", "We bought emergency generators yesterday, by when must approval be recorded?"),
    ("P6-3.3", "Do urgent purchases of large value still need quotes?", "An emergency USD 12,000 repair, should we still get two offers?"),
    ("P6-4.1", "How are repeated identical requests handled?", "Two open requests exist for the same laptops from the same vendor."),
]

MULTI = [
    ("Rules for emergency purchases and quotations", ["P2-3.2", "P6-3.1", "P6-3.2", "P6-3.3"]),
    ("What approvals and quotes does a USD 12,000 purchase need?", ["P1-2.3", "P2-1.3"]),
    ("Requirements for a USD 30,000 purchase from a new supplier", ["P1-2.3", "P2-1.4", "P3-1.1", "P3-1.2"]),
    ("What checks apply to a software subscription costing USD 12,000 a year?", ["P4-2.1", "P4-2.2", "P4-2.3", "P1-2.3"]),
    ("Contract with 60% upfront payment and 90 day terms", ["P5-2.1", "P5-2.2", "P5-2.3"]),
    ("Is splitting a USD 8,000 order to avoid quotes allowed?", ["P6-1.1", "P2-1.3"]),
]

NEGATIVES = [
    "What is the dress code in the office?", "How do I reset my email password?", "Cafeteria opening hours",
    "Annual leave entitlement for employees", "How are travel expenses reimbursed?",
    "What is the parking arrangement for visitors?", "Company holiday calendar for next year",
    "How do I request a new access badge?", "Salary review process", "What is the policy on remote work?",
    "Steps for onboarding a new hire", "Procedure to report a workplace injury",
]


def build() -> list[dict]:
    out, n = [], 0

    def add(query: str, relevant: list[str], qtype: str) -> None:
        nonlocal n
        n += 1
        out.append({"id": f"q{n:03d}", "query": query, "relevant": relevant, "type": qtype})

    for ref, question, scenario in PER_CLAUSE:
        add(question, [ref], "question")
        add(scenario, [ref], "scenario")
    for query, refs in MULTI:
        add(query, refs, "multi")
    for query in NEGATIVES:
        add(query, [], "negative")
    return out


if __name__ == "__main__":
    queries = build()
    path = Path(__file__).parent / "retrieval_queries.json"
    path.write_text(json.dumps(queries, indent=1), encoding="utf-8")
    print(f"wrote {len(queries)} queries to {path}")
