# Invoice Extraction Pipeline (Mistral)

This pipeline turns invoice PDFs into structured JSON. Each field carries the printed value, a bounding box on the page, and a flag that says whether a person should check it.

It is built for a mixed batch: born-digital PDFs, scans, handwriting, invoices in languages other than English, and documents that span more than one page. The sample set lives under `data/`, grouped by those kinds:

| Folder | What is in it |
| --- | --- |
| `data/digital/` | Text-based PDFs, including one multi-page invoice |
| `data/scanned/` | Scanned paper invoices |
| `data/handwritten/` | Handwritten invoices |
| `data/multilingual/` | Invoices printed in languages other than English (Hong Kong, Vietnam, Singapore samples) |

## What you get for each invoice

Every extracted value is wrapped the same way, whether it is a header field or a line-item cell:

```json
{
  "value": "CSOS 202602-931",
  "bbox": {"page": 1, "x1": 517.0, "y1": 139.0, "x2": 652.0, "y2": 153.0},
  "isHumanReviewRequired": false,
  "reviewReasons": []
}
```

- `value` is the text as it appears on the invoice. Dates are not reformatted, amounts are not recalculated, and a field that is not printed is `null`.
- `bbox` is the rectangle of the OCR block that best matches that text. Coordinates come from Mistral OCR (`top_left` / `bottom_right` of the matched block or word). `page` is 1-indexed. If nothing matches well enough, `bbox` is `null`.
- `isHumanReviewRequired` is `true` when the value is missing (mandatory fields only), cannot be tied to a confident box, or fails a simple sanity check.
- `reviewReasons` lists why. The codes used on a field are `FIELD_MISSING` and `LOW_CONFIDENCE`.

The document itself has the same two review fields. An invoice is flagged when any **mandatory** header field is missing or itself needs review.

**Mandatory fields:** `invoiceNumber`, `invoiceDate`, `supplierName`, `buyerName`, `currency`, `totalAmount`.

**Other header fields** (optional; a blank one is normal and is not flagged): `dueDate`, `supplierTaxId`, `buyerTaxId`, `subtotal`, `taxAmount`, `amountDue`, `paymentTerms`, `purchaseOrderNumber`.

**Line-item fields:** `description`, `quantity`, `unitPrice`, `taxRate`, `taxAmount`, `lineAmount`. A row is dropped if every cell is empty. Subtotal, tax, and grand-total rows stay on the header; they are not copied into `lineItems`.

## Why two model calls

The assignment needs three things at once: the field value, where it sits on the page, and a review flag. One Mistral OCR call already returns markdown, tables, blocks, and word-level confidence, including handwriting and non-English text. Asking that same call to also emit the full invoice schema was slower and truncated the JSON.

So the pipeline splits the work:

1. **OCR** (`mistral-ocr-latest`) reads the PDF and keeps the geometry.
2. **Field copy** (`mistral-small-latest`, temperature 0) reads the OCR text and fills a strict JSON schema. The prompt tells it to copy what is printed, use `null` when a field is absent, and not invent tax splits or rewrite dates. `supplierName` is the seller; `buyerName` is the bill-to party. Currency becomes a short code or symbol when the page makes that clear (`RM`, `SGD`, `PHP`, `HKD`, `VND`, `USD`, and similar).
3. **Local code** links each copied string back to an OCR block and applies the review rules. No third model call.

## How one PDF becomes JSON

```
PDF
  → Mistral OCR (markdown, tables, blocks, word confidence)
  → structured field copy (mistral-small-latest)
  → match each value to an OCR block → bbox
  → review rules
  → output/json/<stem>.json
  → output/metrics.json
```

| Stage | What it does |
| --- | --- |
| OCR | Sends the PDF as a base64 data URL. Requests blocks, markdown tables, and word confidence. |
| Field copy | Flattens every page (header, markdown, tables, footer) into one string, capped at 20,000 characters, and asks for the invoice schema. |
| BBox linking | Builds a list of spans from blocks and, when present, individual words. Each value is normalized (lowercase, collapsed whitespace, punctuation stripped) and scored against those spans. An exact match scores 100. A containment match scores at least 80. Otherwise RapidFuzz `partial_ratio` is used. Ties prefer the shorter span, so the box hugs the value. A score below `MATCH_SCORE_THRESHOLD` (default 70) leaves `bbox` empty and flags the field. |
| Human review | See the rules below. |
| Cache | OCR responses are stored as `output/cache/<stem>_<hash>.json`, where the hash covers the model name and the PDF bytes. Field JSON is stored as `output/cache/fields_<stem>.json`. A later run reuses both and does not call the API. `--force` ignores the OCR cache and calls OCR again. Delete `fields_<stem>.json` if you also want the field-copy call to run again. |

## Review rules

A **mandatory** field with no value gets `FIELD_MISSING` and `isHumanReviewRequired: true`. An optional field left empty does not.

A field that has a value is flagged `LOW_CONFIDENCE` when any of these is true:

