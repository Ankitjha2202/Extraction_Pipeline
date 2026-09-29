"""Human-review flagging for extracted fields and documents."""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Optional

from src.bbox import MatchResult
from src.models import (
    HEADER_FIELDS,
    LINE_ITEM_FIELDS,
    MANDATORY_FIELDS,
    DocumentResult,
    FieldValue,
    InvoiceFields,
    LineItem,
)


def _confidence_threshold() -> float:
    return float(os.getenv("CONFIDENCE_THRESHOLD", "0.75"))


def _match_threshold() -> float:
    return float(os.getenv("MATCH_SCORE_THRESHOLD", "70"))


DATE_PATTERNS = (
    r"\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2}",
    r"\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4}",
    r"\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4}",
    r"[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{2,4}",
)

CURRENCY_RE = re.compile(
    r"^(USD|EUR|GBP|JPY|CNY|HKD|SGD|VND|PHP|INR|AUD|CAD|CHF|NZD|KRW|THB|MYR|IDR|"
    r"\$|€|£|¥|₱|₫|R\$|Rp)$",
    re.I,
)


def _looks_like_date(value: str) -> bool:
    for pat in DATE_PATTERNS:
        if re.search(pat, value, flags=re.I):
            return True
    if re.search(r"\d{1,2}(?:st|nd|rd|th)\s+[A-Za-z]{3,12}", value, flags=re.I):
        return True
    if re.search(r"(?:19|20)\d{2}", value):
        return True
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            datetime.strptime(value.strip(), fmt)
            return True
        except ValueError:
            continue
    return False


def build_field_value(
    raw: Optional[str],
    match: MatchResult,
    field_name: str,
    *,
    mandatory: bool = False,
) -> FieldValue:
    reasons: list[str] = []
    value = None if raw is None else str(raw).strip()
    if value == "":
        value = None

    conf_thr = _confidence_threshold()
    match_thr = _match_threshold()

    if value is None:
        # Absent optional fields are normal; only mandatory gaps need review.
        if mandatory:
            reasons.append("FIELD_MISSING")
    else:
        if match.bbox is None or match.match_score < match_thr:
            reasons.append("LOW_CONFIDENCE")
        if match.confidence is not None and match.confidence < conf_thr:
            if "LOW_CONFIDENCE" not in reasons:
                reasons.append("LOW_CONFIDENCE")

        # Field-specific sanity checks
        if field_name in ("invoiceDate", "dueDate") and not _looks_like_date(value):
            if "LOW_CONFIDENCE" not in reasons:
                reasons.append("LOW_CONFIDENCE")
        if field_name in (
            "subtotal",
            "taxAmount",
            "totalAmount",
            "amountDue",
            "quantity",
            "unitPrice",
            "taxRate",
            "lineAmount",
        ):
            if not re.search(r"\d", value):
                if "LOW_CONFIDENCE" not in reasons:
                    reasons.append("LOW_CONFIDENCE")
        if field_name == "currency":
            stripped = value.strip()
            known_names = {
                "DOLLAR",
                "DOLLARS",
                "EURO",
                "EUROS",
                "PESO",
                "PESOS",
                "DONG",
                "YUAN",
                "RUPIAH",
            }
            if not CURRENCY_RE.match(stripped) and stripped.upper() not in known_names:
                if len(stripped) > 4:
                    if "LOW_CONFIDENCE" not in reasons:
                        reasons.append("LOW_CONFIDENCE")

    return FieldValue(
        value=value,
        bbox=match.bbox,
        isHumanReviewRequired=bool(reasons),
        reviewReasons=reasons,
    )


def apply_document_review(result: DocumentResult) -> DocumentResult:
    doc_reasons: list[str] = []

    for name in MANDATORY_FIELDS:
        field: FieldValue = getattr(result.invoice, name)
        if field.value is None or "FIELD_MISSING" in field.reviewReasons:
            if "MANDATORY_FIELD_MISSING" not in doc_reasons:
                doc_reasons.append("MANDATORY_FIELD_MISSING")
            field.isHumanReviewRequired = True
            if "FIELD_MISSING" not in field.reviewReasons:
                field.reviewReasons.append("FIELD_MISSING")

    # Also escalate if any mandatory field already needs review
    for name in MANDATORY_FIELDS:
        field = getattr(result.invoice, name)
        if field.isHumanReviewRequired and "MANDATORY_FIELD_REVIEW" not in doc_reasons:
            if "FIELD_MISSING" not in field.reviewReasons:
                doc_reasons.append("MANDATORY_FIELD_REVIEW")

    result.isHumanReviewRequired = bool(doc_reasons) or any(
        getattr(result.invoice, name).isHumanReviewRequired for name in MANDATORY_FIELDS
    )
    # Deduplicate while preserving order
    seen: set[str] = set()
    ordered: list[str] = []
    for r in doc_reasons:
        if r not in seen:
            seen.add(r)
            ordered.append(r)
    result.reviewReasons = ordered
    return result


def empty_invoice() -> InvoiceFields:
    return InvoiceFields(**{name: FieldValue() for name in HEADER_FIELDS})


def empty_line_item() -> LineItem:
    return LineItem(**{name: FieldValue() for name in LINE_ITEM_FIELDS})
