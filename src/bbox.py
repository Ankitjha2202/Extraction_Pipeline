"""Link extracted field values to OCR block / word bounding boxes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from rapidfuzz import fuzz

from src.models import BBox


@dataclass
class OCRSpan:
    page: int  # 1-indexed
    text: str
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: Optional[float] = None


def _norm(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\w\s./%-]", "", text)
    return text


def extract_spans(ocr_payload: dict[str, Any]) -> list[OCRSpan]:
    """Build searchable spans from OCR blocks and word confidence scores."""
    spans: list[OCRSpan] = []
    pages = ocr_payload.get("pages") or []

    for page in pages:
        page_index = int(page.get("index", 0))
        page_num = page_index + 1  # API is 0-indexed

        word_scores = []
        conf = page.get("confidence_scores") or {}
        if isinstance(conf, dict):
            word_scores = conf.get("word_confidence_scores") or []

        blocks = page.get("blocks") or []
        for block in blocks:
            content = (block.get("content") or "").strip()
            if not content:
                continue
            x1 = float(block.get("top_left_x") or block.get("x1") or 0)
            y1 = float(block.get("top_left_y") or block.get("y1") or 0)
            x2 = float(block.get("bottom_right_x") or block.get("x2") or 0)
            y2 = float(block.get("bottom_right_y") or block.get("y2") or 0)

            block_conf = None
            bconf = block.get("confidence_scores") or {}
            if isinstance(bconf, dict):
                block_conf = bconf.get("average_content_confidence_score")
                if block_conf is None:
                    block_conf = bconf.get("minimum_content_confidence_score")

            spans.append(
                OCRSpan(
                    page=page_num,
                    text=content,
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                    confidence=_as_float(block_conf),
                )
            )

        # Also index individual words when available for tighter boxes
        for w in word_scores:
            if not isinstance(w, dict):
                continue
            text = (w.get("text") or w.get("word") or "").strip()
            if not text:
                continue
            # Coordinate field names vary across API versions
            x1 = w.get("top_left_x", w.get("x1", w.get("left")))
            y1 = w.get("top_left_y", w.get("y1", w.get("top")))
            x2 = w.get("bottom_right_x", w.get("x2", w.get("right")))
            y2 = w.get("bottom_right_y", w.get("y2", w.get("bottom")))
            if None in (x1, y1, x2, y2):
                continue
            score = w.get("confidence_score", w.get("confidence"))
            spans.append(
                OCRSpan(
                    page=page_num,
                    text=text,
                    x1=float(x1),
                    y1=float(y1),
                    x2=float(x2),
                    y2=float(y2),
                    confidence=_as_float(score),
                )
            )

        # Fallback: whole-page markdown as a weak span if no blocks
        if not blocks:
            md = (page.get("markdown") or "").strip()
            dims = page.get("dimensions") or {}
            width = float(dims.get("width") or 0)
            height = float(dims.get("height") or 0)
            if md:
                spans.append(
                    OCRSpan(
                        page=page_num,
                        text=md,
                        x1=0,
                        y1=0,
                        x2=width or 1,
                        y2=height or 1,
                        confidence=_as_float(
                            conf.get("average_page_confidence_score")
                            if isinstance(conf, dict)
                            else None
                        ),
                    )
                )

    return spans


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class MatchResult:
    bbox: Optional[BBox]
    confidence: Optional[float]
    match_score: float
    matched_text: Optional[str] = None


def find_bbox_for_value(
    value: Optional[str],
    spans: list[OCRSpan],
    min_score: float = 70.0,
) -> MatchResult:
    if value is None or str(value).strip() == "":
        return MatchResult(bbox=None, confidence=None, match_score=0.0)

    needle = _norm(str(value))
    if not needle:
        return MatchResult(bbox=None, confidence=None, match_score=0.0)

    best: Optional[OCRSpan] = None
    best_score = 0.0

    for span in spans:
        hay = _norm(span.text)
        if not hay:
            continue

        # Prefer containment / exact-ish matches
        if needle == hay:
            score = 100.0
        elif needle in hay or hay in needle:
            score = 95.0 * min(len(needle), len(hay)) / max(len(needle), len(hay))
            score = max(score, 80.0)
        else:
            score = float(fuzz.partial_ratio(needle, hay))

        # Prefer shorter spans when scores are close (tighter bbox)
        if score > best_score or (
            abs(score - best_score) < 1e-6
            and best is not None
            and len(span.text) < len(best.text)
        ):
            best_score = score
            best = span

    if best is None or best_score < min_score:
        return MatchResult(
            bbox=None,
            confidence=None,
            match_score=best_score,
            matched_text=best.text if best else None,
        )

    return MatchResult(
        bbox=BBox(
            page=best.page,
            x1=best.x1,
            y1=best.y1,
            x2=best.x2,
            y2=best.y2,
        ),
        confidence=best.confidence,
        match_score=best_score,
        matched_text=best.text,
    )
