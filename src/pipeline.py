"""End-to-end invoice extraction orchestration."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable, Optional

from tqdm import tqdm

from src.bbox import extract_spans, find_bbox_for_value
from src.mistral_client import MistralOCRClient
from src.models import (
    HEADER_FIELDS,
    LINE_ITEM_FIELDS,
    MANDATORY_FIELDS,
    DocumentResult,
    FieldValue,
    InvoiceFields,
    LineItem,
)
from src.review import apply_document_review, build_field_value

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUTPUT_JSON_DIR = ROOT / "output" / "json"


def discover_pdfs(data_dir: Path = DATA_DIR) -> list[Path]:
    return sorted(data_dir.rglob("*.pdf"))


def _match_threshold() -> float:
    return float(os.getenv("MATCH_SCORE_THRESHOLD", "70"))


def build_document_result(
    document_id: str,
    annotation: dict,
    ocr_payload: dict,
) -> DocumentResult:
    spans = extract_spans(ocr_payload)
    thr = _match_threshold()

    invoice_kwargs: dict[str, FieldValue] = {}
    for name in HEADER_FIELDS:
        raw = annotation.get(name)
        match = find_bbox_for_value(raw, spans, min_score=thr)
        invoice_kwargs[name] = build_field_value(
            raw,
            match,
            name,
            mandatory=name in MANDATORY_FIELDS,
        )

    line_items: list[LineItem] = []
    for item in annotation.get("lineItems") or []:
        if not isinstance(item, dict):
            continue
        li_kwargs: dict[str, FieldValue] = {}
        for name in LINE_ITEM_FIELDS:
            raw = item.get(name)
            match = find_bbox_for_value(raw, spans, min_score=thr)
            li_kwargs[name] = build_field_value(raw, match, name)
        # Skip completely empty line items
        if all(v.value is None for v in li_kwargs.values()):
            continue
        line_items.append(LineItem(**li_kwargs))

    result = DocumentResult(
        documentId=document_id,
        invoice=InvoiceFields(**invoice_kwargs),
        lineItems=line_items,
    )
    return apply_document_review(result)


def process_pdf(
    pdf_path: Path,
    client: Optional[MistralOCRClient] = None,
    force: bool = False,
) -> DocumentResult:
    pdf_path = Path(pdf_path)
    client = client or MistralOCRClient()
    ocr_payload = client.process_pdf(pdf_path, force=force)
    annotation = client.extract_fields(ocr_payload, cache_stem=pdf_path.stem)
    return build_document_result(pdf_path.name, annotation, ocr_payload)


def save_result(result: DocumentResult, output_dir: Path = OUTPUT_JSON_DIR) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{Path(result.documentId).stem}.json"
    out_path.write_text(
        json.dumps(result.to_assignment_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_path


def run_extraction(
    pdfs: Optional[Iterable[Path]] = None,
    force: bool = False,
    output_dir: Path = OUTPUT_JSON_DIR,
) -> list[DocumentResult]:
    paths = list(pdfs) if pdfs is not None else discover_pdfs()
    if not paths:
        raise FileNotFoundError(f"No PDFs found under {DATA_DIR}")

    client = MistralOCRClient()
    results: list[DocumentResult] = []
    for path in tqdm(paths, desc="Extracting invoices"):
        result = process_pdf(path, client=client, force=force)
        save_result(result, output_dir=output_dir)
        results.append(result)
    return results
