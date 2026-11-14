"""Rule-based field extraction with source tracking.

Works on documents laid out as "Label: value" header lines plus one-line item rows - the layouts
produced by the synthetic generator and common in simple business PDFs. It is NOT a general
layout-aware parser; anything it cannot read is left out and surfaces as a missing_field issue.
Returned values are strings/ISO dates so the strict Pydantic models do the real validation.
"""
import re
from dataclasses import dataclass
from datetime import date, datetime

from app.documents.parse import ParsedDocument

CURRENCIES = ("USD", "EUR", "EGP", "GBP", "SAR", "AED")
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d %B %Y", "%B %d, %Y", "%d %b %Y", "%b %d, %Y")


@dataclass
class Line:
    page: int
    text: str
    start: int
    end: int


def iter_lines(doc: ParsedDocument) -> list[Line]:
    lines: list[Line] = []
    for page in doc.pages:
        pos = 0
        for raw in page.text.split("\n"):
            lines.append(Line(page.page_no, raw, pos, pos + len(raw)))
            pos += len(raw) + 1
    return lines


def parse_date(value: str) -> str | None:
    value = value.strip().rstrip(".")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_number(value: str) -> str | None:
    cleaned = re.sub(r"[^\d.,-]", "", value)
    if not cleaned or not re.search(r"\d", cleaned):
        return None
    return cleaned.replace(",", "")


class Extractor:
    def __init__(self, doc: ParsedDocument):
        self.doc = doc
        self.lines = iter_lines(doc)
        self.raw: dict = {}
        self.provenance: dict[str, dict] = {}

    # -- primitives ---------------------------------------------------------------
    def _record(self, name: str, line: Line) -> None:
        self.provenance[name] = {
            "page": line.page, "start": line.start, "end": line.end, "text": line.text.strip()[:200],
        }

    def text_field(self, name: str, labels: list[str]) -> str | None:
        pattern = re.compile(rf"^\s*(?:{'|'.join(labels)})\s*[:\-]\s*(.+?)\s*$", re.IGNORECASE)
        for line in self.lines:
            m = pattern.match(line.text)
            if m and m.group(1):
                self.raw[name] = m.group(1)
                self._record(name, line)
                return m.group(1)
        return None

    def date_field(self, name: str, labels: list[str]) -> None:
        pattern = re.compile(rf"^\s*(?:{'|'.join(labels)})\s*[:\-]\s*(.+?)\s*$", re.IGNORECASE)
        for line in self.lines:
            m = pattern.match(line.text)
            if m:
                parsed = parse_date(m.group(1))
                self.raw[name] = parsed if parsed else m.group(1)  # unparseable -> model rejects it
                self._record(name, line)
                return

    def money_field(self, name: str, label: str) -> None:
        pattern = re.compile(
            rf"^\s*(?:{label})(?:\s*\([^)]*\))?\s*[:\s]\s*(?:[A-Z]{{3}}\s*)?([\d.,]+)\s*(?:[A-Z]{{3}})?\s*$", re.IGNORECASE
        )
        for line in self.lines:
            m = pattern.match(line.text)
            if m:
                num = parse_number(m.group(1))
                if num is not None:
                    self.raw[name] = num
                    self._record(name, line)
                    return

    def currency(self) -> None:
        if self.text_field("currency", ["Currency"]):
            self.raw["currency"] = self.raw["currency"].strip().upper()[:3]
            return
        counts = {c: len(re.findall(rf"\b{c}\b", self.doc.text)) for c in CURRENCIES}
        best = max(counts, key=counts.get)
        if counts[best]:
            self.raw["currency"] = best

    def items(self) -> None:
        row_a = re.compile(
            r"^\s*(?P<desc>\S.*?)\s{2,}(?P<qty>[\d.,]+)\s+(?P<unit>[\d.,]+)\s+(?P<total>[\d.,]+)\s*$"
        )
        row_b = re.compile(
            r"^\s*(?:\d+\.\s*)?(?P<qty>[\d.,]+)\s*x\s+(?P<desc>.+?)\s*@\s*(?:[A-Z]{3}\s*)?(?P<unit>[\d.,]+)"
            r"\s*=\s*(?:[A-Z]{3}\s*)?(?P<total>[\d.,]+)\s*$"
        )
        out = []
        for line in self.lines:
            m = row_b.match(line.text) or row_a.match(line.text)
            if not m:
                continue
            qty, unit, total = (parse_number(m.group(k)) for k in ("qty", "unit", "total"))
            if None in (qty, unit, total):
                continue
            self._record(f"items.{len(out)}", line)
            out.append({
                "description": m.group("desc").strip(), "quantity": qty,
                "unit_price": unit, "line_total": total,
            })
        if out:
            self.raw["items"] = out

    def terms(self) -> None:
        self.text_field("payment_terms", ["Payment Terms"])


