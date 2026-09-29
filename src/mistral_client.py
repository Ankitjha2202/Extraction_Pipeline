"""Mistral Document AI OCR + document annotation client with disk cache."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

DEFAULT_CACHE_DIR = ROOT / "output" / "cache"

DOCUMENT_ANNOTATION_PROMPT = None  # set after import to avoid circular issues


def _import_annotation_prompt() -> str:
    from schemas.invoice_annotation import DOCUMENT_ANNOTATION_PROMPT as prompt

    return prompt


def _import_annotation_model():
    from schemas.invoice_annotation import InvoiceAnnotation

    return InvoiceAnnotation


def pdf_to_data_url(pdf_path: Path) -> str:
    raw = pdf_path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:application/pdf;base64,{b64}"


def cache_key(pdf_path: Path, model: str) -> str:
    digest = hashlib.sha256()
    digest.update(model.encode())
    digest.update(pdf_path.read_bytes())
    return digest.hexdigest()[:24]


def _serialize_response(response: Any) -> dict[str, Any]:
    if hasattr(response, "model_dump"):
        return response.model_dump(mode="json")
    if hasattr(response, "dict"):
        return response.dict()
    if isinstance(response, dict):
        return response
    return json.loads(str(response))


class MistralOCRClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        cache_dir: Optional[Path] = None,
        use_cache: bool = True,
    ) -> None:
        self.api_key = api_key or os.getenv("MISTRAL_API_KEY")
        if not self.api_key or self.api_key.startswith("your_mistral"):
            raise RuntimeError(
                "MISTRAL_API_KEY is not set. Copy .env.example to .env and add your key."
            )
        self.model = model or os.getenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest")
        self.cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self.use_cache = use_cache
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        from mistralai.client import Mistral

        self._client = Mistral(api_key=self.api_key)

    def process_pdf(self, pdf_path: Path, force: bool = False) -> dict[str, Any]:
        pdf_path = Path(pdf_path)
        key = cache_key(pdf_path, self.model)
        cache_path = self.cache_dir / f"{pdf_path.stem}_{key}.json"

        if self.use_cache and not force and cache_path.exists():
            return json.loads(cache_path.read_text(encoding="utf-8"))

        payload = self._call_ocr(pdf_path)
        cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return payload

    def _call_ocr(self, pdf_path: Path) -> dict[str, Any]:
        document_url = pdf_to_data_url(pdf_path)

        # OCR only. Structured fields are extracted from this text in a
        # separate fast chat call — document_annotation was truncated and slow.
        kwargs: dict[str, Any] = {
            "model": self.model,
            "document": {
                "type": "document_url",
                "document_url": document_url,
            },
            "include_blocks": True,
            "confidence_scores_granularity": "word",
            "table_format": "markdown",
        }

        response = self._client.ocr.process(**kwargs)
        return _serialize_response(response)

    def extract_fields(self, ocr_payload: dict[str, Any], cache_stem: str) -> dict[str, Any]:
        """Structured field extraction from OCR markdown. Cached per document."""
        cache_path = self.cache_dir / f"fields_{cache_stem}.json"
        if self.use_cache and cache_path.exists():
            return json.loads(cache_path.read_text(encoding="utf-8"))

        text = ocr_to_text(ocr_payload)
        model = os.getenv("MISTRAL_EXTRACT_MODEL", "mistral-small-latest")
        response = self._client.chat.complete(
            model=model,
            temperature=0,
            max_tokens=2500,
            response_format=_COMPACT_INVOICE_SCHEMA,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Copy invoice values exactly as printed. "
                        "Each string must be under 120 characters. "
                        "Use null when a field is not printed. Do not calculate or infer tax splits. "
                        "Do not reformat dates. "
                        "currency is a 3-letter code when RM, SGD, PHP, HKD, VND, USD, or a symbol makes it clear. "
                        "supplierName is the seller. buyerName is the bill-to customer. "
                        "Skip blank table rows and skip subtotal/tax/total rows; those belong in header fields."
                    ),
                },
                {"role": "user", "content": text[:20000]},
            ],
        )
        content = response.choices[0].message.content
        if isinstance(content, str):
            parsed = json.loads(content)
        elif isinstance(content, dict):
            parsed = content
        else:
            parsed = json.loads(str(content))

        cache_path.write_text(
            json.dumps(parsed, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return parsed


def _nullable_string() -> dict[str, Any]:
    return {"type": ["string", "null"]}


_LINE_ITEM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "description": _nullable_string(),
        "quantity": _nullable_string(),
        "unitPrice": _nullable_string(),
        "taxRate": _nullable_string(),
        "taxAmount": _nullable_string(),
        "lineAmount": _nullable_string(),
    },
    "required": [
        "description",
        "quantity",
        "unitPrice",
        "taxRate",
        "taxAmount",
        "lineAmount",
    ],
}

_HEADER_KEYS = [
    "invoiceNumber",
    "invoiceDate",
    "dueDate",
    "supplierName",
    "supplierTaxId",
    "buyerName",
    "buyerTaxId",
    "currency",
    "subtotal",
    "taxAmount",
    "totalAmount",
    "amountDue",
    "paymentTerms",
    "purchaseOrderNumber",
    "lineItems",
]

_COMPACT_INVOICE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "invoice",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                **{key: _nullable_string() for key in _HEADER_KEYS if key != "lineItems"},
                "lineItems": {"type": "array", "items": _LINE_ITEM_SCHEMA},
            },
            "required": _HEADER_KEYS,
        },
    },
}


def ocr_to_text(ocr_payload: dict[str, Any]) -> str:
    """Flatten OCR pages and tables into one prompt string."""
    parts: list[str] = []
    for page in ocr_payload.get("pages") or []:
        index = int(page.get("index", 0)) + 1
        parts.append(f"\n--- PAGE {index} ---\n")
        header = page.get("header")
        footer = page.get("footer")
        if header:
            parts.append(str(header))
        markdown = page.get("markdown") or ""
        parts.append(markdown)
        for table in page.get("tables") or []:
            content = table.get("content") if isinstance(table, dict) else None
            if content:
                parts.append("\nTABLE:\n")
                parts.append(str(content))
        if footer:
            parts.append(str(footer))
    return "\n".join(parts).strip()


def parse_document_annotation(ocr_payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize document_annotation into a plain dict of field values."""
    ann = ocr_payload.get("document_annotation")
    if ann is None:
        return {}
    if isinstance(ann, str):
        try:
            ann = json.loads(ann)
        except json.JSONDecodeError:
            return {}
    if isinstance(ann, dict):
        return ann
    if hasattr(ann, "model_dump"):
        return ann.model_dump(mode="json")
    return {}
