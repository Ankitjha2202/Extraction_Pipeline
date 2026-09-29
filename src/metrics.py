"""Aggregate human-review metrics and optional missed-review rate vs ground truth."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from src.models import (
    HEADER_FIELDS,
    LINE_ITEM_FIELDS,
    MANDATORY_FIELDS,
    DocumentResult,
    FieldValue,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_JSON_DIR = ROOT / "output" / "json"
METRICS_PATH = ROOT / "output" / "metrics.json"


def _iter_fields(result: DocumentResult) -> list[tuple[str, FieldValue]]:
    fields: list[tuple[str, FieldValue]] = []
    for name in HEADER_FIELDS:
        fields.append((f"invoice.{name}", getattr(result.invoice, name)))
    for i, item in enumerate(result.lineItems):
        for name in LINE_ITEM_FIELDS:
            fields.append((f"lineItems[{i}].{name}", getattr(item, name)))
    return fields


def load_results(json_dir: Path = OUTPUT_JSON_DIR) -> list[DocumentResult]:
    results: list[DocumentResult] = []
    for path in sorted(json_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        results.append(DocumentResult.model_validate(data))
    return results


def compute_pipeline_metrics(results: list[DocumentResult]) -> dict[str, Any]:
    fields_extracted = 0
    fields_requiring_review = 0
    mandatory_extracted = 0
    mandatory_requiring_review = 0
    invoices_requiring_review = 0

    per_document: list[dict[str, Any]] = []

    for result in results:
        doc_extracted = 0
        doc_review = 0
        for path, field in _iter_fields(result):
            is_mandatory = path.startswith("invoice.") and path.split(".", 1)[1] in MANDATORY_FIELDS
            if field.value is not None:
                fields_extracted += 1
                doc_extracted += 1
                if is_mandatory:
                    mandatory_extracted += 1
            if field.isHumanReviewRequired:
                fields_requiring_review += 1
                doc_review += 1
                if is_mandatory:
                    mandatory_requiring_review += 1

        if result.isHumanReviewRequired:
            invoices_requiring_review += 1

        per_document.append(
            {
                "documentId": result.documentId,
                "isHumanReviewRequired": result.isHumanReviewRequired,
                "reviewReasons": result.reviewReasons,
                "fieldsExtracted": doc_extracted,
                "fieldsRequiringReview": doc_review,
            }
        )

    return {
        "invoicesProcessed": len(results),
        "totalFieldsExtracted": fields_extracted,
        "fieldsRequiringHumanReview": fields_requiring_review,
        "mandatoryFieldsSuccessfullyExtracted": mandatory_extracted,
        "mandatoryFieldsRequiringHumanReview": mandatory_requiring_review,
        "invoicesRequiringHumanReview": invoices_requiring_review,
        "missedReviewRate": None,
        "missedReviewNote": (
            "Provide evaluation/ground_truth.json and re-run "
            "python -m src.main metrics --gt evaluation/ground_truth.json"
        ),
        "perDocument": per_document,
    }


def _gt_value(gt_doc: dict[str, Any], field_path: str) -> Any:
    """Resolve dotted paths like invoice.invoiceNumber or lineItems[0].description."""
    if field_path.startswith("invoice."):
        name = field_path.split(".", 1)[1]
        invoice = gt_doc.get("invoice") or {}
        val = invoice.get(name)
        if isinstance(val, dict):
            return val.get("value")
        return val

    if field_path.startswith("lineItems["):
        # lineItems[i].field
        rest = field_path[len("lineItems[") :]
        idx_str, rem = rest.split("]", 1)
        idx = int(idx_str)
        name = rem.lstrip(".")
        items = gt_doc.get("lineItems") or []
        if idx >= len(items):
            return None
        item = items[idx] or {}
        val = item.get(name)
        if isinstance(val, dict):
            return val.get("value")
        return val
    return None


def _normalize(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().split())


def compute_missed_review_rate(
    results: list[DocumentResult],
    ground_truth: dict[str, Any],
) -> dict[str, Any]:
    """
    Missed-review rate = incorrect values that were NOT flagged for human review,
    over all extracted (non-null) values that can be compared to GT.
    """
    by_id = {r.documentId: r for r in results}
    # Also allow stem keys
    by_stem = {Path(r.documentId).name: r for r in results}
    by_stem.update({Path(r.documentId).stem: r for r in results})

    incorrect_unflagged = 0
    comparable = 0
    details: list[dict[str, Any]] = []

    documents = ground_truth.get("documents") or ground_truth
    if isinstance(documents, dict) and "documents" not in ground_truth:
        # map of documentId -> gt
        doc_items = list(documents.items())
    else:
        doc_items = []
        for doc in documents:
            doc_id = doc.get("documentId")
            doc_items.append((doc_id, doc))

    for doc_id, gt_doc in doc_items:
        result = by_id.get(doc_id) or by_stem.get(doc_id) or by_stem.get(Path(doc_id).name)
        if result is None:
            continue
        for path, field in _iter_fields(result):
            if field.value is None:
                continue
            gt_val = _gt_value(gt_doc, path)
            if gt_val is None and path.startswith("lineItems"):
                continue  # no GT for this line
            if gt_val is None and not path.startswith("lineItems"):
                # GT explicitly null means field should be empty — extracted value is wrong
                pass

            comparable += 1
            correct = _normalize(field.value) == _normalize(gt_val)
            if not correct and not field.isHumanReviewRequired:
                incorrect_unflagged += 1
                details.append(
                    {
                        "documentId": result.documentId,
                        "field": path,
                        "extracted": field.value,
                        "groundTruth": gt_val,
                    }
                )

    rate = (
        round(100.0 * incorrect_unflagged / comparable, 2) if comparable else None
    )
    return {
        "missedReviewRate": rate,
        "incorrectUnflagged": incorrect_unflagged,
        "comparableExtractedValues": comparable,
        "missedReviewDetails": details,
    }


def write_metrics(
    metrics: dict[str, Any],
    path: Path = METRICS_PATH,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_metrics(
    json_dir: Path = OUTPUT_JSON_DIR,
    gt_path: Optional[Path] = None,
) -> dict[str, Any]:
    results = load_results(json_dir)
    metrics = compute_pipeline_metrics(results)

    if gt_path and Path(gt_path).exists():
        gt = json.loads(Path(gt_path).read_text(encoding="utf-8"))
        missed = compute_missed_review_rate(results, gt)
        metrics.update(missed)
        metrics.pop("missedReviewNote", None)
    return metrics