def _delivery_days(ex: Extractor) -> None:
    text = ex.text_field("delivery_days", ["Delivery(?: Time)?", "Lead Time"])
    if text:
        m = re.search(r"\d+", text)
        ex.raw["delivery_days"] = int(m.group()) if m else text


def _vendor_profile(ex: Extractor) -> None:
    """Optional identification fields printed next to the vendor name (None when the document omits them)."""
    ex.text_field("vendor_tax_id", ["Vendor Tax ID", "Tax ID", r"VAT No\.?", "VAT Number", r"Tax Registration(?: No\.?)?"])
    ex.text_field("vendor_address", ["Vendor Address", "Address"])
    ex.text_field("vendor_email", ["Vendor Email", "Email"])
    ex.text_field("vendor_phone", ["Vendor Phone", "Vendor Tel", "Phone", "Tel"])
    ex.text_field("vendor_country", ["Vendor Country", "Country"])


def extract_quotation(doc: ParsedDocument) -> Extractor:
    ex = Extractor(doc)
    ex.text_field("vendor_name", ["Vendor", "Supplier", "From", "Issued by"])
    _vendor_profile(ex)
    ex.text_field("quote_no", ["Quotation No\\.?", "Quote No\\.?", "Offer Ref", "Reference"])
    ex.date_field("issue_date", ["Date", "Issue Date", "Quotation Date", "Issued"])
    ex.date_field("valid_until", ["Valid Until", "Valid Through", "Expires"])
    ex.currency()
    ex.items()
    ex.money_field("subtotal", "Subtotal|Sub-total|Net Total")
    ex.money_field("tax", "Tax|VAT")
    ex.money_field("total", "Grand Total|Total Price|Total Amount|Total")
    ex.terms()
    _delivery_days(ex)
    return ex


def extract_invoice(doc: ParsedDocument) -> Extractor:
    ex = Extractor(doc)
    ex.text_field("vendor_name", ["Vendor", "Supplier", "From", "Issued by"])
    _vendor_profile(ex)
    ex.text_field("invoice_no", ["Invoice No\\.?", "Invoice Number", "Invoice #"])
    ex.date_field("invoice_date", ["Invoice Date", "Date", "Issued"])
    ex.date_field("due_date", ["Due Date", "Payment Due"])
    ex.text_field("po_reference", ["PO Reference", "PO Number", "Purchase Order"])
    ex.currency()
    ex.items()
    ex.money_field("subtotal", "Subtotal|Sub-total|Net Total")
    ex.money_field("tax", "Tax|VAT")
    ex.money_field("total", "Total Due|Amount Due|Grand Total|Total")
    return ex


def extract_purchase_request(doc: ParsedDocument) -> Extractor:
    ex = Extractor(doc)
    ex.text_field("request_no", ["Request No\\.?", "Request Number", "PR No\\.?"])
    ex.text_field("requester", ["Requester", "Requested By"])
    ex.text_field("department", ["Department"])
    ex.date_field("request_date", ["Request Date", "Date", "Submitted"])
    ex.text_field("supplier", ["Supplier", "Proposed Supplier", "Vendor"])
    ex.text_field("justification", ["Justification", "Business Justification", "Reason"])
    ex.currency()
    ex.items()
    ex.money_field("total", "Total Estimated Cost|Estimated Total|Grand Total|Total")
    return ex


def extract_contract(doc: ParsedDocument) -> Extractor:
    ex = Extractor(doc)
    ex.text_field("contract_no", ["Contract No\\.?", "Agreement No\\.?"])
    ex.text_field("vendor_name", ["Vendor", "Supplier", "Contractor"])
    _vendor_profile(ex)
    ex.date_field("effective_date", ["Effective Date", "Start Date"])
    ex.date_field("end_date", ["End Date", "Expiry Date"])
    ex.currency()
    ex.money_field("total_value", "Contract Value|Total Value")
    ex.terms()
    return ex


def extract_policy_header(doc: ParsedDocument) -> Extractor:
    ex = Extractor(doc)
    ex.text_field("code", ["Policy Code"])
    ex.text_field("title", ["Title", "Policy Title"])
    ex.text_field("version", ["Version"])
    ex.date_field("effective_date", ["Effective Date"])
    ex.text_field("category", ["Category"])
    return ex


EXTRACTORS = {
    "quotation": extract_quotation,
    "invoice": extract_invoice,
    "purchase_request": extract_purchase_request,
    "contract": extract_contract,
    "policy": extract_policy_header,
}


def effective_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None