- No OCR span scores at or above `MATCH_SCORE_THRESHOLD` (default 70), so there is no trustworthy box.
- The matched span’s OCR confidence is below `CONFIDENCE_THRESHOLD` (default 0.75).
- `invoiceDate` or `dueDate` does not look like a date.
- A money or quantity field (`subtotal`, `taxAmount`, `totalAmount`, `amountDue`, `quantity`, `unitPrice`, `taxRate`, `lineAmount`) contains no digit.
- `currency` is longer than four characters and is not a known code, symbol, or name (for example `USD`, `RM`, `€`, `PESO`).

Document-level reasons:

- `MANDATORY_FIELD_MISSING` — at least one mandatory field has no value.
- `MANDATORY_FIELD_REVIEW` — a mandatory field has a value, but that field is flagged (usually `LOW_CONFIDENCE`).

`isHumanReviewRequired` on the document is true when either of those reasons is present.

## Setup

Python 3.10 or newer. Get an API key from [console.mistral.ai](https://console.mistral.ai/).

```bash
cd Extraction_Pipeline
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set `MISTRAL_API_KEY`. The client refuses to start if the key is missing or still the placeholder from the example file.

Optional settings in `.env`:

| Variable | Default | Effect |
| --- | --- | --- |
| `MISTRAL_OCR_MODEL` | `mistral-ocr-latest` | OCR model. Changing it changes the cache key, so the next run calls OCR again. |
| `MISTRAL_EXTRACT_MODEL` | `mistral-small-latest` | Model used for the structured field copy. |
| `CONFIDENCE_THRESHOLD` | `0.75` | OCR confidence below this flags the field `LOW_CONFIDENCE`. |
| `MATCH_SCORE_THRESHOLD` | `70` | Fuzzy-match score below this drops the bbox and flags the field. |

## Run

Extract every PDF under `data/`. Progress is printed per file. When the batch finishes, metrics are written and a short summary is printed.

```bash
python -m src.main extract
```

One file:

```bash
python -m src.main extract --file data/digital/digital_01.pdf
```

Call OCR again even if a cache file exists:

```bash
python -m src.main extract --force
```

Attach ground truth while extracting, so `missedReviewRate` is filled in the same run:

```bash
python -m src.main extract --gt evaluation/ground_truth.json
```

Recompute metrics from the JSON already in `output/json/`, without calling Mistral:

```bash
python -m src.main metrics
python -m src.main metrics --gt evaluation/ground_truth.json
```

## Outputs

| Path | Contents |
| --- | --- |
| `output/json/<stem>.json` | One invoice. `documentId` is the PDF file name. `invoice` holds the header fields. `lineItems` is the table rows. |
| `output/metrics.json` | Counts across the batch, plus a `perDocument` list. |
| `output/cache/` | Raw OCR payloads and the intermediate field JSON. Safe to delete; the next run will call the API again. |

`output/metrics.json` reports:

| Field | Meaning |
| --- | --- |
| `invoicesProcessed` | JSON files read from `output/json/` |
| `totalFieldsExtracted` | Header and line-item fields whose `value` is not null |
| `fieldsRequiringHumanReview` | Fields with `isHumanReviewRequired: true`, including mandatory fields that are missing |
| `mandatoryFieldsSuccessfullyExtracted` | Mandatory header fields that have a value |
| `mandatoryFieldsRequiringHumanReview` | Mandatory header fields that are flagged |
| `invoicesRequiringHumanReview` | Documents flagged at the top level |
| `missedReviewRate` | Percent of extracted values that disagree with ground truth and were **not** flagged. `null` until you pass `--gt` |
| `perDocument` | For each invoice: review flag, reasons, fields extracted, fields flagged |

## Missed-review rate

The rate is the share of extracted values that are wrong and were still marked as not needing review. It needs a ground-truth file; the pipeline does not invent one.

```bash
cp evaluation/ground_truth.example.json evaluation/ground_truth.json
```

Edit `evaluation/ground_truth.json` with the correct values for the invoices you want to score. A few fields per document is enough for a spot-check. Then:

```bash
python -m src.main metrics --gt evaluation/ground_truth.json
```

Comparison is case-insensitive and ignores extra whitespace. Only fields with a non-null extracted value are counted. Line items are matched by index (`lineItems[0]`, then `lineItems[1]`, …), so the ground-truth row order should follow the extraction. Details of each miss land in `incorrectUnflagged`, `comparableExtractedValues`, and `missedReviewDetails`. See [evaluation/spot_check.md](evaluation/spot_check.md).

## Project layout

```
src/main.py                    CLI: extract, metrics
src/pipeline.py                Discover PDFs, run the stages, write JSON
src/mistral_client.py          OCR call, field-copy call, disk cache
src/bbox.py                    OCR spans and value → box matching
src/review.py                  Field and document review flags
src/models.py                  Pydantic output schema
src/metrics.py                 Batch counts and missed-review rate
schemas/invoice_annotation.py  Field definitions used to describe the invoice
evaluation/                    Ground-truth example and spot-check notes
data/                          Input PDFs
output/json/                   Extraction results
output/metrics.json            Aggregate metrics
output/cache/                  Cached API responses
```
