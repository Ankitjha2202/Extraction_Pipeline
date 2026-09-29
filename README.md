# Invoice Extraction Pipeline (Mistral)

Batch invoice extraction for digital, scanned, handwritten, multilingual, and multi-page PDFs. Mistral OCR (`mistral-ocr-latest`) reads the page, including handwriting and non-English text, and returns blocks with bounding boxes. A second short structured call (`mistral-small-latest`) copies invoice fields from that text. Each value is then linked back to an OCR block and flagged for human review when it is missing, unmatched, or fails a simple check.

## Why Mistral

This assignment needs field values, bounding boxes, and a review flag. Mistral OCR supplies the text and the boxes, including scans, handwriting, and multiple languages. A small structured model then fills the invoice schema from that text, which is faster and more complete than asking OCR annotation to emit the full schema in one shot.

## Architecture

```
PDF → Mistral OCR (markdown, tables, blocks, confidence)
    → structured field copy (mistral-small-latest)
    → match each value to an OCR block → bbox
    → review rules
    → output/json/*.json + output/metrics.json
```

| Stage | Role |
| --- | --- |
| OCR | `mistral-ocr-latest` with blocks, tables, and word confidence |
| Field copy | Compact JSON schema on the OCR text. Values are copied, not recalculated |
| BBox linking | Fuzzy-match each value to OCR blocks |
| Human review | `FIELD_MISSING` or `LOW_CONFIDENCE`. The invoice is flagged if any mandatory field is missing or uncertain |
| Cache | OCR and field JSON under `output/cache/` so a rerun does not call the API again |

**Mandatory fields:** `invoiceNumber`, `invoiceDate`, `supplierName`, `buyerName`, `currency`, `totalAmount`.

## Setup

```bash
cd Extraction_Pipeline
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and set MISTRAL_API_KEY
```

Get an API key from [https://console.mistral.ai/](https://console.mistral.ai/).

## Run

Extract all invoices under `data/`:

```bash
python -m src.main extract
```

Single file:

```bash
python -m src.main extract --file data/digital/digital_01.pdf
```

Force re-OCR (ignore cache):

```bash
python -m src.main extract --force
```

Recompute metrics (optional ground truth for missed-review rate):

```bash
python -m src.main metrics
python -m src.main metrics --gt evaluation/ground_truth.json
```

## Outputs

| Path | Contents |
| --- | --- |
| `output/json/<stem>.json` | Assignment-shaped extraction per invoice |
| `output/metrics.json` | Invoices/fields requiring human review; missed-review rate if GT provided |
| `output/cache/` | Cached Mistral OCR responses |

### JSON shape (per field)

```json
{
  "value": "INV-001",
  "bbox": {"page": 1, "x1": 100, "y1": 100, "x2": 250, "y2": 130},
  "isHumanReviewRequired": false,
  "reviewReasons": []
}
```

## Missed-review rate

See [evaluation/spot_check.md](evaluation/spot_check.md). Without ground truth, `missedReviewRate` is `null` and pipeline review counts are still reported.

## Project layout

```
src/models.py              # Output schema
src/mistral_client.py      # OCR + annotation + cache
src/bbox.py                # Value → bbox matching
src/review.py              # Human-review rules
src/pipeline.py            # Orchestration
src/metrics.py             # Aggregate metrics
src/main.py                # CLI
schemas/invoice_annotation.py
evaluation/
data/                      # Input PDFs
output/
```
