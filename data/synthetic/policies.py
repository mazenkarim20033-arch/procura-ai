"""Synthetic procurement policies for the fictional company "Northwind Industrial Co.".

All content is invented for this demo. PRC-002 3.2 and PRC-006 3.3 deliberately disagree about
emergency purchases, and PRC-006 2.2 is deliberately vague: they exist to test how the system
handles conflicting or ambiguous policy text.
"""

COMPANY = "Northwind Industrial Co."

POLICIES = [
    {
        "code": "PRC-001", "title": "Purchasing Authority and Approvals", "version": "2.0",
        "effective_date": "2025-01-01", "category": "approvals",
        "sections": [
            ("Scope", [
                "This policy applies to all purchases of goods and services made on behalf of Northwind Industrial Co.",
                "Purchases must be approved before an order is placed with a supplier.",
                "All amounts in this policy are expressed in USD; purchases in other currencies are converted using the treasury rate on the request date.",
            ]),
            ("Approval Thresholds", [
                "Purchases up to USD 1,000 may be approved by the department manager.",
                "Purchases above USD 1,000 and up to USD 10,000 must be approved by a procurement officer.",
                "Purchases above USD 10,000 and up to USD 50,000 must be approved by the finance director.",
                "Purchases above USD 50,000 must be approved by the chief financial officer.",
            ]),
            ("Segregation of Duties", [
                "The requester of a purchase must not approve the same purchase.",
                "Approvers must record written reasoning for every approval or rejection.",
            ]),
        ],
    },
    {
        "code": "PRC-002", "title": "Competitive Quotations", "version": "2.1",
        "effective_date": "2025-01-01", "category": "quotations",
        "sections": [
            ("Quotation Requirements", [
                "Purchases up to USD 1,000 do not require a competitive quotation.",
                "Purchases above USD 1,000 and up to USD 5,000 require at least one written quotation.",
                "Purchases above USD 5,000 and up to USD 25,000 require at least three written quotations from different suppliers.",
                "Purchases above USD 25,000 must be run as a formal tender.",
            ]),
            ("Quotation Validity and Content", [
                "Quotations must remain valid for at least 30 days from the date of the purchase request.",
                "Quotations must show the supplier name, a quotation number, itemised prices and the currency.",
                "Quotations that contain arithmetic errors must be corrected by the supplier before they can be used.",
            ]),
            ("Exceptions", [
                "A single-source purchase above USD 1,000 requires a written sole-source justification approved by the procurement officer.",
                "Emergency purchases are exempt from the quotation requirements in section 1.",
            ]),
        ],
    },
    {
        "code": "PRC-003", "title": "Approved Suppliers and Conflicts of Interest", "version": "1.4",
        "effective_date": "2024-07-01", "category": "suppliers",
        "sections": [
            ("Approved Supplier List", [
                "Purchases above USD 5,000 must be placed with a supplier on the approved supplier list.",
                "A supplier may be added to the approved supplier list only after the procurement officer has reviewed its registration documents and tax identification.",
            ]),
            ("Conflicts of Interest", [
                "Employees must disclose any personal or financial relationship with a proposed supplier.",
                "An employee with an undisclosed relationship to a supplier must not take part in selecting that supplier.",
            ]),
            ("Supplier Information", [
                "Every purchase request must identify the proposed supplier by its full legal name.",
                "Supplier names in quotations and invoices must match the supplier named in the purchase request.",
            ]),
        ],
    },
    {
        "code": "PRC-004", "title": "IT Hardware and Software", "version": "1.2",
        "effective_date": "2025-03-01", "category": "it",
        "sections": [
            ("Hardware", [
                "All IT hardware purchases must be reviewed by the IT department before approval.",
                "Laptops must be selected from the standard configuration catalog unless the IT department approves an exception in writing.",
                "Any single IT hardware item priced above USD 2,000 requires a written technical justification.",
            ]),
            ("Software", [
                "Software licences must be reviewed by the information security team before purchase.",
                "Subscription software with an annual cost above USD 10,000 requires a contract reviewed by legal.",
                "Software must be licensed to the company, not to an individual employee.",
            ]),
        ],
    },
    {
        "code": "PRC-005", "title": "Services and Contracts", "version": "1.1",
        "effective_date": "2025-01-01", "category": "contracts",
        "sections": [
            ("Contract Review", [
                "Contracts with a total value above USD 10,000 require legal review before signature.",
                "Contracts must state the effective date, the end date, the total value and the payment terms.",
            ]),
            ("Payment Terms", [
                "Payment terms must be at least net 30 days.",
                "Payment terms longer than net 60 days require finance director approval.",
                "Advance payments must not exceed 30 percent of the contract value.",
            ]),
            ("Services", [
                "Consulting engagements must define deliverables and an acceptance procedure.",
                "Services must not begin before the contract is signed by both parties.",
            ]),
        ],
    },
    {
        "code": "PRC-006", "title": "Purchase Integrity and Special Cases", "version": "1.0",
        "effective_date": "2025-06-01", "category": "integrity",
        "sections": [
            ("Split Purchases", [
                "Purchases must not be split into smaller orders to avoid an approval threshold or quotation requirement.",
                "Purchases from the same supplier in the same category within 30 days are combined when determining the approval level.",
            ]),
            ("Justification", [
                "Every purchase request must include a business justification.",
                "Purchases of items outside the standard catalog must be accompanied by a reasonable justification.",
            ]),
            ("Emergency Purchases", [
                "An emergency purchase is one needed to prevent immediate harm to people, property or operations.",
                "Emergency purchases require retrospective approval within 3 business days.",
                "Emergency purchases above USD 5,000 still require at least two written quotations where feasible.",
            ]),
            ("Duplicate Requests", [
                "Requests that duplicate an open request for the same items and supplier must be rejected or merged.",
            ]),
        ],
    },
]
